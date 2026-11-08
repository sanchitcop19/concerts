#!/usr/bin/env node
// Concert robot: opens your Concert Archives profile in YOUR Chrome, reads your shows,
// writes data/concerts.csv and pushes it so the dashboard updates.
//
//   node robot/scrape.mjs            # normal run (hidden browser)
//   node robot/scrape.mjs --headed   # show the browser (use if Cloudflare asks you to click)
//   node robot/scrape.mjs --no-push  # update the CSV but don't commit/push
import { chromium } from 'playwright';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { extractRows } from './extract.mjs';

const USER = process.env.CA_USER || 'sanchitcop19';
const START_URL = `https://www.concertarchives.org/${USER}`;
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CSV_PATH = path.join(ROOT, 'data', 'concerts.csv');
const PROFILE_DIR = path.join(os.homedir(), '.concert-robot-profile');
const HEADED = process.argv.includes('--headed');
const PUSH = !process.argv.includes('--no-push');
const MAX_PAGES = 50;

const sh = cmd => execSync(cmd, { cwd: ROOT, stdio: 'pipe' }).toString().trim();
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function open(page, url) {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  // Cloudflare's "Just a moment..." page normally clears by itself in a real browser.
  // In --headed mode you get 5 minutes to click the checkbox if it asks.
  const deadline = Date.now() + (HEADED ? 300_000 : 60_000);
  while (/just a moment|attention required/i.test(await page.title())) {
    if (Date.now() > deadline) {
      throw new Error('Cloudflare check did not clear. Run once with --headed and click the checkbox; it will be remembered.');
    }
    await sleep(2000);
  }
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
}

function toCsv(rows) {
  const q = v => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  const lines = [['Date', 'Concert Name', 'Bands', 'Venue', 'Location', 'URL'].join(',')];
  for (const r of rows) lines.push([r.date, r.title, r.bands.join('; '), r.venue, r.location, r.url].map(q).join(','));
  return lines.join('\n') + '\n';
}

async function main() {
  if (PUSH) sh('git pull --ff-only --quiet');

  const ctx = await chromium.launchPersistentContext(PROFILE_DIR, {
    channel: 'chrome', // your installed Google Chrome, not a bundled test browser
    headless: !HEADED,
  });
  const page = ctx.pages()[0] || (await ctx.newPage());
  const all = new Map();
  try {
    let url = START_URL;
    for (let n = 1; url && n <= MAX_PAGES; n++) {
      await open(page, url);
      const { rows, next } = await page.evaluate(extractRows);
      console.log(`page ${n}: ${rows.length} shows`);
      if (!rows.length && n === 1) {
        fs.writeFileSync(path.join(ROOT, 'robot', 'debug.html'), await page.content());
        throw new Error('Found no shows on the page. Saved robot/debug.html; share it so the parser can be fixed.');
      }
      rows.forEach(r => all.set(r.url, r));
      url = next && next !== url ? next : null;
      if (url) await sleep(3000); // be polite: one page every few seconds
    }
  } finally {
    await ctx.close();
  }

  const rows = [...all.values()].sort((a, b) => b.date.localeCompare(a.date));
  // Safety net: never replace a good file with a much smaller one (e.g. a half-loaded page).
  if (fs.existsSync(CSV_PATH)) {
    const before = fs.readFileSync(CSV_PATH, 'utf8').trim().split('\n').length - 1;
    if (rows.length < before * 0.8) {
      throw new Error(`Only found ${rows.length} shows but the file has ${before}. Not overwriting.`);
    }
  }
  fs.writeFileSync(CSV_PATH, toCsv(rows));
  console.log(`Saved ${rows.length} shows to data/concerts.csv`);

  if (!PUSH) return;
  sh('git add data/concerts.csv');
  if (!sh('git diff --cached --name-only')) {
    console.log('No changes since last run.');
    return;
  }
  sh(`git commit -m "Update concerts (${rows.length} shows)" --quiet`);
  sh('git push --quiet');
  console.log('Pushed. The dashboard will update in about a minute.');
}

main().catch(err => {
  console.error(`Concert robot failed: ${err.message}`);
  process.exit(1);
});
