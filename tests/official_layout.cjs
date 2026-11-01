// Test the production layout directly, including score ties and both boundaries.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('tools/site_assets/charts.js', 'utf8');
const data = JSON.parse(fs.readFileSync('docs/data/charts.json', 'utf8'));
const context = vm.createContext({document: {querySelector: () => null, querySelectorAll: () => []}});
vm.runInContext(source.replace('  const root = document.querySelector',
  '  globalThis.layout = {officialMarkerLayout, officialDensity};\n  const root = document.querySelector'), context);
const {officialMarkerLayout, officialDensity} = context.layout;
for (const width of [309, 654, 1166]) {
  const fixtures = Object.entries(data.leaderboards).map(([name, board]) => ({
    rows: [...board.rows].sort((a, b) => b.score-a.score || a.model.localeCompare(b.model)),
    max: data.official.subsets[name].axis_max
  }));
  for (const score of [0, 50, 100]) fixtures.push({rows: Array.from({length: 12}, () => ({score})), max: 100});
  fixtures.push({rows: [], max: 100}, {rows: [{score: 50}], max: 100});
  for (const {rows, max} of fixtures) {
    const original = JSON.stringify(rows), points = officialMarkerLayout(rows, max, width);
    assert.equal(JSON.stringify(rows), original, 'Layout mutated scores');
    assert.equal(JSON.stringify(points), JSON.stringify(officialMarkerLayout(rows, max, width)), 'Nondeterministic layout');
    assert.equal(points.length, rows.length);
    points.forEach((a, i) => {
      assert(a.x >= 16 && a.x <= width-16, 'Marker outside plot');
      assert.equal(a.y, i%2 ? .5 : .78, 'Markers must alternate by rank');
      assert(Math.abs(16+a.value[0]/max*(width-32)-a.x) < 1e-9, 'Focus and visual coordinates differ');
      points.slice(i+1).forEach(b => {
        // Actual grid is 276px tall; each 22px marker has a 24px focus target.
        assert(Math.hypot(a.x-b.x, (a.y-b.y)*276/2) >= 28-1e-9, 'Marker/focus targets overlap');
        if (a.y === b.y) assert(a.x > b.x, 'Rank order inverted in a row');
      });
    });
  }
  // Isolated marks must retain their exact score positions.
  const rows = [90, 70, 50, 30, 10].map(score => ({score}));
  officialMarkerLayout(rows, 100, width).forEach((p, i) => assert(Math.abs(p.value[0]-rows[i].score) < 1e-9));
}
for (const board of Object.values(data.official.subsets)) {
  for (let mask = 0; mask < 8; mask++) {
    const rows = board.entries.filter(r => (!(mask&1) || r.mini) && (!(mask&2) || r.os_model) && (!(mask&4) || r.attempts === '1'));
    const bins = officialDensity(rows, board.axis_max);
    assert.equal(bins.reduce((a, b) => a+b, 0), rows.length);
    assert.equal(JSON.stringify(bins), JSON.stringify(officialDensity([...rows].reverse(), board.axis_max)));
    const sorted = rows.map(r => r.resolved).sort((a, b) => a-b);
    const median = sorted.length ? (sorted[Math.floor((sorted.length-1)/2)]+sorted[Math.floor(sorted.length/2)])/2 : null;
    assert.equal(board.summaries[mask].median, median);
  }
}
assert.equal(officialDensity([{resolved: 0}, {resolved: 100}], 100).at(-1), 1);
console.log('Official marker layout: all subsets, ties, bounds, rank order, density and medians passed.');
