"""Offline official snapshot contract, sanitization and comparison statistics."""
import copy
import hashlib
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import build_site as b


class OfficialContextTests(unittest.TestCase):
    def setUp(self):
        self.entries = [dict(folder=f'e{i}', name=f'Entry {i}', agent='mini-SWE-agent' if i & 1 else 'Other',
                             agent_org=None, model_display=f'model-{i}', model_org=None, os_model=bool(i & 2),
                             resolved=i*10, date='2026-01-01', tags=['System: Attempts - 1' if i & 4 else 'System: Attempts - 2+'],
                             cost=999, instance_cost=999, instance_calls=999, logo='https://example.org/logo',
                             logs='https://example.org/private', os_system=True) for i in range(8)]
        self.snapshot = {'leaderboards': [dict(name=n, results=copy.deepcopy(self.entries)) for n in ['Verified', 'Test', 'Lite']]}
        self.comparison = dict(retrieved_at='2026-10-29T01:02:03Z', commit='193160a'+'a'*33, sha256='83cd949a'+'b'*56)
        self.boards = {n: dict(rows=[dict(model='ours', score=20, total=100), dict(model='ours2', score=50, total=100)], provisional=False)
                       for n in ['Full', 'Verified', 'Lite']}

    def build(self):
        return b.official_context(self.snapshot, self.comparison, self.boards, ['ours', 'ours2'])

    def test_whitelist_flags_and_deterministic_jitter(self):
        result = self.build()
        fields = set(b.OFFICIAL_FIELDS) | {'id', 'attempts', 'mini'}
        for board in result['subsets'].values():
            for r in board['entries']:
                self.assertEqual(set(r), fields)
                i = int(r['id'][1:])
                self.assertIs(r['mini'], bool(i & 1))
                self.assertIs(r['os_model'], bool(i & 2))
                self.assertGreaterEqual(board['jitter'][r['id']], -.12)
                self.assertLessEqual(board['jitter'][r['id']], .12)
        expected = (int(hashlib.sha256(b'e3').hexdigest()[:8], 16)/0xffffffff-.5)*.24
        self.assertEqual(b.official_jitter('e3'), expected)
        self.assertNotEqual(b.official_jitter('e3'), b.official_jitter('e4'))
        for board in self.snapshot['leaderboards']: board['results'].reverse()
        self.assertEqual(b.json_text(self.build()), b.json_text(result))

    def test_attempts_parsing(self):
        for value, expected in [('1', '1'), ('2+', '2+'), ('2', '2+'), ('10', '2+'), ('unknown', 'unknown'),
                                ('0', 'unknown'), ('1+', 'unknown'), ('1 extra', 'unknown')]:
            self.assertEqual(b.official_attempts(['Model: x', 'System: Attempts - '+value]), expected)
        self.assertEqual(b.official_attempts([]), 'unknown')
        self.assertEqual(b.official_attempts(['System: Attempts - 1', 'System: Attempts - 2+']), 'unknown')
        self.assertEqual(b.official_attempts(['System: Attempts - 1']*2), '1')

    def test_filters_and_combine_all_eight_states(self):
        board = self.build()['subsets']['Full']
        for mask in range(8):
            expected = [r for i, r in enumerate(board['entries']) if i & mask == mask]
            self.assertEqual(b.official_filter(board['entries'], mask), expected)
            s = board['summaries'][str(mask)]
            self.assertEqual(s['count'], len(expected))
            scores = [r['resolved'] for r in expected]
            self.assertEqual(s['above'], sum(v > 50 for v in scores))
            self.assertEqual(s['below'], sum(v < 20 for v in scores))
        self.assertEqual(board['summaries']['0']['median'], 35)
        self.assertEqual(board['summaries']['0']['above'], 2)  # Ties excluded.
        self.assertEqual(board['summaries']['0']['below'], 2)

    def test_empty_filter_and_ungraded_provisional(self):
        for board in self.snapshot['leaderboards']: board['results'] = []
        self.boards['Full']['provisional'] = True
        self.boards['Full']['rows'][0]['score'] = None
        self.boards['Full']['rows'][1]['score'] = None
        s = self.build()['subsets']['Full']['summaries']['0']
        self.assertIsNone(s['median']); self.assertIsNone(s['above']); self.assertIsNone(s['below'])
        self.assertTrue(s['title'].startswith('Provisional:'))
        self.assertIn('our 2 models', s['title'])
        self.assertIn('await grading', s['caption'])
        self.assertIn('no official entries', s['caption'])

    def test_plain_copy_uses_filtered_counts_ranges_and_median(self):
        context = self.build()
        for name, board in context['subsets'].items():
            for mask in range(8):
                s = board['summaries'][str(mask)]
                rows = b.official_filter(board['entries'], mask)
                subset = 'the full test set' if name == 'Full' else f'SWE-bench {name} (100 tasks)'
                self.assertEqual(s['title'], f'Where our 2 models land among the {len(rows)} official entries for {subset}')
                self.assertIn('Our scores run from 20.0% to 50.0%', s['caption'])
                self.assertIn(f'the official entries run from {min(r["resolved"] for r in rows):.1f}% '
                              f'to {max(r["resolved"] for r in rows):.1f}%', s['caption'])
                self.assertIn(f'with a middle value of {s["median"]:.1f}%', s['caption'])
                self.assertEqual('mini-SWE-agent' in s['filter_help'], bool(mask & 1))
                self.assertEqual('an open-weight model' in s['filter_help'], bool(mask & 2))
                self.assertEqual('a single attempt' in s['filter_help'], bool(mask & 4))
        self.assertEqual(context['subsets']['Full']['summaries']['7']['filter_help'],
                         'Showing the 1 entry that used mini-SWE-agent with an open-weight model and a single attempt.')

    def test_even_and_tied_medians_do_not_claim_half_are_strictly_above(self):
        for board in self.snapshot['leaderboards']:
            for row in board['results']: row['resolved'] = 42
        summary = self.build()['subsets']['Verified']['summaries']['0']
        self.assertEqual(summary['median'], 42)
        self.assertIn('middle value of 42.0%', summary['caption'])
        self.assertNotIn('Half', summary['caption'])

    def test_exact_names_case_insensitive_no_alias_or_substring(self):
        self.snapshot['leaderboards'][0]['results'][0]['model_display'] = 'OURS'
        self.snapshot['leaderboards'][1]['results'][0]['tags'].append('Model: OuRs2')
        self.snapshot['leaderboards'][2]['results'][0]['model_display'] = 'ours-base'
        result = self.build()
        self.assertEqual(result['exact_matches'], [dict(model='ours', subset='Verified', id='e0'),
                                                  dict(model='ours2', subset='Test', id='e0')])
        self.assertIn('Exact model-name matches', result['snapshot'])
        self.assertNotIn('No official entry', result['snapshot'])
        self.assertIn('ours, ours2', result['snapshot'])

    def test_guard_rejection_identifies_entry_does_not_drop_it(self):
        self.snapshot['leaderboards'][0]['results'][2]['name'] = 'Low cost agent'
        with self.assertRaisesRegex(ValueError, 'Verified/e2'):
            self.build()
        self.snapshot['leaderboards'][0]['results'][2]['name'] = 'Bearer'+' secret'
        with self.assertRaises(ValueError) as error:
            self.build()
        self.assertNotIn('secret', str(error.exception))
        self.assertIn('entry sha256', str(error.exception))

    def test_html_escapes_and_fallback_tables_are_open(self):
        self.snapshot['leaderboards'][0]['results'][0]['name'] = '<script>alert(1)</script>'
        page = b.official_section(self.build())
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertIn('details open', page)
        self.assertEqual(page.count('<table>'), len(self.boards))
        self.assertEqual(page.count('<tfoot>'), len(self.boards))
        self.assertIn(b.OFFICIAL_CAUTION, page)


class PublishedOfficialTests(unittest.TestCase):
    def setUp(self):
        self.charts = b.read_json(ROOT/'docs/data/charts.json')
        self.context = self.charts['official']

    def test_real_counts_scores_and_snapshot(self):
        self.assertEqual({n: len(b['entries']) for n, b in self.context['subsets'].items()},
                         {'Full': 24, 'Verified': 180, 'Lite': 84})
        self.assertEqual(self.context['exact_matches'], [])
        comparison = b.read_json(ROOT/'docs/data/official-comparison.json')
        for value in [comparison['retrieved_at'][:10], comparison['commit'][:7], comparison['sha256'][:8]]:
            self.assertIn(value, self.context['snapshot'])
        for name, board in self.context['subsets'].items():
            ours = [r['score'] for r in self.charts['leaderboards'][name]['rows'] if r['score'] is not None]
            for mask in range(8):
                rows = b.official_filter(board['entries'], mask)
                s = board['summaries'][str(mask)]
                self.assertEqual(s['count'], len(rows))
                self.assertEqual(s['above'], sum(r['resolved'] > max(ours) for r in rows))
                self.assertEqual(s['below'], sum(r['resolved'] < min(ours) for r in rows))
                self.assertTrue(all(r['resolved'] <= board['axis_max'] for r in rows))

    def test_forbidden_keys_in_charts_and_all_generated_json(self):
        def inspect(value, pattern):
            if isinstance(value, dict):
                for key, child in value.items():
                    self.assertIsNone(pattern.search(key), key)
                    inspect(child, pattern)
            elif isinstance(value, list):
                for child in value: inspect(child, pattern)
        inspect(self.charts, re.compile(r'cost|price|log|traj|s3|logo', re.I))
        for path in (ROOT/'docs').rglob('*.json'):
            inspect(b.read_json(path), re.compile(r'cost|price', re.I))
        for board in self.context['subsets'].values():
            for row in board['entries']:
                self.assertEqual(set(row), set(b.OFFICIAL_FIELDS) | {'id', 'attempts', 'mini'})

    def test_placement_caution_and_guards(self):
        page = (ROOT/'docs/index.html').read_text()
        start = page.index('<section class="sk-card chart-card" id="card-official">')
        end = page.index('<section><h2>Official leaderboard</h2>')
        section = page[start:end]
        self.assertTrue(section.endswith('</section>'))
        self.assertEqual(section.count(b.OFFICIAL_CAUTION), 1)
        self.assertLess(section.index(b.OFFICIAL_CAUTION), section.index('<details'))
        self.assertIn('Show the official entries as a table', section)
        b.guard_docs(ROOT/'docs')


if __name__ == '__main__':
    unittest.main()
