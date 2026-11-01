#!/usr/bin/env python3
"""Check local HTML, CSS, lazy data and packaged evidence links; never use network."""
from __future__ import annotations
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.ids = set()
        self.duplicate_ids = set()
        self.issues = []
        self.tables = 0
        self.captions = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            if attrs['id'] in self.ids:
                self.duplicate_ids.add(attrs['id'])
            self.ids.add(attrs['id'])
        for key in ('href', 'src', 'data-source'):
            if attrs.get(key):
                self.links.append(attrs[key])
        if tag == 'table':
            self.tables += 1
        if tag == 'caption':
            self.captions += 1
        if tag == 'th' and attrs.get('scope') not in ('row', 'col', 'rowgroup', 'colgroup'):
            self.issues.append('Table heading lacks scope')
        if tag == 'img' and 'alt' not in attrs:
            self.issues.append('Image lacks alt text')
        if tag == 'html' and not attrs.get('lang'):
            self.issues.append('Document lacks language')
        if tag == 'script' and attrs.get('src', '').startswith(('http:', 'https:')):
            self.issues.append('Unexpected external script')


def check(root, publish=False, repository_root=ROOT, config=None):
    root = Path(root).resolve()
    repository_root = Path(repository_root).resolve()
    if publish:
        config = config or json.loads((repository_root/'tools/partners.json').read_text())
        repository_url = config['repository_url'].rstrip('/')
        branch = quote(config['branch'], safe='')
        subpath = urlsplit(config['site_url']).path.rstrip('/') + '/'
    errors = []
    docs = {}
    for p in sorted(root.rglob('*.html')):
        doc = Document()
        doc.feed(p.read_text())
        docs[p] = doc
        errors += [f'{p.relative_to(root)}: {issue}' for issue in doc.issues]
        errors += [f'{p.relative_to(root)}: duplicate ID {ident}' for ident in doc.duplicate_ids]
        if doc.tables != doc.captions:
            errors.append(f'{p.relative_to(root)}: table missing caption')
    if not docs:
        errors.append('No HTML pages found')
    def resolve(origin, link):
        url = urlsplit(link)
        if url.scheme or url.netloc:
            if publish:
                # Only configured GitHub repository URLs map to checkout files.
                repo = urlsplit(repository_url)
                if (url.scheme, url.netloc) == (repo.scheme, repo.netloc):
                    for kind in ('raw', 'blob', 'tree'):
                        if not url.path.startswith(f'{repo.path}/{kind}/'):
                            continue
                        prefix = f'{repo.path}/{kind}/{branch}/'
                        if not url.path.startswith(prefix):
                            errors.append(f'{origin.name}: GitHub link uses an unexpected branch')
                            break
                        path = unquote(url.path[len(prefix):])
                        target = (repository_root/path).resolve()
                        if not target.is_relative_to(repository_root):
                            errors.append(f'{origin.name}: GitHub link escapes repository')
                        elif not (target.is_dir() if kind == 'tree' else target.is_file()):
                            errors.append(f'{origin.name}: missing GitHub target')
                        break
            return
        path = unquote(url.path)
        if publish and path.startswith('/'):
            if origin != root/'404.html' or not path.startswith(subpath):
                errors.append(f'{origin.name}: root-absolute link outside 404 site sub-path')
                return
            path = path[len(subpath):]
            target = (root/path).resolve()
        else:
            target = (root/path.lstrip('/') if path.startswith('/') else origin.parent/path).resolve() if path else origin
        if publish and not target.is_relative_to(root):
            errors.append(f'{origin.name}: relative link escapes docs')
            return
        if not publish and not target.is_relative_to(root.parent):
            errors.append(f'{origin.name}: link escapes repository')
            return
        if target.is_dir():
            target /= 'index.html'
        if not target.is_file():
            errors.append(f'{origin.name}: missing {path}')
        elif url.fragment and target in docs and unquote(url.fragment) not in docs[target].ids:
            errors.append(f'{origin.name}: missing fragment {url.fragment}')
    for p, doc in docs.items():
        for link in doc.links:
            resolve(p, link)
    for p in root.rglob('*.css'):
        for link in re.findall(r'url\([\s\'"]*([^\)\'"\s]+)', p.read_text()):
            resolve(p, link)
    instances = root/'data/instances.json'
    if instances.exists():
        d = json.loads(instances.read_text())
        for instance, repo_idx, statuses, available in d['rows']:
            if len(statuses) != len(d['models']) or len(available) != len(d['models']):
                errors.append('Invalid compact instance row')
                continue
            for model, present in zip(d['models'], available):
                if present:
                    repo = d['repos'][repo_idx].replace('/', '__')
                    path = f'evidence/models/{model}/attempts/{repo}/{instance}.json.gz'
                    link = f'{repository_url}/raw/{branch}/{quote(path, safe="/")}' if publish else '../'+path
                    resolve(root/'instances.html', link)
    return errors, len(docs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', nargs='?', type=Path, default=Path('docs'))
    parser.add_argument('--publish', action='store_true', help='Validate GitHub targets locally and reject links outside the Pages root')
    parser.add_argument('--repository-root', type=Path, default=ROOT, help='Checkout containing partners config and evidence')
    args = parser.parse_args()
    errors, pages = check(args.directory, publish=args.publish, repository_root=args.repository_root)
    if errors:
        # Do not print arbitrary URLs/source content from an unsafe document.
        print(f'Link/static HTML check failed: {len(errors)} errors. First affected file: {errors[0].split(":")[0]}', file=sys.stderr)
        return 1
    print(f'Checked {pages} HTML pages, local assets, fragments and available evidence links: passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
