"""Official comparison presentation regressions; no external dependencies."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OfficialPolishTests(unittest.TestCase):
    def test_chip_and_tab_styles_never_strike_through(self):
        css = (ROOT/'tools/site_assets/site.css').read_text()
        rules = re.findall(r'([^{}]+)\{([^{}]*)\}', re.sub(r'/\*.*?\*/', '', css, flags=re.S))
        selected_rules = 0
        for selectors, declarations in rules:
            if re.search(r'aria-(?:pressed|selected)|family-toggle|official-filters|\.tabs|\bbutton\b', selectors):
                selected_rules += 1
                self.assertNotRegex(declarations, r'text-decoration(?:-line)?\s*:[^;]*line-through', selectors)
        self.assertGreater(selected_rules, 5)
        # Ancestor decorations propagate and cannot be undone by a child.
        self.assertNotRegex(css, r'text-decoration(?:-line)?\s*:[^;}]*line-through')
        page = (ROOT/'docs/index.html').read_text()
        for button in re.findall(r'<button\b[^>]*>.*?</button>', page, flags=re.S):
            if re.search(r'aria-(?:pressed|selected)', button):
                self.assertNotRegex(button, r'<(?:s|del)\b')

    def test_key_and_accessible_explanations(self):
        page = (ROOT/'docs/index.html').read_text()
        for copy in ('Entry from another team',
                     'Entry that used mini-SWE-agent, the same simple agent we used',
                     'Entry that used an open-weight model (diamond)',
                     'Keyboard: Tab to a row, arrow keys to move between dots, Escape to close the card.',
                     'Nearby model markers are spaced apart for readability; exact scores are below.'):
            self.assertIn(copy, page)
        self.assertIn('<ol id="official-key" class="official-key" aria-label="Our models and scores">', page)
        css = (ROOT/'tools/site_assets/site.css').read_text()
        self.assertIn('@media(max-width:800px){.official-key{grid-template-columns:minmax(0,1fr)}}', css)
        self.assertIn('.official-model-name{overflow-wrap:anywhere}', css)

    @unittest.skipUnless(shutil.which('node'), 'Node required for production geometry')
    def test_production_marker_and_density_geometry(self):
        result = subprocess.run(['node', 'tests/official_layout.cjs'], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_browser_review_is_self_contained(self):
        from browser_review import offline_page
        for theme in ('light', 'dark'):
            page = offline_page(theme)
            markup = re.sub(r'<script\b[^>]*>.*?</script>', '', page, flags=re.S)
            self.assertTrue("default-src 'none'" in markup)
            self.assertFalse(re.search(r'<link\b|<script\b[^>]*src=|@import\s', markup))
            self.assertFalse(re.search(r'<img\b[^>]*src="(?!data:)', markup))
            self.assertTrue('window.fetch=async()' in page)
            self.assertTrue('horizontal page scroll' in page)


if __name__ == '__main__':
    unittest.main()
