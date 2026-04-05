# Automated pipeline demo script.

**To see periodic running of script, please proceed to GitHub Actions tab (Reddit Virality Monitor workflow).**

For the automated pipeline, set two environment variables in GitHub Actions secrets:

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

1. Clone the Repository
git clone https://github.com/your-username/your-repo.git
cd your-repo

2. Create Virtual Environment
macOS / Linux
```bash
python3 -m venv venv
source venv/bin/activate
```

Windows
```bash
python -m venv venv
venv\Scripts\activate
```

3. Install Dependencies
```bash
pip install --upgrade pip
pip install aiohttp pandas requests
```

4. Configure Scraper Mode
Set how much historical data to pull using TIME_FILTER:
macOS / Linux
```bash
export TIME_FILTER=hour
```

Windows (PowerShell)
```bash
$env:TIME_FILTER="hour"
```

Windows (CMD)
```bash
set TIME_FILTER=hour
```

5. Run Scraper
```bash
python scrapers/reddit_scraper.py
```

6. Run Enrichment (Comments + Authors)
After scraping:
```bash
python scrapers/reddit_enrichment.py
```