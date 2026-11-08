# concerts

A personal dashboard for my [Concert Archives](https://www.concertarchives.org/sanchitcop19) history: shows per year, by month and day of week, most-seen artists, top venues and cities, plus a searchable list of every show.

It's one static page (`index.html`) hosted on GitHub Pages. No build step.

## How the data gets in

Concert Archives has no public API and blocks automated scraping, so the data comes from its built-in **Export to Spreadsheet** feature (hover your avatar on the website, then pick "Export to Spreadsheet"). The file is emailed to you.

The dashboard reads the first of these files it finds:

1. `data/concerts.csv`
2. `data/concerts.xlsx`
3. `data/sample.csv` (made-up demo data, shown with a yellow banner)

Column names are detected automatically (date, bands/artists, venue, city, state, country). The page footer shows which column it mapped to each field.

### Option A: upload by hand
On GitHub, open `data/`, click **Add file → Upload files**, drop in the export, and rename it to `concerts.csv` (or `concerts.xlsx`). The site redeploys in about a minute.

### Option B: automatic (Gmail → GitHub)
`automation/gmail-to-github.gs` is a Google Apps Script that checks your Gmail every hour for the Concert Archives export email and commits the attachment for you. Setup steps are at the top of the file. After that, the only manual step is clicking **Export to Spreadsheet** after you log new shows.

## One-time GitHub Pages setup
Repo **Settings → Pages → Source: GitHub Actions**. Every push to `master` then deploys via `.github/workflows/deploy.yml`.

## Run locally
```sh
python3 -m http.server
# open http://localhost:8000
```
