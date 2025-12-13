import os
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Dict, Optional, Tuple, Union

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

try:
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
except ImportError:  # Playwrightがインストールされていない場合でもフォールバックできるようにする
    PlaywrightError = Exception  # type: ignore[assignment]
    sync_playwright = None  # type: ignore[assignment]

# --- 定数定義 ---
load_dotenv()
DISCORD_WEBHOOK_URL: Optional[str] = os.getenv("DISCORD_WEBHOOK_URL") or os.getenv("DISCORD_WEBHOOK")
FINANCIE_COMMUNITY_URL: str = "https://financie.jp/communities/orochi_cnp/"
FINANCIE_MARKET_URL: str = "https://financie.jp/communities/orochi_cnp/market"
FINANCIE_BANCOR_API: str = "https://financie.jp/api/charts/bancor/{connector_address}/day"
STATS_CSV_PATH: str = "stats.csv"
CONNECTOR_INPUT_SELECTOR: str = "#gtm-connector-address"
WEI_DECIMAL = Decimal("1e18")
COMMUNITY_OPEN_DATE: date = date(2025, 1, 17)

# --- 型定義 ---
FinancieData = Dict[str, Union[int, float]]
DiffData = Tuple[int, float, int]


def _load_manual_yesterday_entry(now: datetime) -> Optional[Dict[str, Union[int, float, str]]]:
    """
    環境変数に手動で前日データが指定されている場合、その値を読み込んで返します。
    すべての値（メンバー数・価格・在庫）が揃っていない場合や日付が不正な場合はNoneを返します。
    """
    manual_members = os.getenv("MANUAL_YESTERDAY_MEMBERS")
    manual_price = os.getenv("MANUAL_YESTERDAY_PRICE")
    manual_stock = os.getenv("MANUAL_YESTERDAY_STOCK")
    manual_date_str = os.getenv("MANUAL_YESTERDAY_DATE")

    if not any([manual_members, manual_price, manual_stock, manual_date_str]):
        return None

    missing = [
        name
        for name, value in [
            ("MANUAL_YESTERDAY_MEMBERS", manual_members),
            ("MANUAL_YESTERDAY_PRICE", manual_price),
            ("MANUAL_YESTERDAY_STOCK", manual_stock),
        ]
        if not value
    ]
    if missing:
        print(
            "[ManualYesterday] 環境変数が不足しています。以下をすべて設定してください: "
            + ", ".join(missing)
        )
        return None

    if manual_date_str:
        try:
            manual_date = datetime.strptime(manual_date_str, "%Y-%m-%d")
        except ValueError:
            print("[ManualYesterday] MANUAL_YESTERDAY_DATE は YYYY-MM-DD 形式で指定してください。")
            return None
    else:
        manual_date = now - timedelta(days=1)

    if manual_date.date() >= now.date():
        print("[ManualYesterday] 手動データの日付は今日より前の日付を指定してください。")
        return None

    try:
        members = int(manual_members)
        price = float(manual_price)
        stock = int(manual_stock)
    except ValueError as exc:
        print(f"[ManualYesterday] 手動データの形式に問題があります: {exc}")
        return None

    manual_entry = {
        "date": manual_date.strftime("%Y-%m-%d"),
        "members": members,
        "price": price,
        "stock": stock,
    }
    print(f"[ManualYesterday] {manual_entry['date']} の手動データを使用します: {manual_entry}")
    return manual_entry


def _parse_int(text: str) -> Optional[int]:
    cleaned = re.sub(r"[^0-9]", "", text)
    return int(cleaned) if cleaned else None


def _parse_float(text: str) -> Optional[float]:
    cleaned = re.sub(r"[^0-9.,]", "", text).replace(",", "")
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _fetch_financie_data_with_requests() -> Optional[FinancieData]:
    session = requests.Session()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ja,en;q=0.9",
    }
    try:
        community_res = session.get(FINANCIE_COMMUNITY_URL, headers=headers, timeout=30)
        community_res.raise_for_status()
        market_res = session.get(FINANCIE_MARKET_URL, headers=headers, timeout=30)
        market_res.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching FiNANCiE pages via HTTP: {e}")
        return None

    data: Dict[str, Union[int, float]] = {}
    community_soup = BeautifulSoup(community_res.text, "lxml")
    connector_input = community_soup.select_one(CONNECTOR_INPUT_SELECTOR)
    connector_address = connector_input["value"] if connector_input and connector_input.get("value") else None
    if not connector_address:
        print(f"[HTTP] Failed to find connector address with selector '{CONNECTOR_INPUT_SELECTOR}'.")
        return None

    market_soup = BeautifulSoup(market_res.text, "lxml")

    member_element = community_soup.select_one(".profile_databox .profile_num")
    if member_element and (members := _parse_int(member_element.get_text())) is not None:
        data["owner_count"] = members
        print(f"[HTTP] Parsed member count: {members}")

    market_data = _fetch_market_data_via_api(session, headers, connector_address)
    if market_data:
        data.update(market_data)

    required_keys = {"owner_count", "token_price", "token_stock"}
    if required_keys <= data.keys():
        return data

    missing_keys = required_keys - set(data.keys())
    print(f"[HTTP] Failed to get all required data. Missing: {missing_keys}.")
    return None


def _fetch_market_data_via_api(
    session: requests.Session, headers: Dict[str, str], connector_address: str
) -> Optional[FinancieData]:
    url = FINANCIE_BANCOR_API.format(connector_address=connector_address)
    try:
        response = session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[HTTP] Error fetching market API ({url}): {e}")
        return None

    try:
        raw_price = Decimal(payload["bancor"]["latest_price"])
        raw_stock = Decimal(payload["market"]["stock"])
    except (KeyError, InvalidOperation, TypeError) as e:
        print(f"[HTTP] Market API payload missing expected fields: {e}")
        return None

    price_decimal = (raw_price / WEI_DECIMAL).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    stock_decimal = raw_stock / WEI_DECIMAL

    price = float(price_decimal)
    stock = int(stock_decimal)

    print(f"[HTTP] Parsed token price from API: {price}")
    print(f"[HTTP] Parsed token stock from API: {stock}")
    return {
        "token_price": price,
        "token_stock": stock,
    }


def get_financie_data_from_web() -> Optional[FinancieData]:
    """
    FiNANCiEのWebページをスクレイピングし、統計データを取得します。
    Playwrightを使い、コミュニティページからメンバー数、マーケットページから
    トークン価格と在庫数を取得します。
    """
    print("Starting web scraping...")
    data = _fetch_financie_data_with_playwright()
    if data:
        return data

    print("Playwright scraping failed or returned incomplete data. Falling back to HTTP scraping.")
    return _fetch_financie_data_with_requests()


def _fetch_financie_data_with_playwright() -> Optional[FinancieData]:
    if sync_playwright is None:
        print("Playwright is not available. Skipping Playwright scraping.")
        return None

    data: Dict[str, Union[int, float]] = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                print(f"Navigating to community page: {FINANCIE_COMMUNITY_URL}")
                page.goto(FINANCIE_COMMUNITY_URL, timeout=60000)
                member_element = page.query_selector(".profile_databox .profile_num")
                if member_element:
                    members = int(re.sub(r"[^0-9]", "", member_element.inner_text()))
                    data["owner_count"] = members
                    print(f"Parsed member count: {members}")

                print(f"Navigating to market page: {FINANCIE_MARKET_URL}")
                page.goto(FINANCIE_MARKET_URL, timeout=60000)

                price_selector = ".js-bancor-latest-price .connector-price"
                print(f"Waiting for price element ('{price_selector}') to be visible...")
                page.wait_for_selector(price_selector, timeout=30000)
                print("Price element is visible.")

                stock_element = page.query_selector(".selling_stock .connector-instock .currency.int-part")
                if stock_element:
                    stock = int(re.sub(r"[^0-9]", "", stock_element.inner_text()))
                    data["token_stock"] = stock
                    print(f"Parsed token stock: {stock}")

                price_int_element = page.query_selector(".js-bancor-latest-price .connector-price .currency.int-part")
                price_float_element = page.query_selector(
                    ".js-bancor-latest-price .connector-price .currency.float-part"
                )

                if price_int_element:
                    price_str = re.sub(r"[^0-9.]", "", price_int_element.inner_text())
                    if price_float_element and price_float_element.inner_text():
                        price_str += price_float_element.inner_text()

                    price = float(price_str)
                    data["token_price"] = price
                    print(f"Parsed token price: {price}")

                required_keys = {"owner_count", "token_price", "token_stock"}
                if required_keys <= data.keys():
                    return data

                missing_keys = required_keys - set(data.keys())
                print(f"Failed to get all required data. Missing: {missing_keys}. Selectors might be incorrect.")
                return None
            finally:
                browser.close()
                print("Browser closed.")
    except PlaywrightError as e:
        print(f"Error scraping data from FiNANCiE with Playwright: {e}")
        return None


def read_stats_csv(file_path: str) -> pd.DataFrame:
    """
    統計データが記録されたCSVファイルを読み込みます。
    """
    try:
        df = pd.read_csv(file_path, dtype={'date': str})
        print(f"Successfully read {file_path}.")
        for col, dtype in {"price": 0.0, "stock": 0}.items():
            if col not in df.columns:
                df[col] = dtype
        return df
    except FileNotFoundError:
        print(f"{file_path} not found. Creating new DataFrame.")
        return pd.DataFrame(columns=["date", "members", "price", "stock"])


def calculate_diffs(current_data: FinancieData, yesterday_data: Optional[pd.Series]) -> DiffData:
    """
    当日データと前日データを比較し、各指標の差分を計算します。
    """
    if yesterday_data is not None and not yesterday_data.empty:
        member_diff = int(current_data["owner_count"] - yesterday_data["members"])
        price_diff = float(current_data["token_price"] - yesterday_data["price"])
        stock_diff = int(current_data["token_stock"] - yesterday_data["stock"])
        print(f"Calculated diffs: members={member_diff}, price={price_diff}, stock={stock_diff}")
        return member_diff, price_diff, stock_diff
    else:
        print("No yesterday's data found. Diffs set to 0.")
        return 0, 0.0, 0


def update_stats_csv(df: pd.DataFrame, file_path: str, today_str: str, current_data: FinancieData) -> pd.DataFrame:
    """
    DataFrameを更新し、CSVファイルとして保存します。
    """
    today_data_row = {
        "date": today_str,
        "members": current_data["owner_count"],
        "price": current_data["token_price"],
        "stock": current_data["token_stock"]
    }

    df["date"] = df["date"].astype(str).str.strip()

    if today_str in df["date"].values:
        df.loc[df["date"] == today_str, list(today_data_row.keys())] = list(today_data_row.values())
        print(f"Updated existing entry for {today_str} in {file_path}.")
    else:
        new_df = pd.DataFrame([today_data_row])
        df = pd.concat([df, new_df], ignore_index=True)
        print(f"Added new entry for {today_str} to {file_path}.")

    df = df.drop_duplicates(subset="date", keep="last")
    df = df.sort_values(by="date").reset_index(drop=True)

    df.to_csv(file_path, index=False)
    print(f"Saved {file_path}. Tail:\n{df.tail()}")
    return df


def apply_manual_yesterday_if_needed(df: pd.DataFrame, file_path: str, now: datetime) -> pd.DataFrame:
    """
    環境変数で指定された前日データがあればCSVに反映します。
    """
    manual_entry = _load_manual_yesterday_entry(now)
    if not manual_entry:
        return df

    manual_financie_data: FinancieData = {
        "owner_count": manual_entry["members"],
        "token_price": manual_entry["price"],
        "token_stock": manual_entry["stock"],
    }
    df = update_stats_csv(df, file_path, manual_entry["date"], manual_financie_data)
    print("[ManualYesterday] CSVを手動データで更新しました。")
    return df


def format_discord_message(post_time: datetime, current_data: FinancieData, diffs: DiffData) -> str:
    """
    Discordに投稿するためのメッセージ文字列をフォーマットします。
    """
    member_diff, price_diff, stock_diff = diffs
    open_day = (post_time.date() - COMMUNITY_OPEN_DATE).days + 1
    message = f"""◆FiNANCiE開運オロチトークン現在情報（{post_time.strftime('%Y年%m月%d日 %H:%M時点')}）
・オープン{open_day}日目
・メンバー数 {current_data["owner_count"]:,}人（前日比 {member_diff:+,}人）
・トークン価格 {current_data["token_price"]:.4f}円（前日比 {price_diff:+.4f}円）
・トークン在庫 {current_data["token_stock"]:,}枚（前日比 {stock_diff:+,}枚）
#CNPオロチ #開運オロチ
"""
    print(f"Formatted Discord message:\n{message}")
    return message


def send_discord_notification(webhook_url: Optional[str], message: str) -> None:
    """
    指定されたWebhook URLにメッセージを送信します。
    """
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL is not set. Skipping Discord notification.")
        return
    try:
        response = requests.post(webhook_url, json={"content": message})
        response.raise_for_status()
        print("Successfully sent notification to Discord.")
    except requests.exceptions.RequestException as e:
        print(f"Error sending notification to Discord: {e}")


def main() -> None:
    """
    メイン処理。
    """
    print("Script started.")
    JST = timezone(timedelta(hours=+9), 'JST')
    now = datetime.now(JST)
    today_str = now.strftime('%Y-%m-%d')
    print(f"Current JST date: {today_str}")

    financie_data = get_financie_data_from_web()
    if not financie_data:
        print("Failed to get FiNANCiE data. Exiting.")
        return

    df = read_stats_csv(STATS_CSV_PATH)
    df = apply_manual_yesterday_if_needed(df, STATS_CSV_PATH, now)

    yesterday_data: Optional[pd.Series] = None
    if not df.empty:
        df['date_stripped'] = df['date'].astype(str).str.strip()
        df['date_dt'] = pd.to_datetime(df['date_stripped'], errors='coerce', format='mixed')
        invalid_dates = df[df['date_dt'].isna()]
        if not invalid_dates.empty:
            print(
                "Warning: Found rows with unparseable dates. Excluding them from diff calculation: "
                f"{invalid_dates['date'].tolist()}"
            )

        df_valid = df[df['date_dt'].notna()].copy()
        df_valid['date_dt'] = df_valid['date_dt'].dt.normalize()
        df_valid = df_valid.sort_values(by='date_dt')

        today_dt = pd.to_datetime(today_str).normalize()
        df_past = df_valid[df_valid['date_dt'] < today_dt]

        if not df_past.empty:
            latest_available = df_past.iloc[-1]
            gap_days = (today_dt - latest_available['date_dt']).days

            yesterday_data = latest_available
            if gap_days == 1:
                print(f"Using yesterday's data ({yesterday_data['date']}): {yesterday_data.to_dict()}")
            else:
                print(
                    "Most recent stats entry is from "
                    f"{latest_available['date']} ({gap_days} day(s) old). "
                    "Using it for diff calculation."
                )
        else:
            print("No past data found for yesterday's calculation.")
        df = df.drop(columns=['date_dt', 'date_stripped'])

    diffs = calculate_diffs(financie_data, yesterday_data)

    df = update_stats_csv(df, STATS_CSV_PATH, today_str, financie_data)

    post_time_fixed = now.replace(hour=6, minute=0, second=0, microsecond=0)
    message = format_discord_message(post_time_fixed, financie_data, diffs)

    send_discord_notification(DISCORD_WEBHOOK_URL, message)
    print("Script finished.")


if __name__ == "__main__":
    main()
