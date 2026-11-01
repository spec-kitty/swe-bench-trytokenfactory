"""Family identity and WCAG contrast checked against actual Day/Night CSS tokens."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    'deepseek-v4.1-flash-1017': ('deepseek', 'build'),
    'deepseek-v4.1-flash-1017-uncensored-fp8': ('deepseek', 'build'),
    'glm-5.3': ('glm', 'role-frame'),
    'glm-5.3-flash': ('glm', 'role-frame'),
    'glm-5.3-flash-uncensored-fp8': ('glm', 'role-frame'),
    'glm-5.3-uncensored-fp8': ('glm', 'role-frame'),
    'kimi-k3': ('kimi', 'factory'),
    'kimi-k3-abliterated': ('kimi', 'factory'),
    'nemotron-3-ultra': ('nemotron', 'brain'),
    'nemotron-3-super': ('nemotron', 'brain'),
    'nemotron-3.5-lightning': ('nemotron', 'brain'),
    'minimax-m3.1-flash': ('minimax', 'role-move'),
}


def rgb(color):
    if color.startswith('#'):
        return [int(color[i:i+2], 16) for i in (1, 3, 5)]
    return [int(x) for x in re.findall(r'\d+', color)]


def linear(v):
    v /= 255
    return v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4


def luminance(color):
    return sum(linear(v)*weight for v, weight in zip(rgb(color), (.2126, .7152, .0722)))


class PaletteSourceTests(unittest.TestCase):
    def test_no_literal_colors_or_identity_gold_in_chart_code(self):
        source = (ROOT/'tools/site_assets/charts.js').read_text()
        self.assertNotRegex(source, r'#[0-9a-fA-F]{3,8}\b')
        self.assertNotRegex(source, r'(?:--|[\x22\x27])spec(?:-soft|-ink)?\b')

    def test_heading_wrap_and_model_svg_hooks(self):
        headings = 0
        for page in (ROOT/'docs').rglob('*.html'):
            text = page.read_text()
            for heading in re.findall(r'<h[1-6]\b[^>]*>(.*?)</h[1-6]>', text, re.S):
                if 'SWE-bench' in heading:
                    headings += 1
                    self.assertNotIn('SWE-bench', heading.replace('<span class="nowrap">SWE-bench</span>', ''))
        self.assertGreater(headings, 0)
        self.assertIn('.nowrap{white-space:nowrap;overflow-wrap:normal}', (ROOT/'docs/assets/site.css').read_text())
        for model in EXPECTED:
            slug = re.sub(r'[^a-z0-9]+', '-', model.lower()).strip('-')
            text = (ROOT/f'docs/models/{slug}.html').read_text()
            self.assertIn(f'data-model-palette="{model}"', text)
            self.assertIn('fill="var(--model-color, var(--ink-muted))"', text)
            self.assertIn('src="../assets/charts.js"', text)


@unittest.skipUnless(shutil.which('node'), 'Node required to exercise production colour helpers')
class PaletteRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        css = (ROOT/'docs/assets/design-system/tokens.css').read_text()
        blocks = re.findall(r'--surface:[^}]+', css)
        cls.themes = {name: dict(re.findall(r'--([\w-]+):(#[0-9a-fA-F]{6})', block))
                      for name, block in zip(('light', 'dark'), blocks[:2])}
        cls.models = list(EXPECTED)+['future-model', 'constructor-model']
        result = subprocess.run(['node', 'tests/chart_palette.cjs'], cwd=ROOT,
                                input=json.dumps(dict(themes=cls.themes, models=cls.models)),
                                text=True, capture_output=True, check=True)
        cls.actual = json.loads(result.stdout)

    def test_real_model_families_stable_and_unknown_neutral(self):
        real = json.loads((ROOT/'docs/data/charts.json').read_text())['model_order']
        self.assertEqual(set(real), set(EXPECTED))
        for model, family, color in zip(self.models, self.actual['families'], self.actual['modelColors']):
            self.assertEqual((family['key'], family['token']), EXPECTED.get(model, ('other', 'ink-muted')))
            self.assertEqual(family['flash'], model in ('glm-5.3-flash', 'glm-5.3-flash-uncensored-fp8'))
            self.assertEqual(family['patterned'], bool({'uncensored', 'abliterated'} & set(model.split('-'))))
            self.assertIn(f'var(--{family["token"]})', color)
            self.assertEqual('70%' in color, family['flash'])

    def test_outcome_adjacent_greyscale_contrast(self):
        for theme, values in self.actual['outcomeContrast'].items():
            # Exact prescribed soft backgrounds are near-isoluminant; the
            # required hatch/outline supplies the non-colour distinction.
            self.assertLess(values['background'], 1.15, theme)
            for ratio in values['adjacent']:
                self.assertGreaterEqual(ratio, 1.15, theme)

    def test_entire_ramp_contrast_and_linear_light_interpolation(self):
        for theme, samples in self.actual['ramps'].items():
            endpoints = sorted((self.themes[theme][key] for key in ('surface-sunk', 'build')), key=luminance, reverse=True)
            start, end = map(rgb, endpoints)
            self.assertGreater(luminance(samples[0]['fill']), luminance(samples[-1]['fill']))
            for i, sample in enumerate(samples):
                a, b = luminance(sample['fill']), luminance(sample['label'])
                self.assertGreaterEqual((max(a, b)+.05)/(min(a, b)+.05), 4.5, (theme, i, sample))
                # Independently reconstruct each linear-light channel, allowing
                # half a channel for the renderer's integer RGB quantisation.
                for channel, low, high in zip(rgb(sample['fill']), start, end):
                    v = linear(low)+(linear(high)-linear(low))*i/1000
                    encoded = 255*(12.92*v if v <= .0031308 else 1.055*v**(1/2.4)-.055)
                    self.assertLessEqual(abs(channel-encoded), .500001)


if __name__ == '__main__':
    unittest.main()
