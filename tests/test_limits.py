import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import build_site as b
from test_charts import fixture


class LimitTests(unittest.TestCase):
    def test_definition_and_denominator(self):
        records = {
            'a': dict(grade_reason='empty_patch', exit_status='ContextBudgetExceeded'),
            'b': dict(grade_reason='empty_patch', exit_status='TimeExceeded'),
            'c': dict(grade_reason='empty_patch', exit_status='OuterProcessTimeout'),
            'd': dict(grade_reason='empty_patch', exit_status='Submitted'),
            'e': dict(grade_reason=None, exit_status='ContextBudgetExceeded'),
        }
        row = b.limit_counts(records, 'abcdef')
        self.assertEqual((row['count'], row['context_cap'], row['time_limit']), (3, 1, 2))
        self.assertEqual(row['share'], .5)
        self.assertTrue(row['provisional'])
        self.assertEqual(b.limit_counts(records, 'de')['count'], 0)
        self.assertIsNone(b.limit_counts(records, [])['share'])

    def test_threshold_exactly_and_on_both_sides(self):
        records = {i: dict(grade_reason='empty_patch', exit_status='TimeExceeded') for i in range(21)}
        for count, expected in [(19, False), (20, True), (21, True)]:
            row = b.limit_counts({i: records[i] for i in range(count)}, range(100))
            self.assertEqual(row['limit_constrained'], expected)
            self.assertEqual('limit-constrained' in b.limit_text(row), expected)

    def test_subsets_and_chart_contract(self):
        data, metrics, reviews = fixture()
        metrics['alpha']['t0'].update(grade_reason='empty_patch', exit_status='TimeExceeded')
        limits = b.limits_data(data, metrics)
        self.assertEqual(limits['subsets']['Full']['alpha']['share'], 1/6)
        self.assertEqual(limits['subsets']['Verified']['alpha']['share'], 1)
        charts = b.chart_data(data, metrics, reviews)
        for name, board in charts['leaderboards'].items():
            for row in board['rows']:
                self.assertEqual(row['limits'], limits['subsets'][name][row['model']])
        self.assertIn('inside our limits', charts['leaderboards']['Full']['title'])
        data['boards']['Verified']['alpha']['complete'] = False
        self.assertTrue(b.limits_data(data, metrics)['subsets']['Verified']['alpha']['provisional'])
        self.assertEqual(b.limits_data(data, metrics)['subsets']['Verified']['alpha']['count'], 1)

    def test_real_export_matches_all_packed_attempts(self):
        export = json.loads((ROOT/'docs/data/limits.json').read_text())
        for model, expected in export['subsets']['Full'].items():
            path = ROOT/'docs/data/models'/f'{b.slug(model)}.json'
            data = json.loads(path.read_text())
            # Site model exports are collected from raw active attempts, not samples.
            records = data['attempts']
            actual = b.limit_counts(records, records)
            self.assertEqual(actual, expected)
            packed = json.loads((ROOT/'evidence/models'/model/'results.json').read_text())
            for subset in ('Full', 'Verified', 'Lite'):
                ids = set(packed) if subset == 'Full' else {json.loads(line)['instance_id'] for line in
                    (ROOT.parent/f'artifacts/datasets/SWE-bench_{subset}.jsonl').read_text().splitlines()}
                self.assertEqual(b.limit_counts(packed, ids), export['subsets'][subset][model])
        page = (ROOT/'docs/methodology.html').read_text()
        self.assertIn('id="limits-effects"', page)
        self.assertIn('rerun has not happened', page)
        self.assertIn('gateway team', page)
        self.assertIn('Cut off by limits', (ROOT/'docs/index.html').read_text())
