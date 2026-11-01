(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const themeButton = $('#theme-toggle');
  function currentTheme() {
    return document.documentElement.dataset.theme || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  }
  function themeLabel() { if (themeButton) themeButton.textContent = currentTheme() === 'dark' ? 'Use Day theme' : 'Use Night theme'; }
  themeLabel();
  if (themeButton) themeButton.addEventListener('click', () => {
    const theme = currentTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('spec-kitty-theme', theme); } catch (_) { /* Keep the session choice. */ }
    themeLabel();
    window.notifyThemeChange();
  });
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', themeLabel);
  const rawBase = document.documentElement.dataset.evidenceBase || '';
  function repoHref(path, relative) { return (rawBase || relative) + path; }
  const tabs = Array.from(document.querySelectorAll('[role="tab"]')).filter(t => !t.dataset.chartSubset && !t.dataset.officialSubset);
  function selectTab(tab) {
    tabs.forEach(t => {
      const active = t === tab;
      t.setAttribute('aria-selected', String(active)); t.tabIndex = active ? 0 : -1;
      document.getElementById(t.getAttribute('aria-controls')).hidden = !active;
    });
  }
  tabs.forEach((tab, i) => {
    tab.addEventListener('click', () => selectTab(tab));
    tab.addEventListener('keydown', e => {
      let next;
      if (e.key === 'ArrowRight') next = (i+1)%tabs.length;
      if (e.key === 'ArrowLeft') next = (i+tabs.length-1)%tabs.length;
      if (e.key === 'Home') next = 0;
      if (e.key === 'End') next = tabs.length-1;
      if (next !== undefined) { e.preventDefault(); selectTab(tabs[next]); tabs[next].focus(); }
    });
  });
  document.querySelectorAll('table[data-sortable]').forEach(table => {
    table.querySelectorAll('button[data-column]').forEach(button => button.addEventListener('click', () => {
      const col = Number(button.dataset.column), th = button.parentElement;
      const ascending = th.getAttribute('aria-sort') !== 'ascending';
      table.querySelectorAll('thead th').forEach(h => h.setAttribute('aria-sort', 'none'));
      th.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
      const rows = Array.from(table.tBodies[0].rows);
      rows.sort((a, b) => {
        const x = a.cells[col].dataset.sort, y = b.cells[col].dataset.sort;
        const cmp = Number.isFinite(Number(x)) && Number.isFinite(Number(y)) ? Number(x)-Number(y) : x.localeCompare(y);
        return (ascending ? cmp : -cmp) || a.cells[1].textContent.localeCompare(b.cells[1].textContent);
      });
      rows.forEach(row => table.tBodies[0].appendChild(row));
    }));
  });
  const explorer = $('#explorer');
  if (!explorer) return;
  const loadButton = $('#load-instances'), status = $('#explorer-status');
  let data, page = 0;
  let linkedTask = new URLSearchParams(location.search || '').get('task') || '';
  if (linkedTask) $('#search').value = linkedTask;
  const perPage = 30;
  const filters = ['search', 'repo-filter', 'model-filter', 'status-filter', 'solved-filter'];
  function elem(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function render() {
    const query = $('#search').value.toLowerCase(), repo = $('#repo-filter').value;
    const model = $('#model-filter').value, desired = $('#status-filter').value, solved = $('#solved-filter').value;
    const found = data.rows.filter(row => (linkedTask ? row[0] === linkedTask : row[0].toLowerCase().includes(query)) && (repo === '' || row[1] === Number(repo)) &&
      (desired === '' || (model === '' ? row[2].includes(Number(desired)) : row[2][Number(model)] === Number(desired))) &&
      (solved === '' || row[2].filter(s => data.statuses[s] === 'resolved').length === Number(solved)));
    const pageCount = Math.max(1, Math.ceil(found.length/perPage));
    page = Math.min(page, pageCount-1);
    const start = page*perPage, end = Math.min(found.length, start+perPage);
    status.textContent = found.length ? `${found.length.toLocaleString()} matching tasks. Showing ${start+1}–${end}.` : 'No tasks match these filters.';
    const target = $('#instance-results'); target.replaceChildren();
    found.slice(start, end).forEach(row => {
      const card = elem('article', undefined, 'task-card');
      card.append(elem('h2', row[0]));
      const resolved = row[2].filter(s => data.statuses[s] === 'resolved').length;
      card.append(elem('p', `${data.repos[row[1]]} · ${resolved} / ${data.models.length} models resolved`));
      const list = elem('ul', undefined, 'task-models');
      data.models.forEach((m, i) => {
        const li = elem('li'); li.append(elem('span', m));
        const s = data.statuses[row[2][i]];
        li.append(document.createElement('br'));
        li.append(elem('span', s, 'sk-badge '+(s === 'resolved' ? 'sk-badge-success' : s === 'ungraded' || s === 'missing' ? 'sk-badge-warning' : '')));
        if (row[3][i]) {
          const path = `evidence/models/${m}/attempts/${data.repos[row[1]].replace('/', '__')}/${row[0]}.json.gz`;
          const a = elem('a', 'Download evidence'); a.href = repoHref(path, '../'); li.append(a);
        } else li.append(elem('small', 'Evidence not packaged'));
        list.append(li);
      });
      card.append(list); target.append(card);
    });
    $('#previous').disabled = page === 0; $('#next').disabled = page >= pageCount-1;
  }
  async function loadInstances() {
    loadButton.disabled = true; status.textContent = 'Loading task data…';
    try {
      const response = await fetch(explorer.dataset.source);
      if (!response.ok) throw new Error('Task data unavailable');
      data = await response.json();
      if (!Array.isArray(data.rows) || !Array.isArray(data.models)) throw new Error('Invalid task data');
      explorer.querySelector('.filters').hidden = false; explorer.querySelector('.pager').hidden = false;
      loadButton.hidden = true; render();
    } catch (_) {
      status.textContent = 'Task data could not load. Serve the site over HTTP, then try again, or download the CSV.';
      loadButton.disabled = false;
    }
  }
  loadButton.addEventListener('click', loadInstances);
  if (linkedTask) loadInstances();
  filters.forEach(id => document.getElementById(id).addEventListener('input', () => { if (id === 'search') linkedTask = ''; if (data) { page = 0; render(); } }));
  $('#previous').addEventListener('click', () => { page--; render(); });
  $('#next').addEventListener('click', () => { page++; render(); });
})();
