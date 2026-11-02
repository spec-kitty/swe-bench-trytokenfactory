"""Offline contracts for partner publication, derived facts and language policy."""
import json
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import build_site as b
import test_build_site


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.metas, self.images = [], {}, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a':
            self.links.append(attrs)
        if tag == 'meta':
            self.metas[attrs.get('name', attrs.get('property'))] = attrs.get('content')
        if tag == 'img':
            self.images.append(attrs)


class PublicationGuardTests(unittest.TestCase):
    def test_dollar_amount_fails_without_echoing(self):
        with self.assertRaises(ValueError) as caught:
            b.publication_guard('<p>$5</p>')
        self.assertNotIn('$5', str(caught.exception))

    def test_every_prohibited_word_case_insensitive_and_identifiers(self):
        words = ('pricing price prices billing invoice tier quota allowance credit credits '
                 'subscription per-token cost costs costly free').split()
        for word in words:
            with self.subTest(word=word):
                for content in (f'<p>{word.upper()}</p>', f'"test_{word}_example"'):
                    with self.assertRaises(ValueError):
                        b.publication_guard(content)

    def test_clean_words_and_technical_counts_pass(self):
        b.publication_guard('Costa, costumer, credited, frontier, 128 slots, token counts, steps')
        b.publication_guard('<p>Spec Kitty with Mirantis TokenFactory and exe.dev</p>')

    def test_html_entities_cannot_hide_amount_or_word(self):
        for text in ('&#36;5', '&dollar;5', 'pr&#105;ce'):
            with self.assertRaises(ValueError):
                b.publication_guard(text)

    def test_scans_all_extensions_and_unowned_nested_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for extension in b.TEXT_EXTENSIONS:
                path = root/'unowned'/('old'+extension.upper())
                path.parent.mkdir(exist_ok=True)
                path.write_text('"$5"')
                with self.assertRaises(ValueError):
                    b.guard_docs(root)
                path.unlink()
            (root/'index.html').write_text('<p>Token counts and steps</p>')
            (root/'data.json').write_text('{"attempts": 12}')
            b.guard_docs(root)

    def test_recursive_export_omits_every_cost_key(self):
        source = {'instance_cost': 5, 'COSTestimate': 7,
                  'attempts': [{'steps': 3, 'totalCost': 4, 'nested': {'api_cost': 1}}]}
        self.assertEqual(b.public_data(source), {'attempts': [{'steps': 3, 'nested': {}}]})
        self.assertIn('instance_cost', source)

    def test_existing_json_fields_and_escaped_text_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for value in ('{"totalCost":3}', '{"note":"pr\\u0069ce"}', '{"pr\\u0069ce":3}'):
                (root/'data.json').write_text(value)
                with self.assertRaises(ValueError):
                    b.guard_docs(root)

    def test_rejection_precedes_output_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = b.Site(ROOT, Path(tmp), {'models': ['m']}, 'time', 'commit', None)
            with self.assertRaises(ValueError):
                site.write('index.html', '<p>$5</p>')
            self.assertFalse((Path(tmp)/'index.html').exists())


class PartnerTests(unittest.TestCase):
    def test_urls_and_dynamic_role_come_from_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'partners.json'
            config = b.read_json(ROOT/'tools/partners.json')
            config['partners'][1]['url'] = 'https://example.org/changed'
            p.write_text(json.dumps(config))
            partners = b.load_partners(p, 7)
            self.assertEqual(partners[1]['url'], 'https://example.org/changed')
            self.assertIn('all 7 models', partners[1]['role'])
            config['partners'][1]['url'] = 'javascript:alert(1)'
            p.write_text(json.dumps(config))
            with self.assertRaises(ValueError):
                b.load_partners(p, 7)

    def test_shared_shell_on_root_model_about_and_missing_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = b.Site(ROOT, Path(tmp).resolve(), {'models': ['m']}, 'time', 'commit', None)
            for relative in ['index.html', 'methodology.html', 'about.html', '404.html', 'models/m.html']:
                site.page(relative, 'Example', '<p>Example body</p>')
                text = (site.out/relative).read_text()
                parsed = PageParser(); parsed.feed(text)
                for key in ('description', 'og:title', 'og:description', 'twitter:title', 'twitter:description'):
                    for name in ('Spec Kitty', 'Mirantis TokenFactory', 'exe.dev'):
                        self.assertIn(name, parsed.metas[key])
                urls = [p['url'] for p in site.partners]
                external = [a for a in parsed.links if a.get('href') in urls]
                self.assertEqual([a['href'] for a in external], urls+urls)
                self.assertTrue(all(a['target'] == '_blank' and a['rel'] == 'noopener' for a in external))
                self.assertIn(b.JOINT_PROJECT, text)
                prefix = '../' if relative.startswith('models/') else ''
                self.assertTrue(any(a['href'] == prefix+'about.html' for a in parsed.links))
                self.assertEqual([i['src'] for i in parsed.images],
                                 [prefix+'assets/design-system/kitty-mark.svg', prefix+'assets/design-system/kitty-mark-night.svg'])
                self.assertLess(text.index('class="partner-strip"'), text.index('<nav'))

    def test_infrastructure_length_and_incident_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'source'
            test_build_site.ReportTests().fixture(source)
            site = b.Site(source, Path(tmp).resolve()/'docs', b.load_data(source), 'time', 'commit', None)
            section = b.infrastructure_section(site)
            prose = section.split('<details>')[0]
            words = re.sub('<[^>]+>', ' ', prose).split()
            self.assertGreaterEqual(len(words), 700)
            self.assertLessEqual(len(words), 1000)
            for anchor in ('incidents', 'reviewed-timeouts', 'invalidated-history'):
                self.assertIn(f'href="#{anchor}"', section)
            self.assertIn('Where these facts come from', section)
            b.publication_guard(section)

    def test_theme_text_contrast(self):
        tokens = {t['name']: t['value'] for t in b.read_json(ROOT/'vendor/design-system/tokens.json')['color']['tokens']}
        def luminance(hex_value):
            channels = [int(hex_value[i:i+2], 16)/255 for i in (1, 3, 5)]
            channels = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in channels]
            return sum(c*w for c, w in zip(channels, (.2126, .7152, .0722)))
        for theme in ('light', 'dark'):
            for ink in ('ink', 'ink-muted'):
                for ground in ('surface', 'surface-raised', 'surface-sunk'):
                    a, z = sorted((luminance(tokens[ink][theme]), luminance(tokens[ground][theme])))
                    self.assertGreaterEqual((z+.05)/(a+.05), 4.5)
        css = (ROOT/'tools/site_assets/site.css').read_text()
        self.assertIn('outline:2px solid var(--focus);outline-offset:2px', css)
        self.assertIn('.partner-footer{grid-template-columns:1fr;', css)
        self.assertIn('.partner-strip>a:first-child{flex-basis:100%}', css)


class InfrastructureFactsTests(unittest.TestCase):
    def test_copy_rounds_windows_but_preserves_exact_data_and_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = root/'source'
            test_build_site.ReportTests().fixture(source)
            site = b.Site(source, root/'docs', b.load_data(source), 'time', 'commit', None)
            facts = b.infrastructure_facts(source, site.data)
            facts.update(provision_seconds=211, observed_hours=62.009745546666664)
            with patch.object(b, 'infrastructure_facts', return_value=facts):
                section = b.infrastructure_section(site)
            prose, detail = section.split('<details>', 1)
            self.assertIn('about 3.5 minutes (211 seconds)', prose)
            self.assertIn('about 62 hours', prose)
            self.assertNotIn(str(facts['observed_hours']), prose)
            self.assertIn(str(facts['observed_hours']), detail)
            for key in ('provision_first', 'provision_last', 'observed_first', 'observed_last'):
                self.assertIn(facts[key], detail)
            exported = b.read_json(site.out/'data/infrastructure.json')
            for key, value in facts.items():
                self.assertEqual(exported[key], value)
            partner_facts = b.read_json(ROOT/'tools/partners.json')['facts']
            self.assertEqual(exported['partner_facts'], partner_facts)
            for fact in partner_facts:
                self.assertIn(b.E(fact['source']), detail)
            self.assertIn('We searched every collected trajectory, log, prediction and grading file '
                          'for the real gateway key and found no match.', prose)

    def test_project_tag_is_escaped_plain_text_from_partner_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(); source = root/'source'
            test_build_site.ReportTests().fixture(source)
            site = b.Site(source, root/'docs', b.load_data(source), 'time', 'commit', None)
            config = b.read_json(ROOT/'tools/partners.json')
            tag = next(f for f in config['facts'] if f['id'] == 'vm-tag')
            tag['value'] = '<changed-tag>'
            read_json = b.read_json
            def read(path):
                return config if path == ROOT/'tools/partners.json' else read_json(path)
            with patch.object(b, 'read_json', side_effect=read):
                section = b.infrastructure_section(site)
            self.assertIn('All 2 workers carry the shared project tag &lt;changed-tag&gt; '
                          'in the exe.dev VM list.', section)
            self.assertNotIn('<changed-tag>', section)

    def test_derived_window_excludes_old_or_unidentified_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); test_build_site.ReportTests().fixture(root)
            facts = b.infrastructure_facts(root, b.load_data(root))
            self.assertEqual(facts['workers'], 2)
            self.assertEqual(facts['slots'], 16)
            self.assertEqual(facts['provision_seconds'], 120)
            self.assertEqual(facts['observed_hours'], 2)
            self.assertEqual(facts['models'], 1)
            self.assertEqual(facts['attempts'], 2)
            self.assertEqual(facts['tagged_workers'], 0)
            self.assertEqual(facts['initial_memory'], 32)
            self.assertEqual(facts['upgraded_memory'], 72)

    def test_changed_source_values_change_derived_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); test_build_site.ReportTests().fixture(root)
            script = root/'scripts/upgrade_fleet.py'
            script.write_text(script.read_text().replace('--parallel 8', '--parallel 6').replace('--cpu=16', '--cpu=24'))
            facts = b.infrastructure_facts(root, b.load_data(root))
            self.assertEqual(facts['slots'], 12)
            self.assertEqual(facts['upgraded_cpus'], 24)

    def test_missing_clean_observation_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); test_build_site.ReportTests().fixture(root)
            (root/'artifacts/telemetry-history.jsonl').write_text('')
            with self.assertRaisesRegex(ValueError, 'No telemetry'):
                b.infrastructure_facts(root, b.load_data(root))

    def test_incomplete_upgrade_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); test_build_site.ReportTests().fixture(root)
            (root/'artifacts/upgrade-v2.json').write_text('{"w1":"upgraded","w2":"draining"}')
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                b.infrastructure_facts(root, b.load_data(root))


if __name__ == '__main__':
    unittest.main()
