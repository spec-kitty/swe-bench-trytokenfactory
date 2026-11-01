// Offline runtime smoke test: native Node modules and a minimal DOM, no network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
class Element {
  constructor(tag = 'div', attrs = {}) { this.tag = tag; this.attrs = attrs; this.dataset = {}; this.children = []; this.events = {}; this.value = ''; this.hidden = false; this.textContent = ''; }
  addEventListener(name, fn) { this.events[name] = fn; }
  getAttribute(k) { return this.attrs[k]; }
  setAttribute(k, v) { this.attrs[k] = v; }
  append(...items) { this.children.push(...items); }
  appendChild(item) { this.children = this.children.filter(x => x !== item); this.children.push(item); }
  replaceChildren(...items) { this.children = items; }
  focus() { this.focused = true; }
  querySelector(s) { return this.selectors[s]; }
}
(async () => {
  for (const rawBase of ['', 'https://github.com/example/preview/raw/review/']) {
  for (const linked of [false, true]) {
  const nodes = {};
  for (const id of ['theme-toggle', 'explorer', 'load-instances', 'explorer-status', 'search', 'repo-filter', 'model-filter', 'status-filter', 'solved-filter', 'instance-results', 'previous', 'next']) nodes['#'+id] = new Element();
  nodes['#explorer'].selectors = {'.filters': new Element(), '.pager': new Element()};
  nodes['#explorer'].dataset.source = 'data/instances.json';
  const tabs = ['Full', 'Verified', 'Lite'].map(name => {
    nodes['#panel-'+name] = new Element();
    return new Element('button', {'aria-controls': 'panel-'+name});
  });
  const headings = [new Element('th'), new Element('th')];
  const buttons = headings.map((h, i) => { const b = new Element('button'); b.dataset.column = String(i); b.parentElement = h; return b; });
  const row = (rank, name) => ({cells: [{dataset: {sort: String(rank)}}, {dataset: {sort: name}, textContent: name}]});
  const tbody = new Element(); tbody.children = [row(2, 'B'), row(1, 'A')];
  Object.defineProperty(tbody, 'rows', {get: () => tbody.children});
  const table = {tBodies: [tbody], querySelectorAll: s => s.startsWith('button') ? buttons : headings};
  const document = {
    dispatchEvent() {},
    documentElement: {dataset: {evidenceBase: rawBase}}, querySelector: s => nodes[s] || null,
    querySelectorAll: s => s === '[role="tab"]' ? tabs : s === 'table[data-sortable]' ? [table] : [],
    getElementById: id => nodes['#'+id], createElement: tag => new Element(tag)
  };
  const fixture = {models: ['A', 'B'], repos: ['org/repo'], statuses: ['resolved', 'unresolved', 'ungraded', 'missing'],
    rows: [['org__repo-1', 0, [0, 1], [1, 0]], ['org__repo-10', 0, [2, 3], [0, 0]]]};
  const context = vm.createContext({document, Event, URLSearchParams, window: {matchMedia: () => ({matches: true, addEventListener() {}})},
    localStorage: {getItem() { throw new Error('disabled'); }, setItem() { throw new Error('disabled'); }},
    location: {hostname: 'spec-kitty.github.io', search: linked ? '?task=org__repo-1' : ''}, fetch: async () => ({ok: true, json: async () => fixture}),
    console: {error() { throw new Error('Console error'); }}});
  const assets = path.join(__dirname, '..', 'tools', 'site_assets');
  vm.runInContext(fs.readFileSync(path.join(assets, 'theme.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(assets, 'site.js'), 'utf8'), context);
  if (linked) {
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(nodes['#search'].value, 'org__repo-1');
    assert.equal(nodes['#instance-results'].children.length, 1);
    assert.equal(nodes['#instance-results'].children[0].children[0].textContent, 'org__repo-1');
    nodes['#search'].value = ''; nodes['#search'].events.input();
    assert.equal(nodes['#instance-results'].children.length, 2);
  }
  assert.equal(nodes['#theme-toggle'].textContent, 'Use Day theme');
  nodes['#theme-toggle'].events.click();
  assert.equal(document.documentElement.dataset.theme, 'light');
  tabs[1].events.click();
  assert.equal(nodes['#panel-Full'].hidden, true);
  assert.equal(nodes['#panel-Verified'].hidden, false);
  tabs[1].events.keydown({key: 'ArrowRight', preventDefault() {}});
  assert.equal(tabs[2].focused, true);
  buttons[0].events.click();
  assert.equal(tbody.rows[0].cells[1].textContent, 'A');
  buttons[0].events.click();
  assert.equal(tbody.rows[0].cells[1].textContent, 'B');
  await nodes['#load-instances'].events.click();
  assert.equal(nodes['#instance-results'].children.length, 2);
  const firstLink = nodes['#instance-results'].children[0].children[2].children[0].children.at(-1);
  assert.equal(firstLink.href, (rawBase || '../') + 'evidence/models/A/attempts/org__repo/org__repo-1.json.gz');
  nodes['#status-filter'].value = '3'; nodes['#status-filter'].events.input();
  assert.equal(nodes['#instance-results'].children.length, 1);
  nodes['#model-filter'].value = '0'; nodes['#model-filter'].events.input();
  assert.equal(nodes['#instance-results'].children.length, 0);
  assert.equal(nodes['#explorer-status'].textContent, 'No tasks match these filters.');
  nodes['#status-filter'].value = ''; nodes['#solved-filter'].value = '1'; nodes['#solved-filter'].events.input();
  assert.equal(nodes['#instance-results'].children.length, 1);
  context.fetch = async () => { throw new Error('offline'); };
  await nodes['#load-instances'].events.click();
  assert.equal(nodes['#load-instances'].disabled, false);
  assert.match(nodes['#explorer-status'].textContent, /could not load/);
  }
  }
  process.stdout.write('Offline JavaScript runtime smoke test passed.\n');
})().catch(error => { process.stderr.write(error.stack+'\n'); process.exitCode = 1; });
