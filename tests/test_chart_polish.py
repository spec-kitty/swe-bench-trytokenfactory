"""Plain-language chart contracts and data-derived statistical summaries."""
import copy
import json
import re
import unittest
from pathlib import Path
from test_charts import b, fixture, ROOT


class ChartPolishTests(unittest.TestCase):
    def test_spearman_known_examples_ties_and_degenerate_inputs(self):
        self.assertAlmostEqual(b.spearman([1, 2, 3, 4, 5], [1, 3, 2, 5, 4]), .8)
        self.assertEqual(b.spearman([1, 2, 3], [3, 2, 1]), -1)
        self.assertEqual(b.spearman([1, 2, 3], [1, 2, 3]), 1)
        self.assertAlmostEqual(b.spearman([1, 1, 2], [1, 2, 3]), 3**.5/2)
        self.assertIsNone(b.spearman([], []))
        self.assertIsNone(b.spearman([1], [1]))
        self.assertIsNone(b.spearman([1, 1], [1, 2]))
        with self.assertRaises(ValueError): b.spearman([1], [])

    def test_scatter_headline_branches(self):
        for rho in (-1, -.3):
            self.assertEqual(b.scatter_headline(rho), 'More steps did not mean better scores')
        for rho in (1, .3):
            self.assertEqual(b.scatter_headline(rho), 'Models that took more steps scored higher')
        for rho in (None, -.29, 0, .29):
            self.assertEqual(b.scatter_headline(rho), 'There is no clear link between steps and score')

    def test_outcome_title_plural_and_zero_clauses(self):
        self.assertEqual(b.outcome_headline(1234, 20), '1,234 attempts ended with no patch, and 20 ran out of time')
        self.assertEqual(b.outcome_headline(1, 0), '1 attempt ended with no patch')
        self.assertEqual(b.outcome_headline(0, 1), '1 attempt ran out of time')
        self.assertEqual(b.outcome_headline(0, 0), 'How every attempt ended')

    def test_project_title_uses_median_task_count_and_editorial_description(self):
        cells = [dict(repo='psf/requests', score=score, total=50) for score in (10, 30, 90, 20)]
        descriptions = b.read_json(ROOT/'tools/projects.json')
        self.assertEqual(b.heatmap_headline(cells, descriptions),
                         'The hardest project was requests, a library for making web requests: the typical model solved 25.00% of its 50 tasks')
        self.assertEqual(b.heatmap_headline(cells, {}),
                         'The hardest project was requests: the typical model solved 25.00% of its 50 tasks')
        self.assertNotIn('a a ', b.heatmap_headline(cells, descriptions))
        cells[0]['score'] = None
        self.assertIn('30.00%', b.heatmap_headline(cells, descriptions))
        self.assertEqual(b.heatmap_headline([], descriptions), 'Repository scores await grading')

    def test_difficulty_copy_and_conditional_notes(self):
        data, metrics, reviews = fixture()
        charts = b.chart_data(data, metrics, reviews)
        self.assertEqual(charts['difficulty']['title'], 'All 2 models together solve 3 of the 6 tasks (50.0%)')
        self.assertIn('The remaining 3 tasks, 50.0% of the benchmark', charts['difficulty']['caption'])
        self.assertIn('best single model solves 2 tasks', charts['difficulty']['caption'])
        self.assertIn('Adding the other 1 brings in only 1 more', charts['difficulty']['caption'])
        for status in ('resolved', 'unresolved', 'ungraded'):
            d = copy.deepcopy(data)
            for m in d['models']:
                d['statuses'][m] = dict.fromkeys(d['tasks'], status)
                d['boards']['Full'][m] = b.count_statuses(d['statuses'][m].values())
            c = b.chart_data(d, metrics, reviews)
            self.assertIn('100.0%' if status == 'resolved' else '0.0%', c['difficulty']['title'])
            for key in ('difficulty', 'unique'):
                self.assertEqual('Pending or missing results' in c[key]['caption'], status == 'ungraded')
                self.assertNotRegex(c[key]['title']+' '+c[key]['caption'], r'(?i)histogram|distribution|exclusive|verdict')

    def test_real_family_note(self):
        from test_chart_palette import EXPECTED
        self.assertEqual(b.family_note(list(EXPECTED)),
                         'GLM Flash routes use lighter fills. Diagonal marks identify uncensored or abliterated variants.')
        self.assertEqual(b.family_note(['minimax-m3.1-flash']), '')
        self.assertNotIn('lighter', b.family_note(['glm-5.3-flashbang', 'glm-5.3']))
        self.assertIn('GLM Flash routes', b.family_note(['glm-5.3-flash', 'glm-5.3-uncensored-fp8']))

    def test_published_chart_copy_is_contextual(self):
        charts = b.read_json(ROOT/'docs/data/charts.json')
        texts = [b['title'] for b in charts['leaderboards'].values()]
        for name in ['outcomes', 'difficulty', 'unique', 'heatmap', 'scatter']:
            texts += [charts[name]['title'], charts[name]['caption']]
        texts.append(charts['scatter']['evidence'])
        for text in texts:
            clean = text.replace('Pending verdicts may still change these counts.', '').replace('Some verdicts are still missing and are left out.', '')
            self.assertNotRegex(clean, r'\b(adjudicated|exclusive|verdicts)\b')
            if re.search(r'\d(?:\.\d+)?%', text):
                self.assertRegex(text, r'(?:of (?:the |its )?[\d,]+ .*tasks|of those tasks|% of the benchmark)')
        # Official comparison copy uses the requested range/middle-value
        # sentence; its subset is named in the heading and denominator on axis.
        for name, board in charts['official']['subsets'].items():
            for summary in board['summaries'].values():
                self.assertIn('full test set' if name == 'Full' else name, summary['title'])
                self.assertIn('Each grey dot is one entry on the public SWE-bench leaderboard.', summary['caption'])
                self.assertNotRegex(summary['caption'], r'\b(adjudicated|exclusive|verdicts)\b')
        page = (ROOT/'docs/index.html').read_text()
        self.assertIn('Each dot is one model. Further left', page)
        self.assertIn('A step is one round trip:', page)
        self.assertIn('Steps are the number of model calls in an attempt; the median is taken over all', page)
        self.assertIn('How we count timeouts', page)
        self.assertIn('What the '+str(len(charts['heatmap']['projects']))+' projects are', page)
        self.assertIn('confidence interval (Wilson): a range describing uncertainty', page)
        self.assertIn('The project’s own tests pass after the model’s patch.', page)

    def test_evidence_is_derived_and_outlier_requires_majority_empty(self):
        data, metrics, reviews = fixture()
        for i, m in enumerate(data['models']):
            for row in metrics[m].values(): row['usage']['steps'] = 10+i*10
        charts = b.chart_data(data, metrics, reviews)
        self.assertEqual(charts['scatter']['rho'], -1)
        self.assertIn('10 and 20 steps per attempt', charts['scatter']['evidence'])
        self.assertNotIn('most of its attempts', charts['scatter']['evidence'])
