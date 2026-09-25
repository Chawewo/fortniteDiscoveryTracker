'use strict';
// Map lookup shared by the dashboard and the map page: island codes open directly,
// names and creators search the daily catalog index (loaded on first use).
(() => {
  const form = document.querySelector('#map-search');
  if (!form) return;
  const input = form.querySelector('input');
  const results = document.querySelector('#search-results');
  const CODE = /^\s*(\d{4})-?(\d{4})-?(\d{4})\s*$/;
  let index, loading;

  const open = code => { location.href = `map.html?code=${encodeURIComponent(code)}`; };
  function message(text) { results.replaceChildren(Object.assign(document.createElement('li'), {className: 'hint', textContent: text})); }
  function load() {
    loading ??= fetch('catalog.json', {cache: 'force-cache'})
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(rows => { index = rows.map(([code, title, creator]) => [code, title, creator, title.toLowerCase(), creator.toLowerCase()]); });
    return loading;
  }
  function search() {
    const query = input.value.trim().toLowerCase();
    if (CODE.test(query)) { message('Press Enter to open this island code.'); return; }
    if (query.length < 2) { results.replaceChildren(); return; }
    if (!index) {
      message('Loading the map index (every public map, about 5 MB)…');
      load().then(search).catch(() => message('Name search starts after the next daily catalog crawl. Island codes work now.'));
      return;
    }
    const scored = [];
    for (const row of index) {
      const [, , , title, creator] = row;
      const score = creator === query ? 0 : title === query ? 1 : title.startsWith(query) ? 2 : creator.startsWith(query) ? 3
        : title.includes(query) ? 4 : creator.includes(query) ? 5 : -1;
      if (score >= 0) scored.push([score, row]);
    }
    scored.sort((a, b) => a[0] - b[0] || a[1][1].localeCompare(b[1][1]));
    if (!scored.length) { message('No public map matches. Try the island code.'); return; }
    results.replaceChildren(...scored.slice(0, 25).map(([, [code, title, creator]]) => {
      const item = document.createElement('li');
      const link = Object.assign(document.createElement('a'), {href: `map.html?code=${code}`});
      link.append(Object.assign(document.createElement('strong'), {textContent: title || code}),
        Object.assign(document.createElement('small'), {textContent: `${creator || 'unknown creator'} · ${code}`}));
      item.append(link);
      return item;
    }));
    if (scored.length > 25) results.append(Object.assign(document.createElement('li'), {className: 'hint', textContent: `${scored.length - 25} more; keep typing to narrow it down.`}));
  }
  let timer;
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(search, 150); });
  form.addEventListener('submit', event => {
    event.preventDefault();
    const match = input.value.match(CODE);
    if (match) return open(`${match[1]}-${match[2]}-${match[3]}`);
    const first = results.querySelector('a');
    if (first) location.href = first.href;
  });
})();
