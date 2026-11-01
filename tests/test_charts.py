"""Chart math, report semantics, offline assets and the exact library exemption."""
import copy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import build_site as b


def fixture():
    tasks = {f't{i}': 'org/a' if i < 3 else 'org/b' for i in range(6)}
    statuses = {'alpha': dict(zip(tasks, ['resolved', 'unresolved', 'unresolved', 'unresolved', 'resolved', 'unresolved'])),
                'beta': dict(zip(tasks, ['unresolved', 'resolved', 'unresolved', 'unresolved', 'unresolved', 'unresolved']))}
    boards = {'Full': {m: b.count_statuses(s.values()) for m, s in statuses.items()}}
    boards['Verified'] = {m: b.count_statuses([statuses[m]['t0']]) for m in statuses}
    boards['Lite'] = copy.deepcopy(boards['Verified'])
    data = dict(models=list(statuses), tasks=tasks, statuses=statuses, boards=boards,
                repos=['org/a', 'org/b'], subsets={'Full': set(tasks), 'Verified': {'t0'}, 'Lite': {'t0'}},
                repository_counts={m: {r: b.count_statuses(s[i] for i in tasks if tasks[i] == r)
                                      for r in ['org/a', 'org/b']} for m, s in statuses.items()})
    records = {m: {i: dict(grade_reason='empty_patch' if i in ('t2', 't3') else None,
                           usage=dict(steps=n+1, prompt_tokens=None, completion_tokens=None, total_tokens=None))
                   for n, i in enumerate(tasks)} for m in statuses}
    records['alpha']['t5']['grade_reason'] = 'reviewed_test_timeout'
    reviews = [{'original_queue': {'model': 'alpha', 'instance': 't3'}}]
    return data, records, reviews


class ChartDataTests(unittest.TestCase):
    def setUp(self):
        self.data, self.metrics, self.reviews = fixture()
        self.charts = b.chart_data(self.data, self.metrics, self.reviews)

    def test_percentages_and_wilson_use_the_board_denominator(self):
        row = self.charts['leaderboards']['Full']['rows'][0]
        self.assertAlmostEqual(row['score'], 100*2/6)
        self.assertEqual(row['interval'], [v*100 for v in b.wilson(2, 6)])
        self.assertLess(row['interval'][0], row['score'])
        self.assertGreater(row['interval'][1], row['score'])
        for successes in (0, 6):
            lo, hi = b.wilson(successes, 6)
            self.assertTrue(0 <= lo <= successes/6 <= hi <= 1)

    def test_outcomes_partition_attempts_and_do_not_double_count(self):
        for row in self.charts['outcomes']['rows']:
            self.assertEqual(sum(row['counts'].values()), row['total'])
            self.assertAlmostEqual(sum(row['percentages'].values()), 100)
        row = self.charts['outcomes']['rows'][0]
        self.assertEqual(row['counts'], dict(resolved=2, patch=1, empty=1, timeout=2))
        duplicate = b.chart_data(self.data, self.metrics, self.reviews*2)
        self.assertEqual(duplicate, self.charts)

    def test_resolved_precedes_timeout_annotations(self):
        reviews = self.reviews+[dict(model='alpha', instance='t0')]
        self.assertEqual(b.chart_data(self.data, self.metrics, reviews), self.charts)

    def test_histogram_and_heatmap_reconcile(self):
        self.assertEqual(self.charts['difficulty']['union']+self.charts['difficulty']['never'], len(self.data['tasks']))
        for model in self.data['models']:
            cells = [r for r in self.charts['heatmap']['cells'] if r['model'] == model]
            self.assertEqual(sum(r['resolved'] for r in cells), self.data['boards']['Full'][model]['resolved'])
            self.assertEqual(sum(r['total'] for r in cells), len(self.data['tasks']))
        self.assertEqual(self.charts['difficulty']['never'], 3)

    def test_scatter_reuses_model_page_medians_and_observation_counts(self):
        for p in self.charts['scatter']['points']:
            summary = b.usage_summary(self.metrics[p['model']])['steps']
            self.assertEqual((p['steps'], p['samples']), (summary['median'], summary['n']))
        self.metrics['beta'] = {i: dict(grade_reason=None) for i in self.data['tasks']}
        chart = b.chart_data(self.data, self.metrics, self.reviews, limit=3)['scatter']
        self.assertEqual(chart['omitted'], ['beta'])
        self.assertEqual(len(chart['points']), 1)
        self.assertEqual(chart['usage_limit_per_model'], 3)

    def test_subset_uses_authoritative_supplemental_board(self):
        self.data['boards']['Verified']['alpha'] = b.count_statuses(['unresolved'])
        chart = b.chart_data(self.data, self.metrics, self.reviews)
        self.assertEqual(chart['leaderboards']['Verified']['rows'][0]['score'], 0)
        self.assertGreater(chart['leaderboards']['Full']['rows'][0]['score'], 0)

    def test_partial_score_excludes_pending_but_outcomes_retain_it(self):
        self.data['statuses']['alpha']['t1'] = 'ungraded'
        self.data['boards']['Full']['alpha'] = b.count_statuses(self.data['statuses']['alpha'].values())
        chart = b.chart_data(self.data, self.metrics, self.reviews)
        row = chart['leaderboards']['Full']['rows'][0]
        self.assertAlmostEqual(row['score'], 40)
        self.assertAlmostEqual(row['coverage'], 100*5/6)
        self.assertEqual(row['interval'], [v*100 for v in b.wilson(2, 5)])
        outcome = chart['outcomes']['rows'][0]
        self.assertEqual(outcome['counts']['pending'], 1)
        self.assertEqual(sum(outcome['counts'].values()), 6)
        self.assertTrue(chart['leaderboards']['Full']['title'].startswith('Provisional:'))

    def test_pending_is_explicit_and_all_ungraded_is_supported(self):
        for m in self.data['models']:
            self.data['statuses'][m] = dict.fromkeys(self.data['tasks'], 'ungraded')
            self.data['boards']['Full'][m] = b.count_statuses(self.data['statuses'][m].values())
            self.data['repository_counts'][m] = {r: b.count_statuses(['ungraded']*3) for r in self.data['repos']}
        chart = b.chart_data(self.data, self.metrics, self.reviews)
        self.assertTrue(chart['provisional'])
        self.assertIsNone(chart['leaderboards']['Full']['rows'][0]['score'])
        self.assertIsNone(chart['leaderboards']['Full']['rows'][0]['interval'])
        self.assertEqual(chart['outcomes']['rows'][0]['counts']['pending'], 6)
        self.assertEqual(chart['scatter']['points'], [])
        self.assertEqual(chart['heatmap']['title'], 'Provisional: Repository scores await grading')
        self.assertTrue(chart['difficulty']['title'].startswith('Provisional:'))

    def test_ties_and_stable_order(self):
        self.data['boards']['Full']['beta'] = copy.deepcopy(self.data['boards']['Full']['alpha'])
        chart = b.chart_data(self.data, self.metrics, self.reviews)
        self.assertEqual([r['rank'] for r in chart['leaderboards']['Full']['rows']], [1, 1])
        self.assertIn('share the lead', chart['leaderboards']['Full']['title'])
        self.assertEqual(b.json_text(chart), b.json_text(b.chart_data(self.data, self.metrics, self.reviews)))


class ChartPublicationTests(unittest.TestCase):
    def test_vendor_exemption_requires_exact_path_and_hash(self):
        raw = (ROOT/'vendor/echarts/echarts.min.js').read_bytes()
        record = b.read_json(ROOT/'vendor/echarts/VENDORED.json')
        self.assertEqual(record['sha256'], hashlib.sha256(raw).hexdigest())
        b.publication_guard(raw, b.ECHARTS_PATH)
        for path in ('assets/echarts.min.js', 'other/'+b.ECHARTS_PATH, b.ECHARTS_PATH+'.copy.js', 'data/charts.json'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                b.publication_guard(raw, path)
        for modified in (raw+b' ', b'"pricing"'):
            with self.assertRaisesRegex(ValueError, 'checksum'):
                b.publication_guard(modified, b.ECHARTS_PATH)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root/b.ECHARTS_PATH; path.parent.mkdir(parents=True); path.write_bytes(raw)
            b.guard_docs(root)
            path.write_bytes(raw+b' ')
            with self.assertRaises(ValueError): b.guard_docs(root)
            path.write_bytes(raw)
            (root/'unowned.js').write_bytes(raw)
            with self.assertRaises(ValueError): b.guard_docs(root)

    def test_no_remote_scripts_or_styles_and_no_other_chart_library(self):
        allowed = {'fonts.googleapis.com', 'fonts.gstatic.com'}
        class Parser(HTMLParser):
            def handle_starttag(parser, tag, attrs):
                a = dict(attrs)
                if tag == 'script' or (tag == 'link' and a.get('rel') == 'stylesheet'):
                    url = a.get('src', a.get('href', ''))
                    if urlsplit(url).netloc:
                        self.assertIn(urlsplit(url).hostname, allowed)
        for path in (ROOT/'docs').rglob('*'):
            if not path.is_file() or path.suffix not in ('.html', '.js', '.css', '.json'):
                continue
            text = path.read_text()
            self.assertNotIn('mer'+'maid', text.lower(), path.name)
            if path.suffix == '.html': Parser().feed(text)
            # Literal remote JS/CSS imports, script.src and link.href assignments.
            for url in re.findall(r'(?:https?:)?//[^\s\x22\x27<>`]+', text):
                if re.search(r'\.(?:js|css)(?:[?#]|$)', url):
                    self.assertIn(urlsplit(url).hostname, allowed, path.name)

    def test_generated_data_reconciles_with_publication(self):
        charts = b.read_json(ROOT/'docs/data/charts.json')
        boards = b.read_json(ROOT/'docs/data/leaderboard.json')
        self.assertEqual(charts['task_count'], 2294)
        self.assertEqual(charts['difficulty']['union']+charts['difficulty']['never'], 2294)
        for name, board in charts['leaderboards'].items():
            for r in board['rows']:
                c = boards[name][r['model']]
                self.assertAlmostEqual(r['score'], c['score']*100)
                self.assertEqual(r['interval'], [v*100 for v in c['wilson']])
        for r in charts['outcomes']['rows']:
            self.assertEqual(sum(r['counts'].values()), boards['Full'][r['model']]['total'])
            self.assertAlmostEqual(sum(r['percentages'].values()), 100)
        for model, c in boards['Full'].items():
            self.assertEqual(sum(r['resolved'] for r in charts['heatmap']['cells'] if r['model'] == model), c['resolved'])
        for p in charts['scatter']['points']:
            model = b.read_json(ROOT/f'docs/data/models/{b.slug(p["model"])}.json')
            self.assertEqual(p['steps'], model['distributions']['steps']['median'])
            self.assertEqual(p['samples'], model['distributions']['steps']['n'])

    def test_generated_headline_fallbacks_and_final_banner(self):
        text = (ROOT/'docs/index.html').read_text()
        self.assertEqual(text.replace('<span class="nowrap">SWE-bench</span>', 'SWE-bench').count(b.HEADLINE), 4)
        self.assertNotIn('Same tasks. Different models.', text)
        self.assertEqual(text.count('class="chart-canvas"'), 7)
        self.assertEqual(text.count('open class="chart-data"'), 10)
        self.assertEqual(text.count('Show the data as a table'), 9)
        self.assertIn('Charts need JavaScript.', text)
        charts = b.read_json(ROOT/'docs/data/charts.json')
        boards = b.read_json(ROOT/'docs/data/leaderboard.json')
        incomplete = any(not row['complete'] for board in boards.values() for row in board.values())
        self.assertEqual('Grading is still incomplete.' in text, incomplete)
        self.assertIn(f'We ran {charts["model_count"]} models', text)
        for file in ['echarts.min.js', 'LICENSE', 'NOTICE']:
            self.assertEqual((ROOT/'docs/assets/vendor/echarts'/file).read_bytes(), (ROOT/'vendor/echarts'/file).read_bytes())

    @unittest.skipUnless(shutil.which('node'), 'Node unavailable; skipping generated chart JS syntax and SVG runtime checks')
    def test_generated_javascript_syntax_and_offline_svg_runtime(self):
        result = subprocess.run(['node', '--check', str(ROOT/'docs/assets/charts.js')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(['node', str(ROOT/'tests/charts_runtime.cjs')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
