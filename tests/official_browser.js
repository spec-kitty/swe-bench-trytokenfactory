// Runs inside each offline review frame in a real browser, not a mocked DOM.
(async () => {
  const errors = [], check = (ok, message) => { if (!ok) errors.push(message); };
  await new Promise(resolve => setTimeout(resolve, 1200));
  const card = document.getElementById('card-official');
  const charts = await (await fetch()).json();
  check(!!card.querySelector('svg'), 'chart did not render');
  check(document.documentElement.scrollWidth <= innerWidth, 'horizontal page scroll');
  const difficulty = document.querySelector('.difficulty-bar');
  const groups = [...difficulty.querySelectorAll('.difficulty-group')];
  check(groups.length === charts.difficulty.rows.length, 'missing difficulty groups');
  groups.forEach((group, i) => {
    const fill = group.querySelector('.difficulty-fill'), label = group.querySelector('.difficulty-label');
    const rect = fill.getBoundingClientRect();
    check(Math.abs(rect.width - difficulty.clientWidth * charts.difficulty.rows[i].percentage / 100) < 1,
      'difficulty segment not proportional');
    check(label.scrollWidth <= label.clientWidth, 'difficulty text overflow');
    check(label.getBoundingClientRect().right <= innerWidth, 'difficulty label outside viewport');
    group.focus();
    check(getComputedStyle(group.querySelector('.difficulty-tip')).display !== 'none', 'difficulty focus detail unavailable');
    group.blur();
    if (innerWidth === 375 && i) {
      check(group.getBoundingClientRect().top > groups[i-1].getBoundingClientRect().bottom, 'difficulty rows overlap');
    }
  });
  const examples = [...document.querySelectorAll('.difficulty-examples figure')];
  examples.forEach(figure => check(figure.scrollWidth <= figure.clientWidth, 'example text overflow'));
  check(examples.length === charts.difficulty.examples.length, 'missing task examples');
  card.querySelectorAll('[aria-pressed],[aria-selected]').forEach(node => {
    check(!getComputedStyle(node).textDecorationLine.includes('line-through'), 'struck-through chip/tab');
    const r = node.getBoundingClientRect();
    check(r.left >= 0 && r.right <= innerWidth, 'chip/tab outside viewport');
  });
  const subset = document.getElementById('official-tab-Verified');
  subset.click();
  await new Promise(resolve => setTimeout(resolve, 800));
  const key = document.querySelectorAll('#official-key li');
  check(key.length === charts.leaderboards.Verified.rows.filter(r => r.score != null).length, 'missing numbered key');
  key.forEach(row => {
    check(row.scrollWidth <= row.clientWidth, 'key text overflow');
  });
  if (innerWidth === 375 && key.length) {
    check(new Set([...key].map(row => Math.round(row.getBoundingClientRect().left))).size === 1, 'key must be one column');
  }
  const focus = [...document.querySelectorAll('#official-focus button')];
  const texts = [...card.querySelectorAll('#chart-official svg text')].map(t => t.getBoundingClientRect());
  texts.forEach((a, i) => texts.slice(i+1).forEach(b => {
    check(!(a.left < b.right-.5 && a.right > b.left+.5 && a.top < b.bottom-.5 && a.bottom > b.top+.5), 'chart labels overlap');
  }));
  check(focus.filter(b => b.tabIndex === 0).length === 2, 'row keyboard entry points');
  focus[0]?.focus();
  check(!document.getElementById('official-card').hidden, 'focus card unavailable');
  focus[0]?.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  check(document.getElementById('official-card').hidden, 'Escape failed');
  focus[0]?.blur();
  card.scrollIntoView();
  parent.postMessage({review: document.documentElement.dataset.theme+'-'+innerWidth,
    result: errors.length ? errors.join(', ') : 'PASS'}, '*');
})();
