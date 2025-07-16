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

            return members, price

        except Exception as e:
            print(f"スクレイピングエラー: {e}")
            raise
        finally:
            browser.close()

def get_last_stats() -> tuple[int | None, float | None]:
    """CSVから最新の統計データを読み込む"""
    if not CSV_PATH.exists():
        return None, None
    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader, None)  # ヘッダーをスキップ
        last_row = None
        for row in reader:
            last_row = row
        if last_row:
            return int(last_row[1]), float(last_row[2])
    return None, None

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
        members, price = get_financie_stats_with_playwright()
    except Exception:
        return

    last_f, last_p = get_last_stats()

    diff_f = f"{members - last_f:+,}" if last_f is not None else "―"
    diff_p = f"{price - last_p:+.4f}" if last_p is not None else "―"

    message = (
        message = (        f"◆FiNANCiE開運オロチトークン現在情報（{datetime.now(JST).strftime('%Y年%m月%d日')} 6時時点）\n"        f"・メンバー数 {members:,}人（前日比 {diff_f}人）\n"        f"・トークン価格 {price:.4f}円（前日比 {diff_p}円）\n"        f"#CNPオロチ #開運オロチ"    )
    )
    print(message)

    post_to_discord(message)

    file_exists = CSV_PATH.exists()
    with open(CSV_PATH, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['date', 'followers', 'price_jpy'])
        writer.writerow([today_str, members, price])
    print(f"Successfully saved data to {CSV_PATH}")

if __name__ == '__main__':
    main()
