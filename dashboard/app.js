'use strict';
const $ = selector => document.querySelector(selector);
const fmt = new Intl.NumberFormat('en-US');
const compact = new Intl.NumberFormat('en-US', {notation: 'compact', maximumFractionDigits: 1});
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
let data, kwKind = 'word', kwSort = 'players', kwDir = -1;

try { const theme = localStorage.getItem('theme'); if (['light', 'dark'].includes(theme)) document.documentElement.dataset.theme = theme; } catch {}
$('#theme').addEventListener('click', () => {
  const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.dataset.theme = dark ? 'light' : 'dark';
  try { localStorage.setItem('theme', document.documentElement.dataset.theme); } catch {}
});

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}
function ago(stamp) {
  const minutes = (Date.now() - Date.parse(stamp)) / 60000;
  if (minutes < 60) return `${Math.max(0, Math.round(minutes))}m ago`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)}h ago`;
  return `${Math.round(minutes / 1440)}d ago`;
}
function localTime(stamp) {
  return new Date(stamp).toLocaleString([], {weekday: 'short', hour: 'numeric', minute: '2-digit'});
}
function islandLink(code, title, creator) {
  const cell = el('td', 'map');
  const link = el('a', '', title || code);
  link.href = `https://fortnite.gg/island?code=${encodeURIComponent(code)}`;
  link.target = '_blank'; link.rel = 'noopener noreferrer';
  cell.append(link, el('small', '', [creator, code].filter(Boolean).join(' · ')));
  return cell;
}
function emptyRow(tbody, columns, message) {
  tbody.replaceChildren();
  const row = tbody.insertRow(), cell = el('td', 'empty', message);
  cell.colSpan = columns; row.append(cell);
}
const tooltip = $('#tooltip');
function showTip(event, text) {
  tooltip.textContent = text; tooltip.hidden = false;
  const x = Math.min(event.clientX + 14, innerWidth - tooltip.offsetWidth - 8);
  const y = event.clientY + 16 + tooltip.offsetHeight > innerHeight ? event.clientY - tooltip.offsetHeight - 10 : event.clientY + 16;
  tooltip.style.left = `${x}px`; tooltip.style.top = `${y}px`;
}
const hideTip = () => { tooltip.hidden = true; };

// ---------- best time to publish ----------
const METRICS = {
  took24: {n: c => c[0], v: c => c[0] ? c[1] / c[0] : null, label: 'took off within 24h', pct: true},
  pick24: {n: c => c[0], v: c => c[0] ? c[2] / c[0] : null, label: 'sudden pickup within 24h', pct: true},
  took144: {n: c => c[3], v: c => c[3] ? c[4] / c[3] : null, label: 'took off within 6 days', pct: true},
  pick144: {n: c => c[3], v: c => c[3] ? c[5] / c[3] : null, label: 'sudden pickup within 6 days', pct: true},
  hours: {n: c => c[5], v: c => c[6], label: 'median hours to pickup', lowerIsBetter: true},
  volume: {n: c => c[0], v: c => c[0], label: 'launches measured at 24h', count: true},
};
function renderTiming() {
  const grids = data.timing || {};
  const group = grids[$('#timing-group').value] ? $('#timing-group').value : 'all';
  const grid = grids[group];
  const metric = METRICS[$('#timing-metric').value];
  const minimum = metric.count ? 1 : Number($('#timing-min').value);
  const offset = Math.round(-new Date().getTimezoneOffset() / 60);
  const heat = $('#heatmap');
  heat.replaceChildren(el('span'));
  for (let h = 0; h < 24; h++) heat.append(el('span', 'hour', h % 3 === 0 ? `${h}` : ''));
  const empty = $('#timing-empty');
  if (!grid || !grid.some(c => c[0] || c[3])) {
    heat.hidden = true; $('#heat-legend').replaceChildren(); $('#best-slots').replaceChildren();
    empty.hidden = false;
    const start = data.tracking_since ? new Date(Date.parse(data.tracking_since) + 24 * 3600e3) : null;
    empty.textContent = `Launch results arrive once maps have been live for 24 hours${start ? ` (first ones around ${start.toLocaleString([], {weekday: 'long', hour: 'numeric'})})` : ''}. The grid fills in over the first few weeks; each hour of the week needs several launches before its rate means much.`;
    return;
  }
  heat.hidden = false; empty.hidden = true;
  const cells = [];
  for (let local = 0; local < 168; local++) {
    const c = grid[((local - offset) % 168 + 168) % 168];
    cells.push({local, n: metric.n(c), value: metric.v(c), raw: c});
  }
  const valid = cells.filter(c => c.n >= minimum && c.value != null);
  const values = valid.map(c => c.value);
  const lo = Math.min(...values), hi = Math.max(...values);
  const show = v => metric.pct ? `${Math.round(v * 100)}%` : metric.count ? fmt.format(v) : `${v}h`;
  for (let day = 0; day < 7; day++) {
    heat.append(el('span', 'day', DAYS[day]));
    for (let hour = 0; hour < 24; hour++) {
      const cell = cells[day * 24 + hour];
      const node = el('div', 'cell');
      node.tabIndex = 0;
      const enough = cell.n >= minimum && cell.value != null;
      if (enough) {
        let t = hi > lo ? (cell.value - lo) / (hi - lo) : 1;
        if (metric.lowerIsBetter) t = 1 - t;
        node.style.background = `color-mix(in oklab, var(--heat) ${Math.round(8 + 92 * t)}%, var(--wash))`;
      } else if (cell.n > 0) node.classList.add('low');
      const when = `${DAYS[day]} ${hour}:00–${hour + 1}:00`;
      const r = cell.raw;
      const text = enough
        ? `${when}\n${show(cell.value)} ${metric.label}\n${fmt.format(r[0])} launches at 24h · ${fmt.format(r[3])} at 6 days`
        : `${when}\n${cell.n ? `Only ${cell.n} launch${cell.n === 1 ? '' : 'es'}. Needs ${minimum}.` : 'No launches measured yet'}`;
      node.setAttribute('aria-label', text.replace(/\n/g, '. '));
      node.addEventListener('pointermove', e => showTip(e, text));
      node.addEventListener('pointerleave', hideTip);
      node.addEventListener('focus', e => { const b = e.target.getBoundingClientRect(); showTip({clientX: b.right, clientY: b.bottom}, text); });
      node.addEventListener('blur', hideTip);
      heat.append(node);
    }
  }
  const legend = $('#heat-legend');
  legend.replaceChildren(el('span', '', metric.lowerIsBetter ? 'Slower' : 'Lower'), el('span', 'ramp'),
    el('span', '', metric.lowerIsBetter ? 'Faster' : 'Higher'), el('span', 'swatch low cell'), el('span', '', `Fewer than ${minimum} launches`));
  const best = [...valid].sort((a, b) => metric.lowerIsBetter ? a.value - b.value : b.value - a.value).slice(0, 5);
  $('#best-slots').replaceChildren(...(metric.count ? [] : best.map(c => {
    const chip = el('span');
    chip.append(el('b', '', `${DAYS[Math.floor(c.local / 24)]} ${c.local % 24}:00`), ` · ${show(c.value)} · ${fmt.format(c.n)} launches`);
    return chip;
  })));
  $('#tz-note').textContent = `Your time (UTC${offset >= 0 ? '+' : ''}${offset})`;
}

// ---------- live launches ----------
function sparkline(values, pickupIndex) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 150 30'); svg.setAttribute('class', 'spark'); svg.setAttribute('aria-hidden', 'true');
  if (!values.length) return svg;
  const max = Math.max(...values, 1), step = values.length > 1 ? 148 / (values.length - 1) : 0;
  if (pickupIndex != null && pickupIndex < values.length) {
    const line = document.createElementNS(svg.namespaceURI, 'line');
    const x = 1 + pickupIndex * step;
    line.setAttribute('x1', x); line.setAttribute('x2', x); line.setAttribute('y1', 0); line.setAttribute('y2', 30);
    svg.append(line);
  }
  const path = document.createElementNS(svg.namespaceURI, 'path');
  path.setAttribute('d', values.map((v, i) => `${i ? 'L' : 'M'}${(1 + i * step).toFixed(1)},${(28 - v / max * 26).toFixed(1)}`).join(''));
  svg.append(path);
  return svg;
}
function renderLive() {
  const query = $('#live-search').value.trim().toLowerCase();
  const rows = (data.live || []).filter(item => !query || [item.title, item.creator, item.code, ...(item.tags || [])].join(' ').toLowerCase().includes(query));
  $('#live-count').textContent = `${fmt.format(rows.length)} maps`;
  const tbody = $('#live-rows');
  if (!rows.length) return emptyRow(tbody, 6, data.live?.length ? 'No launches match that filter.' : 'New maps appear here after their first check, 2 hours after release.');
  tbody.replaceChildren();
  for (const item of rows.slice(0, 120)) {
    const row = tbody.insertRow();
    const map = islandLink(item.code, item.title, item.creator);
    if (item.pickup) map.querySelector('a').append(el('span', 'pill', 'PICKUP'));
    if (item.source === 'catalog') map.querySelector('small').append(' · found late');
    const released = el('td', '', ago(item.first_seen)); released.title = localTime(item.first_seen);
    const pickupHours = item.pickup ? (Date.parse(item.pickup) - Date.parse(item.first_seen)) / 3600e3 : null;
    const pickup = el('td', item.pickup ? '' : 'muted', item.pickup ? `+${pickupHours.toFixed(1)}h` : '—');
    if (item.pickup) pickup.title = localTime(item.pickup);
    const spark = el('td', 'left');
    spark.append(sparkline(item.spark || [], pickupHours != null ? Math.floor(pickupHours) : null));
    row.append(map, released, el('td', '', fmt.format(item.peak)), el('td', '', fmt.format(item.ccu)), pickup, spark);
  }
}

// ---------- pickups ----------
function renderPickups() {
  const list = $('#pickups');
  const rows = data.pickups || [];
  if (!rows.length) { list.replaceChildren(el('li', 'empty', 'No sudden jumps detected yet. They show up as new and ranked maps get checked.')); return; }
  list.replaceChildren(...rows.slice(0, 80).map(row => {
    const item = el('li');
    const map = el('div', 'map');
    const link = el('a', '', row.title || row.code);
    link.href = `https://fortnite.gg/island?code=${encodeURIComponent(row.code)}`; link.target = '_blank'; link.rel = 'noopener noreferrer';
    map.append(link, el('small', '', row.kind === 'launch' ? `New map · ${row.age_hours}h after release` : `Established map · ${row.creator || row.code}`));
    const jump = el('div', 'jump', `${fmt.format(row.ccu_before)} → ${fmt.format(row.ccu_after)}`);
    jump.append(el('small', '', 'players'));
    const when = el('span', 'when', ago(row.at)); when.title = localTime(row.at);
    item.append(when, map, jump);
    return item;
  }));
}

// ---------- keywords ----------
function renderKeywords() {
  const kw = data.keywords;
  const tbody = $('#kw-rows');
  if (!kw) { $('#kw-date').textContent = ''; return emptyRow(tbody, 7, 'Keyword supply and demand is computed once a day from the full catalog. The first table appears a few hours after tracking starts.'); }
  $('#kw-date').textContent = `As of ${kw.date}${kw.compared_to ? ` · change vs ${kw.compared_to}` : ''}`;
  const query = $('#kw-search').value.trim().toLowerCase();
  const rows = (kwKind === 'word' ? kw.words : kw.tags).filter(r => !query || r.term.includes(query));
  rows.sort((a, b) => {
    const av = a[kwSort], bv = b[kwSort];
    if (av == null && bv == null) return 0; if (av == null) return 1; if (bv == null) return -1;
    return (typeof av === 'string' ? av.localeCompare(bv) : av - bv) * kwDir;
  });
  document.querySelectorAll('[data-kw-sort]').forEach(b => b.classList.toggle('selected', b.dataset.kwSort === kwSort));
  if (!rows.length) return emptyRow(tbody, 7, 'No terms match.');
  tbody.replaceChildren();
  for (const r of rows.slice(0, 150)) {
    const row = tbody.insertRow();
    const change = el('td', r.players_change > 0 ? 'positive' : r.players_change < 0 ? 'negative' : 'muted',
      r.players_change == null ? '—' : `${r.players_change > 0 ? '+' : ''}${compact.format(r.players_change)}`);
    row.append(el('td', 'left', r.term), el('td', '', fmt.format(r.islands)), el('td', '', fmt.format(r.new_7d)),
      el('td', '', fmt.format(r.ranked)), el('td', '', compact.format(r.players)),
      el('td', '', r.players_per_ranked == null ? '—' : compact.format(r.players_per_ranked)), change);
  }
}

// ---------- success factors ----------
function renderSuccess() {
  const kind = $('#success-kind').value;
  const rows = (data.success || []).filter(r => r.kind === kind).sort((a, b) => b.took_off / b.launches - a.took_off / a.launches || b.launches - a.launches);
  const tbody = $('#success-rows');
  if (!rows.length) return emptyRow(tbody, 5, `Appears once launches finish their 6-day window (about ${Math.round(data.settings.window_hours / 24) + 1} days after tracking starts).`);
  tbody.replaceChildren();
  const pct = (a, b) => `${Math.round(a / b * 100)}%`;
  for (const r of rows.slice(0, 60)) {
    const row = tbody.insertRow();
    row.append(el('td', 'left', kind === 'tags' ? `${r.name}${r.name === '4' ? '+' : ''} tags` : r.name), el('td', '', fmt.format(r.launches)),
      el('td', '', pct(r.took_off, r.launches)), el('td', '', pct(r.picked_up, r.launches)), el('td', '', fmt.format(r.median_peak)));
  }
}

// ---------- genre leaders ----------
function renderGenres() {
  const leaders = data.leaders;
  const list = $('#genre-rows');
  if (!leaders) { list.replaceChildren(el('li', 'empty', 'Genre rankings arrive on the first run; Epic publishes each hour a few hours late.')); return; }
  $('#genre-hour').textContent = `Snapshot ${localTime(leaders.hour)}`;
  const select = $('#genre');
  if (!select.options.length) {
    for (const g of leaders.genres) select.append(new Option(g.name, g.slug));
  }
  const genre = leaders.genres.find(g => g.slug === select.value) || leaders.genres[0];
  list.replaceChildren(...(genre?.rows || []).map(r => {
    const item = el('li');
    const map = el('div', 'map');
    const link = el('a', '', r.title || r.code);
    link.href = `https://fortnite.gg/island?code=${encodeURIComponent(r.code)}`; link.target = '_blank'; link.rel = 'noopener noreferrer';
    map.append(link, el('small', '', r.title ? [r.creator, r.code].filter(Boolean).join(' · ') : 'Title arrives on its next stats refresh'));
    const move = r.change > 0 ? el('span', 'move positive', `▲ ${r.change}`) : r.change < 0 ? el('span', 'move negative', `▼ ${-r.change}`)
      : el('span', 'move muted', r.new ? 'NEW' : leaders.compared_to ? '—' : '');
    item.append(el('span', 'rank', r.rank), map, move);
    return item;
  }));
}

function render() {
  const age = data.latest_run ? (Date.now() - Date.parse(data.latest_run)) / 60000 : Infinity;
  $('#status-dot').classList.toggle('stale', age > data.settings.stale_minutes);
  $('#freshness').textContent = data.latest_run ? `Updated ${ago(data.latest_run)}` : 'Waiting for the first run';
  $('#tracking').textContent = data.tracking_since ? `Tracking since ${new Date(data.tracking_since).toLocaleDateString([], {month: 'short', day: 'numeric'})} · ${data.runs_24h} runs in 24h` : 'Snapshots every ~15 minutes';
  $('#new24').textContent = fmt.format(data.new_24h);
  $('#new7').textContent = `${fmt.format(data.new_7d)} in the last 7 days`;
  $('#pickcount').textContent = fmt.format((data.pickups || []).length);
  $('#pickup-rule').textContent = `${data.settings.pickup_min_ccu}+`;
  document.querySelectorAll('.pickup-rule').forEach(n => { n.textContent = `${data.settings.pickup_min_ccu}+`; });
  $('#pickup-factor').textContent = `${data.settings.pickup_factor}×`;
  $('#early').textContent = fmt.format(data.launches_early);
  $('#final').textContent = fmt.format(data.launches_finished);
  const groupSelect = $('#timing-group');
  if (groupSelect.options.length === 1) {
    const keys = Object.keys(data.timing || {}).filter(k => k !== 'all').sort((a, b) => (a.startsWith('tag:') - b.startsWith('tag:')) || a.localeCompare(b));
    for (const key of keys) groupSelect.append(new Option(key.startsWith('tag:') ? `Tag: ${key.slice(4)}` : `Built in ${key}`, key));
  }
  renderTiming(); renderLive(); renderPickups(); renderKeywords(); renderSuccess(); renderGenres();
}

['#timing-metric', '#timing-group', '#timing-min'].forEach(s => $(s).addEventListener('change', renderTiming));
$('#live-search').addEventListener('input', renderLive);
$('#kw-search').addEventListener('input', renderKeywords);
$('#success-kind').addEventListener('change', renderSuccess);
$('#genre').addEventListener('change', renderGenres);
document.querySelectorAll('[data-kind]').forEach(button => button.addEventListener('click', () => {
  kwKind = button.dataset.kind;
  document.querySelectorAll('[data-kind]').forEach(b => { b.classList.toggle('active', b === button); b.setAttribute('aria-pressed', String(b === button)); });
  renderKeywords();
}));
document.querySelectorAll('[data-kw-sort]').forEach(button => button.addEventListener('click', () => {
  const key = button.dataset.kwSort;
  kwDir = key === kwSort ? -kwDir : key === 'term' ? 1 : -1; kwSort = key;
  renderKeywords();
}));

fetch(`data.json?t=${Date.now()}`, {cache: 'no-store'})
  .then(response => { if (!response.ok) throw new Error(response.status); return response.json(); })
  .then(json => { data = json; render(); })
  .catch(() => { $('#freshness').textContent = 'No data yet: the first collection has not finished.'; $('#status-dot').classList.add('stale'); });
setInterval(() => fetch(`data.json?t=${Date.now()}`, {cache: 'no-store'}).then(r => r.ok && r.json()).then(json => { if (json) { data = json; render(); } }).catch(() => {}), 5 * 60 * 1000);
