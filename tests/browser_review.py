"""Make a self-contained real-browser review; no server or network is needed.

Run: python3 tests/browser_review.py --output /tmp/official-review.html
Open that file in a browser. Each frame uses the complete generated page at its
declared viewport, local ECharts and data, and offline font fallbacks.
"""
import argparse
import base64
import html
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def offline_page(theme):
    page = (ROOT/'docs/index.html').read_text()
    page = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', page)
    page = re.sub(r'<link\b[^>]*>', '', page)
    page = page.replace('<head>', '<head><meta http-equiv="Content-Security-Policy" '
                        'content="default-src \'none\'; script-src \'unsafe-inline\'; '
                        'style-src \'unsafe-inline\'; img-src data:">')
    def image(match):
        tag, src = match[0], match[1]
        path = (ROOT/'docs'/src).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            return ''
        mime = 'image/svg+xml' if path.suffix == '.svg' else 'image/webp'
        return tag.replace(src, 'data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode())
    page = re.sub(r'<img\b[^>]*src="([^"]+)"[^>]*>', image, page)
    styles = '\n'.join(re.sub(r'@import\s+url\([^)]*\)\s*;', '', (ROOT/'docs'/p).read_text()) for p in (
        'assets/design-system/tokens.css', 'assets/design-system/bundle.css', 'assets/site.css'))
    page = page.replace('</head>', '<style>'+styles+'</style></head>')
    data = (ROOT/'docs/data/charts.json').read_text()
    scripts = [f'document.documentElement.dataset.theme={json.dumps(theme)};'
               f'window.fetch=async()=>({{ok:true,json:async()=>({data})}});',
               (ROOT/'vendor/echarts/echarts.min.js').read_text(),
               (ROOT/'docs/assets/charts.js').read_text(),
               (ROOT/'tests/official_browser.js').read_text()]
    return page.replace('</body>', ''.join('<script>'+s.replace('</script', '<\\/script')+'</script>' for s in scripts)+'</body>')


def build(out):
    buttons, frames = [], []
    for theme in ('light', 'dark'):
        for width in (375, 768, 1280):
            key = f'{theme}-{width}'
            buttons.append(f'<button onclick="show({html.escape(json.dumps(key), quote=True)})">{key}</button>')
            frames.append(f'<iframe id="{key}" title="{key}" width="{width}" height="1800" '
                          f'srcdoc="{html.escape(offline_page(theme), quote=True)}"></iframe>')
    out.write_text('<!doctype html><meta charset="utf-8"><title>Offline official chart review</title>'
                   '<style>body{font:15px sans-serif;margin:16px}button{margin:4px;padding:8px}'
                   'iframe{position:absolute;left:16px;top:170px;visibility:hidden;border:1px solid #aaa}'
                   'pre{white-space:pre-wrap}</style><h1>Offline official chart review</h1>'
                   +''.join(buttons)+'<pre id="results">Checking all six views…</pre>'+''.join(frames)
                   +'<script>function show(id){document.querySelectorAll("iframe").forEach(f=>'
                   'f.style.visibility=f.id===id?"visible":"hidden")}show("light-375");'
                   'const reports={};addEventListener("message",e=>{if(e.data.review){'
                   'reports[e.data.review]=e.data.result;document.getElementById("results").textContent='
                   'Object.entries(reports).map(([k,v])=>k+": "+v).join(" · ")}})</script>')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/official-review.html'))
    args = parser.parse_args()
    build(args.output)
    print(args.output)
