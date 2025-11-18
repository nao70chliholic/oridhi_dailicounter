# Daily Stats Poster

This project automatically posts daily statistics (token price and member count) to Discord.

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
