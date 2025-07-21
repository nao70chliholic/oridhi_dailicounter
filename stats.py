
"""
FiNANCiEのコミュニティ情報をスクレイピングし、日々の統計データを記録・通知するスクリプト。

主な機能:
- Playwrightを使用してFiNANCiEのWebページからメンバー数、トークン価格、トークン在庫を取得します。
- 取得したデータをCSVファイル(stats.csv)に日付と共に記録します。
- 前日のデータと比較し、メンバー数、価格、在庫の増減を計算します。
- 計算結果を整形し、DiscordのWebhookを使用して指定のチャンネルに通知します。
- GitHub Actionsでの定期実行を想定しており、.envファイルから環境変数を読み込みます。
"""

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

import pandas as pd
import requests
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# --- 定数定義 ---
# .envファイルから環境変数を読み込む
load_dotenv()
DISCORD_WEBHOOK_URL: Optional[str] = os.getenv("DISCORD_WEBHOOK_URL")
FINANCIE_COMMUNITY_URL: str = "https://financie.jp/communities/orochi_cnp/"
FINANCIE_MARKET_URL: str = "https://financie.jp/communities/orochi_cnp/market"
STATS_CSV_PATH: str = "stats.csv"

# --- 型定義 ---
FinancieData = Dict[str, int | float]
DiffData = Tuple[int, float, int]


def get_financie_data_from_web() -> Optional[FinancieData]:
    """
    FiNANCiEのWebページをスクレイピングし、統計データを取得します。

    Playwrightを使い、コミュニティページからメンバー数、マーケットページから
    トークン価格と在庫数を取得します。

    Returns:
        Optional[FinancieData]: 取得したデータの辞書。
                                 キー: "owner_count", "token_price", "token_stock"
                                 取得に失敗した場合はNoneを返します。
    """
    print("Starting web scraping...")
    data: Dict[str, int | float] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            # メンバー数を取得
            print(f"Navigating to community page: {FINANCIE_COMMUNITY_URL}")
            page.goto(FINANCIE_COMMUNITY_URL, timeout=60000)
            member_element = page.query_selector(".profile_databox .profile_num")
            if member_element:
                members = int(re.sub(r'[^0-9]', '', member_element.inner_text()))
                data["owner_count"] = members
                print(f"Parsed member count: {members}")

            # トークン価格と在庫を取得
            print(f"Navigating to market page: {FINANCIE_MARKET_URL}")
            page.goto(FINANCIE_MARKET_URL, timeout=60000)
            page.wait_for_selector(".p-market-overview__data-area")

            stock_element = page.query_selector(".selling_stock .connector-instock .currency.int-part")
            if stock_element:
                stock = int(re.sub(r'[^0-9]', '', stock_element.inner_text()))
                data["token_stock"] = stock
                print(f"Parsed token stock: {stock}")

            price_int = page.query_selector(".js-bancor-latest-price .connector-price .currency.int-part")
            price_float = page.query_selector(".js-bancor-latest-price .connector-price .currency.float-part")
            if price_int and price_float:
                price_str = f"{re.sub(r'[^0-9]', '', price_int.inner_text())}{price_float.inner_text()}"
                price = float(price_str)
                data["token_price"] = price
                print(f"Parsed token price: {price}")

            if "owner_count" in data and "token_price" in data and "token_stock" in data:
                return data
            else:
                print("Failed to get all required data. Selectors might be incorrect.")
                return None

        except Exception as e:
            print(f"Error scraping data from FiNANCiE: {e}")
            return None
        finally:
            browser.close()
            print("Browser closed.")


def read_stats_csv(file_path: str) -> pd.DataFrame:
    """
    統計データが記録されたCSVファイルを読み込みます。

    ファイルが存在しない場合は、新しい空のDataFrameを作成します。
    既存のファイルに特定のカラムがない場合も考慮し、カラムを追加します。

    Args:
        file_path (str): CSVファイルのパス。

    Returns:
        pd.DataFrame: 読み込んだデータ、または空のDataFrame。
    """
    try:
        df = pd.read_csv(file_path)
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

    Args:
        current_data (FinancieData): スクレイピングで取得した当日のデータ。
        yesterday_data (Optional[pd.Series]): 前日のデータ。存在しない場合はNone。

    Returns:
        DiffData: メンバー数、価格、在庫の前日比のタプル。
    """
    if yesterday_data is not None:
        member_diff = int(current_data["owner_count"] - yesterday_data["members"])
        price_diff = float(current_data["token_price"] - yesterday_data["price"])
        stock_diff = int(current_data["token_stock"] - yesterday_data["stock"])
        print(f"Calculated diffs: members={member_diff}, price={price_diff}, stock={stock_diff}")
        return member_diff, price_diff, stock_diff
    else:
        print("No yesterday's data found. Diffs set to 0.")
        return 0, 0.0, 0


def update_stats_csv(df: pd.DataFrame, file_path: str, today_str: str, current_data: FinancieData) -> None:
    """
    DataFrameを更新し、CSVファイルとして保存します。

    当日のデータが既に存在する場合は上書きし、存在しない場合は新しい行として追加します。

    Args:
        df (pd.DataFrame): 更新対象のDataFrame。
        file_path (str): 保存先のCSVファイルのパス。
        today_str (str): 今日の日付文字列 (YYYY-MM-DD)。
        current_data (FinancieData): 当日のデータ。
    """
    today_data_row = {
        "date": today_str,
        "members": current_data["owner_count"],
        "price": current_data["token_price"],
        "stock": current_data["token_stock"]
    }

    if today_str in df["date"].values:
        df.loc[df["date"] == today_str, list(today_data_row.keys())] = list(today_data_row.values())
        print(f"Updated existing entry for {today_str} in {file_path}.")
    else:
        new_df = pd.DataFrame([today_data_row])
        df = pd.concat([df, new_df], ignore_index=True)
        print(f"Added new entry for {today_str} to {file_path}.")

    df.to_csv(file_path, index=False)
    print(f"Saved {file_path}. Tail:\n{df.tail()}")


def format_discord_message(post_time: datetime, current_data: FinancieData, diffs: DiffData) -> str:
    """
    Discordに投稿するためのメッセージ文字列をフォーマットします。

    Args:
        post_time (datetime): 投稿時刻。
        current_data (FinancieData): 当日のデータ。
        diffs (DiffData): 前日比のデータ。

    Returns:
        str: フォーマットされたメッセージ。
    """
    member_diff, price_diff, stock_diff = diffs
    message = f"""◆FiNANCiE開運オロチトークン現在情報（{post_time.strftime('%Y年 %m月%d日 %H:%M時点')}）
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

    URLが設定されていない場合は、メッセージを送信せずに処理をスキップします。

    Args:
        webhook_url (Optional[str]): DiscordのWebhook URL。
        message (str): 送信するメッセージ。
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
    データの取得、処理、通知の全体の流れを制御します。
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

    yesterday_data: Optional[pd.Series] = None
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df_past = df[df['date'] < pd.to_datetime(today_str)].copy()

        if not df_past.empty:
            yesterday_data = df_past.sort_values(by='date', ascending=False).iloc[0]
            print(f"Yesterday's data: {yesterday_data.to_dict()}")
        else:
            print("No past data found for yesterday's calculation.")
        # 日付を文字列に戻す
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')

    diffs = calculate_diffs(financie_data, yesterday_data)

    update_stats_csv(df, STATS_CSV_PATH, today_str, financie_data)

    # 投稿時刻をAM6:00に固定
    post_time_fixed = now.replace(hour=6, minute=0, second=0, microsecond=0)
    message = format_discord_message(post_time_fixed, financie_data, diffs)

    send_discord_notification(DISCORD_WEBHOOK_URL, message)
    print("Script finished.")


if __name__ == "__main__":
    main()
