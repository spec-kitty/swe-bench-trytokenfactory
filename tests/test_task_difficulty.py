"""Task difficulty, examples and single-resolver counts share report semantics."""
import csv
import json
import re
from html import unescape
import unittest
from collections import Counter
from urllib.parse import parse_qs, urlsplit

from test_charts import b, ROOT, fixture


class DifficultyTests(unittest.TestCase):
    def test_greedy_hand_example_and_score_ties(self):
        sets = dict(a={1, 2, 3, 4}, b={1, 2, 3}, c={4, 5}, d={5, 6}, e={6})
        orders = b.accumulation_orders(sets, list(sets))
        self.assertEqual([r['model'] for r in orders['score']], [None, 'a', 'b', 'c', 'd', 'e'])
        self.assertEqual([r['new'] for r in orders['score']], [0, 4, 0, 1, 1, 0])
        self.assertEqual([r['model'] for r in orders['greedy']], [None, 'a', 'd', 'b', 'c', 'e'])
        self.assertEqual([r['solved'] for r in orders['greedy']], [0, 4, 6, 6, 6, 6])
        # Equal new-task counts choose the higher overall score, even if input order differs.
        self.assertEqual(b.accumulation_orders(dict(reversed(list(sets.items()))), list(sets)), orders)

    def test_changed_model_count_zero_and_full_union(self):
        data, _, _ = fixture()
        for count in (1, 2):
            models = data['models'][:count]
            for status in ('unresolved', 'resolved'):
                data['statuses'] = {m: dict.fromkeys(data['tasks'], status) for m in models}
                h, unique = b.difficulty_data(data, models, False)
                expected = len(data['tasks']) if status == 'resolved' else 0
                self.assertEqual(h['union'], expected)
                self.assertEqual(h['never'], len(data['tasks'])-expected)
                self.assertEqual(len(h['examples']), 1)
                self.assertIn(f'All {count} models', h['title'])
                self.assertEqual(len(unique['rows']), count)
                for rows in h['orders'].values():
                    self.assertEqual(rows[0]['solved'], 0)
                    self.assertEqual(rows[-1]['solved'], expected)
                    self.assertEqual(len(rows), count+1)

    def test_literal_first_line_and_selected_example_whitelist(self):
        self.assertEqual(b.issue_first_line('  <issue & title>  \nprivate later text'), '<issue & title>')
        self.assertEqual(b.issue_first_line('x'*200+'\nother'), 'x'*110)
        self.assertEqual(b.issue_first_line(''), '')
        data, _, _ = fixture()
        data['task_titles'] = {i: '<issue & title>' for i in data['tasks']}
        difficulty, _ = b.difficulty_data(data, data['models'], False)
        example = difficulty['examples'][0]
        self.assertEqual(example['instance_id'], 't2')
        self.assertEqual(example['quote'], '<issue & title>')
        self.assertEqual(set(example), {'label', 'instance_id', 'repo', 'quote', 'href'})
        self.assertEqual(parse_qs(urlsplit(example['href']).query), {'task': ['t2']})
        for marker in b.FORBIDDEN:
            data['task_titles']['t2'] = marker.decode()+'redacted'
            with self.assertRaises(ValueError): b.difficulty_data(data, data['models'], False)

    def test_research_and_explorer_agree_with_real_groups_and_examples(self):
        charts = b.read_json(ROOT/'docs/data/charts.json')
        facts = b.read_json(ROOT/'docs/data/research.json')
        difficulty, unique = charts['difficulty'], charts['unique']
        with (b.DEFAULT_SOURCE/'artifacts/report/instances.csv').open() as f:
            results = list(csv.DictReader(f))
        resolvers = {r['instance_id']: [] for r in results}
        for row in results:
            if row['status'] == 'resolved': resolvers[row['instance_id']].append(row['model'])
        exact = Counter(len(ms) for ms in resolvers.values())
        self.assertEqual((facts['none'], facts['every'], facts['exactly_one']),
                         (difficulty['never'], difficulty['every'], sum(r['tasks'] for r in unique['rows'])))
        solved_sets = {m: {i for i, ms in resolvers.items() if m in ms} for m in charts['model_order']}
        union = set().union(*solved_sets.values())
        self.assertEqual(len(union), 1586)  # Snapshot sanity check, independently recomputed above.
        self.assertEqual(difficulty['union'], len(union))
        for name, rows in difficulty['orders'].items():
            seen, remaining = set(), list(charts['model_order'])
            self.assertEqual(rows[0], dict(model=None, models=0, new=0, solved=0))
            for index, row in enumerate(rows[1:], 1):
                expected = (max(remaining, key=lambda m: (len(solved_sets[m]-seen), -charts['model_order'].index(m)))
                            if name == 'greedy' else remaining[0])
                self.assertEqual(row['model'], expected)
                self.assertEqual(row['new'], len(solved_sets[expected]-seen))
                seen |= solved_sets[expected]
                self.assertEqual(row['solved'], len(seen))
                self.assertEqual(row['models'], index)
                remaining.remove(expected)
            self.assertEqual(rows[-1]['solved'], len(resolvers)-exact[0])
            self.assertEqual([r['solved'] for r in rows], sorted(r['solved'] for r in rows))
        singles = Counter(ms[0] for ms in resolvers.values() if len(ms) == 1)
        self.assertEqual([r['model'] for r in unique['rows']], charts['model_order'])
        for row in unique['rows']: self.assertEqual(row['tasks'], singles[row['model']])
        explorer = b.read_json(ROOT/'docs/data/instances.json')
        for row in explorer['rows']:
            self.assertEqual(sum(explorer['statuses'][s] == 'resolved' for s in row[2]), len(resolvers[row[0]]))
        selected = {e['instance_id']: e for e in difficulty['examples']}
        for line in (b.DEFAULT_SOURCE/'artifacts/datasets/agent-input.jsonl').read_text().splitlines():
            item = json.loads(line)
            if item['instance_id'] in selected:
                example = selected[item['instance_id']]
                self.assertEqual(example['repo'], item['repo'])
                self.assertEqual(example['quote'], b.issue_first_line(item['problem_statement']))
                self.assertLessEqual(len(example['quote']), 110)
        self.assertEqual([e['instance_id'] for e in difficulty['examples']],
                         [min(i for i, ms in resolvers.items() if len(ms) == n) for n in (0, charts['model_count'])])

    def test_published_copy_tables_focus_and_runtime_tokens(self):
        charts = b.read_json(ROOT/'docs/data/charts.json')
        for key in ('difficulty', 'unique'):
            for field in ('title', 'caption'):
                self.assertNotRegex(charts[key][field], r'(?i)histogram|distribution|exclusive|verdict')
        h = charts['difficulty']
        self.assertEqual(h['title'], f'All {charts["model_count"]} models together solve {b.number(h["union"])} of the {b.number(charts["task_count"])} tasks ({100*h["union"]/charts["task_count"]:.1f}%)')
        self.assertIn(f'Adding the other {charts["model_count"]-1} brings in only {b.number(h["union"]-h["best"])} more.', h['caption'])
        self.assertIn(f'one of the {charts["model_count"]} models', charts['unique']['caption'])
        page = (ROOT/'docs/index.html').read_text()
        self.assertNotRegex(page.lower(), r'\b(histogram|distribution|exclusive|verdict)\b')
        self.assertIn('id="chart-accumulation"', page)
        self.assertNotIn('difficulty-bar', page)
        self.assertIn('id="chart-unique"', page)
        self.assertIn('Tasks solved by just one model</caption>', page)
        self.assertIn(b.attempt_basis(charts['model_count'], charts['task_count']), page)
        for key in h['orders']:
            self.assertIn(f'aria-controls="accumulation-panel-{key}"', page)
            self.assertIn(f'id="accumulation-panel-{key}"', page)
        for example in h['examples']:
            self.assertIn(f'<blockquote>{b.E(example["quote"])}</blockquote>', page)
        css = (ROOT/'tools/site_assets/site.css').read_text().split('/* Cumulative solves')[1]
        self.assertNotRegex(css, r'#[0-9a-fA-F]{3,8}\b|--spec\b')
        self.assertIn('overflow-x:auto', css)
        self.assertIn('@media(max-width:600px)', css)

    def test_vocabulary_all_pages_and_shared_glossary(self):
        charts = b.read_json(ROOT/'docs/data/charts.json')
        count = b.number(charts['attempts'])
        for path in (ROOT/'docs').rglob('*.html'):
            text = unescape(re.sub('<[^>]+>', ' ', path.read_text()))
            self.assertNotRegex(text.lower(), r'attempts used|tasks graded|graded tasks', path.name)
            for match in re.finditer(re.escape(count), text):
                nearby = text[max(0, match.start()-100):match.end()+100].lower()
                self.assertTrue('attempts' in nearby or ' x ' in nearby, path.name)
        for page in ('index.html', 'methodology.html', 'research.html'):
            html = (ROOT/'docs'/page).read_text()
            self.assertEqual(html.count('Three words we use'), 1)
            self.assertIn(b.glossary(dict(models=charts['model_order'], tasks=range(charts['task_count']))), html)
            self.assertLess(html.index('Three words we use'), html.index('<h2', html.index('Three words we use')))
        page = (ROOT/'docs/index.html').read_text()
        self.assertIn('Attempts graded</p>', page)
        for footer in re.findall(r'<p class="chart-source"[^>]*>(.*?)</p>', page):
            self.assertNotRegex(footer, r'\.(?:csv|json)\b|Source:')

    def test_three_official_titles_and_caption_denominators(self):
        charts = b.read_json(ROOT/'docs/data/charts.json')
        for name, board in charts['official']['subsets'].items():
            ours = charts['leaderboards'][name]
            tasks = ours['rows'][0]['total']
            suffix = 'the full test set' if name == 'Full' else f'SWE-bench {name} ({b.number(tasks)} tasks)'
            for summary in board['summaries'].values():
                prefix = 'Provisional: ' if ours['provisional'] else ''
                self.assertEqual(summary['title'], prefix+f'Where our {len(ours["rows"])} models land among the {summary["count"]} official entries for {suffix}')
                self.assertIn(f'Scores show the share of {b.number(tasks)} tasks solved.', summary['caption'])


if __name__ == '__main__':
    unittest.main()
