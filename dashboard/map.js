'use strict';
// One map: live data straight from Epic's public API (it allows browser requests),
// plus what our tracker recorded (maps.json). No third-party sites involved.
const API = 'https://api.fortnite.com/ecosystem/v1';
const $ = selector => document.querySelector(selector);
const fmt = new Intl.NumberFormat('en-US');
const compact = new Intl.NumberFormat('en-US', {notation: 'compact', maximumFractionDigits: 1});
const code = (new URLSearchParams(location.search).get('code') || '').trim();
let series = {day: [], week: []}, range = 'week', marks = [];

try { const theme = localStorage.getItem('theme'); if (['light', 'dark'].includes(theme)) document.documentElement.dataset.theme = theme; } catch {}
$('#theme').addEventListener('click', () => {
  const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.dataset.theme = dark ? 'light' : 'dark';
  try { localStorage.setItem('theme', document.documentElement.dataset.theme); } catch {}
});

const el = (tag, className, text) => { const n = document.createElement(tag); if (className) n.className = className; if (text != null) n.textContent = text; return n; };
const when = stamp => new Date(stamp).toLocaleString([], {weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});
const hoursBetween = (a, b) => (Date.parse(b) - Date.parse(a)) / 3600e3;
const pct = v => v == null ? '—' : `${Math.round(v * 100)}%`;
const num = v => v == null ? '—' : fmt.format(Math.round(v));
const iso = ms => new Date(ms).toISOString();

async function epic(path, params = {}) {
  const query = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) (Array.isArray(v) ? v : [v]).forEach(x => query.append(k, x));
  const response = await fetch(`${API}${path}${query.size ? `?${query}` : ''}`);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Epic answered ${response.status}`);
  return response.json();
}
function points(payload, metric) {
  return (payload?.[metric] || []).map(p => ({t: Date.parse(p.timestamp), v: p.value ?? null, d1: p.d1, d7: p.d7}));
}

// ---------- chart ----------
const tooltip = $('#tooltip');
function showTip(x, y, text) {
  tooltip.textContent = text; tooltip.hidden = false;
  tooltip.style.left = `${Math.min(x + 14, innerWidth - tooltip.offsetWidth - 8)}px`;
  tooltip.style.top = `${y + 16 + tooltip.offsetHeight > innerHeight ? y - tooltip.offsetHeight - 10 : y + 16}px`;
}
function drawChart() {
  const data = series[range];
  const box = $('#chart');
  box.replaceChildren();
  const known = data.filter(p => p.v != null);
  $('#chart-empty').hidden = known.length > 0;
  if (!known.length) { $('#chart-empty').textContent = 'No player counts in this range. Epic only reports a 10-minute bucket once at least 5 players were on the map.'; return; }
  $('#chart-note').textContent = `Peak players per ${range === 'day' ? '10 minutes' : 'hour'} from Epic's public data. Dashed lines mark when our tracker first saw the map go public and any player surges.`;
  const W = Math.max(320, box.clientWidth), H = 260, L = 48, R = 12, T = 12, B = 28;
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('width', W); svg.setAttribute('height', H);
  const t0 = data[0].t, t1 = data[data.length - 1].t;
  const max = Math.max(...known.map(p => p.v)) * 1.1 || 1;
  const x = t => L + (t - t0) / Math.max(1, t1 - t0) * (W - L - R);
  const y = v => T + (1 - v / max) * (H - T - B);
  const add = (tag, attrs, parent = svg) => { const n = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); parent.append(n); return n; };
  for (let i = 0; i <= 3; i++) {
    const v = max / 1.1 * i / 3;
    add('line', {x1: L, x2: W - R, y1: y(v), y2: y(v), class: 'grid'});
    add('text', {x: L - 8, y: y(v) + 4, 'text-anchor': 'end', class: 'axis'}).textContent = compact.format(Math.round(v));
  }
  const step = range === 'day' ? 6 * 3600e3 : 24 * 3600e3;
  for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) {
    const label = new Date(t).toLocaleString([], range === 'day' ? {hour: 'numeric'} : {weekday: 'short', day: 'numeric'});
    add('text', {x: x(t), y: H - 8, 'text-anchor': 'middle', class: 'axis'}).textContent = label;
  }
  for (const mark of marks.filter(m => m.t >= t0 && m.t <= t1)) {
    add('line', {x1: x(mark.t), x2: x(mark.t), y1: T, y2: H - B, class: 'marker'});
    add('text', {x: x(mark.t) + 4, y: T + 10, class: 'axis'}).textContent = mark.label;
  }
  let path = '', open = false;
  for (const p of data) {
    if (p.v == null) { open = false; continue; }
    path += `${open ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`; open = true;
  }
  add('path', {d: path, class: 'line'});
  const cross = add('line', {y1: T, y2: H - B, class: 'cross', visibility: 'hidden'});
  const dot = add('circle', {r: 5, class: 'dot', visibility: 'hidden'});
  svg.addEventListener('pointermove', event => {
    const rect = svg.getBoundingClientRect();
    const t = t0 + ((event.clientX - rect.left) * (W / rect.width) - L) / (W - L - R) * (t1 - t0);
    const p = data.reduce((best, q) => Math.abs(q.t - t) < Math.abs(best.t - t) ? q : best, data[0]);
    cross.setAttribute('x1', x(p.t)); cross.setAttribute('x2', x(p.t)); cross.setAttribute('visibility', 'visible');
    if (p.v != null) { dot.setAttribute('cx', x(p.t)); dot.setAttribute('cy', y(p.v)); dot.setAttribute('visibility', 'visible'); } else dot.setAttribute('visibility', 'hidden');
    showTip(event.clientX, event.clientY, `${when(p.t)}\n${p.v == null ? 'Under 5 players' : `${fmt.format(p.v)} players`}`);
  });
  svg.addEventListener('pointerleave', () => { cross.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); tooltip.hidden = true; });
  box.append(svg);
}
document.querySelectorAll('[data-range]').forEach(button => button.addEventListener('click', () => {
  range = button.dataset.range;
  document.querySelectorAll('[data-range]').forEach(b => { b.classList.toggle('active', b === button); b.setAttribute('aria-pressed', String(b === button)); });
  drawChart();
}));
addEventListener('resize', () => { clearTimeout(drawChart.timer); drawChart.timer = setTimeout(drawChart, 150); });

// ---------- our tracker ----------
function renderTracker(tracked, meta) {
  const box = $('#tracker');
  $('#tracker-since').textContent = meta.tracking_since ? `Tracking since ${new Date(meta.tracking_since).toLocaleDateString([], {month: 'short', day: 'numeric'})}` : '';
  const genreName = slug => meta.genres?.[slug] || slug;
  if (!tracked) {
    box.replaceChildren(el('p', 'empty', 'No launch record. This map was public before tracking began, or first appeared more than 30 days ago. The live data above still covers its last 7 days.'));
    return;
  }
  const parts = [];
  const facts = el('dl', 'facts');
  const fact = (label, value, note) => { facts.append(el('dt', '', label)); const dd = el('dd', '', value); if (note) dd.append(el('small', '', note)); facts.append(dd); };
  if (tracked.first_seen) fact('Went public', when(tracked.first_seen), tracked.source === 'head'
    ? 'First seen in Epic\'s newest-first list; accurate to about 15 minutes.' : 'Found by the daily crawl, so this time can be up to a day late.');
  if (tracked.rank) fact('Genre rank', `#${tracked.rank[1]} in ${genreName(tracked.rank[0])}`, `Snapshot ${when(tracked.rank[2])}`);
  parts.push(facts);
  const launch = tracked.launch || {};
  if (launch['24'] || launch['144']) {
    const table = el('table');
    table.innerHTML = '<thead><tr><th class="left">WINDOW</th><th>PEAK</th><th>PLAYS</th><th>FAVORITES</th><th>RECOMMENDS</th><th>FIRST SURGE</th></tr></thead>';
    const body = table.createTBody();
    for (const [stage, label] of [['24', 'First 24 hours'], ['144', 'First 6 days']]) {
      const r = launch[stage];
      if (!r) continue;
      const row = body.insertRow();
      row.append(el('td', 'left', label), el('td', '', num(r.peak_ccu)), el('td', '', num(r.plays)), el('td', '', num(r.favorites)),
        el('td', '', num(r.recommendations)), el('td', '', r.hours_to_pickup != null ? `+${r.hours_to_pickup}h` : 'None'));
    }
    const wrap = el('div', 'table-scroll'); wrap.append(table); parts.push(wrap);
    const final = launch['144'];
    if (final && (final.d1 != null || final.best_rank != null)) {
      parts.push(el('p', 'lede', `Days 1–6: ${final.unique_players != null ? `${fmt.format(final.unique_players)} player-days, ` : ''}D1 retention ${pct(final.d1)}, D7 ${pct(final.d7)}${final.best_rank != null ? `, best genre rank #${final.best_rank} in ${genreName(final.best_rank_genre)}` : ''}.`));
    }
  } else if (tracked.first_seen) {
    parts.push(el('p', 'lede', 'Launch results are saved at 24 hours and again after 6 days.'));
  }
  if (tracked.surges?.length) {
    const list = el('ol', 'pickups');
    for (const [at, before, after] of [...tracked.surges].reverse()) {
      const item = el('li');
      item.append(el('span', 'when', when(at)), el('div', 'map', tracked.first_seen ? `+${hoursBetween(tracked.first_seen, at).toFixed(1)}h after going public` : 'Player surge'),
        el('div', 'jump', `${fmt.format(before)} → ${fmt.format(after)}`));
      list.append(item);
    }
    parts.push(el('h3', 'subhead', 'Player surges'), list);
  }
  box.replaceChildren(...parts);
}

// ---------- load ----------
async function main() {
  if (!/^\d{4}-\d{4}-\d{4}$/.test(code)) {
    $('#map-title').textContent = code ? 'That is not an island code' : 'Look up a map';
    $('#map-meta').textContent = 'Search above by island code, map name or creator.';
    document.querySelectorAll('.stats, .card:not(.search-card), .two').forEach(n => { n.hidden = true; });
    $('#map-query').focus();
    return;
  }
  $('#map-code').textContent = code;
  const now = Date.now();
  const since = iso(now - 7 * 24 * 3600e3 + 10 * 60e3);
  const [meta, hour, minute, day, ranks, tracker] = await Promise.all([
    epic(`/islands/${code}`),
    epic(`/islands/${code}/metrics/hour`, {from: since, to: iso(now), metrics: ['peakCCU', 'plays']}),
    epic(`/islands/${code}/metrics/minute`, {from: iso(now - 24 * 3600e3), to: iso(now), metrics: ['peakCCU', 'plays']}),
    epic(`/islands/${code}/metrics/day`, {from: since, to: iso(now)}),
    epic(`/islands/${code}/rankings`, {from: since, to: iso(now)}).catch(() => null),
    fetch('maps.json', {cache: 'no-store'}).then(r => r.ok ? r.json() : {maps: {}}).catch(() => ({maps: {}})),
  ].map(p => p.catch ? p.catch(error => ({error})) : p));
  if (!meta || meta.error) {
    $('#map-title').textContent = meta?.error ? 'Could not reach Epic' : 'Map not found';
    $('#map-meta').textContent = meta?.error ? String(meta.error.message) : 'Epic\'s public data only covers public, discoverable islands.';
    document.querySelectorAll('.stats, .card:not(.search-card), .two').forEach(n => { n.hidden = true; });
    return;
  }
  document.title = `${meta.title} · Drop Zone`;
  $('#map-title').textContent = meta.title;
  $('#map-meta').textContent = [meta.creatorCode && `by ${meta.creatorCode}`, meta.createdIn && `Built in ${meta.createdIn}`, meta.category].filter(Boolean).join(' · ');
  $('#map-tags').replaceChildren(...(meta.tags || []).map(t => el('span', 'pill', t)));
  const copy = el('button', 'quiet', 'Copy code');
  copy.addEventListener('click', () => navigator.clipboard?.writeText(code).then(() => { copy.textContent = 'Copied'; }));
  const gg = el('a', 'quiet', 'Compare on fortnite.gg ↗');
  gg.href = `https://fortnite.gg/island?code=${code}`; gg.target = '_blank'; gg.rel = 'noopener noreferrer';
  $('#map-links').replaceChildren(copy, gg);

  series.week = points(hour, 'peakCCU');
  series.day = points(minute, 'peakCCU');
  const tracked = tracker?.maps?.[code];
  marks = [];
  if (tracked?.first_seen) marks.push({t: Date.parse(tracked.first_seen), label: 'Public'});
  for (const [at] of tracked?.surges || []) marks.push({t: Date.parse(at), label: 'Surge'});
  drawChart();

  const recent = series.day.filter(p => p.v != null);
  $('#s-peak').textContent = recent.length ? fmt.format(Math.max(...recent.map(p => p.v))) : 'Under 5';
  const plays = points(minute, 'plays').reduce((sum, p) => sum + (p.v || 0), 0);
  $('#s-plays').textContent = plays ? fmt.format(plays) : '—';
  const days = points(day, 'uniquePlayers').map((p, i) => ({...p, peak: points(day, 'peakCCU')[i]?.v, plays: points(day, 'plays')[i]?.v,
    minutes: points(day, 'averageMinutesPerPlayer')[i]?.v, fav: points(day, 'favorites')[i]?.v, rec: points(day, 'recommendations')[i]?.v,
    d1: points(day, 'retention')[i]?.d1, d7: points(day, 'retention')[i]?.d7}));
  const today = new Date().toISOString().slice(0, 10);
  const full = days.filter(d => new Date(d.t).toISOString().slice(0, 10) < today && d.v != null);
  const last = full[full.length - 1];
  $('#s-unique').textContent = last ? fmt.format(last.v) : '—';
  $('#s-unique-note').textContent = last ? new Date(last.t).toLocaleDateString([], {timeZone: 'UTC', weekday: 'long', month: 'short', day: 'numeric'}) + ' (UTC)' : 'No full day with 5+ players';
  const withRetention = [...days].reverse().find(d => d.d1 != null);
  $('#s-retention').textContent = withRetention ? `${pct(withRetention.d1)} / ${pct(withRetention.d7)}` : '—';
  $('#s-minutes').textContent = last?.minutes != null ? `${last.minutes.toFixed(1)} average minutes per player` : 'Average minutes per player';

  const tbody = $('#daily');
  tbody.replaceChildren();
  for (const d of [...days].reverse()) {
    const row = tbody.insertRow();
    row.append(el('td', 'left', new Date(d.t).toLocaleDateString([], {timeZone: 'UTC', weekday: 'short', month: 'short', day: 'numeric'})),
      el('td', '', num(d.peak)), el('td', '', num(d.plays)), el('td', '', num(d.v)), el('td', '', d.minutes != null ? d.minutes.toFixed(1) : '—'),
      el('td', '', num(d.fav)), el('td', '', num(d.rec)), el('td', '', pct(d.d1)), el('td', '', pct(d.d7)));
  }
  if (!days.length) { const row = tbody.insertRow(); const c = el('td', 'empty', 'No daily data in the last 7 days.'); c.colSpan = 9; row.append(c); }

  const rankList = $('#ranks');
  const snaps = ranks?.data || [];
  const byGenre = {};
  for (const snap of snaps) for (const g of snap.genres || []) {
    const entry = byGenre[g.genreSlug] ??= {name: g.genre, best: g.rank, bestAt: snap.timestamp, latest: g.rank, latestAt: snap.timestamp};
    if (g.rank < entry.best) Object.assign(entry, {best: g.rank, bestAt: snap.timestamp});
    if (snap.timestamp >= entry.latestAt) Object.assign(entry, {latest: g.rank, latestAt: snap.timestamp});
  }
  const genres = Object.values(byGenre).sort((a, b) => a.latest - b.latest);
  rankList.replaceChildren(...(genres.length ? genres.map(g => {
    const item = el('li');
    item.append(el('span', 'rank', `#${g.latest}`), el('div', 'map', g.name), el('span', 'move muted', `best #${g.best} · ${when(g.bestAt)}`));
    return item;
  }) : [el('li', 'empty', 'Not ranked in any genre in the last 7 days.')]));

  renderTracker(tracked, tracker || {});
}
main().catch(error => { $('#map-title').textContent = 'Something went wrong'; $('#map-meta').textContent = error.message; });
