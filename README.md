# Vantage

A free stock research site. You type a ticker and read a scored checklist: growth, profitability, balance sheet,
valuation, trust and red flags, risks, and market behavior. No paid APIs, no AI calls, no API keys.

It is a research aid, not financial advice. It never gives buy, sell, or hold ratings.

## How it works

1. `tickers.json` is your list of stocks.
2. A GitHub Action (`.github/workflows/update-reports.yml`) runs `scripts/build_reports.py` every weekday after the US
   market closes. The script pulls public data from Yahoo Finance (through the `yfinance` library), calculates every
   metric in code, scores each one, and saves `data/reports.json`.
3. `index.html` reads that file and displays the report. Until the first run, it shows `data/sample.json`
   (a made-up company called Demo Company) so you can see the layout.

## Set it up (about 10 minutes)

1. Create a GitHub account if you do not have one, then create a **new public repository** (for example, `vantage`).
2. Upload every file and folder from this project into it. In the repository, choose **Add file > Upload files**
   and drag everything in. Keep the folder structure, including the hidden `.github` folder.
   Tip: if the `.github` folder will not upload by drag and drop, use **Add file > Create new file**, type
   `.github/workflows/update-reports.yml` as the file name, and paste the contents of that file.
3. Go to **Settings > Actions > General > Workflow permissions** and choose **Read and write permissions**. Save.
4. Go to **Settings > Pages**. Under Source choose **Deploy from a branch**, pick the `main` branch and the `/ (root)`
   folder, and save. Your site appears at `https://YOUR-USERNAME.github.io/REPO-NAME/` after a minute or two.
5. Go to the **Actions** tab, choose **Update reports**, and click **Run workflow**. When it finishes (a couple of
   minutes), refresh your site. You now see real reports instead of the sample.

## Change your stock list

Edit `tickers.json`. Use plain tickers for US stocks and add `.TO` for Toronto Stock Exchange stocks, for example
`["AAPL", "MSFT", "SHOP.TO", "RY.TO"]`. Saving the file triggers a fresh run automatically.

## Change how things are scored

Open `scripts/build_reports.py` and edit the `T` table at the top. Each line holds a "strong" cutoff, a "concern"
cutoff, and a plain-English rule. The rules are shown on the site under "See the rules behind every rating".
The thresholds are blunt on purpose. Banks, utilities, and software companies are not alike, so adjust them for the
kinds of stocks you follow.

## Test it on your own computer (optional)

```
pip install -r requirements.txt
python scripts/build_reports.py
python -m http.server 8000
```
Then open http://localhost:8000. (Opening index.html by double-clicking will not load the data file.)

## Limits to know about

- Yahoo data through `yfinance` is unofficial. It can be delayed, incomplete, or break when Yahoo changes things.
  Spot-check important numbers against the company's own filings.
- Insider activity from Yahoo is limited. The report links to the official SEC Form 4 filings.
- Moat, management quality, competition, and legal risk cannot be scored by code. Each report lists them as
  questions with links so you can judge them yourself.
- Reports update once per weekday, so prices are not live.
- The watchlist is saved in your own browser only.
- This is for personal research. Do not redistribute the data without checking the data provider's terms.
