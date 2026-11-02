"""Research copy, computed facts, archive coverage and executable examples."""
import contextlib
import copy
import csv
import gzip
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import build_site as b
import check_links
from test_charts import fixture

SOURCES = {
    'SWE-bench leaderboard': 'https://github.com/SWE-bench/experiments',
    'Terminal-Bench 2.1': 'https://github.com/harbor-framework/terminal-bench-2-1',
    'Epoch AI Benchmarking Hub': 'https://epoch.ai/blog/benchmarking-hub-update',
    'Nebius SWE-rebench': 'https://huggingface.co/datasets/nebius/SWE-agent-trajectories',
}


class ResearchParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.attrs = []
        self.codes = {}
        self.pre = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.attrs.append((tag, attrs))
        if tag == 'pre':
            self.pre = attrs.get('id')
            self.codes[self.pre] = ''

    def handle_endtag(self, tag):
        if tag == 'pre':
            self.pre = None

    def handle_data(self, text):
        if self.pre:
            self.codes[self.pre] += text


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.data, self.metrics, self.reviews = fixture()
        self.site = b.Site(ROOT, self.root/'docs', self.data, '2026-11-01', 'commit', 1)
        self.inventory = dict(available=0, expected=12, files=0, bytes=0,
                              compressed_bytes=0, indexed=0, trajectories=0, messages=0)

    def render(self):
        b.build_research(self.site, self.inventory)
        return (self.site.out/'research.html').read_text()

    def test_counts_share_difficulty_and_change_with_data(self):
        for statuses in (self.data['statuses'], {'alpha': dict.fromkeys(self.data['tasks'], 'resolved'),
                                               'beta': dict.fromkeys(self.data['tasks'], 'resolved')}):
            self.data['statuses'] = statuses
            self.data['boards']['Full'] = {m: b.count_statuses(s.values()) for m, s in statuses.items()}
            page = self.render()
            facts = b.read_json(self.site.out/'data/research.json')
            charts = b.chart_data(self.data, self.metrics, self.reviews)
            self.assertEqual((facts['none'], facts['every'], facts['exactly_one']),
                             (charts['difficulty']['never'], charts['difficulty']['every'],
                              sum(r['tasks'] for r in charts['unique']['rows'])))
            self.assertIn('All 2 models attempted the same 6 tasks', page)
            self.assertIn('One file per attempt, 12 attempts in all', page)
            for key, label in [('none', 'no model'), ('every', 'every model')]:
                self.assertIn(f'Tasks {label} resolved: <strong>{facts[key]}</strong>', page)

    def test_pending_grades_and_unpacked_archive_are_explicit(self):
        self.data['statuses']['alpha']['t0'] = 'ungraded'
        self.data['boards']['Full']['alpha'] = b.count_statuses(self.data['statuses']['alpha'].values())
        page = self.render()
        self.assertIn('Provisional paired counts: 11 / 12', page)
        self.assertIn('Archive coverage: 0 / 12', page)
        self.assertIn('archive is not packaged yet', page)
        self.assertIn('not necessarily a failure', page)

    def test_primary_source_rows_and_external_link_allowlist(self):
        page = self.render()
        self.assertEqual(page.count('<th scope="row">'), len(SOURCES))
        parsed = ResearchParser(); parsed.feed(page)
        links = [a for tag, a in parsed.attrs if tag == 'a']
        for name, url in SOURCES.items():
            self.assertIn(f'<th scope="row">{name}</th>', page)
            matches = [a for a in links if a.get('href') == url]
            self.assertEqual(len(matches), 1)
            self.assertEqual((matches[0]['rel'], matches[0]['target']), ('noopener', '_blank'))
        allowed = set(SOURCES.values()) | {p['url'] for p in self.site.partners}
        for _, attrs in parsed.attrs:
            for key in ('href', 'src'):
                url = attrs.get(key, '')
                if urlsplit(url).netloc:
                    self.assertTrue(url in allowed or urlsplit(url).hostname in
                                    {'fonts.googleapis.com', 'fonts.gstatic.com'}, url)
        self.assertIn('1 November 2026', page)
        self.assertIn('we did not survey exhaustively', page)
        self.assertNotIn('85%', page)

    def test_guards_and_brand_shell(self):
        page = self.render()
        b.safe_bytes(page.encode())
        b.publication_guard(page)
        b.guard_docs(self.site.out)
        self.assertIn('class="partner-strip"', page)
        self.assertIn('class="partner-footer"', page)
        self.assertIn('aria-current="page">For researchers</a>', page)
        self.assertNotIn('echarts.min.js', page)

    def test_citation_config_and_optional_licence(self):
        config = b.read_json(ROOT/'tools/partners.json')
        self.assertIn(config['repository_url'], self.render())
        copyright_line = next(line for line in (ROOT/'LICENSE').read_text().splitlines() if line.startswith('Copyright (c) '))
        self.assertIn('Licence: MIT, '+copyright_line, self.render())
        local = self.root/'tools/site_assets'; local.mkdir(parents=True)
        (local/'research.html').write_bytes((ROOT/'tools/site_assets/research.html').read_bytes())
        config['repository_url'] = 'https://example.org/changed-repository'
        (self.root/'tools/partners.json').write_text(json.dumps(config))
        with patch.object(b, 'ROOT', self.root):
            page = self.render()
        self.assertNotIn('Licence:', page)
        self.assertIn(config['repository_url'], page)

    def test_inventory_uses_only_published_attempt_indexes(self):
        path = self.root/self.site.evidence_path('alpha', 't0')
        path.parent.mkdir(parents=True)
        path.write_bytes(b'abc')
        index = self.root/'evidence/models/alpha/results.json'
        index.write_text(json.dumps({'t0': {'messages': 7}, 't1': {'messages': 999}}))
        (path.parent/'.pack-staging').write_bytes(b'staging')
        with patch.object(b, 'ROOT', self.root):
            inventory = b.evidence_inventory(self.site)
        self.assertEqual((inventory['available'], inventory['files'], inventory['compressed_bytes']), (1, 2, 3))
        self.assertEqual((inventory['indexed'], inventory['trajectories'], inventory['messages']), (1, 1, 7))
        self.inventory = inventory
        page = self.render()
        self.assertIn('archive is incomplete', page)
        self.assertIn('trajectories, 1; trajectory messages, 7', page)

    def test_attempt_example_alphabetical_and_split_trajectory(self):
        self.data['models'].reverse()
        examples = b.research_examples(self.site)
        self.assertEqual(examples['first'], ('alpha', 't0'))
        parsed = ResearchParser(); parsed.feed(self.render())
        self.assertEqual(parsed.codes['read-attempt'], examples['attempt'])
        path = self.root/self.site.evidence_path(*examples['first'])
        path.parent.mkdir(parents=True)
        payload = dict(status='resolved', result={'exit_status': 'Submitted'},
                       prediction={'model_patch': 'diff example\n+fixed'}, trajectory={'messages': [{}, {}]})
        for split in (False, True):
            current = copy.deepcopy(payload)
            if split:
                trajectory = path.with_name('t0.trajectory.json.gz')
                raw = gzip.compress(json.dumps(current['trajectory']).encode(), mtime=0)
                trajectory.write_bytes(raw)
                current['trajectory'] = {'file': trajectory.relative_to(self.root/'evidence').as_posix(),
                                         'sha256': hashlib.sha256(raw).hexdigest()}
            path.write_bytes(gzip.compress(json.dumps(current).encode(), mtime=0))
            with contextlib.chdir(self.root), contextlib.redirect_stdout(io.StringIO()) as out:
                exec(parsed.codes['read-attempt'], {})
            self.assertIn('Messages: 2', out.getvalue())
            self.assertIn('Status: resolved', out.getvalue())
            self.assertIn('+fixed', out.getvalue())
        trajectory.write_bytes(b'changed')
        with contextlib.chdir(self.root), contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'checksum'):
            exec(examples['attempt'], {})

    def test_inventory_does_not_count_files_arriving_after_listing(self):
        original = self.site.evidence_path
        def arriving(model, instance):
            relative = original(model, instance)
            path = self.root/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'new bundle')
            return relative
        with patch.object(b, 'ROOT', self.root), patch.object(self.site, 'evidence_path', side_effect=arriving):
            inventory = b.evidence_inventory(self.site)
        self.assertEqual((inventory['available'], inventory['files'], inventory['bytes']), (0, 0, 0))

    def test_matrix_example_executes_and_rejects_partial_or_pending(self):
        parsed = ResearchParser(); parsed.feed(self.render())
        code = parsed.codes['solved-matrix']
        for model, statuses in self.data['statuses'].items():
            path = self.root/'evidence/models'/model/'results.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({i: {'status': s} for i, s in statuses.items()}))
        csv_path = self.root/'docs/data/results.csv'
        csv_path.write_text('instance_id\n'+'\n'.join(self.data['tasks'])+'\n')
        def run():
            with contextlib.chdir(self.root), contextlib.redirect_stdout(io.StringIO()) as out:
                exec(code, {})
            return out.getvalue()
        self.assertEqual(run(), 'alpha 2\nbeta 1\n')
        index = self.root/'evidence/models/beta/results.json'
        rows = b.read_json(index); rows['t0']['status'] = 'ungraded'
        index.write_text(json.dumps(rows))
        with self.assertRaisesRegex(ValueError, 'Provisional grades'): run()
        del rows['t0']; index.write_text(json.dumps(rows))
        with self.assertRaisesRegex(ValueError, 'Incomplete pack'): run()
        index.unlink()
        with self.assertRaisesRegex(ValueError, 'Incomplete pack'): run()

    def test_no_resolved_attempt_does_not_invent_example(self):
        for statuses in self.data['statuses'].values():
            statuses.update(dict.fromkeys(statuses, 'unresolved'))
        self.assertIsNone(b.research_examples(self.site)['first'])
        self.assertIn('No resolved attempt is recorded yet', self.render())


class BuiltResearchTests(unittest.TestCase):
    def test_built_page_nav_links_and_numbers_match_real_report(self):
        docs = ROOT/'docs'
        self.assertTrue((docs/'research.html').is_file())
        self.assertIn('research.html', b.read_json(docs/'data/site-files.json'))
        for path in docs.rglob('*.html'):
            page = path.read_text()
            nav = re.search(r'<nav aria-label="Main">(.*?)</nav>', page).group(1)
            self.assertRegex(nav, r'Evidence</a><a href="(?:\.\./|/swe-bench-trytokenfactory/|/)?research.html"(?: aria-current="page")?>For researchers</a>')
        source = ROOT.parent/'artifacts/report/instances.csv'
        # Published clones can validate the exported matrix without the private
        # collection. In this workspace also compare directly to its source.
        with (source if source.is_file() else docs/'data/results.csv').open() as stream:
            rows = list(csv.DictReader(stream))
        models = {r['model'] for r in rows}
        tasks = {r['instance_id'] for r in rows}
        solved = {i: set() for i in tasks}
        for row in rows:
            if row['status'] == 'resolved': solved[row['instance_id']].add(row['model'])
        facts = b.read_json(docs/'data/research.json')
        self.assertEqual((facts['models'], facts['tasks'], facts['attempts']), (len(models), len(tasks), len(rows)))
        for key, n in [('none', 0), ('every', len(models)), ('exactly_one', 1)]:
            self.assertEqual(facts[key], sum(len(s) == n for s in solved.values()))
        self.assertEqual(tuple(facts['example']), min((r['model'], r['instance_id']) for r in rows if r['status'] == 'resolved'))
        self.assertEqual(check_links.check(docs, publish='rel="canonical"' in (docs/'index.html').read_text())[0], [])
        b.guard_docs(docs)

    def test_front_card_and_context_links(self):
        page = (ROOT/'docs/index.html').read_text()
        self.assertLess(page.index('id="card-scatter"'), page.index('Open evidence for research'))
        self.assertLess(page.index('Open evidence for research'), page.index('Leaderboard data'))
        self.assertIn('href="research.html"', page.split('<h2 class="sk-card-title">Thanks</h2>')[1])
        for name in ('evidence.html', 'about.html'):
            main = (ROOT/'docs'/name).read_text().split('<main id="main">')[1].split('</main>')[0]
            self.assertIn('href="research.html"', main)


if __name__ == '__main__':
    unittest.main()
