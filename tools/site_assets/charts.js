/* Local ECharts, local data, and design-system tokens. No remote chart assets. */
(() => {
  'use strict';
  // One identity map for chart marks, row chips, legends and model-page SVGs.
  const families = {
    deepseek: {name: 'DeepSeek', token: 'build'}, glm: {name: 'GLM', token: 'role-frame'},
    kimi: {name: 'Kimi', token: 'factory'}, nemotron: {name: 'Nemotron', token: 'brain'},
    minimax: {name: 'MiniMax', token: 'role-move'}, other: {name: 'other', token: 'ink-muted'}
  };
  let modelList = [];
  function modelFamily(model, models = modelList) {
    const prefix = model.split('-')[0];
    const key = Object.hasOwn(families, prefix) && prefix !== 'other' ? prefix : 'other';
    const parts = model.split('-'), flashAt = parts.indexOf('flash');
    const base = parts.slice(0, flashAt).join('-');
    const flash = flashAt > 0 && models.some(id => !id.split('-').includes('flash') &&
      id.split('-')[0] === prefix && id.replace(/-(?:uncensored|abliterated)(?:-|$).*$/, '') === base);
    return {key, ...families[key], flash,
      patterned: /(?:^|-)(uncensored|abliterated)(?:-|$)/.test(model)};
  }
  document.querySelectorAll('[data-model-palette]').forEach(element => {
    modelList = JSON.parse(element.dataset.modelList || '[]');
    const family = modelFamily(element.dataset.modelPalette);
    element.style.setProperty('--model-color', family.flash
      ? `color-mix(in srgb-linear, var(--${family.token}) 70%, var(--surface))` : `var(--${family.token})`);
  });
  const root = document.querySelector('[data-charts]');
  if (!root) return;
  const byId = id => document.getElementById(id);
  const fmt = n => Number(n).toLocaleString('en-US', {maximumFractionDigits: 1});
  const pct = n => n == null ? 'Unavailable' : `${n.toFixed(2)}%`;
  const escape = value => String(value).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const scheme = window.matchMedia('(prefers-color-scheme: dark)');
  const keys = ['leaderboard', 'outcomes', 'unique', 'heatmap', 'scatter', 'official', 'accumulation'];
  const instances = new Map();
  const dimmed = new Set();
  const familyCharts = ['leaderboard', 'outcomes', 'unique', 'heatmap', 'scatter'];
  const legendButtons = [];
  let data, subset = 'Full', timer;
  let officialSubset = 'Full', officialMask = 0, accumulationOrder = 'score';
  const officialAscending = {};

  function tokens() {
    const style = getComputedStyle(document.documentElement);
    return Object.fromEntries(['ink', 'ink-muted', 'line', 'line-strong', 'surface', 'surface-raised', 'surface-sunk', 'accent', 'accent-soft', 'shadow-1', 'radius-md',
      'build', 'role-frame', 'factory', 'brain', 'role-move', 'role-selector', 'role-selector-soft', 'role-frame-soft', 'role-move-soft', 'success-ink', 'warning-soft', 'warning-ink', 'danger-ink']
      .map(name => [name, style.getPropertyValue(`--${name}`).trim()]));
  }
  // Resolve either hex or rgb tokens through ECharts' own colour parser.
  function rgb(value) { return echarts.color.parse(value).slice(0, 3); }
  function linear(v) { return (v /= 255) <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }
  function encoded(v) { return Math.round(255 * (v <= .0031308 ? 12.92 * v : 1.055 * v ** (1/2.4) - .055)); }
  function mix(a, b, fraction) {
    const x = rgb(a).map(linear), y = rgb(b).map(linear);
    const f = Math.max(0, Math.min(1, fraction));
    return `rgb(${x.map((v, i) => encoded(v + (y[i] - v) * f)).join(',')})`;
  }
  function diagonal(color) {
    return {symbol: 'rect', dashArrayX: [1, 0], dashArrayY: [1, 5], rotation: -Math.PI/4, color};
  }
  function familyOpacity(model) { return dimmed.has(modelFamily(model).key) ? .18 : 1; }
  function barDelay(i) { return motion.matches ? 0 : i * 40; }
  function modelStyle(model, t) {
    const family = modelFamily(model), color = t[family.token];
    return {color: family.flash ? mix(t.surface, color, .7) : color, opacity: familyOpacity(model),
      decal: family.patterned ? diagonal(labelInk(color, t)) : null};
  }
  function modelTitle(model) { return `${escape(model)} · ${modelFamily(model).name}`; }
  function familyRich(t) {
    return Object.fromEntries(Object.entries(families).map(([key, family]) =>
      [key, {width: 8, height: 8, borderRadius: 2, backgroundColor: t[family.token]}]));
  }
  function makeLegends() {
    const counts = new Map();
    data.model_order.forEach(model => { const key = modelFamily(model).key; counts.set(key, (counts.get(key) || 0) + 1); });
    function refresh() {
      legendButtons.forEach(button => button.setAttribute('aria-pressed', String(dimmed.has(button.dataset.family))));
      familyCharts.forEach(render);
    }
    familyCharts.forEach(key => {
      const legend = document.createElement('div');
      legend.className = 'family-legend'; legend.setAttribute('role', 'group');
      legend.setAttribute('aria-label', 'Model families · press to dim across charts');
      Object.entries(families).forEach(([family, info]) => {
        if (!counts.has(family)) return;
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'family-toggle'; button.dataset.family = family;
        button.setAttribute('aria-pressed', 'false');
        button.setAttribute('aria-label', `Dim ${info.name} family · ${counts.get(family)} models`);
        const chip = document.createElement('span'); chip.className = 'family-chip';
        chip.setAttribute('aria-hidden', 'true'); chip.style.backgroundColor = `var(--${info.token})`;
        button.append(chip, document.createTextNode(`${info.name} · ${counts.get(family)}`));
        button.addEventListener('click', () => {
          if (dimmed.has(family)) dimmed.delete(family); else dimmed.add(family);
          refresh();
        });
        legendButtons.push(button); legend.append(button);
      });
      const reset = document.createElement('button'); reset.type = 'button'; reset.className = 'family-toggle';
      reset.textContent = 'Show all'; reset.setAttribute('aria-label', 'Show all model families');
      reset.addEventListener('click', () => { dimmed.clear(); refresh(); }); legend.append(reset);
      byId(`chart-${key}`).before(legend);
    });
  }
  function luminance(value) {
    return rgb(value).map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
      .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
  }
  function contrast(a, b) {
    const x = luminance(a), y = luminance(b);
    return (Math.max(x, y) + .05) / (Math.min(x, y) + .05);
  }
  function labelInk(background, t) {
    const candidates = [t.ink, t['surface-sunk'], t['surface-raised']].sort((a, b) => luminance(a) - luminance(b));
    const best = colors => colors.reduce((a, b) => contrast(background, a) >= contrast(background, b) ? a : b);
    const token = best(candidates);
    if (contrast(background, token) >= 4.5) return token;
    // Mid-ramp cells need a deeper ink or a paler paper tint to keep small
    // numerals legible. Both are derived from this theme's token endpoints.
    const deepInk = `rgb(${rgb(candidates[0]).map(v => Math.round(v * .02)).join(',')})`;
    const palePaper = `rgb(${rgb(candidates.at(-1)).map(v => Math.round(v + (255-v) * .98)).join(',')})`;
    return best([deepInk, palePaper]);
  }
  function short(model, compact) {
    if (!compact) return model;
    return model.replace('deepseek-', 'ds-').replace('nemotron-', 'n-').replace('minimax-', 'mm-')
      .replace('-1017', '').replace('-uncensored', '-unc.').replace('-abliterated', '-abl.');
  }
  function base(t) {
    return {
      backgroundColor: 'transparent', color: [t.accent],
      animation: !motion.matches, animationDuration: 700, animationDurationUpdate: 700,
      animationEasing: 'cubicOut', animationEasingUpdate: 'cubicOut',
      textStyle: {fontFamily: 'IBM Plex Sans, sans-serif', fontSize: 13, color: t.ink},
      tooltip: {trigger: 'item', confine: true, backgroundColor: t['surface-raised'], borderColor: t.line,
        borderWidth: 1, padding: 12, textStyle: {color: t.ink, fontSize: 13, fontFamily: 'IBM Plex Sans, sans-serif'},
        extraCssText: `box-shadow:${t['shadow-1']};border-radius:${t['radius-md']};font-variant-numeric:tabular-nums;max-width:calc(100% - 24px);white-space:normal;overflow-wrap:anywhere;`},
      grid: {top: 24, bottom: 42, left: 16, right: 24, containLabel: true}
    };
  }
  function axis(t, type = 'value') {
    return {type, axisLine: {show: false, lineStyle: {color: t['line-strong']}}, axisTick: {show: false},
      axisLabel: {color: t['ink-muted'], fontSize: 13, hideOverlap: true},
      splitLine: {show: type === 'value', lineStyle: {color: t.line, width: 1}},
      nameTextStyle: {color: t['ink-muted'], fontSize: 13}};
  }
  function modelAxis(t, models, compact, ranked = false) {
    return {...axis(t, 'category'), data: models, inverse: true,
      axisLabel: {color: t.ink, fontSize: 13, width: compact ? 132 : 330, overflow: 'truncate',
        rich: {...familyRich(t), rank: {color: t['ink-muted']}, leader: {fontWeight: 700, color: t.ink},
          badge: {color: t.ink, backgroundColor: t['surface-sunk'], padding: [2, 4], borderRadius: 3}},
        formatter: (m, i) => {
          const rank = ranked ? data.leaderboards[subset].rows[i].rank : null;
          return `${ranked ? `{rank|${rank}}  ` : ''}{${modelFamily(m).key}|}  ` +
            (rank === 1 ? `{leader|${short(m, compact)}}${compact ? '\n' : ' '}{badge|leader}` : short(m, compact));
        }}};
  }
  function leaderboard(t, compact) {
    const rows = data.leaderboards[subset].rows;
    const option = base(t);
    option.grid.right = compact ? 58 : 82;
    option.xAxis = {...axis(t), min: 0, max: Math.min(100, Math.ceil(Math.max(0, ...rows.map(r => r.interval ? r.interval[1] : 0)) / 10) * 10 + 10),
      axisLabel: {...axis(t).axisLabel, formatter: '{value}%'}, splitNumber: compact ? 2 : 5};
    option.yAxis = modelAxis(t, rows.map(r => r.model), compact, true);
    option.tooltip.formatter = p => {
      const r = rows[p.dataIndex];
      return `${modelTitle(r.model)}<br><strong>${pct(r.score)}</strong> resolved · ${fmt(r.resolved)} / ${fmt(r.graded)} graded<br>` +
        `${fmt(data.confidence * 100)}% Wilson interval: ${r.interval ? r.interval.map(pct).join('–') : 'Unavailable'}<br>Coverage: ${pct(r.coverage)}`;
    };
    option.series = [{id: 'scores', type: 'bar', barMaxWidth: 22, animationDelay: barDelay,
      showBackground: true, backgroundStyle: {color: t['surface-sunk'], borderRadius: 4},
      data: rows.map(r => ({id: r.model, name: r.model, value: r.score,
        itemStyle: {...modelStyle(r.model, t), borderColor: t.ink, borderWidth: r.rank === 1 ? 2 : 0, borderRadius: 4}})),
      label: {show: true, position: 'right', distance: 12, color: t.ink, fontSize: 13, formatter: p => pct(rows[p.dataIndex].score)},
      emphasis: {itemStyle: {opacity: 1}},
      universalTransition: true},
    {id: 'intervals', type: 'custom', silent: true, z: 5,
      data: rows.flatMap((r, i) => r.interval ? [[r.interval[0], i, r.interval[1]]] : []),
      renderItem: (params, api) => {
        const low = api.coord([api.value(0), api.value(1)]), high = api.coord([api.value(2), api.value(1)]);
        // Place whiskers just beneath the bars so value labels remain unobscured.
        const y = low[1] + 15;
        const style = {stroke: t['ink-muted'], lineWidth: 1, opacity: familyOpacity(rows[api.value(1)].model)};
        return {type: 'group', children: [
          {type: 'line', shape: {x1: low[0], y1: y, x2: high[0], y2: y}, style},
          ...[low[0], high[0]].map(x => ({type: 'line', shape: {x1: x, y1: y-3, x2: x, y2: y+3}, style}))]};
      }}];
    return option;
  }
  function outcomeStyles(t) {
    return {
      resolved: {color: t['success-ink']},
      patch: {color: t['accent-soft'], borderColor: t['ink-muted'], borderWidth: 1},
      empty: {color: t['warning-soft'], decal: {...diagonal(t['warning-ink']), dashArrayY: [1, 4]}},
      timeout: {color: t['danger-ink']},
      pending: {color: t['surface-sunk'], borderColor: t['line-strong'], borderWidth: 1}
    };
  }
  function outcomes(t, compact) {
    const chart = data.outcomes, option = base(t), narrow = compact || byId('chart-outcomes').clientWidth < 700;
    option.grid.top = 40 + chart.categories.length * 22;
    option.xAxis = {...axis(t), min: 0, max: 100, splitNumber: 2, axisLabel: {...axis(t).axisLabel, formatter: '{value}%'}};
    option.yAxis = modelAxis(t, data.model_order, narrow);
    const styles = outcomeStyles(t);
    option.legend = {top: 8, left: 8, right: 8, orient: 'vertical', itemWidth: 18, itemHeight: 12, itemGap: 8,
      icon: 'rect', selectedMode: false, textStyle: {color: t['ink-muted'], fontSize: 13},
      data: chart.categories.map(c => ({name: c.label, icon: 'rect', itemStyle: styles[c.key]}))};
    option.tooltip.formatter = p => {
      const r = chart.rows[p.dataIndex];
      return `${modelTitle(r.model)}<br>`+chart.categories.map(c => `${escape(c.label)}: <strong>${fmt(r.counts[c.key])}</strong> (${pct(r.percentages[c.key])})`).join('<br>');
    };
    option.series = chart.categories.map(c => ({name: c.label, type: 'bar', stack: 'attempts', barMaxWidth: 22, animationDelay: barDelay,
      itemStyle: styles[c.key], emphasis: {itemStyle: {borderColor: t.ink, borderWidth: 1}},
      data: chart.rows.map(r => {
        const present = chart.categories.filter(cat => r.counts[cat.key]);
        const first = present[0]?.key === c.key, last = present.at(-1)?.key === c.key;
        return {value: r.counts[c.key] ? r.percentages[c.key] : null, itemStyle: {opacity: familyOpacity(r.model), borderRadius: [last ? 4 : 0, last ? 4 : 0, first ? 4 : 0, first ? 4 : 0]}};
      })}));
    // A minimum-size stacked bar can extend past 100% and be clipped back
    // below two pixels. Anchor this final category inside its true endpoint.
    const timeout = option.series[chart.categories.findIndex(c => c.key === 'timeout')];
    timeout.type = 'custom'; delete timeout.stack;
    timeout.encode = {x: 0, y: 1};
    timeout.data = chart.rows.map((r, i) => ({value: [r.percentages.timeout, i]}));
    timeout.renderItem = (params, api) => {
      const row = chart.rows[params.dataIndex];
      if (!row.counts.timeout) return null;
      const end = api.coord([100, params.dataIndex]);
      const start = api.coord([100-row.percentages.timeout, params.dataIndex]);
      const width = Math.max(2, end[0]-start[0]);
      return {type: 'rect', shape: {x: end[0]-width, y: end[1]-11, width, height: 22},
        style: {fill: t['danger-ink'], opacity: familyOpacity(row.model)}};
    };
    return option;
  }
  function unique(t, compact) {
    const rows = data.unique.rows, option = base(t);
    option.grid.right = compact ? 64 : 90;
    option.xAxis = {...axis(t), min: 0, max: Math.max(1, ...rows.map(r => r.tasks)),
      minInterval: 1, splitNumber: compact ? 2 : 5, name: 'Number of tasks', nameLocation: 'middle', nameGap: 30};
    option.yAxis = modelAxis(t, rows.map(r => r.model), compact);
    option.tooltip.formatter = p => `${modelTitle(rows[p.dataIndex].model)}<br>${fmt(p.value)} tasks no other model solved`;
    option.series = [{type: 'bar', barMaxWidth: 18, animationDelay: barDelay,
      data: rows.map(r => ({value: r.tasks, itemStyle: modelStyle(r.model, t)})),
      label: {show: true, position: 'right', color: t.ink, fontSize: 13, formatter: p => `${fmt(p.value)} tasks`}}];
    return option;
  }
  function heatFill(t, fraction) {
    const ends = [t['surface-sunk'], t.build].sort((a, b) => luminance(b)-luminance(a));
    return mix(ends[0], ends[1], fraction);
  }
  function heatmap(t, compact) {
    const chart = data.heatmap, option = base(t);
    const narrow = byId('chart-heatmap').clientWidth < 700;
    const repos = chart.repositories, models = data.model_order;
    const scores = chart.cells.map(r => r.score).filter(s => s != null);
    const min = scores.length ? Math.min(...scores) : 0, max = scores.length ? Math.max(...scores) : 0;
    const ramp = fraction => heatFill(t, fraction);
    // A sampled linear-light visual map, matching the cell ramp rather than
    // ECharts' default sRGB interpolation. Cells retain their contrast labels.
    option.visualMap = {type: 'continuous', min, max, dimension: 2, orient: 'horizontal', left: 'center', bottom: 0,
      itemWidth: 8, itemHeight: compact ? 110 : 200, calculable: false, precision: 1,
      text: scores.length ? [pct(max), pct(min)] : ['Unavailable', 'Unavailable'],
      textStyle: {color: t['ink-muted'], fontSize: 13},
      inRange: {color: Array.from({length: 65}, (_, i) => ramp(i/64))}};
    option.grid = {top: 150, bottom: 58, left: narrow ? 96 : 342, right: 16};
    option.xAxis = {...axis(t, 'category'), data: repos, position: 'top', splitArea: {show: false}, triggerEvent: true,
      tooltip: {show: true, formatter: p => {
        const project = chart.projects.find(r => r.repo === p.value);
        return `${escape(p.value)}: ${escape(project?.description || '')}`;
      }},
      axisLabel: {fontSize: 13, color: t['ink-muted'], interval: 0, hideOverlap: false, margin: 12,
        rotate: narrow ? 90 : 45, formatter: r => r.split('/').at(-1)}};
    option.yAxis = modelAxis(t, models, false);
    option.yAxis.triggerEvent = true;
    option.yAxis.tooltip = {show: narrow, formatter: p => escape(p.value)};
    option.yAxis.axisLabel.width = narrow ? 82 : 330;
    option.yAxis.axisLabel.overflow = narrow ? 'truncate' : 'none';
    option.tooltip.formatter = p => {
      const r = chart.cells[p.dataIndex];
      return `${modelTitle(r.model)}<br>${escape(r.repo)}<br><strong>${pct(r.score)}</strong> resolved<br>`+
        `${fmt(r.resolved)} / ${fmt(r.total)} total tasks · ${fmt(r.graded)} graded`;
    };
    option.series = [{type: 'heatmap', progressive: 0,
      data: chart.cells.map(r => {
        const fill = ramp(r.score == null || max === min ? 0 : (r.score - min)/(max - min));
        return {value: [repos.indexOf(r.repo), models.indexOf(r.model), r.score ?? '-'], visualMap: false,
          itemStyle: {color: fill, opacity: familyOpacity(r.model), borderColor: t['surface-raised'], borderWidth: narrow ? 1 : 3},
          label: {color: labelInk(fill, t)}};
      }), label: {show: !narrow, fontSize: 13, formatter: p => p.value[2] === '-' ? '—' : `${Math.round(p.value[2])}`},
      emphasis: {itemStyle: {borderColor: t.ink, borderWidth: 2}, label: {show: !narrow}}}];
    return option;
  }
  function overlaps(a, b, gap = 4) {
    return a.x < b.x + b.width + gap && a.x + a.width + gap > b.x &&
      a.y < b.y + b.height + gap && a.y + a.height + gap > b.y;
  }
  // Deterministic, bounded label placement. Mandatory candidates get first choice;
  // every accepted rectangle avoids all markers and previously accepted labels.
  function scatterLabels(points, bounds, priority) {
    const occupied = points.map(p => ({x: p.x-6, y: p.y-6, width: 12, height: 12}));
    const labels = Array(points.length).fill(null);
    const order = [...new Set([...priority, ...points.map((_, i) => i)])];
    order.forEach(i => {
      const p = points[i];
      const candidates = [[p.x+12, p.y-p.height/2], [p.x-p.width-12, p.y-p.height/2],
        [p.x-p.width/2, p.y-p.height-12], [p.x-p.width/2, p.y+12]];
      for (const [cx, cy] of candidates) {
        const x = Math.max(bounds.x, Math.min(cx, bounds.x+bounds.width-p.width));
        const y = Math.max(bounds.y, Math.min(cy, bounds.y+bounds.height-p.height));
        const box = {x, y, width: p.width, height: p.height};
        if (x < bounds.x || y < bounds.y || x+p.width > bounds.x+bounds.width || y+p.height > bounds.y+bounds.height ||
            occupied.some(r => overlaps(box, r))) continue;
        labels[i] = box; occupied.push(box); break;
      }
    });
    return labels;
  }
  function scatterKey(t) {
    const list = byId('scatter-key');
    if (!list) return;
    if (!list.children.length) data.scatter.points.forEach((r, i) => {
      const item = document.createElement('li'), button = document.createElement('button');
      button.type = 'button'; button.className = 'scatter-model';
      const chip = document.createElement('span'); chip.className = 'scatter-marker'; chip.setAttribute('aria-hidden', 'true');
      const text = document.createElement('span'); text.textContent = r.model;
      const stats = document.createElement('small'); stats.textContent = `${fmt(r.steps)} steps per attempt (median) · ${pct(r.score)} of ${fmt(data.task_count)} tasks solved`;
      text.append(stats); button.append(chip, text); item.append(button); list.append(item);
      const show = () => instances.get('scatter')?.dispatchAction({type: 'showTip', seriesIndex: 0, dataIndex: i});
      button.addEventListener('focus', show); button.addEventListener('mouseenter', show);
      button.addEventListener('blur', () => instances.get('scatter')?.dispatchAction({type: 'hideTip'}));
      button.addEventListener('keydown', event => {
        if (event.key === 'Escape') instances.get('scatter')?.dispatchAction({type: 'hideTip'});
        const next = {ArrowDown: (i+1)%data.scatter.points.length, ArrowUp: (i+data.scatter.points.length-1)%data.scatter.points.length, Home: 0, End: data.scatter.points.length-1}[event.key];
        if (next !== undefined) { event.preventDefault(); list.children[next].children[0].focus(); }
      });
    });
    data.scatter.points.forEach((r, i) => {
      const style = modelStyle(r.model, t), chip = list.children[i].children[0].children[0];
      chip.style.backgroundColor = style.color;
      chip.style.backgroundImage = modelFamily(r.model).patterned
        ? `repeating-linear-gradient(135deg, transparent 0 3px, ${labelInk(style.color, t)} 3px 4px)` : 'none';
      chip.style.opacity = style.opacity;
    });
  }
  function scatter(t, compact) {
    const chart = data.scatter, option = base(t), element = byId('chart-scatter');
    scatterKey(t);
    const grid = {top: 142, bottom: 116, left: 48, right: 18};
    option.grid = grid;
    const maxX = Math.ceil(Math.max(0, ...chart.points.map(p => p.steps))/10)*10+10;
    const maxY = Math.min(100, Math.ceil(Math.max(0, ...chart.points.map(p => p.score))/10)*10+10);
    option.xAxis = {...axis(t), min: 0, max: maxX, name: 'Steps per attempt (median)', nameLocation: 'middle', nameGap: 36,
      splitNumber: compact ? 3 : 6};
    option.yAxis = {...axis(t), min: 0, max: maxY, name: `Tasks solved (% of ${fmt(data.task_count)})`, nameGap: 20,
      nameTextStyle: {...axis(t).nameTextStyle, align: 'left'},
      axisLabel: {...axis(t).axisLabel, formatter: '{value}%'}};
    option.tooltip.formatter = p => {
      const r = chart.points[p.dataIndex];
      return `${p.dataIndex+1}. ${modelTitle(r.model)}<br><strong>${pct(r.score)}</strong> of ${fmt(data.task_count)} tasks solved<br>`+
        `${fmt(r.steps)} steps per attempt (median across ${fmt(r.samples)} attempts with recorded model calls)`;
    };
    const leaders = new Set(data.leaderboards.Full.rows.filter(r => r.rank === 1).map(r => r.model));
    option.graphic = [
      ['fewer steps, higher score', 'left', 'top'], ['more steps, higher score', 'right', 'top'],
      ['fewer steps, lower score', 'left', 'bottom'], ['more steps, lower score', 'right', 'bottom']
    ].map(([text, x, y]) => ({type: 'text', [x]: 4, [y]: 4,
      silent: true, style: {text: compact ? text.replace(', ', ',\n') : text, fill: t['ink-muted'], font: '13px IBM Plex Sans, sans-serif'}}));
    if (chart.points.length) option.graphic.push(...[
      `Half the models take more than ${fmt(chart.reference.steps)} steps`,
      `Half the models solve more than ${pct(chart.reference.score)}`
    ].map((text, i) => ({type: 'text', left: 4, top: 62+i*22, silent: true,
      style: {text, fill: t['ink-muted'], font: '13px IBM Plex Sans, sans-serif'}})));
    const bounds = {x: grid.left, y: grid.top, width: element.clientWidth-grid.left-grid.right,
      height: (element.clientHeight || element.height)-grid.top-grid.bottom};
    const labelTexts = chart.points.map((r, i) => `${i+1}. ${compact ? modelFamily(r.model).name : short(r.model, true)}`);
    const sizes = labelTexts.map(text => echarts.format.getTextRect(text, '13px IBM Plex Sans, sans-serif'));
    const positions = chart.points.map((p, i) => ({x: bounds.x+p.steps/maxX*bounds.width, y: bounds.y+(1-p.score/maxY)*bounds.height,
      width: sizes[i].width*1.15+8, height: 18}));
    const priority = chart.points.length ? [0, chart.points.reduce((a, p, i) => p.score < chart.points[a].score ? i : a, 0),
      chart.points.reduce((a, p, i) => p.steps > chart.points[a].steps ? i : a, 0)] : [];
    const labels = scatterLabels(positions, bounds, priority);
    option.series = [{type: 'scatter', symbolSize: 10,
      data: chart.points.map((r, i) => ({name: r.model, value: [r.steps, r.score], label: {show: !!labels[i]},
        itemStyle: {...modelStyle(r.model, t), borderColor: leaders.has(r.model) ? t.ink : t['surface-raised'],
          borderWidth: leaders.has(r.model) ? 2 : 1}})),
      label: {show: true, color: t.ink, fontSize: 13, formatter: p => labelTexts[p.dataIndex]},
      labelLayout: params => ({hideOverlap: true, x: labels[params.dataIndex]?.x, y: labels[params.dataIndex]?.y,
        align: 'left', verticalAlign: 'top'}),
      labelLine: {show: false}, emphasis: {scale: 1.4, itemStyle: {opacity: 1}},
      markLine: {symbol: 'none', silent: true, lineStyle: {color: t['line-strong'], type: 'dashed', width: 1},
        label: {show: false},
        data: chart.points.length ? [{xAxis: chart.reference.steps}, {yAxis: chart.reference.score}] : []}}];
    // ECharts' scatter symbols ignore itemStyle.decal. Clip fine diagonal
    // strokes to the point so variants keep their pattern in the SVG renderer.
    const patterned = chart.points.filter(r => modelFamily(r.model).patterned);
    option.series.push({id: 'point-decals', type: 'custom', silent: true, z: 5,
      data: patterned.map(r => [r.steps, r.score]), renderItem: (params, api) => {
        const r = patterned[params.dataIndex], center = api.coord([api.value(0), api.value(1)]);
        const [x, y] = center, style = modelStyle(r.model, t);
        return {type: 'group', clipPath: {type: 'circle', shape: {cx: x, cy: y, r: 4}},
          children: [-3, 1, 5].map(offset => ({type: 'line',
            shape: {x1: x-5, y1: y+5+offset, x2: x+5, y2: y-5+offset},
            style: {stroke: labelInk(style.color, t), lineWidth: .7, opacity: style.opacity}}))};
      }});
    return option;
  }
  function officialRows() {
    return data.official.subsets[officialSubset].entries.filter(r =>
      (!(officialMask & 1) || r.mini) && (!(officialMask & 2) || r.os_model) && (!(officialMask & 4) || r.attempts === '1'));
  }
  function ourRows() {
    return data.leaderboards[officialSubset].rows.filter(r => r.score != null).slice().sort((a, b) => b.score-a.score || a.model.localeCompare(b.model));
  }
  // Two alternating rank rows. Pool adjacent collisions to minimise horizontal
  // movement, with a fixed gap for numbered markers and their focus outlines.
  // Scores remain exact in the key/card; the spacing is disclosed beside them.
  function officialMarkerLayout(rows, axisMax, width) {
    const left = 16, right = width-16, gap = 28;
    const points = rows.map((r, i) => ({x: left+r.score/axisMax*(right-left), y: i%2 ? .5 : .78}));
    for (let lane = 0; lane < 2; lane++) {
      const indices = rows.map((_, i) => i).filter(i => i%2 === lane).reverse(), pools = [];
      indices.forEach((id, i) => {
        pools.push({ids: [id], sum: points[id].x-i*gap});
        while (pools.length > 1) {
          const a = pools.at(-2), b = pools.at(-1);
          if (a.sum/a.ids.length <= b.sum/b.ids.length) break;
          pools.splice(-2, 2, {ids: [...a.ids, ...b.ids], sum: a.sum+b.sum});
        }
      });
      let index = 0;
      pools.forEach(pool => {
        const base = Math.max(left, Math.min(right-(indices.length-1)*gap, pool.sum/pool.ids.length));
        pool.ids.forEach(id => { points[id].x = base+index++*gap; });
      });
    }
    return points.map(p => ({...p, value: [(p.x-left)/(right-left)*axisMax, p.y]}));
  }
  function officialDensity(rows, axisMax, bins = 40) {
    const counts = Array(bins).fill(0);
    rows.forEach(r => { counts[Math.min(bins-1, Math.floor(r.resolved/axisMax*bins))]++; });
    return counts;
  }
  function officialPointText(r, ours) {
    return ours ? `${r.model} · ${pct(r.score)} resolved · ${fmt(data.confidence*100)}% Wilson interval ${r.interval.map(pct).join('–')}` :
      `${r.name} · Agent: ${r.agent} · Model: ${r.model_display} · ${pct(r.resolved)} resolved · Date: ${r.date} · Attempts: ${r.attempts}`;
  }
  function officialKey(t) {
    const list = byId('official-key'), rows = ourRows(), card = byId('official-card');
    const identity = JSON.stringify(rows);
    if (list.dataset.models !== identity) {
      list.replaceChildren(); list.dataset.models = identity;
      rows.forEach((r, i) => {
        const li = document.createElement('li'), button = document.createElement('button');
        button.type = 'button'; button.className = 'official-model';
        const number = document.createElement('span'); number.textContent = String(i+1);
        number.className = 'official-number'; number.setAttribute('aria-hidden', 'true');
        const chip = document.createElement('span'); chip.className = 'family-chip'; chip.setAttribute('aria-hidden', 'true');
        const name = document.createElement('span'); name.className = 'official-model-name'; name.textContent = r.model;
        const score = document.createElement('span'); score.className = 'official-score'; score.textContent = pct(r.score);
        button.setAttribute('aria-label', `${i+1}. ${modelFamily(r.model).name}: ${officialPointText(r, true)}`);
        button.append(number, chip, name, score); li.append(button); list.append(li);
        const show = () => { card.textContent = officialPointText(r, true); card.hidden = false; };
        button.addEventListener('focus', show); button.addEventListener('mouseenter', show); button.addEventListener('click', show);
        button.addEventListener('blur', () => { card.hidden = true; });
        button.addEventListener('mouseleave', () => { if (document.activeElement !== button) card.hidden = true; });
        button.addEventListener('keydown', event => { if (event.key === 'Escape') card.hidden = true; });
      });
    }
    rows.forEach((r, i) => {
      const chip = list.children[i].children[0].children[1], style = modelStyle(r.model, t);
      chip.style.backgroundColor = style.color;
      chip.style.backgroundImage = modelFamily(r.model).patterned
        ? `repeating-linear-gradient(135deg, transparent 0 3px, ${labelInk(style.color, t)} 3px 4px)` : 'none';
    });
    byId('official-key-wrap').hidden = false;
  }
  function official(t, compact) {
    const board = data.official.subsets[officialSubset], rows = officialRows(), ours = ourRows(), option = base(t);
    // A single shared percentage axis for the two strips; each subset keeps its
    // own unfiltered domain so switching filters cannot distort positions.
    const width = byId('chart-official').clientWidth;
    const markers = officialMarkerLayout(ours, board.axis_max, width);
    const summary = board.summaries[String(officialMask)];
    const density = officialDensity(rows, board.axis_max);
    option.grid = {top: 40, bottom: 64, left: 16, right: 16};
    option.xAxis = {...axis(t), min: 0, max: board.axis_max, splitNumber: compact ? 3 : 6,
      axisLabel: {...axis(t).axisLabel, formatter: '{value}%'}, name: 'Share of tasks solved (%)', nameLocation: 'middle', nameGap: 32};
    option.yAxis = {...axis(t), min: 0, max: 2, show: false};
    option.graphic = ['Official leaderboard entries (one dot each)', 'Our models'].map((text, i) => ({type: 'text', left: 0, top: i ? 142 : 4,
      silent: true, style: {text, fill: t['ink-muted'], font: '13px IBM Plex Sans, sans-serif'}}));
    if (summary.median != null) option.graphic.push({type: 'text', left: 0, top: 124, silent: true,
      style: {text: `Median of official entries: ${pct(summary.median)}`, fill: t['ink-muted'], font: '13px IBM Plex Sans, sans-serif'}});
    [...new Set([0, ours.length-1])].filter(i => ours[i]).forEach(i => {
      const text = `${i+1}. ${short(ours[i].model, true)}\n${i ? 'Lowest' : 'Leader'} · ${pct(ours[i].score)}`;
      const size = echarts.format.getTextRect(text, '13px IBM Plex Sans, sans-serif');
      option.graphic.push({type: 'text', left: Math.max(0, Math.min(width-size.width, markers[i].x-size.width/2)),
        top: i ? 274 : 164, silent: true, style: {text, fill: t.ink, font: '13px IBM Plex Sans, sans-serif', lineHeight: 16}});
    });
    option.tooltip.formatter = p => escape(officialPointText((p.seriesIndex === 1 ? ours : rows)[p.dataIndex], p.seriesIndex === 1));
    option.series = [{type: 'scatter', symbolSize: 7,
      data: rows.map(r => ({name: r.name, value: [r.resolved, 1.6 + board.jitter[r.id]], symbol: r.os_model ? 'diamond' : 'circle',
        itemStyle: {color: r.mini ? t.ink : t['ink-muted'], opacity: r.mini ? 1 : .55}})),
      emphasis: {scale: 1.7, itemStyle: {opacity: 1}}},
    {type: 'scatter', symbolSize: 22, z: 4,
      data: ours.map((r, i) => ({name: r.model, value: markers[i].value,
        label: {color: labelInk(modelStyle(r.model, t).color, t)},
        itemStyle: {...modelStyle(r.model, t), opacity: 1, borderColor: t.ink, borderWidth: r.rank === 1 ? 2 : 1}})),
      label: {show: true, position: 'inside', fontSize: 13, formatter: p => String(p.dataIndex+1)},
      labelLine: {show: false}, emphasis: {scale: false}},
    {id: 'official-density', type: 'custom', silent: true, z: 0,
      data: density.map((count, i) => [i, count]),
      renderItem: (_, api) => {
        const count = api.value(1);
        if (!count) return;
        const a = api.coord([api.value(0)/density.length*board.axis_max, 1.78]);
        const b = api.coord([(api.value(0)+1)/density.length*board.axis_max, 1.42]);
        return {type: 'rect', shape: {x: a[0], y: a[1], width: b[0]-a[0], height: b[1]-a[1]},
          style: {fill: t['ink-muted'], opacity: .04+.16*count/Math.max(...density)}};
      }},
    {id: 'official-median-tick', type: 'custom', silent: true, z: 3,
      data: summary.median == null ? [] : [[summary.median]],
      renderItem: (_, api) => {
        const a = api.coord([api.value(0), 1.83]), b = api.coord([api.value(0), 1.43]);
        return {type: 'line', shape: {x1: a[0], y1: a[1], x2: b[0], y2: b[1]},
          style: {stroke: t.ink, lineWidth: 1}};
      }}];
    return option;
  }
  function officialFocus(chart) {
    const layer = byId('official-focus'), card = byId('official-card');
    const previous = document.activeElement?.dataset.officialPoint;
    layer.replaceChildren();
    const board = data.official.subsets[officialSubset];
    const markers = officialMarkerLayout(ourRows(), board.axis_max, byId('chart-official').clientWidth);
    [officialRows(), ourRows()].forEach((rows, group) => {
      const buttons = rows.map((r, i) => {
        const button = document.createElement('button'), identity = `${group}:${r.id || r.model}`;
        button.type = 'button'; button.className = 'official-point'; button.dataset.officialPoint = identity;
        button.tabIndex = i === 0 ? 0 : -1;
        button.setAttribute('aria-label', officialPointText(r, group === 1));
        button.setAttribute('aria-describedby', 'official-help');
        const [x, y] = chart.convertToPixel({gridIndex: 0}, group ? markers[i].value : [r.resolved, 1.6 + board.jitter[r.id]]);
        button.style.left = `${x}px`; button.style.top = `${y}px`;
        const show = () => { card.textContent = officialPointText(r, group === 1); card.hidden = false; };
        button.addEventListener('focus', show); button.addEventListener('mouseenter', show);
        button.addEventListener('click', show);
        button.addEventListener('blur', () => { card.hidden = true; });
        button.addEventListener('mouseleave', () => { if (document.activeElement !== button) card.hidden = true; });
        button.addEventListener('keydown', event => {
          if (event.key === 'Escape') { card.hidden = true; return; }
          const next = {ArrowRight: (i+1)%rows.length, ArrowDown: (i+1)%rows.length,
            ArrowLeft: (i+rows.length-1)%rows.length, ArrowUp: (i+rows.length-1)%rows.length, Home: 0, End: rows.length-1}[event.key];
          if (next !== undefined) {
            event.preventDefault(); buttons.forEach(b => { b.tabIndex = -1; }); buttons[next].tabIndex = 0; buttons[next].focus();
          }
        });
        layer.append(button);
        return button;
      });
      const restore = buttons.find(b => b.dataset.officialPoint === previous);
      if (restore) { buttons.forEach(b => { b.tabIndex = -1; }); restore.tabIndex = 0; restore.focus(); }
    });
  }
  function updateOfficial() {
    const board = data.official.subsets[officialSubset], summary = board.summaries[String(officialMask)];
    byId('title-official').textContent = summary.title;
    byId('chart-official').setAttribute('aria-label', summary.title);
    byId('official-caption').textContent = summary.caption;
    byId('official-count').textContent = summary.filter_help;
    byId('official-card').hidden = true;
    document.querySelectorAll('[data-official-filter]').forEach(b => b.setAttribute('aria-pressed',
      String(Number(b.dataset.officialFilter) === 0 ? officialMask === 0 : !!(officialMask & Number(b.dataset.officialFilter)))));
    document.querySelectorAll('[data-official-subset]').forEach(tab => {
      const active = tab.dataset.officialSubset === officialSubset;
      tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1;
      byId(tab.getAttribute('aria-controls')).hidden = !active;
    });
    const target = byId(`official-rows-${officialSubset}`); target.replaceChildren();
    officialRows().sort((a, b) => (officialAscending[officialSubset] ? a.resolved-b.resolved : b.resolved-a.resolved) || a.id.localeCompare(b.id)).forEach(r => {
      const tr = document.createElement('tr');
      [r.name, r.agent, r.model_display, pct(r.resolved), r.date, r.attempts].forEach((value, i) => {
        const cell = document.createElement(i ? 'td' : 'th'); if (!i) cell.setAttribute('scope', 'row');
        cell.textContent = value; tr.append(cell);
      });
      target.append(tr);
    });
    byId(`official-footer-${officialSubset}`).textContent = summary.footer;
    const panel = byId(`official-panel-${officialSubset}`);
    panel.querySelector('caption').textContent = `${officialSubset} official entries · ${officialMask ? 'Current filters' : 'All entries'}`;
    panel.querySelector('[aria-sort]').setAttribute('aria-sort', officialAscending[officialSubset] ? 'ascending' : 'descending');
    render('official');
  }
  function startOfficial() {
    const tabs = Array.from(document.querySelectorAll('[data-official-subset]'));
    const safely = fn => { try { fn(); } catch (_) { fail(); } };
    tabs.forEach((tab, i) => {
      tab.addEventListener('click', () => safely(() => { officialSubset = tab.dataset.officialSubset; updateOfficial(); }));
      tab.addEventListener('keydown', e => {
        const next = {ArrowRight: (i+1)%tabs.length, ArrowLeft: (i+tabs.length-1)%tabs.length, Home: 0, End: tabs.length-1}[e.key];
        if (next !== undefined) { e.preventDefault(); tabs[next].click(); tabs[next].focus(); }
      });
    });
    document.querySelectorAll('[data-official-filter]').forEach(button => button.addEventListener('click', () => safely(() => {
      const mask = Number(button.dataset.officialFilter); officialMask = mask ? officialMask ^ mask : 0; updateOfficial();
    })));
    document.querySelectorAll('[data-official-sort]').forEach(button => button.addEventListener('click', () => safely(() => {
      officialAscending[officialSubset] = !officialAscending[officialSubset]; updateOfficial();
    })));
    updateOfficial(); byId('official-table').open = false; byId('official-help').hidden = false;
  }
  function accumulation(t, compact) {
    const h = data.difficulty, rows = h.orders[accumulationOrder];
    const option = base(t, h.title);
    const wrapModel = model => {
      if (!model) return '0';
      const label = compact ? model.replace('nemotron-', 'N-').replace('deepseek-', 'DS-')
        .replace('minimax-', 'MM-').replace('-uncensored', '-unc.').replace('-lightning', '-light.') : model;
      const parts = label.split('-');
      return parts.reduce((lines, part) => {
        if (lines.at(-1).length + part.length < 11) lines[lines.length-1] += (lines.at(-1) ? '-' : '')+part;
        else lines.push(part);
        return lines;
      }, ['']).join('\n');
    };
    option.grid = {left: 68, right: 75, top: 64, bottom: 190};
    option.xAxis = {...axis(t, 'category'), boundaryGap: false, data: rows.map(r => r.models),
      name: 'Number of models combined', nameLocation: 'middle', nameGap: 154,
      axisLabel: {interval: 0, color: t.ink, fontSize: 13, lineHeight: 18, margin: 16,
        rich: familyRich(t), formatter: (_, i) => i ? `${i} {${modelFamily(rows[i].model).key}|}\n${wrapModel(rows[i].model)}` : '0'}};
    option.yAxis = {...axis(t), min: 0, max: data.task_count,
      name: 'Tasks solved by at least one of them', nameLocation: 'end', nameGap: 38,
      nameTextStyle: {color: t.ink, fontSize: 13, align: 'left'},
      axisLabel: {color: t['ink-muted'], fontSize: 13, formatter: value => fmt(value), showMaxLabel: false}};
    option.tooltip = {...option.tooltip, trigger: 'item', formatter: p => {
      const row = rows[p.dataIndex];
      return row ? `${escape(row.model || 'No models')}<br>+${fmt(row.new)} new tasks<br>${fmt(row.solved)} tasks solved by at least one model` : '';
    }};
    const note = (text, position, offset) => ({show: true, formatter: text,
      position, offset, color: t.ink, fontSize: 13, lineHeight: 20,
      backgroundColor: t['surface-raised'], padding: [4, 6], borderRadius: 3});
    option.series = [{id: 'accumulation', name: 'Tasks solved', type: 'line', step: 'end',
      data: rows.map(r => r.solved), symbol: 'circle', symbolSize: 6,
      lineStyle: {color: t['role-frame'], width: 3}, itemStyle: {color: t['role-frame']},
      areaStyle: {color: t['role-selector-soft'], opacity: 1},
      label: {show: true, position: 'top', distance: 9, color: t.ink, fontSize: 13, lineHeight: 17,
        formatter: p => p.dataIndex ? `+${fmt(rows[p.dataIndex].new)}\nnew tasks` : ''},
      markLine: {silent: true, symbol: 'none', lineStyle: {color: t.ink, width: 2, type: 'solid'},
        label: {show: true, position: 'insideStartTop', color: t.ink, fontSize: 13,
          formatter: `All ${fmt(data.task_count)} tasks`}, data: [{yAxis: data.task_count}]},
      markArea: {silent: true, itemStyle: {color: t['role-move-soft'],
          decal: {...diagonal(t['role-move']), dashArrayY: [1, 8]}},
        label: note((data.provisional ? 'Provisional: ' : '')+h.never_label, 'inside', [0, 0]),
        data: [[{yAxis: h.union}, {yAxis: data.task_count}]]},
      markPoint: {symbolSize: 0, silent: true, data: [
        {coord: [1, rows[1].solved], label: note(`${rows[1].model} alone solves\n${fmt(rows[1].solved)} (${Math.round(100*rows[1].solved/data.task_count)}%)`, 'insideTopLeft', [10, 50])},
        {coord: [data.model_count, h.union], label: note(h.last_label.replace(' solve ', ' solve\n'), 'insideTopRight', [-10, 50])}
      ]}}];
    return option;
  }
  function selectAccumulation(name) {
    accumulationOrder = name;
    root.querySelectorAll('[data-accumulation-order]').forEach(tab => {
      const active = tab.dataset.accumulationOrder === name;
      tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1;
      byId(tab.getAttribute('aria-controls')).hidden = !active;
    });
    render('accumulation');
  }
  function startAccumulation() {
    const tabs = Array.from(root.querySelectorAll('[data-accumulation-order]'));
    tabs.forEach((tab, i) => {
      tab.addEventListener('click', () => { try { selectAccumulation(tab.dataset.accumulationOrder); } catch (_) { fail(); } });
      tab.addEventListener('keydown', event => {
        const next = {ArrowRight: (i+1)%tabs.length, ArrowLeft: (i+tabs.length-1)%tabs.length, Home: 0, End: tabs.length-1}[event.key];
        if (next !== undefined) { event.preventDefault(); tabs[next].click(); tabs[next].focus(); }
      });
    });
    selectAccumulation(accumulationOrder);
  }
  const builders = {leaderboard, outcomes, unique, heatmap, scatter, official, accumulation};
  function render(key) {
    const element = byId(`chart-${key}`);
    element.hidden = false;
    const compact = (key === 'accumulation' ? element.parentElement.clientWidth : element.clientWidth) < 600;
    if (!instances.has(key)) instances.set(key, echarts.init(element, null, {renderer: 'svg'}));
    const chart = instances.get(key);
    chart.resize();
    chart.setOption(builders[key](tokens(), compact), {replaceMerge: key === 'official' ? ['series', 'graphic'] : ['series'], lazyUpdate: false});
    if (key === 'official') { officialFocus(chart); officialKey(tokens()); }
  }
  function fail() {
    root.querySelector('.chart-fallback').hidden = false;
    root.querySelectorAll('.chart-data').forEach(d => { d.open = true; });
    root.querySelectorAll('[role="tabpanel"]').forEach(p => { p.hidden = false; });
    byId('official-table').open = true;
    byId('official-focus').replaceChildren();
    byId('official-help').hidden = true;
    byId('official-card').hidden = true;
    byId('official-key-wrap').hidden = true;
    document.querySelectorAll('[data-official-subset]').forEach(tab => { byId(tab.getAttribute('aria-controls')).hidden = false; });
    keys.forEach(key => { byId(`chart-${key}`).hidden = true; });
    instances.forEach(chart => chart.dispose());
    instances.clear();
  }
  function redraw() {
    clearTimeout(timer);
    timer = setTimeout(() => { try { keys.forEach(render); } catch (_) { fail(); } }, 100);
  }
  function select(name) {
    subset = name;
    const board = data.leaderboards[name];
    byId('title-leaderboard').textContent = board.title;
    byId('chart-leaderboard').setAttribute('aria-label', board.title);
    byId('source-leaderboard').textContent = `Based on ${fmt(data.model_count)} models x ${fmt(board.rows[0].total)} tasks = ${fmt(data.model_count*board.rows[0].total)} attempts. ${fmt(board.attempts)} attempts graded.`;
    root.querySelectorAll('[data-chart-subset]').forEach(tab => {
      const active = tab.dataset.chartSubset === name;
      tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1;
      byId(tab.getAttribute('aria-controls')).hidden = !active;
    });
    render('leaderboard');
  }
  async function start() {
    try {
      if (typeof echarts === 'undefined') throw new Error('Chart library unavailable');
      const response = await fetch(root.dataset.charts);
      if (!response.ok) throw new Error('Chart data unavailable');
      data = await response.json();
      modelList = data.model_order;
      makeLegends();
      keys.forEach(render);
      select(subset);
      startOfficial();
      startAccumulation();
      root.querySelector('.chart-fallback').hidden = true;
      root.querySelectorAll('.chart-data').forEach(d => { d.open = false; });
      const tabs = Array.from(root.querySelectorAll('[data-chart-subset]'));
      tabs.forEach((tab, i) => {
        tab.addEventListener('click', () => { try { select(tab.dataset.chartSubset); } catch (_) { fail(); } });
        tab.addEventListener('keydown', event => {
          const next = {ArrowRight: (i+1)%tabs.length, ArrowLeft: (i+tabs.length-1)%tabs.length, Home: 0, End: tabs.length-1}[event.key];
          if (next !== undefined) { event.preventDefault(); tabs[next].click(); tabs[next].focus(); }
        });
      });
      document.addEventListener('themechange', redraw);
      scheme.addEventListener('change', redraw);
      motion.addEventListener('change', redraw);
      window.addEventListener('resize', redraw);
      if (document.fonts) document.fonts.ready.then(redraw);
    } catch (_) { fail(); }
  }
  start();
})();
