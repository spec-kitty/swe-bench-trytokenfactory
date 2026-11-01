import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import build_site as b
import check_links


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root/'tools').mkdir()
        self.config = b.read_json(ROOT/'tools/partners.json')
        # Alternate coordinates expose hard-coded repository, branch and path.
        self.config.update(repository_url='https://github.com/example/benchmark',
                           branch='review', site_url='https://example.github.io/nested/preview/')
        (self.root/'tools/partners.json').write_text(json.dumps(self.config))
        self.out = self.root/'site'
        self.patch_root = patch.object(b, 'ROOT', self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        self.site = b.Site(self.root, self.out, {'models': []}, 'snapshot', 'commit', None, publish=True)

    def test_source_download_and_folder_links_at_every_depth(self):
        downloads = ['evidence/models/m/attempts/org__repo/task.json.gz',
                     'evidence/models/m/attempts/org__repo/task.trajectory.json.gz',
                     'evidence/models/m/predictions.jsonl', 'evidence/models/m/results.json',
                     'evidence/MANIFEST.sha256', 'evidence/configs.json']
        sources = ['tools/build_site.py', 'tools/BUILD_SITE.md', 'LICENSE', 'NOTICE',
                   'README.md', 'evidence/README.md']
        for relative, prefix in [('index.html', '../'), ('models/m.html', '../../'),
                                 ('deep/models/m.html', '../../../')]:
            for kind, paths in [('raw', downloads), ('blob', sources), ('tree', ['evidence/', 'tools/'])]:
                for path in paths:
                    with self.subTest(page=relative, path=path):
                        self.assertEqual(self.site.publish_link(relative, prefix+path+'?download=1#part'),
                                         f'{self.config["repository_url"]}/{kind}/review/{path}?download=1#part')
            self.assertEqual(self.site.publish_link(relative, prefix[3:]+'index.html'), prefix[3:]+'index.html')

    def test_transform_only_attributes_and_preserve_fragments(self):
        body = ('<a href="../LICENSE?x=1&amp;y=2#part">Licence</a>'
                '<pre>&lt;a href="../LICENSE"&gt;</pre><a href="#main">Skip</a>')
        self.site.page('index.html', 'Test', body)
        page = (self.out/'index.html').read_text()
        self.assertIn('/blob/review/LICENSE?x=1&amp;y=2#part', page)
        self.assertIn('<pre>&lt;a href="../LICENSE"&gt;</pre>', page)
        self.assertIn('href="#main"', page)
        self.assertIn('data-evidence-base="'+self.config['repository_url']+'/raw/review/"', page)

    def test_404_links_work_at_arbitrary_request_depth(self):
        self.site.page('404.html', 'Missing', '<a href="index.html">Return</a>')
        page = (self.out/'404.html').read_text()
        self.assertNotIn('<base', page)
        doc = check_links.Document(); doc.feed(page)
        subpath = urlsplit(self.config['site_url']).path
        for link in doc.links:
            url = urlsplit(link)
            if url.scheme or url.netloc or not url.path:
                continue
            self.assertTrue(link.startswith(subpath))
            for missing in ('missing', 'deep/nested/missing'):
                self.assertEqual(urljoin(self.config['site_url']+missing, link),
                                 urljoin(self.config['site_url'], link))

    def test_local_staging_keeps_relative_links_without_canonical(self):
        self.site.publish = False
        self.site.staging = True
        self.site.page('404.html', 'Missing', '<a href="../LICENSE">Licence</a>')
        page = (self.out/'404.html').read_text()
        self.assertIn('href="../LICENSE"', page)
        self.assertIn('href="index.html"', page)
        self.assertIn('name="robots" content="noindex,nofollow"', page)
        self.assertNotIn('rel="canonical"', page)
        self.assertNotIn('MIT licensed.', page)

    def test_licence_reads_first_copyright_line_and_omits_when_absent(self):
        self.assertEqual(b.research_licence(), '')
        copyright_line = 'Copyright (c) 2040 Example Holder'
        (self.root/'LICENSE').write_text('MIT License\n'+copyright_line+'\nCopyright (c) 2041 Other\n')
        self.assertIn('Licence: MIT, '+copyright_line+'. See ', b.research_licence())
        self.assertNotIn('2041', b.research_licence())
        self.site.page('index.html', 'Test', b.research_licence())
        page = (self.out/'index.html').read_text()
        self.assertIn('MIT licensed. <a href="'+self.config['repository_url']+'">Source and evidence on GitHub.</a>', page)
        self.assertIn('/blob/review/LICENSE', page)
        self.assertIn('/blob/review/NOTICE', page)

    def test_publish_warning_only_without_staging(self):
        for flags, warning in [([], False), (['--staging'], False),
                               (['--publish'], True), (['--publish', '--staging'], False)]:
            stderr = io.StringIO()
            with patch.object(sys, 'argv', ['build_site.py', *flags]), patch.object(b, 'build') as build, contextlib.redirect_stderr(stderr):
                self.assertEqual(b.main(), 0)
            self.assertEqual('allows search indexing' in stderr.getvalue(), warning)
            self.assertEqual(build.call_args.kwargs['publish'], '--publish' in flags)
            self.assertEqual(build.call_args.kwargs['staging'], '--staging' in flags)

    def write_page(self, links, name='index.html'):
        self.out.mkdir(exist_ok=True)
        (self.out/name).write_text('<html lang="en">'+''.join(f'<a href="{link}">Link</a>' for link in links)+'</html>')

    def check(self):
        return check_links.check(self.out, publish=True, repository_root=self.root)[0]

    def test_checker_maps_github_urls_offline_and_ignores_other_externals(self):
        for path in ('evidence/configs.json', 'evidence/models/m/results.json', 'tools/build_site.py', 'LICENSE'):
            target = self.root/path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('test')
        links = [self.site.repository_link(path) for path in
                 ('evidence/configs.json', 'evidence/models/m/results.json', 'tools/build_site.py', 'LICENSE', 'evidence/')]
        links += ['https://unreachable.invalid/no-network', 'https://github.com/example/benchmark-other/blob/review/missing']
        self.write_page(links)
        self.assertEqual(self.check(), [])
        (self.root/'LICENSE').unlink()
        self.assertEqual(len(self.check()), 1)
        self.write_page([self.config['repository_url']+'/blob/review/%2e%2e/escape'])
        self.assertIn('escapes repository', self.check()[0])
        self.write_page([self.config['repository_url']+'/blob/wrong/tools/build_site.py'])
        self.assertIn('unexpected branch', self.check()[0])

    def test_checker_rejects_escaping_relative_and_root_absolute_links(self):
        (self.root/'LICENSE').write_text('test')
        for link in ('../LICENSE', '%2e%2e/LICENSE', '/index.html', '/nested/preview/index.html'):
            with self.subTest(link=link):
                self.write_page([link])
                self.assertTrue(self.check())
        self.write_page([])
        self.write_page(['/nested/preview/index.html'], '404.html')
        self.assertEqual(self.check(), [])
        self.write_page(['/index.html'], '404.html')
        self.assertTrue(self.check())

    def test_checker_validates_explorer_downloads_against_checkout(self):
        self.write_page([])
        (self.out/'data').mkdir()
        (self.out/'data/instances.json').write_text(json.dumps({
            'models': ['m'], 'repos': ['org/repo'], 'rows': [['org__repo-1', 0, [0], [1]]]}))
        self.assertEqual(len(self.check()), 1)
        target = self.root/'evidence/models/m/attempts/org__repo/org__repo-1.json.gz'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'test')
        self.assertEqual(self.check(), [])


if __name__ == '__main__':
    unittest.main()
