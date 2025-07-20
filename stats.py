import os
import re
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright
import requests

# 環境変数の読み込み
load_dotenv()
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
FINANCIE_URL = "https://financie.jp/communities/orochi_cnp/"
STATS_CSV_PATH = "stats.csv"

def get_financie_data_from_web():
    """FiNANCiEのWebページからメンバー数を取得する"""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            page.goto(FINANCIE_URL, timeout=60000)
            # メンバー数の要素を取得
            member_element = page.query_selector(".profile_databox .profile_num")
            if member_element:
                member_text = member_element.inner_text()
                # 数字のみを抽出
                members = int(re.sub(r'[^0-9]', '', member_text))
                return {"owner_count": members}
            else:
                print("Could not find member count element.")
                return None
        except Exception as e:
            print(f"Error scraping data from FiNANCiE: {e}")
            return None
        finally:
            browser.close()

def read_stats_csv(file_path):
    """stats.csvを読み込む。ファイルが存在しない場合は新しいDataFrameを作成する"""
    try:
        return pd.read_csv(file_path)
    except FileNotFoundError:
        return pd.DataFrame(columns=["date", "members"])

def calculate_diffs(current_data, yesterday_data):
    """前日比を計算する"""
    if yesterday_data is not None:
        member_diff = current_data["owner_count"] - yesterday_data["members"]
    else:
        member_diff = 0
    return member_diff

def update_stats_csv(df, file_path, today_str, current_data):
    """stats.csvを更新または新規書き込みする"""
    today_data_row = {
        "date": today_str,
        "members": current_data["owner_count"],
    }
    
    if today_str in df["date"].values:
        df.loc[df["date"] == today_str, ["members"]] = [today_data_row["members"]]
    else:
        new_df = pd.DataFrame([today_data_row])
        df = pd.concat([df, new_df], ignore_index=True)
        
    df.to_csv(file_path, index=False)

def format_discord_message(post_time, current_data, diffs):
    """Discordへの投稿メッセージを作成する"""
    member_diff = diffs
    message = f"""◆FiNANCiE開運オロチトークン現在情報（{post_time.strftime('%Y年 %m月%d日 %H:%M時点')}）
・メンバー数 {current_data["owner_count"]:,}人（前日比 {member_diff:+,}人）
#CNPオロチ #開運オロチ
"""
    return message

def send_discord_notification(webhook_url, message):
    """Discordにメッセージを投稿する"""
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL is not set.")
        return
    try:
        response = requests.post(webhook_url, json={"content": message})
        response.raise_for_status()
        print("Successfully sent notification to Discord.")
    except requests.exceptions.RequestException as e:
        print(f"Error sending notification to Discord: {e}")

def main():
    """メイン処理"""
    JST = timezone(timedelta(hours=+9), 'JST')
    now = datetime.now(JST)
    today_str = now.strftime('%Y-%m-%d')

    financie_data = get_financie_data_from_web()
    if not financie_data:
        return

    df = read_stats_csv(STATS_CSV_PATH)
    
    yesterday_data = None
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df_past = df[df['date'] < pd.to_datetime(today_str)].copy()
        
        if not df_past.empty:
            df_past.sort_values(by='date', ascending=False, inplace=True)
            yesterday_data = df_past.iloc[0]
        
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')

    diffs = calculate_diffs(financie_data, yesterday_data)
    
    update_stats_csv(df, STATS_CSV_PATH, today_str, financie_data)
    
    post_time_fixed = now.replace(hour=6, minute=0, second=0, microsecond=0)
    message = format_discord_message(post_time_fixed, financie_data, diffs)
    
    print("Generated message:")
    print(message)
    
    send_discord_notification(DISCORD_WEBHOOK_URL, message)

if __name__ == "__main__":
    main()
