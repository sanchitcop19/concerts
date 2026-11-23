// End-to-end checks for the "Add a show" flow in index.html, against fixture data and a fake GitHub API.
//   node tests/site.test.cjs          (needs Playwright + Chromium; CI installs them)
const http = require("http"), fs = require("fs"), path = require("path"), assert = require("assert/strict");
const { chromium } = require("playwright");

const ROOT = path.join(__dirname, "..");
const day = n => { const d = new Date(Date.now() + n * 864e5); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
const us = iso => { const [y, m, d] = iso.split("-"); return `${m}/${d}/${y}`; };

// One show already on Concert Archives, one a week ago, and events around them.
const CSV = `Start Date,End Date,Nonstandard Concert Type,Status,Concert Name,Bands Seen,Bands Not Seen,Venue,Location,URL
${us(day(10))},,,Upcoming,,The Pineapple Thief,,Neptune Theatre,"Seattle, Washington, United States",https://www.concertarchives.org/x/concerts/the-pineapple-thief-1
${us(day(-30))},,,Past,,Russian Circles / Primitive Man,,The Showbox,"Seattle, Washington, United States",https://www.concertarchives.org/x/concerts/russian-circles-2
`;
const EVENTS = [
  { id: "tm:1", d: day(10), t: "20:00", n: "The Pineapple Thief", v: "Neptune Theatre", c: "Seattle", s: "Washington", u: "https://www.ticketmaster.com/event/1", m: "Seattle" },
  { id: "tm:2", d: day(3), t: "19:30", n: "Insomnium & Amorphis", a: ["Insomnium", "Amorphis"], v: "The Showbox", c: "Seattle", s: "Washington", u: "https://www.ticketmaster.com/event/2", m: "Seattle" },
  { id: "sl:9:x", d: day(-2), n: "Björk", v: "Climate Pledge Arena", c: "Seattle", s: "Washington", u: "https://www.setlist.fm/x", m: "Seattle" },
  { id: "tm:3", d: day(5), t: "20:00", n: "Some Band", v: "Bowery Ballroom", c: "New York", s: "New York", m: "New York" },
];
const months = [...new Set(EVENTS.map(e => e.d.slice(0, 7)))];
const INDEX = { generated: new Date().toISOString(), from: day(-700), to: day(360), count: EVENTS.length,
  months: Object.fromEntries(months.map(m => [m, 1])), markets: [{ name: "Seattle", cities: ["Seattle"] }, { name: "New York", cities: ["New York"] }] };
// An added show that later also landed on Concert Archives (must not be counted twice), and one that didn't.
const ADDED = { shows: [
  { id: "a-dupe", date: day(-30), bands: ["Russian Circles"], venue: "Showbox", city: "Seattle", state: "Washington" },
  { id: "a-old-1", date: day(-400), bands: ["Hand Added Band"], venue: "Tractor Tavern", city: "Seattle", state: "Washington", country: "United States" },
] };

function serve() {
  const fixtures = { "/data/concerts.csv": CSV, "/data/added.json": JSON.stringify(ADDED), "/data/events/index.json": JSON.stringify(INDEX),
    "/data/times.json": "{}" };
  for (const m of months) fixtures[`/data/events/${m}.json`] = JSON.stringify({ month: m, events: EVENTS.filter(e => e.d.startsWith(m)) });
  const server = http.createServer((req, res) => {
    const p = decodeURIComponent(req.url.split("?")[0]);
    if (p in fixtures) { res.writeHead(200, { "Content-Type": p.endsWith(".csv") ? "text/csv" : "application/json" }); return res.end(fixtures[p]); }
    if (p.startsWith("/data/")) { res.writeHead(404); return res.end(); }
    const f = path.join(ROOT, p === "/" ? "index.html" : p);
    if (!f.startsWith(ROOT) || !fs.existsSync(f)) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "Content-Type": f.endsWith(".html") ? "text/html" : "application/octet-stream" });
    fs.createReadStream(f).pipe(res);
  });
  return new Promise(r => server.listen(0, () => r(server)));
}

// A fake GitHub contents API holding data/added.json.
function fakeGitHub(page, { status = 404, conflictOnce = false } = {}) {
  const gh = { file: status === 200 ? { shows: [] } : null, sha: "s0", puts: [], conflict: conflictOnce, auth: [] };
  page.route("https://api.github.com/**", async route => {
    const req = route.request();
    gh.auth.push(req.headers()["authorization"]);
    if (req.method() === "GET") {
      if (!gh.file) return route.fulfill({ status: 404, body: "{}" });
      return route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ sha: gh.sha, content: Buffer.from(JSON.stringify(gh.file)).toString("base64") }) });
    }
    const body = JSON.parse(req.postData());
    gh.puts.push(body);
    if (gh.conflict) { gh.conflict = false; gh.file = { shows: [{ id: "someone-else", date: "2020-01-01", bands: ["X"] }] }; gh.sha = "s1"; return route.fulfill({ status: 409, body: "{}" }); }
    if (gh.file && body.sha !== gh.sha) return route.fulfill({ status: 409, body: "{}" });
    gh.file = JSON.parse(Buffer.from(body.content, "base64").toString("utf8"));
    gh.sha = "s" + gh.puts.length;
    return route.fulfill({ status: 201, contentType: "application/json", body: "{}" });
  });
  return gh;
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test("added shows are listed, and ones also on Concert Archives aren't counted twice", async (page, url) => {
  await page.goto(url);
  await page.waitForSelector(".show");
  assert.equal(await page.textContent("#heroNum"), "2"); // Russian Circles once + Hand Added Band
  assert.ok((await page.textContent("#list")).includes("Hand Added Band"));
});

test("search finds events, marks ones you have, and prefills the form", async (page, url) => {
  await page.goto(url);
  await page.click("#addBtn");
  await page.waitForSelector("#aRes .ev");
  // Nothing typed: home city only (no New York event), upcoming and recent
  const initial = await page.textContent("#aRes");
  assert.ok(initial.includes("Insomnium") && initial.includes("Björk") && !initial.includes("Some Band"), initial);
  await page.fill("#aq", "pineapple");
  await page.waitForFunction(() => document.querySelectorAll("#aRes .ev").length === 1);
  assert.ok(await page.isVisible("#aRes .ev.have"), "a show already in the archive is marked");
  await page.fill("#aq", "bjork");  // accents don't matter
  await page.waitForFunction(() => document.querySelector("#aRes").textContent.includes("Björk"));
  await page.fill("#aq", "amorphis showbox");
  await page.waitForFunction(() => document.querySelectorAll("#aRes .ev").length === 1 && document.querySelector("#aRes").textContent.includes("Amorphis"));
  await page.click("#aRes .ev");
  assert.equal(await page.inputValue("#fBands"), "Insomnium\nAmorphis");
  assert.equal(await page.inputValue("#fDate"), day(3));
  assert.equal(await page.inputValue("#fVenue"), "The Showbox");
  assert.equal(await page.inputValue("#fCountry"), "United States");
  assert.ok((await page.textContent("#fHint")).startsWith("Coming up"));
});

test("saving asks for a token once, commits to data/added.json, and shows the new show right away", async (page, url) => {
  const gh = fakeGitHub(page);
  await page.goto(url);
  await page.click("#addBtn");
  await page.fill("#aq", "insomnium");
  await page.waitForFunction(() => document.querySelectorAll("#aRes .ev").length === 1 && document.querySelector("#aRes").textContent.includes("Insomnium"));
  await page.click("#aRes .ev");
  await page.click("#fSave");
  await page.waitForSelector("#stepConnect:not([hidden])");
  assert.ok((await page.getAttribute("#tokLink", "href")).includes("contents=write"));
  await page.fill("#tok", "not a token");
  await page.click("#tokSave");
  assert.ok(await page.isVisible("#tokErr"));
  await page.fill("#tok", "github_pat_" + "x".repeat(40));
  await page.click("#tokSave");
  await page.waitForSelector("#toast.on");
  assert.equal(gh.puts.length, 1);
  assert.equal(gh.auth[0], "Bearer github_pat_" + "x".repeat(40));
  const saved = gh.file.shows[0];
  assert.deepEqual(saved.bands, ["Insomnium", "Amorphis"]);
  assert.equal(saved.date, day(3));
  assert.equal(saved.source, "tm:2");
  assert.equal(saved.start, "19:30");
  await page.waitForSelector("#addBg", { state: "hidden" });
  // Shown immediately (upcoming, in the next 2 weeks), and still there after a reload before the deploy
  await page.waitForFunction(() => document.querySelector("#tickets").textContent.includes("Insomnium"));
  await page.reload();
  await page.waitForFunction(() => document.querySelector("#tickets").textContent.includes("Insomnium"));
  // The token is remembered: a second save goes straight through
  await page.click("#addBtn");
  await page.click("#aManual");
  await page.fill("#fBands", "Hand Typed Act");
  await page.fill("#fDate", day(-1));
  await page.click("#fSave");
  await page.waitForFunction(() => document.querySelector("#toast").textContent.includes("Hand Typed Act"));
  assert.equal(gh.file.shows.length, 2);
  assert.equal(await page.textContent("#heroNum"), "3");
});

test("a save retries when added.json changed in the meantime, keeping the other change", async (page, url) => {
  const gh = fakeGitHub(page, { status: 200, conflictOnce: true });
  await page.goto(url);
  await page.evaluate(() => localStorage.setItem("stubs.ghToken", JSON.stringify("github_pat_" + "y".repeat(40))));
  await page.click("#addBtn");
  await page.click("#aManual");
  await page.fill("#fBands", "Retry Band");
  await page.fill("#fDate", day(-3));
  await page.click("#fSave");
  await page.waitForSelector("#toast.on");
  assert.equal(gh.puts.length, 2);
  assert.deepEqual(gh.file.shows.map(s => s.id).sort()[1], "someone-else");
  assert.equal(gh.file.shows.length, 2);
});

test("the form needs who played and a date", async (page, url) => {
  await page.goto(url);
  await page.click("#addBtn");
  await page.click("#aManual");
  await page.click("#fSave");
  assert.equal(await page.textContent("#fErr"), "Add who played.");
  await page.fill("#fBands", "Someone");
  await page.click("#fSave");
  assert.equal(await page.textContent("#fErr"), "Add the date.");
});

test("an added show can be removed from its page", async (page, url) => {
  const gh = fakeGitHub(page, { status: 200 });
  gh.file = { shows: ADDED.shows };
  await page.goto(url);
  await page.evaluate(() => localStorage.setItem("stubs.ghToken", JSON.stringify("github_pat_" + "z".repeat(40))));
  await page.goto(url + "#/show/a-old-1");
  await page.waitForSelector("#rmShow");
  assert.ok(await page.isHidden("#addBtn"), "no + button on a show page");
  page.once("dialog", d => d.accept());
  await page.click("#rmShow");
  await page.waitForSelector("#toast.on");
  assert.deepEqual(gh.file.shows.map(s => s.id), ["a-dupe"]);
  await page.waitForFunction(() => !document.querySelector("#list").textContent.includes("Hand Added Band"));
});

test("the sheet fits a phone screen without sideways scrolling", async (page, url) => {
  await page.setViewportSize({ width: 375, height: 740 });
  await page.goto(url);
  await page.click("#addBtn");
  await page.waitForSelector("#aRes .ev");
  const box = await page.locator(".sheet").boundingBox();
  assert.ok(box.width <= 375 && box.x >= 0, JSON.stringify(box));
  assert.ok(await page.evaluate(() => document.querySelector(".sheet-body").scrollWidth <= document.querySelector(".sheet-body").clientWidth));
  await page.keyboard.press("Escape");
  await page.waitForSelector("#addBg", { state: "hidden" });
});

(async () => {
  const server = await serve();
  const url = `http://127.0.0.1:${server.address().port}/`;
  const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
  const browser = await chromium.launch(proxy ? { proxy: { server: proxy, bypass: "127.0.0.1,localhost" } } : {});
  let failed = 0;
  for (const [name, fn] of tests) {
    const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", e => errors.push(e.message));
    try {
      await fn(page, url);
      assert.deepEqual(errors, [], "no page errors");
      console.log(`ok    ${name}`);
    } catch (e) {
      failed++;
      console.log(`FAIL  ${name}\n      ${String(e.stack || e).split("\n").slice(0, 4).join("\n      ")}`);
      await page.screenshot({ path: path.join(process.env.SHOT_DIR || ROOT, `fail-${tests.findIndex(t => t[0] === name)}.png`) }).catch(() => {});
    }
    await ctx.close();
  }
  await browser.close();
  server.close();
  console.log(failed ? `${failed} failed` : `all ${tests.length} passed`);
  process.exit(failed ? 1 : 0);
})();
