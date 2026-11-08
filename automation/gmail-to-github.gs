/**
 * Concert Archives -> GitHub auto-sync (Google Apps Script)
 *
 * Concert Archives has no API and blocks bots, but it emails you a spreadsheet
 * when you click "Export to Spreadsheet". This script watches your Gmail for that
 * email and commits the attachment to the repo as data/concerts.csv (or .xlsx).
 * The GitHub Action then redeploys the dashboard automatically.
 *
 * Setup (one time, ~5 min):
 *   1. Go to https://script.google.com -> New project, paste this file in.
 *   2. Project Settings -> Script Properties -> add:
 *        GITHUB_TOKEN = a fine-grained token with "Contents: Read and write"
 *                       on ONLY the concerts repo
 *        GITHUB_REPO  = sanchitcop19/concerts
 *   3. Run `syncConcerts` once and approve the Gmail permission prompt.
 *   4. Run `installTrigger` once. It then checks Gmail every hour.
 */

const GMAIL_QUERY = 'from:concertarchives.org has:attachment newer_than:30d';
const BRANCH = 'master';

function syncConcerts() {
  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty('GITHUB_TOKEN');
  const repo = props.getProperty('GITHUB_REPO');
  if (!token || !repo) throw new Error('Set GITHUB_TOKEN and GITHUB_REPO in Script Properties.');

  const lastSeen = Number(props.getProperty('LAST_MESSAGE_TIME') || 0);
  const threads = GmailApp.search(GMAIL_QUERY, 0, 10);
  let newest = null;
  for (const thread of threads) {
    for (const msg of thread.getMessages()) {
      const t = msg.getDate().getTime();
      if (t <= lastSeen) continue;
      const att = msg.getAttachments().find(a => /\.(csv|xlsx)$/i.test(a.getName()));
      if (att && (!newest || t > newest.time)) newest = { time: t, att };
    }
  }
  if (!newest) { console.log('No new export email.'); return; }

  const ext = /\.xlsx$/i.test(newest.att.getName()) ? 'xlsx' : 'csv';
  const path = `data/concerts.${ext}`;
  putFile_(repo, token, path, newest.att.getBytes(), `Update concerts from Concert Archives export (${new Date(newest.time).toISOString().slice(0, 10)})`);
  // Remove the other format so the dashboard never reads a stale file.
  deleteFile_(repo, token, `data/concerts.${ext === 'csv' ? 'xlsx' : 'csv'}`);
  props.setProperty('LAST_MESSAGE_TIME', String(newest.time));
  console.log(`Committed ${path}`);
}

function installTrigger() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('syncConcerts').timeBased().everyHours(1).create();
}

function api_(repo, token, path, method, payload) {
  const res = UrlFetchApp.fetch(`https://api.github.com/repos/${repo}/contents/${path}`, {
    method, muteHttpExceptions: true, contentType: 'application/json',
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json' },
    payload: payload ? JSON.stringify(payload) : undefined,
  });
  return { code: res.getResponseCode(), body: res.getContentText() ? JSON.parse(res.getContentText()) : {} };
}

function currentSha_(repo, token, path) {
  const r = api_(repo, token, `${path}?ref=${BRANCH}`, 'get');
  return r.code === 200 ? r.body.sha : null;
}

function putFile_(repo, token, path, bytes, message) {
  const sha = currentSha_(repo, token, path);
  const r = api_(repo, token, path, 'put', {
    message, branch: BRANCH, content: Utilities.base64Encode(bytes), ...(sha ? { sha } : {}),
  });
  if (r.code >= 300) throw new Error(`GitHub ${r.code}: ${JSON.stringify(r.body)}`);
}

function deleteFile_(repo, token, path) {
  const sha = currentSha_(repo, token, path);
  if (sha) api_(repo, token, path, 'delete', { message: `Remove stale ${path}`, branch: BRANCH, sha });
}
