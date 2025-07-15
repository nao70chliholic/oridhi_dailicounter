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
