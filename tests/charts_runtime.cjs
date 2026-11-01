// Real ECharts SVG rendering with local data and a minimal DOM; no browser or network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const echarts = require('../vendor/echarts/echarts.min.js');
const rootPath = path.join(__dirname, '..');
const source = fs.readFileSync(process.env.CHART_SOURCE || path.join(rootPath, 'docs/assets/charts.js'), 'utf8');
const snapshot = JSON.parse(fs.readFileSync(path.join(rootPath, 'docs/data/charts.json'), 'utf8'));
const design = JSON.parse(fs.readFileSync(path.join(rootPath, 'vendor/design-system/tokens.json'), 'utf8'));
// ECharts uses realm-local instanceof checks internally; preserve render callbacks
// while moving VM option arrays/objects into the library's Node realm.
function host(value) {
  if (Array.isArray(value)) return Array.from(value, host);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, host(v)]));
  return value;
}
class Element {
  constructor(width = 1000, height = 640) {
    this.clientWidth = width; this.height = height; this.dataset = {}; this.attrs = {}; this.events = {}; this.hidden = false; this.open = true;
    this.children = []; this.style = {setProperty(key, value) { this[key] = value; }};
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  querySelector(selector) { return this.queries?.[selector]; }
  before(element) { this.previous = element; }
  addEventListener(key, fn) { this.events[key] = fn; }
  setAttribute(key, value) { this.attrs[key] = value; }
  getAttribute(key) { return this.attrs[key]; }
  click() { this.events.click(); }
  focus() { this.focused = true; Element.active = this; this.events.focus?.(); }
}
function luminance(color) {
  return echarts.color.parse(color).slice(0, 3).map(v => v/255).map(v => v <= .04045 ? v/12.92 : ((v+.055)/1.055)**2.4)
    .reduce((sum, v, i) => sum + v*[.2126, .7152, .0722][i], 0);
}
function corners(el) {
  const r = el.getBoundingRect(), m = el.getComputedTransform() || [1, 0, 0, 1, 0, 0];
  return [[r.x, r.y], [r.x+r.width, r.y], [r.x+r.width, r.y+r.height], [r.x, r.y+r.height]]
    .map(([x, y]) => [m[0]*x+m[2]*y+m[4], m[1]*x+m[3]*y+m[5]]);
}
// Separating-axis test: rotated column headers may have intersecting bounding
// boxes while the actual text rectangles remain separated.
function intersects(a, b) {
  for (const polygon of [a, b]) for (let i = 0; i < polygon.length; i++) {
    const p = polygon[i], q = polygon[(i+1)%polygon.length], axis = [p[1]-q[1], q[0]-p[0]];
    const project = points => points.map(([x, y]) => x*axis[0]+y*axis[1]);
    const x = project(a), y = project(b);
    if (Math.max(...x) <= Math.min(...y)+.01 || Math.max(...y) <= Math.min(...x)+.01) return false;
  }
  return true;
}
function checkGeometry(chart, key, option, element, data) {
  const texts = chart.getZr().storage.getDisplayList(true).filter(e => e.type === 'tspan' && !e.ignore);
  for (const e of texts) {
    assert(corners(e).every(([x, y]) => x >= -1 && x <= element.clientWidth+1 && y >= -1 && y <= element.height+1),
      `${key} text clipped: ${e.style.text}`);
  }
  if (key === 'accumulation') {
    texts.forEach((text, i) => texts.slice(i+1).forEach(other =>
      assert(!intersects(corners(text), corners(other)), `Accumulation labels overlap: ${text.style.text} / ${other.style.text}`)));
  }
  if (key === 'outcomes') {
    const index = data.outcomes.categories.findIndex(c => c.key === 'timeout');
    const series = chart.getModel().getSeriesByIndex(index).getData();
    const grid = chart.getModel().getComponent('grid').coordinateSystem.getRect();
    data.outcomes.rows.forEach((row, i) => {
      if (!row.counts.timeout) return;
      const layout = series.getItemGraphicEl(i).getBoundingRect();
      const visible = Math.min(layout.x+layout.width, grid.x+grid.width)-Math.max(layout.x, grid.x);
      assert(visible >= 1.99, 'Timeout segment clipped below its two-pixel minimum');
    });
  }
  if (key === 'official') {
    const ours = option.series[1].data.map(d => chart.convertToPixel({gridIndex: 0}, host(d.value)));
    ours.forEach(([x, y], i) => ours.slice(i+1).forEach(([a, b]) =>
      assert(Math.hypot(x-a, y-b) >= 27.9, `Numbered model markers overlap: ${JSON.stringify({x,y,a,b,grid:option.grid})}`)));
    const medianLabel = texts.find(e => e.style.text.startsWith('Median of official entries'));
    if (medianLabel) {
      const bandBottom = chart.convertToPixel({gridIndex: 0}, [0, 1.42])[1];
      assert(Math.min(...corners(medianLabel).map(p => p[1])) > bandBottom, 'Median caption overlaps the density band');
    }
    const labels = texts.filter(e => !/^\d+$/.test(e.style.text));
    ours.forEach(([x, y]) => labels.forEach(label => assert(!intersects(corners(label),
      [[x-12,y-12],[x+12,y-12],[x+12,y+12],[x-12,y+12]]), 'Model marker overlaps chart text')));
  }
  if (key === 'official') texts.forEach((e, i) => {
    texts.slice(i+1).forEach(other => assert(!intersects(corners(e), corners(other)), 'Official text labels overlap'));
  });
  if (key === 'heatmap') {
    const headers = texts.filter(e => data.heatmap.repositories.some(repo => repo.split('/').at(-1) === e.style.text));
    assert.equal(headers.length, data.heatmap.repositories.length);
    headers.forEach((e, i) => {
      const polygon = corners(e);
      assert(polygon.every(([x, y]) => x >= 0 && x <= element.clientWidth && y >= 0 && y < option.grid.top), 'Header outside plot margin');
      headers.slice(i+1).forEach(other => assert(!intersects(polygon, corners(other)), 'Repository headers overlap'));
    });
  }
  if (key === 'scatter') {
    const labels = texts.filter(e => /^\d+\. /.test(e.style.text));
    labels.forEach((e, i) => {
      const polygon = corners(e);
      assert(polygon.every(([x, y]) => x >= option.grid.left && x <= element.clientWidth-option.grid.right &&
        y >= option.grid.top && y <= element.height-option.grid.bottom), 'Scatter label outside plot');
      labels.slice(i+1).forEach(other => assert(!intersects(polygon, corners(other)), 'Scatter labels overlap'));
    });
  }
}
async function scenario(width, theme, reduce, unavailable = false, data = snapshot) {
  const nodes = {}, options = {}, rendered = {}, timers = [], documentEvents = {}, windowEvents = {};
  const details = Array.from({length: 7}, () => new Element());
  const fallback = new Element();
  const keys = ['leaderboard', 'outcomes', 'unique', 'heatmap', 'scatter', 'official', 'accumulation'];
  for (const key of keys) {
    const canvasWidth = width === 1166 ? (key === 'scatter' ? 812 : width) : width;
    nodes['chart-'+key] = new Element(canvasWidth, width < 600 ? 800 : 680);
    nodes['title-'+key] = new Element(); nodes['source-'+key] = new Element();
  }
  nodes['chart-accumulation'].clientWidth = Math.max(width, width < 600 ? 1040 : 1120);
  nodes['chart-accumulation'].height = 600;
  nodes['chart-accumulation'].parentElement = new Element(width);
  nodes['chart-official'].height = 380;
  nodes['chart-scatter'].height = width < 600 ? 900 : 760;
  nodes['chart-outcomes'].height = width < 600 ? 820 : 640;
  nodes['chart-leaderboard'].height = width < 600 ? 760 : 640;
  nodes['chart-unique'].height = width < 600 ? 620 : 480;
  for (const id of ['scatter-key', 'official-key', 'official-key-wrap', 'official-caption', 'official-count', 'official-card', 'official-focus', 'official-table', 'official-help']) nodes[id] = new Element();
  const officialTabs = ['Full', 'Verified', 'Lite'].map(name => {
    const tab = new Element(); tab.dataset.officialSubset = name; tab.attrs['aria-controls'] = 'official-panel-'+name;
    nodes['official-panel-'+name] = new Element();
    nodes['official-panel-'+name].queries = {caption: new Element(), '[aria-sort]': new Element()};
    nodes['official-rows-'+name] = new Element(); nodes['official-footer-'+name] = new Element();
    return tab;
  });
  const officialFilters = [0, 1, 2, 4].map(mask => { const button = new Element(); button.dataset.officialFilter = String(mask); return button; });
  const officialSort = ['Full', 'Verified', 'Lite'].map(name => { const button = new Element(); button.dataset.officialSort = name; return button; });
  const panels = ['Full', 'Verified', 'Lite'].map(name => nodes['chart-panel-'+name] = new Element());
  const tabs = ['Full', 'Verified', 'Lite'].map(name => {
    const el = new Element(); el.dataset.chartSubset = name; el.attrs['aria-controls'] = 'chart-panel-'+name; return el;
  });
  const accumulationTabs = ['score', 'greedy'].map(name => {
    const tab = new Element(); tab.dataset.accumulationOrder = name; tab.attrs['aria-controls'] = 'accumulation-panel-'+name;
    nodes['accumulation-panel-'+name] = new Element(); return tab;
  });
  const root = new Element(); root.dataset.charts = 'data/charts.json';
  root.querySelector = () => fallback;
  root.querySelectorAll = selector => selector === '[data-accumulation-order]' ? accumulationTabs : selector === '.chart-data' ? details : selector === '[role="tabpanel"]' ? panels : tabs;
  const document = {querySelector: () => root, querySelectorAll: selector => ({
    '[data-official-subset]': officialTabs, '[data-official-filter]': officialFilters, '[data-official-sort]': officialSort
  })[selector] || [], get activeElement() { return Element.active; },
    createElement: () => new Element(), createTextNode: text => ({textContent: text}),
    getElementById: id => nodes[id], documentElement: new Element(),
    addEventListener: (name, fn) => { documentEvents[name] = fn; }};
  const media = Object.fromEntries(['(prefers-reduced-motion: reduce)', '(prefers-color-scheme: dark)'].map(name => [name,
    {matches: name.includes('reduce') ? reduce : theme === 'dark', addEventListener(event, fn) { this.change = fn; }}]));
  const variables = Object.fromEntries(['color', 'shadow', 'radius'].flatMap(section => design[section].tokens.map(t =>
    ['--'+t.name, typeof t.value === 'object' ? t.value[theme] : t.value])));
  const instances = [];
  const context = vm.createContext({document,
    window: {matchMedia: name => media[name], addEventListener: (name, fn) => { windowEvents[name] = fn; }},
    getComputedStyle: () => ({getPropertyValue: name => variables[name]}),
    setTimeout: fn => { timers.push(fn); return timers.length; }, clearTimeout: id => { if (id) timers[id-1] = null; },
    fetch: async url => { assert.equal(url, 'data/charts.json'); if (unavailable) throw Error('offline'); return {ok: true, json: async () => data}; },
    echarts: {...echarts, init(element, _, config) {
      assert.equal(config.renderer, 'svg');
      const key = keys.find(k => nodes['chart-'+k] === element);
      const chart = echarts.init(null, null, {renderer: 'svg', ssr: true, width: element.clientWidth, height: element.height});
      instances.push(chart);
      return {dispatchAction(action) { assert(['showTip', 'hideTip'].includes(action.type)); }, resize() {}, dispose() { chart.dispose(); }, convertToPixel: (...args) => chart.convertToPixel(...args.map(host)), setOption(option, opts) {
        options[key] = option;
        assert.equal(option.animation, !reduce);
        assert.equal(option.backgroundColor, 'transparent');
        chart.setOption(host(option), host(opts));
        const svg = chart.renderToSVGString();
        assert.match(svg, /<svg/); assert.doesNotMatch(svg, /NaN|undefined/);
        rendered[key] = svg;
        checkGeometry(chart, key, option, element, data);
      }};
    }}
  });
  vm.runInContext(source.replaceAll('catch (_) { fail(); }', 'catch (error) { globalThis.chartError = error; fail(); }'), context);
  await new Promise(resolve => setImmediate(resolve));
  try {
    if (unavailable) {
      assert.equal(instances.length, 0);
      assert.equal(fallback.hidden, false);
      assert(details.every(d => d.open));
      return;
    }
    assert.equal(fallback.hidden, true, context.chartError?.stack || 'Rendering failed; fallback was shown');
    assert.equal(Object.keys(rendered).length, 7);
    assert(details.every(d => !d.open));
    assert.equal(instances.length, 7);
    tabs[1].events.keydown({key: 'ArrowRight', preventDefault() {}});
    assert.equal(tabs[2].focused, true);
    assert.equal(tabs[2].attrs['aria-selected'], 'true');
    assert.equal(nodes['title-leaderboard'].textContent, data.leaderboards.Lite.title);
    assert.equal(nodes['chart-leaderboard'].attrs['aria-label'], data.leaderboards.Lite.title);
    assert.equal(panels[0].hidden, true);
    tabs[0].click();
    assert.equal(nodes['title-leaderboard'].textContent, data.leaderboards.Full.title);
    assert.equal(options.leaderboard.series[1].type, 'custom');
    assert.equal(options.leaderboard.series[0].data.length, data.model_count);
    assert(options.outcomes.series[2].itemStyle.decal);
    assert.equal(options.outcomes.series[3].itemStyle.decal, undefined);
    assert.equal(options.outcomes.series[3].type, 'custom');
    assert.equal(options.outcomes.legend.icon, 'rect');
    assert.equal(options.accumulation.series[0].step, 'end');
    assert.equal(options.accumulation.yAxis.max, data.task_count);
    assert.equal(options.accumulation.series[0].markArea.itemStyle.decal.color, variables['--role-move']);
    assert.equal(options.accumulation.series[0].lineStyle.color, variables['--role-frame']);
    assert.equal(options.accumulation.series[0].areaStyle.color, variables['--role-selector-soft']);
    assert.match(rendered.accumulation, /solved by no model/);
    assert.match(rendered.accumulation, /new tasks/);
    for (const key of ['ArrowRight', 'ArrowLeft', 'End', 'Home']) {
      const index = ['ArrowRight', 'End'].includes(key) ? 0 : 1;
      accumulationTabs[index].events.keydown({key, preventDefault() {}});
      const selected = ['ArrowRight', 'End'].includes(key) ? 1 : 0;
      assert(accumulationTabs[selected].focused);
      assert.equal(accumulationTabs[selected].attrs['aria-selected'], 'true');
      const order = selected ? 'greedy' : 'score';
      assert.deepEqual(Array.from(options.accumulation.series[0].data), data.difficulty.orders[order].map(r => r.solved));
      assert.equal(nodes['accumulation-panel-'+order].hidden, false);
    }
    assert.equal(options.unique.series[0].data.reduce((a, b) => a+b.value, 0), data.unique.rows.reduce((a, r) => a+r.tasks, 0));
    assert.equal(options.scatter.series[0].markLine.data.length, data.scatter.points.length ? 2 : 0);
    assert.equal(options.scatter.series[1].data.length, data.scatter.points.filter(r => /uncensored|abliterated/.test(r.model)).length);
    assert.equal(options.scatter.series[1].type, 'custom');
    assert.equal(typeof options.scatter.series[0].labelLayout, 'function');
    assert.equal(options.scatter.series[0].labelLine.show, false);
    assert.equal(options.scatter.series[0].label.rich, undefined);
    assert.equal(options.scatter.xAxis.name, 'Steps per attempt (median)');
    assert.equal(options.scatter.yAxis.name, `Tasks solved (% of ${data.task_count.toLocaleString('en-US')})`);
    assert.equal(nodes['scatter-key'].children.length, data.scatter.points.length);
    if (data.scatter.points.length) {
      nodes['scatter-key'].children[0].children[0].focus();
      nodes['scatter-key'].children[0].children[0].events.keydown({key: 'End', preventDefault() {}});
      assert(nodes['scatter-key'].children.at(-1).children[0].focused);
    }
    assert.equal(options.heatmap.xAxis.axisLabel.rotate, width < 700 ? 90 : 45);
    assert.equal(options.heatmap.yAxis.axisLabel.overflow, width < 700 ? 'truncate' : 'none');
    for (const cell of options.heatmap.series[0].data) {
      const a = luminance(cell.itemStyle.color), b = luminance(cell.label.color);
      assert((Math.max(a, b)+.05)/(Math.min(a, b)+.05) >= 4.5, `Heatmap label contrast: ${theme} ${cell.itemStyle.color} / ${cell.label.color}`);
    }
    for (const key of keys) {
      const series = options[key].series[0], datum = series.data[0];
      const tooltip = options[key].tooltip.formatter({dataIndex: 0, name: datum.name, value: datum.value});
      assert(!tooltip.includes('undefined'));
      if (!['unique', 'official', 'accumulation'].includes(key)) assert.match(tooltip, /DeepSeek|GLM|Kimi|Nemotron|MiniMax|other/);
    }
    const familyCharts = ['leaderboard', 'outcomes', 'unique', 'heatmap', 'scatter'];
    const familyCounts = {};
    for (const model of data.model_order) {
      const prefix = model.split('-')[0];
      const family = ['deepseek', 'glm', 'kimi', 'nemotron', 'minimax'].includes(prefix) ? prefix : 'other';
      familyCounts[family] = (familyCounts[family] || 0) + 1;
    }
    for (const key of familyCharts) {
      const legend = nodes['chart-'+key].previous;
      assert.equal(legend.attrs.role, 'group'); assert(legend.attrs['aria-label']);
      assert.equal(legend.children.length, Object.keys(familyCounts).length + 1);
      for (const button of legend.children) {
        assert.equal(button.type, 'button'); assert(button.attrs['aria-label']);
        if (button.dataset.family) {
          assert.equal(button.attrs['aria-pressed'], 'false');
          assert(button.attrs['aria-label'].includes(`${familyCounts[button.dataset.family]} models`));
          if (button.dataset.family === 'other') {
            assert(button.attrs['aria-label'].includes('other'));
            assert.equal(button.children[0].style.backgroundColor, 'var(--ink-muted)');
          }
        } else assert.equal(button.textContent, 'Show all');
      }
    }
    assert.equal(options.leaderboard.series[0].showBackground, true);
    assert.equal(options.leaderboard.series[0].backgroundStyle.color, variables['--surface-sunk']);
    assert.equal(options.leaderboard.series[0].data[0].itemStyle.borderWidth, 2);
    assert.match(options.leaderboard.yAxis.axisLabel.formatter(data.model_order[0], 0), /leader/);
    assert.match(rendered.leaderboard, />leader<\/text>/);
    assert.equal(options.leaderboard.series[0].animationDelay(3), reduce ? 0 : 120);
    const scores = data.heatmap.cells.map(c => c.score).filter(s => s != null);
    assert.equal(options.heatmap.visualMap.min, Math.min(...scores));
    assert.equal(options.heatmap.visualMap.max, Math.max(...scores));
    assert.equal(options.heatmap.series[0].emphasis.itemStyle.borderColor, variables['--ink']);
    assert.deepEqual(Array.from(options.unique.series[0].data, r => r.value), data.unique.rows.map(r => r.tasks));
    assert.equal(options.unique.series[0].label.formatter({value: 0}), '0 tasks');
    options.unique.series[0].data.forEach((r, i) => assert.equal(r.itemStyle.color, options.leaderboard.series[0].data[i].itemStyle.color));
    assert(options.scatter.graphic.every(g => g.style.font.startsWith('13px')));
    const firstLegend = nodes['chart-leaderboard'].previous;
    firstLegend.children[0].click();
    for (const key of familyCharts) {
      assert.equal(nodes['chart-'+key].previous.children[0].attrs['aria-pressed'], 'true');
      const rows = key === 'heatmap' ? data.heatmap.cells : key === 'scatter' ? data.scatter.points :
        key === 'outcomes' ? data.outcomes.rows : key === 'unique' ? data.unique.rows : data.leaderboards.Full.rows;
      options[key].series[0].data.forEach((datum, i) =>
        assert.equal(datum.itemStyle.opacity, rows[i].model.startsWith('deepseek-') ? .18 : 1));
    }
    // Native buttons provide Enter/Space activation. Clicking from another
    // chart must restore all peers without rebuilding or losing focus.
    nodes['chart-heatmap'].previous.children[0].click();
    assert.equal(firstLegend.children[0].attrs['aria-pressed'], 'false');
    firstLegend.children[0].click(); firstLegend.children[1].click();
    nodes['chart-scatter'].previous.children.at(-1).click();
    for (const key of familyCharts) {
      assert(nodes['chart-'+key].previous.children.slice(0, -1).every(b => b.attrs['aria-pressed'] === 'false'));
      assert(options[key].series[0].data.every(d => d.itemStyle.opacity === 1));
    }
    // Independent tabs, all AND filter states, filtered table and summaries.
    assert.equal(nodes['official-table'].open, false);
    officialTabs[0].events.keydown({key: 'ArrowRight', preventDefault() {}});
    assert.equal(officialTabs[1].focused, true);
    assert.equal(nodes['title-leaderboard'].textContent, data.leaderboards.Full.title);
    assert.equal(officialTabs[1].attrs['aria-selected'], 'true');
    if (process.env.CHART_PREVIEW_DIR && data === snapshot) {
      fs.mkdirSync(process.env.CHART_PREVIEW_DIR, {recursive: true});
      fs.writeFileSync(path.join(process.env.CHART_PREVIEW_DIR, `${theme}-${width}-official-verified.svg`), rendered.official);
    }
    for (let mask = 0; mask < 8; mask++) {
      officialFilters[0].click();
      [1, 2, 4].forEach((bit, i) => { if (mask & bit) officialFilters[i+1].click(); });
      const board = data.official.subsets.Verified;
      const expected = board.entries.filter(r => (!(mask & 1) || r.mini) && (!(mask & 2) || r.os_model) && (!(mask & 4) || r.attempts === '1'));
      const marks = options.official.series[0].data;
      assert.equal(marks.length, expected.length);
      assert.equal(nodes['official-rows-Verified'].children.length, expected.length);
      assert.equal(nodes['official-count'].textContent, board.summaries[mask].filter_help);
      assert.equal(nodes['title-official'].textContent, board.summaries[mask].title);
      assert.equal(nodes['chart-official'].attrs['aria-label'], board.summaries[mask].title);
      assert.equal(nodes['official-caption'].textContent, board.summaries[mask].caption);
      assert.equal(nodes['official-footer-Verified'].textContent, board.summaries[mask].footer);
      assert.equal(options.official.xAxis.min, 0);
      assert.equal(options.official.xAxis.max, board.axis_max);
      marks.forEach((m, i) => {
        assert.equal(m.symbol, expected[i].os_model ? 'diamond' : 'circle');
        assert.equal(m.itemStyle.color, variables[expected[i].mini ? '--ink' : '--ink-muted']);
        assert.equal(m.itemStyle.opacity, expected[i].mini ? 1 : .55);
        assert.equal(m.value[1], 1.6 + board.jitter[expected[i].id]);
      });
      assert.equal(options.official.series[1].data.length, data.model_count);
      assert.equal(options.official.series[1].labelLine.show, false);
      assert.equal(options.official.xAxis.name, 'Share of tasks solved (%)');
      assert.equal(options.official.series[2].data.reduce((sum, bin) => sum+bin[1], 0), expected.length);
      assert.equal(options.official.series[3].data[0]?.[0] ?? null, board.summaries[mask].median);
      const ours = [...data.leaderboards.Verified.rows].sort((a, b) => b.score-a.score || a.model.localeCompare(b.model));
      assert.equal(nodes['official-key'].children.length, ours.length);
      ours.forEach((row, i) => {
        const button = nodes['official-key'].children[i].children[0];
        assert.equal(button.children[0].textContent, String(i+1));
        assert.equal(button.children[2].textContent, row.model);
        assert.equal(button.children[3].textContent, row.score.toFixed(2)+'%');
        button.focus(); assert(nodes['official-card'].textContent.includes(row.model));
        button.events.keydown({key: 'Escape'}); assert(nodes['official-card'].hidden);
        const datum = options.official.series[1].data[i];
        const a = luminance(datum.itemStyle.color), b = luminance(datum.label.color);
        assert((Math.max(a, b)+.05)/(Math.min(a, b)+.05) >= 4.5, 'Number contrast');
      });
    }
    officialFilters[0].click();
    officialSort[1].click();
    let tableScores = nodes['official-rows-Verified'].children.map(r => Number(r.children[3].textContent.slice(0, -1)));
    assert.deepEqual(tableScores, [...tableScores].sort((a, b) => a-b));
    officialSort[1].click();
    tableScores = nodes['official-rows-Verified'].children.map(r => Number(r.children[3].textContent.slice(0, -1)));
    assert.deepEqual(tableScores, [...tableScores].sort((a, b) => b-a));
    const focus = nodes['official-focus'].children;
    assert.equal(focus.filter(b => b.tabIndex === 0).length, 2);
    focus[0].focus();
    assert.match(nodes['official-card'].textContent, /Agent:.*Model:.*Date:.*Attempts:/);
    assert.equal(nodes['official-card'].hidden, false);
    focus[0].events.keydown({key: 'ArrowRight', preventDefault() {}});
    assert.equal(focus[1].focused, true);
    focus[1].events.keydown({key: 'Escape'});
    assert.equal(nodes['official-card'].hidden, true);
    focus.at(-1).focus();
    assert.match(nodes['official-card'].textContent, /Wilson interval/);
    officialFilters[1].click(); officialTabs[0].click();
    assert.equal(options.official.series[0].data.length, 0);
    assert.match(nodes['official-caption'].textContent, /no official entries/);
    officialFilters[0].click();
    documentEvents.themechange(); windowEvents.resize();
    media['(prefers-color-scheme: dark)'].change(); media['(prefers-reduced-motion: reduce)'].change();
    timers.filter(Boolean).forEach(fn => fn());
    assert.equal(context.chartError, undefined, context.chartError?.stack);
    assert.equal(instances.length, 7, 'Resize and theme changes must reuse instances');
    // Optional local artifacts for visual inspection; never part of the publication.
    if (process.env.CHART_PREVIEW_DIR && data === snapshot) {
      fs.mkdirSync(process.env.CHART_PREVIEW_DIR, {recursive: true});
      for (const [key, svg] of Object.entries(rendered)) fs.writeFileSync(path.join(process.env.CHART_PREVIEW_DIR, `${theme}-${width}-${key}.svg`), svg);
    }
  } finally { instances.forEach(chart => { if (!chart.isDisposed()) chart.dispose(); }); }
}
(async () => {
  for (const theme of ['light', 'dark']) {
    await scenario(309, theme, true);
    await scenario(654, theme, true);
    await scenario(1166, theme, false);
  }
  await scenario(309, 'light', true, true);
  await scenario(309, 'dark', true, false,
    JSON.parse(JSON.stringify(snapshot).replaceAll('minimax-m3.1-flash', 'future-model')));
  process.stdout.write('Offline SVG charts: both themes, 375/768/1280 layouts, motion, tabs, tooltips, contrast and fallback passed.\n');
})().catch(error => { process.stderr.write(error.stack+'\n'); process.exitCode = 1; });
