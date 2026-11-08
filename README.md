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

### Recommended: automatic, from your calendar
Concert Archives adds every show to a Google Calendar called **Sanchit's Concert Archive**. Every 10 minutes, `.github/workflows/sync-calendar.yml` reads that calendar, merges any new or changed shows into `data/concerts.csv` (`scripts/sync_calendar.py`), and redeploys the site. You don't have to export anything.

One-time setup:
1. Find the calendar feed link Concert Archives gave you when you set up calendar sync. Look in your Concert Archives account or settings for "calendar", "sync", "iCal" or "subscribe". It usually starts with `webcal://` or `https://` and may end in `.ics`. (Google Calendar won't show it, because that calendar is an import, `…@import.calendar.google.com`.)
2. In this repo, go to **Settings → Secrets and variables → Actions → New repository secret**. Name it `CALENDAR_ICS_URL` and paste the link. `webcal://` links work as-is.
3. Under **Actions → Sync from calendar → Run workflow**, run it once now. After that it runs every 10 minutes, so a new show appears on the site about 10–15 minutes after it lands on your calendar.

Treat the feed link like a password: keep it in the secret only, never in a file. The sync only adds or updates shows and never deletes any. A show that's been cancelled still needs a fresh export to be marked Cancelled.

### Option A: upload by hand
On GitHub, open `data/`, click **Add file → Upload files**, drop in the export, and rename it to `concerts.csv` (or `concerts.xlsx`). The site redeploys in about a minute.

### Option B: automatic (Gmail → GitHub)
`automation/gmail-to-github.gs` is a Google Apps Script that checks your Gmail every hour for the Concert Archives export email and commits the attachment for you. Setup steps are at the top of the file. After that, the only manual step is clicking **Export to Spreadsheet** after you log new shows.

### Option C: the robot (fully automatic, runs on your Mac)
`robot/scrape.mjs` opens your Concert Archives profile in **your own Google Chrome**, reads every show, saves `data/concerts.csv` in the same columns as the official export, and pushes it. It runs on your computer rather than in the cloud because Concert Archives blocks cloud servers.

One-time setup (needs [Node.js](https://nodejs.org) and Google Chrome):
```sh
git clone https://github.com/sanchitcop19/concerts.git && cd concerts
bash robot/install-mac.sh             # installs and schedules a daily run at 7:23pm
node robot/scrape.mjs --headed        # first run: watch it work and click Cloudflare's checkbox if asked
```
- Log: `~/Library/Logs/concert-robot.log`
- Run it now: `launchctl kickstart gui/$(id -u)/com.concerts.robot`
- Uninstall: `bash robot/install-mac.sh remove`
- If it says "Found no shows", it saved `robot/debug.html`. Share that file so the parser can be adjusted.
- Safety net: it won't overwrite the CSV if it suddenly finds 20%+ fewer shows (e.g. a half-loaded page).
- Limitation: it can't see whether a show was cancelled, so cancelled shows count as attended. The manual export doesn't have this problem.

## iPhone app
Two ways to get it on your phone:

**Quick: Add to Home Screen.** Open the site in Safari, tap Share, then **Add to Home Screen**. It gets the app icon and opens full-screen.

**Real app (Xcode).** `ios/` holds a small SwiftUI app with four tabs: **Home** (show count and the next 2 weeks), **Stats** (all-time numbers and charts), **Years** (a year picker with that year in review) and **Shows** (search and every show). Each tab is the live site opened with `?view=home|stats|years|shows`, so data and design updates appear without a new build. Pages don't bounce, and each tab refreshes when you come back to the app. Swipe back works on artist, venue and concert pages, Concert Archives links open in Safari, and it falls back to the last copy it loaded when you're offline.
```sh
brew install xcodegen          # one time
cd ios && xcodegen             # creates Concerts.xcodeproj
open Concerts.xcodeproj
```
In Xcode, open the **Concerts** target, go to **Signing & Capabilities**, and pick your team. Plug in your iPhone (turn on Settings → Privacy & Security → Developer Mode the first time), choose it as the run destination, and press ▶. To install without a cable, use **Product → Archive → Distribute App → TestFlight**.

The app icon is drawn by `icons/make_icons.py` (`python3 icons/make_icons.py` regenerates every size).

## One-time GitHub Pages setup
Repo **Settings → Pages → Source: GitHub Actions**. Every push to `master` then deploys via `.github/workflows/deploy.yml`.

## Run locally
```sh
python3 -m http.server
# open http://localhost:8000
```
