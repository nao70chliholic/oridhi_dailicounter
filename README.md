# Daily Stats Poster

This project automatically posts daily statistics (token price and member count) to Discord.

## 対象コミュニティ

1つのスクリプトで複数のFiNANCiEコミュニティを扱う。環境変数を設定しなければ
既定値（開運オロチ）で動くので、オロチ側のワークフローは何も渡していない。

| 環境変数 | 既定値（開運オロチ） | CNPスタープロジェクト |
|---|---|---|
| `FINANCIE_SLUG` | `orochi_cnp` | `cnpninjadao` |
| `STATS_CSV_PATH` | `stats.csv` | `stats_cnp.csv` |
| `TITLE_PREFIX` | `FiNANCiE開運オロチトークン` | `FiNANCiE CNPスタープロジェクト` |
| `POST_HASHTAGS` | `#CNPオロチ #開運オロチ` | `#CNPスタープロジェクト #CNPトークン` |
| `COMMUNITY_OPEN_DATE` | `2025-01-17` | 空（「オープンN日目」を出さない） |

**Discordへの投稿は任意。** `DISCORD_WEBHOOK_URL` が未設定なら投稿をスキップし、
CSVへの記録だけ行う。CNP側は Secrets の `DISCORD_WEBHOOK_URL_CNP` を追加した時点で
投稿が始まる（コード変更は不要）。

両方のジョブが同じリポジトリにCSVをコミットするため、
ワークフローは `concurrency: stats-commit` で直列化している。

CNP側の週報ワークフローはまだ置いていない。週報は「その週の土曜」と「前週の土曜」の
2行を必要とするので、2週分たまるまでは必ず失敗するため。
`weekly_report.yml` をコピーして上表の環境変数を足せば動く。

## stats.csv の列

| 列 | 意味 | 出典 |
|---|---|---|
| `date` | 日付 (JST) | |
| `members` | コミュニティのメンバー数 | コミュニティページ |
| `price` | トークン価格 (円) | `bancor.latest_price` |
| `stock` | 販売在庫 (枚)。減る＝買われた | `market.stock` |
| `volume` | 過去24時間の**売買代金 (円)** | `market.trading_volume` |
| `cap` | 時価総額 (円) | `market.capitalization` |

`volume` / `cap` は 2026-09 に追加した列。
market APIのレスポンスには元から含まれていたが取得していなかった値で、
過去分は遡って取れないため、それ以前の行は空欄。

**⚠️ `trading_volume` の単位は「円」。枚ではない。**
2026-09-12に実際の売買（売り511枚）と突き合わせて確定した。
当初「枚」と誤判定し、`buy` / `sell` 列と投稿の内訳表示を約10倍過大に出していたため、
両列と内訳表示を削除した。

買い/売りの内訳を出すには 円→枚 の換算が要り、片側に偏った日は小さい側の誤差率が大きくなる。
そのため**内訳は出さず、売買代金(円)のみを表示する**（APIの値そのままで換算誤差がゼロ）。

正味の増減が要る場合は `stock` の差分を使う（在庫が減る＝買われた）。こちらは枚で正確。

## Local Execution

To run the `stats.py` script locally, follow these steps:

1.  **Activate Virtual Environment and Install Dependencies:**
    ```bash
    source .venv/bin/activate && pip install -r requirements.txt
    ```

2.  **Install Playwright Browsers:**
    ```bash
    source .venv/bin/activate && playwright install --with-deps chromium
    ```

3.  **Configure Environment Variables:**
    Create a `.env` file in the project root directory based on `.env.example`.
    ```
    FINANCIE_COMM_ID=your_financie_community_id
    DISCORD_WEBHOOK=your_discord_webhook_url
    ```
    **Note:** These are sensitive credentials and should not be committed to public repositories.

4.  **Run the Script:**
    ```bash
    source .venv/bin/activate && python stats.py
    ```

## Manual Backfill (Optional)

If the bot skipped a day and you still know the correct numbers, you can insert or update the previous day's row automatically by setting the following environment variables before running the script:

```
MANUAL_YESTERDAY_DATE=YYYY-MM-DD  # Optional. Defaults to "today - 1 day"
MANUAL_YESTERDAY_MEMBERS=xxxxx
MANUAL_YESTERDAY_PRICE=xx.xxxx
MANUAL_YESTERDAY_STOCK=xxxxx
```

Example:

```bash
export MANUAL_YESTERDAY_DATE=2025-11-18
export MANUAL_YESTERDAY_MEMBERS=22300
export MANUAL_YESTERDAY_PRICE=11.5000
export MANUAL_YESTERDAY_STOCK=50500
source .venv/bin/activate && python stats.py
unset MANUAL_YESTERDAY_DATE MANUAL_YESTERDAY_MEMBERS MANUAL_YESTERDAY_PRICE MANUAL_YESTERDAY_STOCK
```

The script writes the supplied values to `stats.csv` before calculating the current day's differences, so the Discord post uses your corrected “previous day” data. Remember to clear the variables after backfilling.
