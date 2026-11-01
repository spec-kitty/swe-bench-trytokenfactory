// Exercise production helpers directly; fixtures come from the generated CSS tokens.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const echarts = require('../vendor/echarts/echarts.min.js');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync('tools/site_assets/charts.js', 'utf8');
const modelElements = input.models.map(model => ({dataset: {modelPalette: model, modelList: JSON.stringify(input.models)},
  style: {setProperty(key, value) { this[key] = value; }}}));
const context = vm.createContext({echarts, document: {querySelector: () => null, querySelectorAll: () => modelElements}});
vm.runInContext(source.replace("  const root = document.querySelector", '  globalThis.palette = {modelFamily, mix, heatFill, labelInk, outcomeStyles, contrast, scatterLabels, overlaps};\n  const root = document.querySelector'), context);
const {modelFamily, mix, heatFill, labelInk, outcomeStyles, contrast, scatterLabels, overlaps} = context.palette;
assert.equal(modelFamily('glm-5.3-flash', ['glm-6', 'glm-5.3-flash']).flash, false);
assert.equal(modelFamily('glm-5.3-flash', ['glm-5.3-uncensored-fp8']).flash, true);
assert.equal(modelFamily('glm-5.3-flash', ['glm-5.3-other']).flash, false);
assert.equal(modelFamily('glm-5.3-flashbang', ['glm-5.3']).flash, false);
const families = input.models.map(model => modelFamily(model));
assert.deepEqual(families, input.models.map(model => modelFamily(model)));
const ramps = Object.fromEntries(Object.entries(input.themes).map(([name, t]) => [name,
  Array.from({length: 1001}, (_, i) => {
    const fill = heatFill(t, i/1000);
    return {fill, label: labelInk(fill, t)};
  })]));
assert.equal(mix(input.themes.light.build, input.themes.light.ink, -1), mix(input.themes.light.build, input.themes.light.ink, 0));
assert.equal(mix(input.themes.dark.build, input.themes.dark.ink, 2), mix(input.themes.dark.build, input.themes.dark.ink, 1));
const outcomeContrast = {};
for (const [theme, t] of Object.entries(input.themes)) {
  const styles = outcomeStyles(t);
  assert.equal(styles.resolved.color, t['success-ink']);
  assert.equal(styles.patch.color, t['accent-soft']);
  assert.equal(styles.empty.color, t['warning-soft']);
  assert.equal(styles.timeout.color, t['danger-ink']);
  for (const key of ['resolved', 'patch', 'timeout']) assert.equal(styles[key].decal, undefined);
  assert.equal(styles.empty.decal.color, t['warning-ink']);
  // Thin hatch occupies one of each five units. Compare area-averaged
  // linear-light luminance, plus retain the raw background result for audit.
  const fills = [styles.resolved.color, styles.patch.color,
    mix(styles.empty.color, t['warning-ink'], 1/5), styles.timeout.color];
  outcomeContrast[theme] = {background: contrast(styles.patch.color, styles.empty.color),
    adjacent: fills.slice(1).map((f, i) => contrast(fills[i], f))};
  outcomeContrast[theme].adjacent.forEach(ratio => assert(ratio >= 1.15));
}
for (const width of [309, 654, 796, 1166]) {
  const bounds = {x: 48, y: 142, width: width-66, height: 500};
  const points = Array.from({length: 12}, (_, i) => ({x: 70+i*3, y: 170+i*7, width: 90, height: 18}));
  points[11] = {x: width-90, y: 590, width: 70, height: 18};
  const labels = scatterLabels(points, bounds, [0, 11]);
  assert(labels[0]); assert(labels[11]);
  const visible = labels.filter(Boolean);
  visible.forEach((a, i) => {
    assert(a.x >= bounds.x && a.y >= bounds.y && a.x+a.width <= bounds.x+bounds.width && a.y+a.height <= bounds.y+bounds.height);
    visible.slice(i+1).forEach(b => assert(!overlaps(a, b)));
    points.forEach(p => assert(!overlaps(a, {x: p.x-6, y: p.y-6, width: 12, height: 12})));
  });
}
process.stdout.write(JSON.stringify({families, ramps, outcomeContrast, modelColors: modelElements.map(e => e.style['--model-color'])}));
