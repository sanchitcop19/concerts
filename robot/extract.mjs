// Runs INSIDE the browser page (passed to page.evaluate), so it must be self-contained.
// I couldn't see the real Concert Archives page while building this (their bot check
// blocks cloud servers), so it relies on link patterns rather than exact CSS classes:
//   /concerts/<slug>  -> one show
//   /bands/<slug>     -> an artist at that show
//   /venues/<slug>    -> the venue
// If it finds nothing, scrape.mjs saves the page to robot/debug.html for fixing.
export function extractRows() {
  const MONTHS = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };
  const pad = n => String(n).padStart(2, '0');
  const findDate = text => {
    let m;
    if ((m = text.match(/\b(\d{4})-(\d{2})-(\d{2})\b/))) return `${m[1]}-${m[2]}-${m[3]}`;
    if ((m = text.match(/\b(\d{1,2})\/(\d{1,2})\/(\d{4})\b/))) return `${m[3]}-${pad(m[1])}-${pad(m[2])}`;
    if ((m = text.match(/\b([A-Z][a-z]{2})[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b/)) && MONTHS[m[1].toLowerCase()])
      return `${m[3]}-${pad(MONTHS[m[1].toLowerCase()])}-${pad(m[2])}`;
    if ((m = text.match(/\b(\d{1,2})\s+([A-Z][a-z]{2})[a-z]*\.?,?\s+(\d{4})\b/)) && MONTHS[m[2].toLowerCase()])
      return `${m[3]}-${pad(MONTHS[m[2].toLowerCase()])}-${pad(m[1])}`;
    return '';
  };
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  // Text with a space between every piece, so "Mar 8, 2026" + "Show" never glue into "2026Show".
  const spacedText = el => {
    const parts = [], walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) parts.push(walker.currentNode.nodeValue);
    return clean(parts.join(' '));
  };
  const isShowLink = a => /\/concerts\/[^/?#]+/.test(a.getAttribute('href') || '');

  // The "row" for a show is the nearest ancestor that holds exactly one distinct show link.
  const rowFor = a => {
    let el = a.parentElement, best = a.parentElement;
    while (el && el !== document.body) {
      const shows = new Set([...el.querySelectorAll('a[href*="/concerts/"]')].filter(isShowLink).map(x => x.pathname));
      if (shows.size > 1) break;
      best = el;
      if (el.tagName === 'TR' || el.tagName === 'LI') break;
      el = el.parentElement;
    }
    return best;
  };

  const seen = new Map();
  for (const a of document.querySelectorAll('a[href*="/concerts/"]')) {
    if (!isShowLink(a) || seen.has(a.pathname)) continue;
    const row = rowFor(a);
    const bands = [...new Set([...row.querySelectorAll('a[href*="/bands/"]')].map(b => clean(b.textContent)).filter(Boolean))];
    const venueLink = row.querySelector('a[href*="/venues/"]');
    const venue = clean(venueLink?.textContent);
    // Location: a table cell / element after the venue that looks like "City, ST".
    let location = '';
    // Skip anything containing links (show/band/venue names) — the location is plain text.
    const cells = (row.tagName === 'TR' ? [...row.children] : [...row.querySelectorAll('*')].filter(e => !e.children.length))
      .filter(c => !c.querySelector('a') && c.tagName !== 'A');
    for (const c of cells) {
      const t = spacedText(c);
      if (t && t !== venue && /^[^,\d]{2,}, [^,\d]{2,}(, [^,\d]{2,})?$/.test(t) && !bands.includes(t)) { location = t; break; }
    }
    seen.set(a.pathname, {
      date: findDate(spacedText(row)),
      title: clean(a.textContent),
      bands,
      venue,
      location,
      url: a.href,
    });
  }
  const rows = [...seen.values()].filter(r => r.date || r.bands.length || r.venue);
  const next = document.querySelector('a[rel="next"], .pagination a.next, a.next_page, li.next a');
  return { rows, next: next && !next.closest('.disabled') ? next.href : null };
}
