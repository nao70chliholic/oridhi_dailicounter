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
    print("Starting web scraping...")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        try:
            print(f"Navigating to {FINANCIE_URL}")
            page.goto(FINANCIE_URL, timeout=60000)
            html_content = page.content()
            print("Successfully fetched page content.")
            # print(f"HTML Content: {html_content[:500]}...") # HTMLの先頭500文字をログ出力

            # メンバー数の要素を取得
            member_element = page.query_selector(".profile_databox .profile_num")
            if member_element:
                member_text = member_element.inner_text()
                print(f"Raw member text found: {member_text}")
                # 数字のみを抽出
                members = int(re.sub(r'[^0-9]', '', member_text))
                print(f"Parsed member count: {members}")
                return {"owner_count": members}
            else:
                print("Could not find member count element. Check selector.")
                return None
        except Exception as e:
            print(f"Error scraping data from FiNANCiE: {e}")
            return None
        finally:
            browser.close()
            print("Browser closed.")

def read_stats_csv(file_path):
    """stats.csvを読み込む。ファイルが存在しない場合は新しいDataFrameを作成する"""
    try:
        df = pd.read_csv(file_path)
        print(f"Successfully read {file_path}. Head:\n{df.head()}")
        return df
    except FileNotFoundError:
        print(f"{file_path} not found. Creating new DataFrame.")
        return pd.DataFrame(columns=["date", "members"])

def calculate_diffs(current_data, yesterday_data):
    """前日比を計算する"""
    if yesterday_data is not None:
        member_diff = current_data["owner_count"] - yesterday_data["members"]
        print(f"Calculated member diff: {member_diff}")
    else:
        member_diff = 0
        print("No yesterday's data found. Member diff set to 0.")
    return member_diff

def update_stats_csv(df, file_path, today_str, current_data):
    """stats.csvを更新または新規書き込みする"""
    today_data_row = {
        "date": today_str,
        "members": current_data["owner_count"],
    }
    
    if today_str in df["date"].values:
        df.loc[df["date"] == today_str, ["members"]] = [today_data_row["members"]]
        print(f"Updated existing entry for {today_str} in {file_path}.")
    else:
        new_df = pd.DataFrame([today_data_row])
        df = pd.concat([df, new_df], ignore_index=True)
        print(f"Added new entry for {today_str} to {file_path}.")
        
    df.to_csv(file_path, index=False)
    print(f"Saved {file_path}. Tail:\n{df.tail()}")

def format_discord_message(post_time, current_data, diffs):
    """Discordへの投稿メッセージを作成する"""
    member_diff = diffs
    message = f"""◆FiNANCiE開運オロチトークン現在情報（{post_time.strftime('%Y年 %m月%d日 %H:%M時点')}）
・メンバー数 {current_data["owner_count"]:,}人（前日比 {member_diff:+,}人）
#CNPオロチ #開運オロチ
"""
    print(f"Formatted Discord message:\n{message}")
    return message

def send_discord_notification(webhook_url, message):
    """Discordにメッセージを投稿する"""
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL is not set. Skipping Discord notification.")
        return
    try:
        response = requests.post(webhook_url, json={"content": message})
        response.raise_for_status()
        print("Successfully sent notification to Discord.")
    except requests.exceptions.RequestException as e:
        print(f"Error sending notification to Discord: {e}")

def main():
    """メイン処理"""
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
    
    yesterday_data = None
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        df_past = df[df['date'] < pd.to_datetime(today_str)].copy()
        
        if not df_past.empty:
            df_past.sort_values(by='date', ascending=False, inplace=True)
            yesterday_data = df_past.iloc[0]
            print(f"Yesterday's data: {yesterday_data.to_dict()}")
        else:
            print("No past data found for yesterday's calculation.")
        
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')

    diffs = calculate_diffs(financie_data, yesterday_data)
    
    update_stats_csv(df, STATS_CSV_PATH, today_str, financie_data)
    
    post_time_fixed = now.replace(hour=6, minute=0, second=0, microsecond=0)
    message = format_discord_message(post_time_fixed, financie_data, diffs)
    
    send_discord_notification(DISCORD_WEBHOOK_URL, message)
    print("Script finished.")

if __name__ == "__main__":
    main()