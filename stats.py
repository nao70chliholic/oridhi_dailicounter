import os
import csv
import re
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# --- 定数 ---
JST = timezone(timedelta(hours=+9), 'JST')
BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / 'stats.csv'

# FiNANCiEのコミュニティ公開WebページのURL
FINANCIE_MEMBER_URL = 'https://financie.jp/users/orochi_cnp'
FINANCIE_PRICE_URL = 'https://financie.jp/communities/orochi_cnp/market'

# --- 環境変数を読み込み ---
load_dotenv()
DISCORD_WEBHOOK = os.getenv('DISCORD_WEBHOOK')

def get_financie_stats_with_playwright() -> tuple[int, float]:
    """Playwrightを使用してFiNANCiEのWebページをスクレイピングしてメンバー数とトークン価格を取得"""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            # --- メンバー数を取得 ---
            page_member = browser.new_page()
            page_member.goto(FINANCIE_MEMBER_URL)
            page_member.wait_for_selector('#script__trading_card_rate') # 要素が表示されるまで待機
            html_member = page_member.content()
            soup_member = BeautifulSoup(html_member, 'lxml')

            member_span = soup_member.find('span', id='script__trading_card_rate')
            if not member_span:
                raise ValueError("メンバー数の要素が見つかりません")
            
            full_member_text = member_span.get_text(strip=True)
            members_match = re.search(r'(\d{1,3}(?:,\d{3})*)', full_member_text)
            if not members_match:
                raise ValueError("メンバー数の数値が見つかりません")
            members = int(members_match.group(1).replace(',', ''))

            # --- トークン価格を取得 ---
            page_price = browser.new_page()
            page_price.goto(FINANCIE_PRICE_URL)
            page_price.wait_for_selector('.js-bancor-latest-price') # 要素が表示されるまで待機
            html_price = page_price.content()
            soup_price = BeautifulSoup(html_price, 'lxml')

            price_span = soup_price.find('span', class_='js-bancor-latest-price')
            if not price_span:
                raise ValueError("トークン価格の要素が見つかりません")
            
            connector_price_span = price_span.find('span', class_='connector-price')
            if not connector_price_span:
                raise ValueError("トークン価格のコネクタ要素が見つかりません")

            int_part_el = connector_price_span.find('span', class_='int-part')
            float_part_el = connector_price_span.find('span', class_='float-part')

            if not int_part_el or not float_part_el:
                raise ValueError("トークン価格の整数部または小数部の要素が見つかりません")

            int_part = int_part_el.get_text(strip=True)
            float_part = float_part_el.get_text(strip=True)
            price = float(int_part + float_part)

            # --- トークン在庫を取得 ---
            token_supply_span = soup_price.find('span', class_='currency int-part')
            if not token_supply_span:
                raise ValueError("トークン在庫の要素が見つかりません")
            token_supply = int(token_supply_span.get_text(strip=True).replace(',', ''))

            return members, price, token_supply

        except Exception as e:
            print(f"スクレイピングエラー: {e}")
            raise
        finally:
            browser.close()

def get_last_stats() -> tuple[int | None, float | None, int | None]:
    """CSVから最新の統計データを読み込む"""
    if not CSV_PATH.exists():
        return None, None, None
    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader, None)  # ヘッダーを読み込む
        if not header:
            return None, None, None

        # 日付ごとの最新データを格納する辞書
        daily_stats = {}
        for row in reader:
            try:
                date_str = row[0]
                members = int(row[1])
                price = float(row[2])
                token_supply = int(row[3]) if len(row) > 3 else None # トークン在庫を追加
                daily_stats[date_str] = (members, price, token_supply)
            except (ValueError, IndexError) as e:
                print(f"CSVの行の解析エラー: {row}, エラー: {e}")
                continue

        if not daily_stats:
            return None, None, None

        # 日付をソートして最新の日付と前日の日付を取得
        sorted_dates = sorted(daily_stats.keys())
        
        # 最新の日付のデータ
        latest_date = sorted_dates[-1]
        
        # 前日の日付のデータ
        previous_date = None
        if len(sorted_dates) >= 2:
            previous_date = sorted_dates[-2]

        if previous_date:
            return daily_stats[previous_date]
        else:
            # 前日のデータがない場合は、最新のデータを使用（初回実行時など）
            return daily_stats[latest_date]
    return None, None, None

def post_to_discord(message: str):
    """Discord Webhook へメッセージを投稿"""
    if not DISCORD_WEBHOOK:
        print("Discord Webhook URL is not set. Skipping.")
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={'content': message})
    except requests.exceptions.RequestException as e:
        print(f"Discord Error: {e}")

def main():
    """メイン処理"""
    today_str = datetime.now(JST).strftime('%Y-%m-%d')

    try:
        members, price, token_supply = get_financie_stats_with_playwright()
    except Exception:
        return

    last_f, last_p, last_ts = get_last_stats()

    diff_f = f"{members - last_f:+,}" if last_f is not None else "―"
    diff_p = f"{price - last_p:+.4f}" if last_p is not None else "―"
    diff_ts = f"{token_supply - last_ts:+,}" if last_ts is not None else "―"

    message = f"""◆FiNANCiE開運オロチトークン現在情報（{datetime.now(JST).strftime('%Y年%_m月%_d日')} 6時時点）
・メンバー数 {members:,}人（前日比 {diff_f}人）
・トークン価格 {price:.4f}円（前日比 {diff_p}円）
・トークン在庫 {token_supply:,}枚（前日比 {diff_ts}枚）
#CNPオロチ #開運オロチ"""
    print(message)

    post_to_discord(message)

    file_exists = CSV_PATH.exists()
    with open(CSV_PATH, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['date', 'followers', 'price_jpy', 'token_supply'])
        writer.writerow([today_str, members, price, token_supply])
    print(f"Successfully saved data to {CSV_PATH}")

if __name__ == '__main__':
    main()
