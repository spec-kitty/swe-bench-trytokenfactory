import csv
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import build_site as b
import check_links


class StatisticsTests(unittest.TestCase):
    def test_wilson_known(self):
        low, high = b.wilson(50, 100)
        self.assertAlmostEqual(low, 0.40383153, places=7)
        self.assertAlmostEqual(high, 0.59616847, places=7)

    def test_wilson_endpoints_and_empty(self):
        self.assertIsNone(b.wilson(0, 0))
        self.assertAlmostEqual(b.wilson(0, 10)[0], 0)
        self.assertAlmostEqual(b.wilson(10, 10)[1], 1)
        self.assertAlmostEqual(b.wilson(0, 10)[1], 0.2775328, places=6)
        for values in [(1, 0), (-1, 5), (3, -2)]:
            with self.assertRaises(ValueError): b.wilson(*values)

    def test_mcnemar_known(self):
        self.assertEqual(b.mcnemar_exact(0, 0), 1)
        self.assertEqual(b.mcnemar_exact(4, 4), 1)
        self.assertEqual(b.mcnemar_exact(0, 5), 0.0625)
        self.assertAlmostEqual(b.mcnemar_exact(1, 9), 22/1024)
        self.assertEqual(b.mcnemar_exact(10, 21), b.mcnemar_exact(21, 10))

    def test_mcnemar_large_and_invalid(self):
        self.assertEqual(b.mcnemar_exact(1147, 1147), 1)
        self.assertGreater(b.mcnemar_exact(1000, 1100), 0)
        with self.assertRaises(ValueError): b.mcnemar_exact(-1, 5)
        with self.assertRaises(ValueError): b.mcnemar_exact(1.5, 5)

    def test_statuses_never_treat_pending_as_failed(self):
        c = b.count_statuses(['resolved', 'unresolved', 'ungraded', 'missing'])
        self.assertEqual(c['graded'], 2)
        self.assertEqual(c['score'], .5)
        self.assertEqual(c['coverage'], .5)
        self.assertFalse(c['complete'])
        self.assertTrue(b.count_statuses(['unresolved'])['complete'])
        self.assertIsNone(b.count_statuses(['missing'])['score'])
        self.assertFalse(b.count_statuses([])['complete'])
        with self.assertRaises(ValueError): b.count_statuses(['failed'])

    def test_incomplete_coverage_never_rounds_to_complete(self):
        self.assertNotEqual(b.percent(27527/27528), '100.00%')
        self.assertEqual(b.percent(1), '100.00%')

    def test_slug(self):
        self.assertEqual(b.slug('GLM-5.3 Flash / FP8'), 'glm-5-3-flash-fp8')
        self.assertEqual(b.slug(' ../Model_Name.. '), 'model-name')
        self.assertEqual(b.repo_slug('scikit-learn/scikit-learn'), 'scikit-learn__scikit-learn')
        with self.assertRaises(ValueError): b.slug(' ... / ')

    def test_usage_does_not_double_count_tools(self):
        usage = {'prompt_tokens': 5, 'completion_tokens': 0, 'total_tokens': 5}
        extra = {'response': {'usage': usage}}
        d = b.trajectory_metrics({'info': {'model_stats': {'api_calls': 3}}, 'messages': [
            {'role': 'assistant', 'extra': extra}, {'role': 'tool', 'extra': extra},
            {'role': 'assistant', 'extra': {'response': {'usage': {'prompt_tokens': 8}}}},
            {'role': 'assistant'}]})
        self.assertEqual(d['steps'], 3)
        self.assertEqual(d['prompt_tokens'], 13)
        self.assertEqual(d['completion_tokens'], 0)
        self.assertEqual(d['usage_responses']['completion_tokens'], 1)
        self.assertIsNone(b.trajectory_metrics({})['total_tokens'])

    def test_histogram_counts(self):
        d = b.distribution([None, 1, 3, 5, 9])
        self.assertEqual(d['median'], 4)
        self.assertEqual(sum(row[2] for row in d['bins']), 4)
        self.assertEqual(b.distribution([7, 7])['bins'], [[7, 7, 2]])
        self.assertEqual(b.distribution([])['n'], 0)


class SafetyTests(unittest.TestCase):
    def test_missing_inputs_fail_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(b, 'collect_metrics') as collect:
                with self.assertRaisesRegex(ValueError, 'Missing required data files'):
                    b.build(Path(tmp), ROOT/'docs-test-refusal')
                collect.assert_not_called()
            self.assertFalse((ROOT/'docs-test-refusal').exists())

    def test_output_cannot_escape_publication(self):
        with self.assertRaisesRegex(ValueError, 'Output must'):
            b.build(out=ROOT.parent/'forbidden')

    def test_scanner_rejects_markers_without_echoing(self):
        for marker in b.FORBIDDEN:
            with self.assertRaises(ValueError) as caught:
                b.safe_bytes(b'prefix '+marker+b'example')
            self.assertNotIn(marker.decode(), str(caught.exception))
        b.safe_bytes(b'<span class="sk-badge sk-badge-spec">Task-wide policy</span>')

    def test_deterministic_write_keeps_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp).resolve()/'a.json'
            b.atomic_write(p, b.json_text({'b': 1, 'a': 2}))
            before = p.stat().st_mtime_ns
            b.atomic_write(p, b.json_text({'a': 2, 'b': 1}))
            self.assertEqual(before, p.stat().st_mtime_ns)

    def test_link_checker_detects_broken_targets_and_fragments(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p/'index.html').write_text('<html lang="en"><a href="missing.html">x</a><a href="#absent">y</a></html>')
            errors, pages = check_links.check(p)
            self.assertEqual(pages, 1)
            self.assertEqual(len(errors), 2)
            (p/'index.html').write_text('<html lang="en"><a href="#ok">x</a><p id="ok">ok</p></html>')
            self.assertEqual(check_links.check(p)[0], [])

    def test_pending_evidence_is_not_a_broken_link(self):
        d = {'tasks': {'org__repo-1': 'org/repo'}}
        site = b.Site(ROOT, ROOT/'docs', d, 'time', 'commit', None)
        link = site.evidence_link('missing-model', 'org__repo-1', '../../')
        self.assertNotIn('href=', link)
        self.assertIn('not packaged', link)
        self.assertEqual(site.evidence_path('a', 'org__repo-1'), 'evidence/models/a/attempts/org__repo/org__repo-1.json.gz')

    def test_evidence_inventory_excludes_atomic_packer_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            evidence = root/'evidence'; evidence.mkdir()
            (evidence/'published.json.gz').write_bytes(b'abc')
            (evidence/'.pack-staging').write_bytes(b'not published')
            site = b.Site(ROOT, root/'docs', {'models': ['m'], 'tasks': {'org__repo-1': 'org/repo'}}, 'time', 'commit', None)
            with patch.object(b, 'ROOT', root):
                b.build_evidence(site)
            inventory = b.read_json(site.out/'data/evidence.json')
            self.assertEqual((inventory['files'], inventory['bytes']), (1, 3))

    @unittest.skipUnless(shutil.which('node'), 'Node unavailable; optional JS syntax check')
    def test_javascript_syntax(self):
        for path in (ROOT/'tools/site_assets').glob('*.js'):
            result = subprocess.run(['node', '--check', str(path)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode())


    @unittest.skipUnless(shutil.which('node'), 'Node unavailable; optional JS runtime smoke test')
    def test_javascript_runtime_without_network(self):
        result = subprocess.run(['node', str(ROOT/'tests/site_runtime.cjs')], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())


class ReportTests(unittest.TestCase):
    def fixture(self, root):
        for name in b.REQUIRED:
            path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('{}')
        (root/'artifacts/fleet-backups').mkdir()
        def write(name, obj): (root/name).write_text(json.dumps(obj))
        write('configs/experiment.json', {'models': ['m'], 'expected_instances': 2, 'expected_attempts': 2, 'experiment': 'clean-run'})
        write('artifacts/fleet.json', {
            'w1': {'created_at': '2026-01-01T00:00:00Z', 'tags': []},
            'w2': {'created_at': '2026-01-01T00:02:00Z', 'tags': []}})
        write('artifacts/upgrade-v2.json', {'w1': 'upgraded', 'w2': 'upgraded'})
        (root/'scripts/fleet.py').write_text("['--cpu=8', '--memory=32GB']")
        (root/'scripts/upgrade_fleet.py').write_text("['--cpu=16', '--memory=72GB']; command='--parallel 8'")
        observations = [
            {'observed_at': '2025-12-31T00:00:00Z', 'workers': {'w1': {'experiments': ['old-run']}}},
            {'observed_at': '2026-01-01T00:00:00Z', 'workers': {'w1': {'experiments': ['clean-run']}}},
            {'observed_at': '2026-01-01T02:00:00Z', 'workers': {'w1': {'experiments': ['old-run', 'clean-run']}}},
            {'observed_at': '2026-01-02T00:00:00Z', 'workers': {'w1': {}}},
        ]
        (root/'artifacts/telemetry-history.jsonl').write_text('\n'.join(map(json.dumps, observations)))
        tasks = [{'instance_id': 'astropy__astropy-7606', 'repo': 'astropy/astropy'}, {'instance_id': 'a__b-1', 'repo': 'a/b'}]
        (root/'artifacts/datasets/agent-input.jsonl').write_text('\n'.join(map(json.dumps, tasks)))
        for subset in ('Verified', 'Lite'):
            (root/f'artifacts/datasets/SWE-bench_{subset}.jsonl').write_text(json.dumps(tasks[0]))
        (root/'artifacts/report/instances.csv').write_text('model,instance_id,status\nm,astropy__astropy-7606,resolved\nm,a__b-1,missing\n')
        write('artifacts/report/summary.json', [dict(model='m', **b.count_statuses(['resolved', 'missing']))])
        write('artifacts/report/generation-outcomes.json', {'m': {'Submitted': 1}})
        write('artifacts/report/subsets.json', [dict(model='m', subset='SWE-bench_Verified', **b.count_statuses(['unresolved'])),
                                               dict(model='m', subset='SWE-bench_Lite', **b.count_statuses(['resolved']))])
        write('artifacts/report/repositories.json', [dict(model='m', repo='astropy/astropy', **b.count_statuses(['resolved'])),
                                                    dict(model='m', repo='a/b', **b.count_statuses(['missing']))])

    def test_verified_supplemental_verdict_is_not_full_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.fixture(root)
            d = b.load_data(root)
            self.assertEqual(d['boards']['Full']['m']['resolved'], 1)
            self.assertEqual(d['boards']['Verified']['m']['resolved'], 0)
            self.assertEqual(d['boards']['Lite']['m']['resolved'], 1)

    def test_inconsistent_summary_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.fixture(root)
            path = root/'artifacts/report/summary.json'
            rows = json.loads(path.read_text()); rows[0]['resolved'] = 2; path.write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError, 'Summary disagrees'): b.load_data(root)

    def test_subset_cannot_silently_drop_pending_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.fixture(root)
            path = root/'artifacts/report/subsets.json'
            rows = json.loads(path.read_text()); rows[0]['total'] = 0; path.write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError, 'Verified report differs'): b.load_data(root)

    def test_duplicate_csv_row_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); self.fixture(root)
            with (root/'artifacts/report/instances.csv').open('a') as f: f.write('m,a__b-1,missing\n')
            with self.assertRaisesRegex(ValueError, 'duplicate report row'): b.load_data(root)

    def test_frozen_checkpoint_survives_later_report_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); self.fixture(root)
            frozen = b.FrozenSource(root)
            (root/'artifacts/report/summary.json').write_text('[]')
            self.assertEqual(b.load_data(frozen)['boards']['Full']['m']['resolved'], 1)
            with self.assertRaisesRegex(ValueError, 'Summary models disagree'): b.load_data(root)

    def test_metrics_ignore_post_checkpoint_attempts_and_hash_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); self.fixture(root)
            parent = root/'artifacts/fleet-backups/w/runs/v2/m'
            for instance in ('astropy__astropy-7606', 'a__b-1'):
                p = parent/instance; p.mkdir(parents=True)
                (p/'result.json').write_text('{"exit_status":"Submitted"}')
                (p/'grade.json').write_text('{}')
                (p/'trajectory.json').write_text('{"info":{"model_stats":{"api_calls":3}}}')
            data = b.load_data(root)
            cache = root/'cache.sqlite3'
            with contextlib.redirect_stdout(io.StringIO()):
                records = b.collect_metrics(root, data, cache, None)
            self.assertEqual(set(records['m']), {'astropy__astropy-7606'})
            self.assertEqual(records['m']['astropy__astropy-7606']['usage']['steps'], 3)
            p = parent/'astropy__astropy-7606/trajectory.json'
            before = p.stat()
            p.write_text(p.read_text().replace('3', '7'))
            os.utime(p, ns=(before.st_atime_ns, before.st_mtime_ns))
            with contextlib.redirect_stdout(io.StringIO()):
                updated = b.collect_metrics(root, data, cache, None)
            self.assertEqual(updated['m']['astropy__astropy-7606']['usage']['steps'], 7)

    def test_complete_build_is_repeatable_and_links_resolve(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source, publish = root/'source', root/'publish'
            self.fixture(source)
            def write(name, obj): (source/name).write_text(json.dumps(obj))
            experiment = b.read_json(source/'configs/experiment.json')
            experiment.update(mini_commit='a'*40, harness_commit='b'*40, harness_version='test',
                              attempts_per_instance=1, supersedes='Invalidated earlier run')
            write('configs/experiment.json', experiment)
            protocol = dict.fromkeys(['step_limit', 'wall_time_seconds', 'outer_process_timeout_seconds',
                'transport_timeout_seconds', 'max_output_tokens_per_call', 'max_completion_tokens_per_attempt',
                'context_proxy_limit', 'grader_timeout_seconds', 'temperature', 'container_cpus'], 1)
            protocol.update(context_proxy_tokenizer='test', scaffold='test scaffold', container_network='none',
                            container_memory='test', repository_history='base-only')
            write('configs/protocol.json', protocol)
            for name in ['grading-amendments', 'test-timeout-reviews', 'timeout-adjudications', 'transport-amendments']:
                write(f'artifacts/report/{name}.json', [])
            write('artifacts/leaderboards.json', {'leaderboards': [dict(name=n, results=[]) for n in ('Test', 'Verified', 'Lite')]})
            write('artifacts/official-comparison.json', {'models': [{'model': 'm', 'matches': []}],
                  'retrieved_at': '2026-01-01', 'commit': 'c'*40, 'source': 'https://example.org',
                  'sha256': b.digest(source/'artifacts/leaderboards.json')})
            attempt = source/'artifacts/fleet-backups/w/runs/v2/m/astropy__astropy-7606'
            attempt.mkdir(parents=True)
            (attempt/'result.json').write_text('{"exit_status":"Submitted"}')
            (attempt/'trajectory.json').write_text('{"info":{"mini_version":"test","model_stats":{"api_calls":3}}}')
            assets = ['tokens.json', 'components/bundle.css', 'assets/Mascot/kitty-mark.svg',
                      'assets/Mascot/kitty-mark-night.svg', 'assets/Mascot/spectacles.svg']
            for relative in assets:
                dest = publish/'vendor/design-system'/relative; dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT/'vendor/design-system'/relative, dest)
            shutil.copytree(ROOT/'tools/site_assets', publish/'tools/site_assets')
            shutil.copytree(ROOT/'vendor/echarts', publish/'vendor/echarts')
            for name in ('partners.json', 'projects.json', 'limit-observation.json', 'build_site.py', 'pack_evidence.py'):
                shutil.copyfile(ROOT/'tools'/name, publish/'tools'/name)
            with patch.object(b, 'ROOT', publish), patch.object(b, 'source_commit', return_value='d'*40), contextlib.redirect_stdout(io.StringIO()):
                b.build(source, publish/'docs')
                before = {p.relative_to(publish/'docs'): (p.read_bytes(), p.stat().st_mtime_ns)
                          for p in (publish/'docs').rglob('*') if p.is_file()}
                b.build(source, publish/'docs')
            after = {p.relative_to(publish/'docs'): (p.read_bytes(), p.stat().st_mtime_ns)
                     for p in (publish/'docs').rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            self.assertEqual(check_links.check(publish/'docs')[0], [])
            self.assertEqual((publish/'docs/robots.txt').read_text(), 'User-agent: *\nAllow: /\n')
            self.assertNotIn('name="robots"', (publish/'docs/index.html').read_text())
            # Exercise every page builder in both publish modes, independent of
            # an existing docs tree or whether evidence has been packed.
            for staging in (False, True, False):
                # Reuse the output to catch stale noindex/robots settings.
                out = publish/'preview'
                with patch.object(b, 'ROOT', publish), patch.object(b, 'source_commit', return_value='d'*40), contextlib.redirect_stdout(io.StringIO()):
                    b.build(source, out, publish=True, staging=staging)
                    first = {p.relative_to(out): (p.read_bytes(), p.stat().st_mtime_ns)
                             for p in out.rglob('*') if p.is_file()}
                    b.build(source, out, publish=True, staging=staging)
                self.assertEqual(first, {p.relative_to(out): (p.read_bytes(), p.stat().st_mtime_ns)
                                         for p in out.rglob('*') if p.is_file()})
                self.assertEqual(check_links.check(out, publish=True, repository_root=publish)[0], [])
                self.assertEqual((out/'robots.txt').read_text(), 'User-agent: *\n'+('Disallow' if staging else 'Allow')+': /\n')
                config = b.read_json(publish/'tools/partners.json')
                subpath = urlsplit(config['site_url']).path
                for page in out.rglob('*.html'):
                    markup = page.read_text()
                    self.assertEqual('<meta name="robots" content="noindex,nofollow">' in markup, staging)
                    canonical = config['site_url'] + page.relative_to(out).as_posix()
                    self.assertIn(f'<link rel="canonical" href="{canonical}">', markup)
                    self.assertIn(f'<meta property="og:url" content="{canonical}">', markup)
                    document = check_links.Document(); document.feed(markup)
                    for link in document.links:
                        url = urlsplit(link)
                        if url.scheme or url.netloc:
                            continue
                        path = unquote(url.path)
                        if path.startswith('/'):
                            self.assertEqual(page, out/'404.html')
                            self.assertTrue(path.startswith(subpath))
                        elif path:
                            self.assertTrue((page.parent/path).resolve().is_relative_to(out),
                                            f'{page.name}: relative URL escapes docs')



class InfrastructureFigureTests(unittest.TestCase):
    def test_vm_screenshot_ships_with_alt_text_and_caption(self):
        root=Path(__file__).resolve().parents[1]
        template=(root/'tools/site_assets/infrastructure.html').read_text()
        self.assertIn('exe-dev-vm-list.webp', template)
        self.assertRegex(template, r'<img[^>]+alt="[^"]{40,}"')
        self.assertIn('<figcaption>', template)
        self.assertTrue((root/'tools/site_assets/exe-dev-vm-list.webp').stat().st_size < 300_000)

if __name__ == '__main__':
    unittest.main()
