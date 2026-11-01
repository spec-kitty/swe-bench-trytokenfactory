#!/usr/bin/env python3
"""Build an offline, deterministic publication from validated report exports.

Never imports/runs source project scripts or writes to the source tree. A limit
samples trajectory metrics per model only; scores always use the complete export.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import html
from html.parser import HTMLParser
import io
import inspect
import json
import math
import posixpath
from pathlib import Path
import re
import sqlite3
import statistics
from string import Template
import subprocess
import sys
from urllib.parse import quote, unquote, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent
STATUSES = ('resolved', 'unresolved', 'ungraded', 'missing')
CONFIDENCE = 0.95
REQUIRED = [
    'configs/experiment.json', 'configs/protocol.json', 'configs/request-nonce.json',
    'PUBLICATION.md', 'STATUS.md', 'README.md',
    'artifacts/report/summary.json', 'artifacts/report/instances.csv',
    'artifacts/report/subsets.json', 'artifacts/report/repositories.json',
    'artifacts/report/generation-outcomes.json', 'artifacts/report/grading-amendments.json',
    'artifacts/report/timeout-adjudications.json', 'artifacts/report/test-timeout-reviews.json',
    'artifacts/report/model-pauses.json', 'artifacts/report/transport-amendments.json',
    'artifacts/official-comparison.json', 'artifacts/leaderboards.json',
    'artifacts/datasets/agent-input.jsonl', 'artifacts/datasets/SWE-bench_Verified.jsonl',
    'artifacts/datasets/SWE-bench_Lite.jsonl',
    'scripts/report.py', 'scripts/subsets.py', 'scripts/render_report.py',
    'artifacts/fleet.json', 'artifacts/upgrade-v2.json', 'artifacts/telemetry-history.jsonl',
    'scripts/fleet.py', 'scripts/upgrade_fleet.py', 'scripts/bootstrap.sh',
    'scripts/run_job.py', 'scripts/worker_v2.py',
]
TEXT_EXTENSIONS = frozenset(('.html', '.json', '.csv', '.js', '.css', '.txt'))
COMMERCIAL_LANGUAGE = re.compile(
    r'\$\s*\d|(?<![A-Za-z0-9])(?:pricing|price|prices|billing|invoice|tier|quota|'
    r'allowance|credit|credits|subscription|per-token|cost|costs|costly|free)(?![A-Za-z0-9])', re.I)
JOINT_PROJECT = 'A joint project. Every score here is computed from the public evidence in this repository.'
HEADLINE = 'Testing the latest open-weight models against SWE-bench'
ECHARTS_PATH = 'assets/vendor/echarts/echarts.min.js'


def publication_guard(content, name='output'):
    if name == ECHARTS_PATH:
        raw = content.encode('utf-8') if isinstance(content, str) else content
        expected = read_json(ROOT/'vendor/echarts/VENDORED.json').get('sha256')
        if not expected or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Vendored chart library checksum mismatch')
        return
    text = content.decode('utf-8') if isinstance(content, bytes) else content
    if COMMERCIAL_LANGUAGE.search(html.unescape(text)):
        raise ValueError('Publication language guard rejected a text file; content withheld')


def guard_docs(root):
    """Include stale and unowned text files, not just this build's manifest."""
    for path in sorted(Path(root).rglob('*')):
        if path.is_file() and path.suffix.lower() in TEXT_EXTENSIONS:
            raw = path.read_bytes()
            safe_bytes(raw)
            publication_guard(raw, path.relative_to(root).as_posix())
            if path.suffix.lower() == '.json':
                value = json.loads(raw)
                if public_data(value) != value:
                    raise ValueError('Publication data contains excluded fields; content withheld')


def public_data(value):
    """Drop financial fields recursively; reject other prohibited output text."""
    if isinstance(value, dict):
        for key in value:
            if 'cost' not in key.lower():
                publication_guard(key)
        return {k: public_data(v) for k, v in value.items() if 'cost' not in k.lower()}
    if isinstance(value, list):
        return [public_data(v) for v in value]
    if isinstance(value, str):
        publication_guard(value)
    return value


def load_partners(path, model_count):
    config = read_json(path)
    partners = config['partners']
    if [p['name'] for p in partners] != ['Spec Kitty', 'TokenFactory', 'exe.dev']:
        raise ValueError('Partner names or order changed')
    result = []
    for partner in partners:
        url = urlsplit(partner['url'])
        if url.scheme != 'https' or not url.hostname or url.username or url.password:
            raise ValueError('Partner links must be public HTTPS URLs')
        item = dict(partner, role=partner['role'].format(model_count=number(model_count)))
        safe_bytes(json_text(item).encode())
        publication_guard(json_text(item))
        result.append(item)
    return result


def infrastructure_facts(source, data):
    fleet = read_json(source/'artifacts/fleet.json')
    upgrades = read_json(source/'artifacts/upgrade-v2.json')
    if not fleet or set(fleet) != set(upgrades) or any(v != 'upgraded' for v in upgrades.values()):
        raise ValueError('Fleet upgrade evidence is incomplete')
    parse = lambda t: datetime.fromisoformat(t.replace('Z', '+00:00'))
    created = [parse(v['created_at']) for v in fleet.values()]
    observations = []
    for line in (source/'artifacts/telemetry-history.jsonl').read_text().splitlines():
        row = json.loads(line)
        if any(data['experiment']['experiment'] in w.get('experiments', [])
               for w in row['workers'].values() if isinstance(w, dict)):
            observations.append(parse(row['observed_at']))
    if not observations:
        raise ValueError('No telemetry explicitly identifies the clean experiment')
    fleet_script = (source/'scripts/fleet.py').read_text()
    upgrade_script = (source/'scripts/upgrade_fleet.py').read_text()
    def setting(pattern, text):
        values = set(re.findall(pattern, text))
        if len(values) != 1:
            raise ValueError('Infrastructure source setting is missing or ambiguous')
        return int(values.pop())
    slots = setting(r'--parallel (\d+)', upgrade_script)
    return dict(workers=len(fleet), slots=len(fleet)*slots, models=len(data['models']),
                tasks=len(data['tasks']), attempts=data['experiment']['expected_attempts'],
                provision_seconds=int((max(created)-min(created)).total_seconds()),
                provision_first=min(created).isoformat(), provision_last=max(created).isoformat(),
                observed_first=min(observations).isoformat(), observed_last=max(observations).isoformat(),
                observed_hours=(max(observations)-min(observations)).total_seconds()/3600,
                initial_cpus=setting(r'--cpu=(\d+)', fleet_script),
                initial_memory=setting(r'--memory=(\d+)GB', fleet_script),
                upgraded_cpus=setting(r'--cpu=(\d+)', upgrade_script),
                upgraded_memory=setting(r'--memory=(\d+)GB', upgrade_script),
                tagged_workers=sum(bool(vm.get('tags')) for vm in fleet.values()))
# Literal fragments kept separate so source code itself never contains credentials.
FORBIDDEN = tuple(x.encode() for x in ('Bear' + 'er', 'TF_' + 'API_KEY', 's' + 'k-', 'exe-' + 'integration'))
DESIGN_CLASSES = frozenset(re.findall(rb'\.((?:sk-)[a-z0-9-]+)',
    (ROOT/'vendor/design-system/components/bundle.css').read_bytes()))
DESIGN_CLASS_PATTERN = re.compile(rb'(?<![A-Za-z0-9_-])(?:' +
    b'|'.join(re.escape(c) for c in sorted(DESIGN_CLASSES, key=len, reverse=True)) + rb')(?![A-Za-z0-9_-])')


def safe_bytes(data: bytes, name: str = 'output') -> None:
    # The component CSS uses the innocuous sk- namespace. The credential marker
    # must be distinguished from those public design-system class/asset names.
    scrubbed = DESIGN_CLASS_PATTERN.sub(b'', data)
    for marker in FORBIDDEN:
        if (re.search(rb'(?<![A-Za-z0-9])' + re.escape(marker), scrubbed, re.I) if marker == b's' + b'k-' else marker.lower() in scrubbed.lower()):
            raise ValueError(f'Forbidden credential marker in {name}; content withheld')


def slug(value: str) -> str:
    result = re.sub(r'[^a-z0-9]+', '-', value.lower()).strip('-')
    if not result:
        raise ValueError('Empty slug')
    return result


def repo_slug(repo: str) -> str:
    # SWE-bench's repo portion of instance_id, also the packer layout contract.
    return repo.replace('/', '__')


def wilson(resolved: int, graded: int, confidence: float = CONFIDENCE):
    if graded < 0 or not 0 <= resolved <= graded or not 0 < confidence < 1:
        raise ValueError('Invalid Wilson inputs')
    if not graded:
        return None
    z = statistics.NormalDist().inv_cdf((1 + confidence) / 2)
    p = resolved / graded
    denom = 1 + z*z / graded
    center = (p + z*z/(2*graded)) / denom
    half = z * math.sqrt(p*(1-p)/graded + z*z/(4*graded*graded)) / denom
    return max(0, center-half), min(1, center+half)


def mcnemar_exact(only_a: int, only_b: int) -> float:
    if any(not isinstance(v, int) or v < 0 for v in (only_a, only_b)):
        raise ValueError('Discordant counts must be nonnegative integers')
    n = only_a + only_b
    if not n:
        return 1.0
    # Integer binomial coefficients avoid factorial overflow and tail underflow.
    term = total = 1
    for k in range(1, min(only_a, only_b) + 1):
        term = term * (n-k+1) // k
        total += term
    return min(1.0, (2*total) / (1 << n))


def count_statuses(statuses):
    counts = dict.fromkeys(STATUSES, 0)
    for status in statuses:
        if status not in counts:
            raise ValueError('Unknown report status')
        counts[status] += 1
    total = sum(counts.values())
    graded = counts['resolved'] + counts['unresolved']
    return dict(counts, total=total, graded=graded,
                complete=total > 0 and graded == total,
                score=counts['resolved']/graded if graded else None,
                coverage=graded/total if total else 0,
                wilson=wilson(counts['resolved'], graded))


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_sources(source):
    missing = [p for p in REQUIRED if not (source/p).is_file()]
    if not (source/'artifacts/fleet-backups').is_dir():
        missing.append('artifacts/fleet-backups')
    if missing:
        raise ValueError('Missing required data files: ' + ', '.join(missing))


class FrozenFile:
    """Path-like reader for a report captured in memory, never copied to disk."""
    def __init__(self, raw):
        self.raw = raw

    def read_bytes(self):
        return self.raw

    def read_text(self, encoding='utf-8'):
        return self.raw.decode(encoding)

    def open(self, mode='r'):
        if mode != 'r':
            raise ValueError('Snapshot files are read-only')
        return io.StringIO(self.read_text())

    def is_file(self):
        return True


class FrozenSource:
    def __init__(self, root):
        self.root = root
        self.files = {p: (root/p).read_bytes() for p in REQUIRED}
        self.epoch = max((root/p).stat().st_mtime for p in REQUIRED if p.startswith('artifacts/report/'))
        self.fingerprints = {p: hashlib.sha256(raw).hexdigest() for p, raw in self.files.items()}
        if self.fingerprints != {p: digest(root/p) for p in REQUIRED}:
            raise ValueError('Source reports changed while capturing the checkpoint; rerun')

    def __truediv__(self, relative):
        key = str(relative)
        return FrozenFile(self.files[key]) if key in self.files else self.root/relative


def load_data(source):
    require_sources(source)
    experiment = read_json(source/'configs/experiment.json')
    models = experiment['models']
    if len(models) != len(set(models)) or len({slug(m) for m in models}) != len(models):
        raise ValueError('Duplicate model or slug collision')
    if any('/' in m or m in ('.', '..') for m in models):
        raise ValueError('Unsafe model ID')
    tasks, task_titles = {}, {}
    for line in (source/'artifacts/datasets/agent-input.jsonl').read_text().splitlines():
        item = json.loads(line)
        if item['instance_id'] in tasks:
            raise ValueError('Duplicate dataset ID')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', item['instance_id']):
            raise ValueError('Unsafe instance ID')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', item['repo']) or '..' in item['repo'].split('/'):
            raise ValueError('Unsafe repository ID')
        tasks[item['instance_id']] = item['repo']
        task_titles[item['instance_id']] = issue_first_line(item.get('problem_statement', ''))
    subsets = {'Full': set(tasks)}
    for name in ('Verified', 'Lite'):
        subsets[name] = {json.loads(line)['instance_id'] for line in
                         (source/f'artifacts/datasets/SWE-bench_{name}.jsonl').read_text().splitlines()}
        if not subsets[name] <= tasks.keys():
            raise ValueError('Subset contains unknown tasks')
    statuses = {m: {} for m in models}
    with (source/'artifacts/report/instances.csv').open() as f:
        for row in csv.DictReader(f):
            m, i, status = row['model'], row['instance_id'], row['status']
            if m not in statuses or i not in tasks or status not in STATUSES or i in statuses[m]:
                raise ValueError('Invalid or duplicate report row')
            statuses[m][i] = status
    if any(set(rows) != set(tasks) for rows in statuses.values()):
        raise ValueError('Report is not a complete model/task matrix')
    if experiment['expected_instances'] != len(tasks) or experiment['expected_attempts'] != len(tasks)*len(models):
        raise ValueError('Experiment denominators disagree with dataset')
    summary = read_json(source/'artifacts/report/summary.json')
    if {r['model'] for r in summary} != set(models) or len(summary) != len(models):
        raise ValueError('Summary models disagree')
    boards = {'Full': {}}
    for row in summary:
        counts = count_statuses(statuses[row['model']].values())
        if any(row[k] != counts[k] for k in (*STATUSES, 'total', 'graded', 'complete')):
            raise ValueError('Summary disagrees with instances; refresh source reports')
        boards['Full'][row['model']] = counts
    outcomes = read_json(source/'artifacts/report/generation-outcomes.json')
    for m in models:
        if sum(outcomes.get(m, {}).values()) != sum(s != 'missing' for s in statuses[m].values()):
            raise ValueError('Generation report counts disagree with instance checkpoint')
    subrows = read_json(source/'artifacts/report/subsets.json')
    if len(subrows) != (len(subsets)-1)*len(models):
        raise ValueError('Incomplete subset report')
    for name in ('Verified', 'Lite'):
        boards[name] = {}
        for row in subrows:
            if row['subset'] != f'SWE-bench_{name}':
                continue
            m = row['model']
            if m not in models or m in boards[name]:
                raise ValueError('Invalid subset model')
            counts = count_statuses(statuses[m][i] for i in subsets[name])
            if name == 'Lite':
                if any(counts[k] != row[k] for k in (*STATUSES, 'total', 'graded')):
                    raise ValueError('Lite report disagrees with Full')
            else:
                # subsets.py is authoritative for the supplemental Verified
                # contract. Only its single named task may differ from Full.
                special = 'astropy__astropy-7606'
                possible = []
                for verdict in STATUSES if special in subsets[name] else (None,):
                    candidate = count_statuses(verdict if i == special else statuses[m][i]
                                               for i in subsets[name])
                    possible.append(candidate)
                matches = [c for c in possible if all(c[k] == row[k] for k in (*STATUSES, 'total', 'graded'))]
                if not matches:
                    raise ValueError('Verified report differs beyond supplemental contract')
                counts = matches[0]
            boards[name][m] = counts
        if set(boards[name]) != set(models):
            raise ValueError('Missing subset model')
    repos = sorted(set(tasks.values()))
    repository_counts = {m: {r: count_statuses(statuses[m][i] for i in tasks if tasks[i] == r)
                            for r in repos} for m in models}
    rep_rows = read_json(source/'artifacts/report/repositories.json')
    if len(rep_rows) != len(models)*len(repos) or len({(r['model'], r['repo']) for r in rep_rows}) != len(rep_rows):
        raise ValueError('Invalid repository report')
    for row in rep_rows:
        c = repository_counts[row['model']][row['repo']]
        if any(c[k] != row[k] for k in (*STATUSES, 'total')):
            raise ValueError('Repository report disagrees')
    return dict(experiment=experiment, models=models, tasks=tasks, task_titles=task_titles, subsets=subsets,
                statuses=statuses, boards=boards, repos=repos, repository_counts=repository_counts)


def trajectory_metrics(data):
    info = data.get('info', {})
    calls = info.get('model_stats', {}).get('api_calls')
    if not isinstance(calls, (int, float)) or calls < 0:
        calls = None
    sums = Counter()
    observed = Counter()
    response_count = 0
    for message in data.get('messages', []):
        if message.get('role') != 'assistant':
            continue
        response_count += 1
        usage = (message.get('extra') or {}).get('response', {}).get('usage') or {}
        for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
            value = usage.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
                sums[key] += value
                observed[key] += 1
    return {'steps': calls, 'mini_version': info.get('mini_version'),
            'responses': response_count,
            **{key: sums[key] if observed[key] else None for key in
               ('prompt_tokens', 'completion_tokens', 'total_tokens')},
            'usage_responses': dict(observed)}


def distribution(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return {'n': 0, 'median': None, 'min': None, 'max': None, 'bins': []}
    lo, hi = min(values), max(values)
    n_bins = min(10, max(1, math.ceil(math.sqrt(len(values))))) if hi > lo else 1
    width = (hi-lo)/n_bins if hi > lo else 1
    bins = [0]*n_bins
    for v in values:
        bins[min(n_bins-1, int((v-lo)/width))] += 1
    return dict(n=len(values), median=statistics.median(values), min=lo, max=hi,
                bins=[[lo+i*width, min(hi, lo+(i+1)*width), count] for i, count in enumerate(bins)])


def atomic_write(path, content):
    data = content.encode('utf-8') if isinstance(content, str) else content
    safe_bytes(data, path.name)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Symlink in output path')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == data:
        return
    temp = path.with_name(path.name + '.tmp')
    temp.write_bytes(data)
    temp.replace(path)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n'


def collect_metrics(source, data, cache_path, limit):
    if any(p.is_symlink() for p in (cache_path, *cache_path.parents)):
        raise ValueError('Symlink in cache path')
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cache_path)
    conn.execute('CREATE TABLE IF NOT EXISTS metrics (path TEXT PRIMARY KEY, signature TEXT, value TEXT)')
    # Cache semantics depend on extraction, not changes to HTML prose/layout.
    tool_hash = hashlib.sha256(inspect.getsource(trajectory_metrics).encode()).hexdigest() + ':outcomes-v1'
    attempts = {m: {} for m in data['models']}
    root = source/'artifacts/fleet-backups'
    for worker in sorted(root.iterdir()):
        for model in data['models']:
            parent = worker/'runs/v2'/model
            if not parent.is_dir():
                continue
            for p in sorted(parent.iterdir()):
                if p.name not in data['tasks'] or not p.is_dir():
                    continue
                if data['statuses'][model][p.name] == 'missing':
                    continue
                if p.name in attempts[model]:
                    raise ValueError('Duplicate active attempt')
                attempts[model][p.name] = p
    all_metrics = {}
    for model in data['models']:
        records = {}
        sampled = 0
        for instance, p in sorted(attempts[model].items()):
            traj = p/'trajectory.json'
            include_traj = traj.is_file() and (limit is None or sampled < limit)
            if include_traj:
                sampled += 1
            names = ['result.json', 'grade.json'] + (['trajectory.json'] if include_traj else [])
            sig = [tool_hash]
            raw = {}
            for name in names:
                f = p/name
                raw[name] = f.read_bytes() if f.exists() else None
                sig.append((name, hashlib.sha256(raw[name]).hexdigest() if raw[name] is not None else None))
            key = str(p) + ('/usage' if include_traj else '/outcome')
            signature = json_text(sig)
            row = conn.execute('SELECT signature,value FROM metrics WHERE path=?', (key,)).fetchone()
            if row and row[0] == signature:
                record = json.loads(row[1])
            else:
                result = json.loads(raw['result.json']) if raw['result.json'] else {}
                grade = json.loads(raw['grade.json']) if raw['grade.json'] else {}
                record = {'exit_status': result.get('exit_status'), 'grade_reason': grade.get('reason')}
                if include_traj:
                    record['usage'] = trajectory_metrics(json.loads(raw['trajectory.json']))
                encoded = json_text(record)
                safe_bytes(encoded.encode(), 'metric cache')
                conn.execute('INSERT OR REPLACE INTO metrics VALUES (?,?,?)', (key, signature, encoded))
            record['prediction_exists'] = (p/'prediction.json').is_file()
            records[instance] = record
            if len(records) % 100 == 0:
                conn.commit()
        conn.commit()
        all_metrics[model] = records
        print(f'Metrics: {model}: {len(records)} attempts; {sampled} trajectories', flush=True)
    conn.close()
    expected_outcomes = read_json(source/'artifacts/report/generation-outcomes.json')
    for model, records in all_metrics.items():
        if set(records) != {i for i, s in data['statuses'][model].items() if s != 'missing'}:
            raise ValueError('Collected evidence is missing reported attempts')
        observed = dict(Counter(r['exit_status'] for r in records.values() if r['exit_status']))
        if observed != expected_outcomes[model]:
            raise ValueError('Generation outcomes disagree with source report; refresh source exports')
    return all_metrics


E = lambda s: html.escape(str(s), quote=True)


def percent(value):
    if value is None:
        return 'Unavailable'
    digits = 2
    while value < 1 and round(100*value, digits) == 100 and digits < 15:
        digits += 1
    return f'{100*value:.{digits}f}%'


def number(value):
    if value is None:
        return 'Unavailable'
    return f'{value:,.1f}'.removesuffix('.0')


def badge(complete):
    return f'<span class="sk-badge sk-badge-{"success" if complete else "warning"}">{"Final" if complete else "Provisional"}</span>'


def table(caption, headings, rows, sortable=False):
    ths = ''.join(f'<th scope="col" aria-sort="none"><button class="sort" type="button" data-column="{i}">{E(h)}</button></th>'
                  if sortable else f'<th scope="col">{E(h)}</th>' for i, h in enumerate(headings))
    return (f'<div class="table-scroll" tabindex="0" role="region" aria-label="{E(caption)}">'
            f'<table{" data-sortable" if sortable else ""}><caption>{E(caption)}</caption>'
            f'<thead><tr>{ths}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def cells(values):
    return '<tr>' + ''.join(f'<th scope="row">{v}</th>' if i == 0 else f'<td>{v}</td>' for i, v in enumerate(values)) + '</tr>'


def score_bar(counts):
    score = counts['score']
    if score is None:
        return 'Awaiting grading'
    lo, hi = counts['wilson']
    label = f'{percent(score)}; Wilson {CONFIDENCE*100:g}% interval {percent(lo)} to {percent(hi)}'
    return (f'<span class="score-value">{percent(score)}</span><svg class="score-bar" viewBox="0 0 200 22" role="img" aria-label="{E(label)}">'
            f'<rect width="200" height="10" y="6" fill="var(--surface-sunk)"/>'
            f'<rect width="{score*200:.3f}" height="10" y="6" fill="var(--model-color, var(--ink-muted))"/>'
            f'<path d="M {lo*200:.3f} 11 H {hi*200:.3f} M {lo*200:.3f} 3 V 19 M {hi*200:.3f} 3 V 19" stroke="var(--ink)" fill="none"/>'
            f'</svg><small>{percent(lo)}–{percent(hi)}</small>')


class PublishLinks(HTMLParser):
    """Rewrite only URL attributes, preserving prose, examples and HTML bytes."""
    def __init__(self, content, rewrite):
        super().__init__(convert_charrefs=False)
        self.rewrite = rewrite
        self.offsets = [0]
        for line in content.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.edits = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()
        def replace(match):
            value = html.unescape(match[3])
            return match[1] + match[2] + html.escape(self.rewrite(value), quote=True) + match[2]
        updated = re.sub(r'''(\s(?:href|src|data-source)\s*=\s*)(["'])(.*?)\2''',
                         replace, raw, flags=re.I | re.S)
        if updated != raw:
            line, col = self.getpos()
            start = self.offsets[line-1] + col
            self.edits.append((start, start + len(raw), updated))

    handle_startendtag = handle_starttag

    def apply(self, content):
        for start, end, updated in reversed(self.edits):
            content = content[:start] + updated + content[end:]
        return content


class Site:
    def __init__(self, source, out, data, generated, commit, limit, publish=False, staging=False):
        self.source, self.out, self.data = source, out, data
        self.generated, self.commit, self.limit = generated, commit, limit
        self.files = set()
        self.publish, self.staging = publish, staging
        self.config = read_json(ROOT/'tools/partners.json')
        self.partners = load_partners(ROOT/'tools/partners.json', len(data.get('models', [])))

    def repository_link(self, path):
        folder = path.endswith('/') or (ROOT/path).is_dir()
        kind = 'tree' if folder else 'raw' if path.startswith('evidence/') and not path.endswith('.md') else 'blob'
        return (self.config['repository_url'].rstrip('/') + '/' + kind + '/' +
                quote(self.config['branch'], safe='') + '/' + quote(path, safe='/'))

    def publish_link(self, relative, link):
        url = urlsplit(link)
        if url.scheme or url.netloc or not url.path:
            return link
        path = unquote(url.path)
        if path.startswith('/'):
            raise ValueError('Root-absolute URL in publication template')
        # Resolve against a virtual checkout, independent of --output location.
        target = posixpath.normpath(posixpath.join('docs', posixpath.dirname(relative), path))
        if target == '..' or target.startswith('../'):
            raise ValueError('Publication link escapes repository')
        if target != 'docs' and not target.startswith('docs/'):
            target += '/' if path.endswith('/') else ''
            base = urlsplit(self.repository_link(target))
            return urlunsplit(base._replace(query=url.query, fragment=url.fragment))
        if relative == '404.html':
            subpath = urlsplit(self.config['site_url']).path.rstrip('/') + '/'
            path = subpath + (target[5:] if target.startswith('docs/') else '')
            return urlunsplit(url._replace(path=quote(path, safe='/')))
        return link

    def write(self, relative, content):
        if Path(relative).suffix.lower() == '.html':
            if self.publish:
                content = PublishLinks(content, lambda link: self.publish_link(relative, link)).apply(content)
            # Heading-only markup leaves metadata and accessible text unchanged.
            content = re.sub(r'(<h[1-6]\b[^>]*>)(.*?)(</h[1-6]>)',
                             lambda m: m[1]+m[2].replace('SWE-bench', '<span class="nowrap">SWE-bench</span>')+m[3],
                             content, flags=re.S)
        if Path(relative).suffix.lower() in TEXT_EXTENSIONS:
            publication_guard(content, relative)
        self.files.add(relative)
        atomic_write(self.out/relative, content)

    def json(self, relative, value):
        self.write(relative, json_text(public_data(value)))

    def partner_link(self, partner, content=None):
        return f'<a href="{E(partner["url"])}" target="_blank" rel="noopener">{content or E(partner["name"])}</a>'

    def evidence_path(self, model, instance):
        repo = self.data['tasks'][instance]
        return f'evidence/models/{model}/attempts/{repo_slug(repo)}/{instance}.json.gz'

    def evidence_link(self, model, instance, prefix):
        path = self.evidence_path(model, instance)
        if (ROOT/path).is_file():
            return f'<a href="{E(prefix + path)}" data-repo-file="{E(path)}">{E(instance)}</a>'
        return f'<span>{E(instance)} <small>Evidence not packaged</small></span>'

    def page(self, relative, title, body):
        prefix = '../' * (len(Path(relative).parts) - 1)
        nav = [('index.html', 'Leaderboard'), ('compare.html', 'Compare'), ('instances.html', 'Tasks'),
               ('methodology.html', 'Methodology'), ('evidence.html', 'Evidence'),
               ('research.html', 'For researchers'), ('about.html', 'Who made this')]
        links = ''.join('<a href="'+prefix+p+'"'+(' aria-current="page"' if p == relative else '')+'>'+label+'</a>' for p, label in nav)
        metadata = '<meta name="robots" content="noindex,nofollow">' if self.staging else ''
        if self.publish:
            canonical = self.config['site_url'].rstrip('/') + '/' + quote(relative, safe='/')
            metadata += f'<link rel="canonical" href="{E(canonical)}"><meta property="og:url" content="{E(canonical)}">'
        evidence_base = (self.config['repository_url'].rstrip('/') + '/raw/' +
                         quote(self.config['branch'], safe='') + '/') if self.publish else ''
        names = ' with '.join([self.partners[0]['name'], ' and '.join(p['name'] for p in self.partners[1:])])
        description = f'{names}. Single-attempt SWE-bench results, with coverage and evidence.'
        card_title = f'{title} · {names}'
        mark = (f'<span class="partner-mark" aria-hidden="true"><img class="mark-day" src="{prefix}assets/design-system/kitty-mark.svg" width="32" height="32" alt="">'
                f'<img class="mark-night" src="{prefix}assets/design-system/kitty-mark-night.svg" width="32" height="32" alt=""></span>')
        strip = (self.partner_link(self.partners[0], mark + '<span class="product-dot" aria-hidden="true"></span>Spec Kitty') +
                 '<span>with</span>' + self.partner_link(self.partners[1]) + '<span>and</span>' + self.partner_link(self.partners[2]))
        footer = ''.join(f'<section><h2>{self.partner_link(p)}</h2><p>{"We" if i == 0 else E(p["name"])} {E(p["role"])}</p></section>' for i, p in enumerate(self.partners))
        chart_scripts = ('<script src="assets/vendor/echarts/echarts.min.js" defer></script>'
                         '<script src="assets/charts.js" defer></script>') if relative == 'index.html' else ''
        if relative.startswith('models/'):
            chart_scripts = '<script src="../assets/charts.js" defer></script>'
        source_link = f'<a href="{E(self.config["repository_url"])}">Source repository</a>'
        if relative == 'research.html':
            # Keep the local research page's source link in the checkout.
            source_link = ('<a href="../README.md" data-repo-file="README.md">Source repository</a>'
                           if (ROOT/'README.md').is_file() else 'Source repository')
        licence = (f'<p>MIT licensed. <a href="{E(self.config["repository_url"])}">Source and evidence on GitHub.</a></p>'
                   if self.publish and (ROOT/'LICENSE').is_file() else '')
        self.write(relative, f'''<!doctype html>
<html lang="en" data-evidence-base="{E(evidence_base)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)} · Spec Kitty benchmarks</title>
{metadata}
<meta name="description" content="{E(description)}">
<meta property="og:title" content="{E(card_title)}"><meta property="og:description" content="{E(description)}"><meta property="og:type" content="website">
<meta name="twitter:card" content="summary"><meta name="twitter:title" content="{E(card_title)}"><meta name="twitter:description" content="{E(description)}">
<link rel="icon" href="{prefix}assets/design-system/spectacles.svg" type="image/svg+xml">
<link rel="stylesheet" href="{prefix}assets/design-system/tokens.css"><link rel="stylesheet" href="{prefix}assets/design-system/bundle.css">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500&amp;family=IBM+Plex+Sans:wght@400;500;600;700&amp;family=IBM+Plex+Mono:wght@400;500&amp;display=swap">
<link rel="stylesheet" href="{prefix}assets/site.css"><script src="{prefix}assets/theme.js"></script>
<script src="{prefix}assets/site.js" defer></script>{chart_scripts}</head><body>
<a class="skip" href="#main">Skip to results</a><div class="shell"><header>
<div class="partner-strip" aria-label="Project partners">{strip}</div>
<a class="brand" href="{prefix}index.html">Benchmarks</a>
<button type="button" id="theme-toggle" class="sk-btn sk-btn-sm sk-btn-quiet">Change theme</button>
<nav aria-label="Main">{links}</nav></header><main id="main"><p class="eyebrow">TokenFactory · SWE-bench</p><h1>{E(title)}</h1>{body}</main>
<footer><div class="partner-footer">{footer}</div><p>{JOINT_PROJECT}</p>{licence}<p>Generated for source snapshot <time datetime="{E(self.generated)}">{E(self.generated)}</time>. Source commit <code>{E(self.commit)}</code>.</p>
<p>We share the evidence behind these scores so you can inspect this scaffold, gateway and protocol. <a href="{prefix}data/results.csv" download>Download results CSV</a> · <a href="{prefix}data/build-info.json">Build provenance</a> · {source_link}</p></footer></div></body></html>''')

    def assets(self):
        vendor = ROOT/'vendor/design-system'
        tokens = read_json(vendor/'tokens.json')
        def val(v):
            return re.sub(r'\{([^}]+)\}', r'var(--\1)', v)
        common = [f'--font-{k}:{v}' for k, v in tokens['type']['families'].items()]
        for section in ('spacing', 'radius'):
            common += [f'--{t["name"]}:{t["value"]}' for t in tokens[section]['tokens']]
        def theme(name):
            return ';'.join(f'--{t["name"]}:{val(t["value"][name])}' for section in ('color', 'shadow') for t in tokens[section]['tokens'])
        css = ':root{'+';'.join(common)+';'+theme('light')+';color-scheme:light}\n'
        css += '@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){'+theme('dark')+';color-scheme:dark}}\n'
        css += ':root[data-theme="dark"]{'+theme('dark')+';color-scheme:dark}\n'
        self.write('assets/design-system/tokens.css', css)
        for src, dest in [('tokens.json', 'tokens.json'), ('components/bundle.css', 'bundle.css'),
                          ('assets/Mascot/kitty-mark.svg', 'kitty-mark.svg'),
                          ('assets/Mascot/kitty-mark-night.svg', 'kitty-mark-night.svg'),
                          ('assets/Mascot/spectacles.svg', 'spectacles.svg')]:
            self.write('assets/design-system/'+dest, (vendor/src).read_bytes())
        for name in ('site.css', 'site.js', 'theme.js', 'charts.js'):
            self.write('assets/'+name, (ROOT/'tools/site_assets'/name).read_bytes())
        for name in ('echarts.min.js', 'LICENSE', 'NOTICE'):
            self.write('assets/vendor/echarts/'+name, (ROOT/'vendor/echarts'/name).read_bytes())
        self.write('assets/exe-dev-vm-list.webp', (ROOT/'tools/site_assets/exe-dev-vm-list.webp').read_bytes())


def usage_summary(records):
    usage = [r['usage'] for r in records.values() if 'usage' in r]
    return {k: distribution(u[k] for u in usage) for k in
            ('steps', 'prompt_tokens', 'completion_tokens', 'total_tokens')}


def solve_counts(data):
    """Full task counts, including tasks with pending verdicts, shared by pages."""
    return Counter(sum(data['statuses'][m][i] == 'resolved' for m in data['models'])
                   for i in data['tasks'])


def issue_first_line(text):
    """Public issue text only: no paraphrase, metadata or later lines."""
    return text.splitlines()[0].strip()[:110] if text else ''


def accumulation_orders(solved_sets, leaderboard_order):
    """Cumulative union; greedy ties use leaderboard score order, then stable model ID."""
    rank = {model: i for i, model in enumerate(leaderboard_order)}
    def steps(greedy):
        remaining, union, rows = set(leaderboard_order), set(), []
        while remaining:
            model = min(remaining, key=lambda m: (-len(solved_sets[m]-union) if greedy else 0, rank[m], m))
            added = len(solved_sets[model]-union)
            union.update(solved_sets[model])
            remaining.remove(model)
            rows.append(dict(model=model, models=len(rows)+1, new=added, solved=len(union)))
        return [dict(model=None, models=0, new=0, solved=0), *rows]
    return dict(score=steps(False), greedy=steps(True))


def attempt_basis(models, tasks):
    return f'Based on {number(models)} models x {number(tasks)} tasks = {number(models*tasks)} attempts.'


def glossary(data):
    models, tasks = len(data['models']), len(data['tasks'])
    return ('<section class="glossary" aria-labelledby="three-words"><h2 id="three-words">Three words we use</h2><dl>'
            f'<div><dt>Task</dt><dd>One problem in the benchmark, a real bug report from an open-source project. The benchmark has {number(tasks)} tasks.</dd></div>'
            f'<div><dt>Attempt</dt><dd>One model’s try at one task. {number(models)} models x {number(tasks)} tasks = {number(models*tasks)} attempts.</dd></div>'
            '<div><dt>Solved</dt><dd>The project’s own tests pass after the model’s patch.</dd></div></dl></section>')


def difficulty_data(data, order, provisional):
    models, total = len(order), len(data['tasks'])
    resolvers = {i: [m for m in order if data['statuses'][m][i] == 'resolved'] for i in data['tasks']}
    solved = Counter(len(ms) for ms in resolvers.values())
    hard, every = solved[0], solved[models]
    sets = {m: {i for i in data['tasks'] if data['statuses'][m][i] == 'resolved'} for m in order}
    orders = accumulation_orders(sets, order)
    union = total-hard
    best_model = max(order, key=lambda m: len(sets[m]))
    best = len(sets[best_model])
    percentage = lambda n: 100*n/total if total else 0
    prefix = 'Provisional: ' if provisional else ''
    title = f'All {models} models together solve {number(union)} of the {number(total)} tasks ({percentage(union):.1f}%)'
    caption = (f'Here is what happens when you combine the models. The best single model solves {number(best)} tasks. '
               f'Adding the other {models-1} brings in only {number(union-best)} more. '
               f'The remaining {number(hard)} tasks, {percentage(hard):.1f}% of the benchmark, were solved by no model.')
    note = (' Counts reflect tests graded so far. Pending or missing results may change these counts; '
            'a task with no recorded solution may still be solved.') if provisional else ''
    examples = []
    for count, label in [(0, 'Stumped every model'), (models, f'Solved by all {models} models')]:
        instance = next((i for i in sorted(resolvers) if len(resolvers[i]) == count), None)
        if instance:
            quote = data.get('task_titles', {}).get(instance, '')
            safe_bytes(quote.encode())
            examples.append(dict(label=prefix+label, instance_id=instance, repo=data['tasks'][instance], quote=quote,
                                 href=f'instances.html?task={instance}'))
    unique = Counter(ms[0] for ms in resolvers.values() if len(ms) == 1)
    return (dict(title=prefix+title, caption=caption+note, orders=orders, examples=examples,
                 union=union, never=hard, every=every, best=best, best_model=best_model,
                 first_label=f'{best_model} alone solves {number(best)} ({percentage(best):.0f}%)',
                 last_label=f'All {models} together solve {number(union)} ({percentage(union):.0f}%)',
                 never_label=f'{number(hard)} tasks, {percentage(hard):.0f}%, solved by no model'),
            dict(title=prefix+'Some models solve tasks no other model can',
                 caption=f'These are tasks where exactly one of the {models} models passed the tests. '
                         'They show where models differ, not just who scores higher.'+note,
                 rows=[dict(model=m, tasks=unique[m]) for m in order]))


def spearman(xs, ys):
    """Pearson correlation of average ranks, including ties; None if undefined."""
    if len(xs) != len(ys):
        raise ValueError('Rank series must have equal lengths')
    def ranks(values):
        ordered = sorted(values)
        return [1 + (ordered.index(v) + len(ordered)-1-ordered[::-1].index(v))/2 for v in values]
    if len(xs) < 2:
        return None
    x, y = ranks(xs), ranks(ys)
    mx, my = statistics.mean(x), statistics.mean(y)
    denominator = math.sqrt(sum((v-mx)**2 for v in x)*sum((v-my)**2 for v in y))
    return sum((a-mx)*(b-my) for a, b in zip(x, y))/denominator if denominator else None


def scatter_headline(rho):
    if rho is not None and rho <= -.3:
        return 'More steps did not mean better scores'
    if rho is not None and rho >= .3:
        return 'Models that took more steps scored higher'
    return 'There is no clear link between steps and score'


def outcome_headline(empty, timeouts):
    clauses = []
    if empty:
        clauses.append(f'{number(empty)} attempt{"s" if empty != 1 else ""} ended with no patch')
    if timeouts:
        clauses.append(f'{number(timeouts)}' + ('' if empty else f' attempt{"s" if timeouts != 1 else ""}') + ' ran out of time')
    return ', and '.join(clauses) if clauses else 'How every attempt ended'


def heatmap_headline(cells, descriptions):
    medians = [(statistics.median(values), repo) for repo in sorted({c['repo'] for c in cells})
               if (values := [r['score'] for r in cells if r['repo'] == repo and r['score'] is not None])]
    if not medians:
        return 'Repository scores await grading'
    score, repo = min(medians)
    short = repo.split('/')[-1]
    description = descriptions.get(short)
    clause = f', {description}' if description else ''
    total = next(c['total'] for c in cells if c['repo'] == repo)
    return f'The hardest project was {short}{clause}: the typical model solved {score:.2f}% of its {number(total)} tasks'


def family_note(models):
    light = sorted({m.split('-')[0] for m in models if 'flash' in m.split('-') and
                    any('flash' not in candidate.split('-') and re.sub(r'-(?:uncensored|abliterated)(?:-|$).*', '', candidate) == m.split('-flash')[0] for candidate in models)})
    names = {'glm': 'GLM', 'deepseek': 'DeepSeek', 'kimi': 'Kimi', 'minimax': 'MiniMax', 'nemotron': 'Nemotron'}
    note = ', '.join(names.get(f, f) for f in light)+' Flash routes use lighter fills. ' if light else ''
    if any(re.search(r'(?:^|-)(uncensored|abliterated)(?:-|$)', m) for m in models):
        note += 'Diagonal marks identify uncensored or abliterated variants.'
    return note.strip()


def chart_data(data, metrics, adjudications=(), limit=None):
    """Numeric chart contract. Scores and intervals reuse validated report boards.

    Outcome precedence: resolved, pending, adjudicated timeout, empty patch,
    remaining unresolved nonempty patch. Annotations never add attempts.
    Only the leaderboard switches subsets; all other panels describe Full.
    """
    def pct(value):
        return None if value is None else 100 * value

    leaderboards = {}
    for name, board in data['boards'].items():
        ordered = sorted(board, key=lambda m: (-(board[m]['score'] if board[m]['score'] is not None else -1), m))
        rows = [dict(model=m, rank=1+sum(c['score'] is not None and board[m]['score'] is not None
                                        and c['score'] > board[m]['score'] for c in board.values()),
                     resolved=board[m]['resolved'], graded=board[m]['graded'], total=board[m]['total'],
                     score=pct(board[m]['score']), coverage=pct(board[m]['coverage']),
                     interval=[pct(v) for v in board[m]['wilson']] if board[m]['wilson'] else None)
                for m in ordered]
        provisional = not all(c['complete'] for c in board.values())
        leaders = [r['model'] for r in rows if r['score'] is not None and r['score'] == rows[0]['score']]
        if not leaders:
            title = f'{name} scores await grading'
        else:
            subject = ', '.join(leaders)
            verb = 'leads' if len(leaders) == 1 else 'share the lead'
            title = f'{subject} {verb}, resolving {rows[0]["score"]:.2f}% of the {number(rows[0]["graded"])} {name} tasks' + (' graded so far' if provisional else '')
        leaderboards[name] = dict(rows=rows, title=('Provisional: ' if provisional else '')+title,
                                 attempts=sum(r['graded'] for r in rows), provisional=provisional)

    order = [r['model'] for r in leaderboards['Full']['rows']]
    full = data['boards']['Full']
    attempts = sum(c['total'] for c in full.values())
    graded = sum(c['graded'] for c in full.values())
    provisional = leaderboards['Full']['provisional']
    prefix = 'Provisional: ' if provisional else ''
    timeouts = set()
    for review in adjudications:
        record = review.get('original_queue', review)
        key = (record.get('model'), record.get('instance', record.get('instance_id')))
        if key[0] not in data['models'] or key[1] not in data['tasks']:
            raise ValueError('Timeout annotation does not identify an active model/task')
        timeouts.add(key)
    categories = [dict(key='resolved', label='Solved'),
                  dict(key='patch', label='Patch failed the tests'),
                  dict(key='empty', label='No patch submitted'),
                  dict(key='timeout', label='Ran out of time')]
    if provisional:
        categories.insert(1, dict(key='pending', label='Waiting to be graded'))
    outcomes = []
    for model in order:
        counts = dict.fromkeys([c['key'] for c in categories], 0)
        for instance, status in data['statuses'][model].items():
            record = metrics[model].get(instance, {})
            reason = record.get('grade_reason')
            if status == 'resolved':
                category = 'resolved'
            elif status in ('ungraded', 'missing'):
                category = 'pending'
            elif (model, instance) in timeouts or reason == 'reviewed_test_timeout':
                category = 'timeout'
            elif reason == 'empty_patch':
                category = 'empty'
            else:
                if instance not in metrics[model]:
                    raise ValueError('Missing outcome evidence for a graded attempt')
                category = 'patch'
            counts[category] += 1
        total = full[model]['total']
        outcomes.append(dict(model=model, total=total, counts=counts,
                             percentages={k: v/total*100 if total else 0 for k, v in counts.items()}))
    empty_total = sum(r['counts']['empty'] for r in outcomes)
    timeout_total = sum(r['counts']['timeout'] for r in outcomes)
    outcome_title = outcome_headline(empty_total, timeout_total)
    tasks = number(len(data['tasks']))
    outcome_caption = (f'All {tasks} tasks for every model. Colour shows how each attempt ended, not which model made it. '
                       'Each attempt is counted once, in the first group that fits: solved, still waiting to be graded, '
                       'ran out of time, no patch submitted, or a patch that failed the tests.')

    heatmap = []
    for model in order:
        for repo in data['repos']:
            c = data['repository_counts'][model][repo]
            heatmap.append(dict(model=model, repo=repo, score=pct(c['score']), resolved=c['resolved'],
                                total=c['total'], graded=c['graded']))
    descriptions = read_json(ROOT/'tools/projects.json')
    heat_title = heatmap_headline(heatmap, descriptions)
    projects = [dict(repo=r, description=descriptions.get(r.split('/')[-1], ''),
                     tasks=sum(repo == r for repo in data['tasks'].values())) for r in data['repos']]
    heat_caption = (f'Each row is a model and each column is one of the {len(projects)} open-source projects the tasks come from. '
                    "A cell shows the share of that project's tasks the model solved, and darker means more. Hover a cell for the exact counts.")
    if provisional:
        heat_caption += ' Some attempts are not yet graded and are left out.'

    solved = solve_counts(data)
    difficulty, unique = difficulty_data(data, order, provisional)

    points, omitted = [], []
    for model in order:
        steps = usage_summary(metrics[model])['steps']
        if steps['median'] is None or full[model]['score'] is None:
            omitted.append(model)
        else:
            points.append(dict(model=model, steps=steps['median'], samples=steps['n'],
                               score=pct(full[model]['score'])))
    reference = dict(steps=statistics.median(p['steps'] for p in points) if points else None,
                     score=statistics.median(p['score'] for p in points) if points else None)
    rho = spearman([p['steps'] for p in points], [p['score'] for p in points])
    scatter_title = scatter_headline(rho) if points else 'Step data is unavailable'
    scatter_caption = (f'Each dot is one model. Further left means it usually needed fewer steps per attempt; higher up means it solved more of the {tasks} tasks. '
                       'A step is one round trip: the model asks for a command, the tool runs it, and the output goes back.')
    evidence = ''
    if len(points) >= 2:
        best = sorted(points, key=lambda p: (-p['score'], p['model']))[:2]
        most = max(points, key=lambda p: (p['steps'], p['model']))
        evidence = (f'The two highest-scoring models took about {number(best[0]["steps"])} and {number(best[1]["steps"])} steps per attempt; '
                    f'the model that took the most steps ({number(most["steps"])}) solved {most["score"]:.2f}% of the {tasks} tasks.')
    outliers = [p for p in points if p['steps'] < reference['steps'] and p['score'] < reference['score'] and
                next(r for r in outcomes if r['model'] == p['model'])['percentages']['empty'] > 50]
    if outliers:
        outlier = min(outliers, key=lambda p: (p['score'], p['model']))
        share = next(r for r in outcomes if r['model'] == outlier['model'])['percentages']['empty']
        evidence += f' {outlier["model"]} took few steps but solved few tasks; most of its attempts ended with no patch ({share:.2f}% of its {tasks} attempts).'
    return dict(title=HEADLINE, model_order=order, model_count=len(order), task_count=len(data['tasks']),
                attempts=attempts, graded=graded, provisional=provisional, confidence=CONFIDENCE,
                leaderboards=leaderboards,
                family_note=family_note(order),
                outcomes=dict(title=prefix+outcome_title, caption=outcome_caption, rows=outcomes, categories=categories, attempts=attempts),
                heatmap=dict(title=prefix+heat_title, caption=heat_caption, cells=heatmap, repositories=data['repos'], projects=projects, attempts=graded),
                difficulty=difficulty, unique=unique,
                scatter=dict(title=prefix+scatter_title, points=points, omitted=omitted, reference=reference,
                             caption=scatter_caption, evidence=evidence.strip(), rho=rho,
                             attempts=sum(p['samples'] for p in points), usage_limit_per_model=limit))


OFFICIAL_FIELDS = ('name', 'agent', 'agent_org', 'model_display', 'model_org', 'os_model', 'resolved', 'date')
OFFICIAL_SUBSETS = {'Full': 'Test', 'Verified': 'Verified', 'Lite': 'Lite'}
OFFICIAL_CAUTION = ('Official entries use different agents, budgets, tools and attempt counts, and they are not run by us. '
                    'This is context, not a controlled comparison or an official submission.')


def official_attempts(tags):
    values = []
    for tag in tags:
        match = re.fullmatch(r'System: Attempts - (\d+)(\+?)', tag)
        if match:
            n = int(match[1])
            values.append('1' if n == 1 and not match[2] else '2+' if n >= 2 else 'unknown')
    return values[0] if values and len(set(values)) == 1 else 'unknown'


def official_jitter(entry_id):
    """Stable across processes, input order, filters and subsets; never Python hash()."""
    return (int(hashlib.sha256(entry_id.encode()).hexdigest()[:8], 16) / 0xffffffff - .5) * .24


def official_filter(entries, mask=0):
    return [r for r in entries if (not mask & 1 or r['mini'])
            and (not mask & 2 or r['os_model']) and (not mask & 4 or r['attempts'] == '1')]


def official_exact_matches(models, boards):
    matches = []
    for board in boards:
        for entry in board['results']:
            names = [entry.get('model_display', '')] + [tag[len('Model: '):] for tag in entry.get('tags', [])
                                                        if tag.casefold().startswith('model: ')]
            for model in models:
                if model.casefold() in {name.casefold() for name in names}:
                    matches.append(dict(model=model, subset=board['name'], id=entry['folder']))
    return sorted(matches, key=lambda r: (r['model'], r['subset'], r['id']))


def official_context(snapshot, comparison, boards, models):
    """Whitelist entry records; compute all AND-filter summaries from the same score boards."""
    selected = [b for b in snapshot['leaderboards'] if b['name'] in OFFICIAL_SUBSETS.values()]
    matches = official_exact_matches(models, selected)
    result = dict(subsets={}, exact_matches=matches)
    match_text = ('No official entry shares an exact model name with ours.' if not matches else
                  'Exact model-name matches in the official entries: '+', '.join(sorted({r['model'] for r in matches}))+'.')
    result['snapshot'] = (f'Snapshot of swebench.com retrieved {comparison["retrieved_at"][:10]} '
                          f'(commit {comparison["commit"][:7]}, sha256 {comparison["sha256"][:8]}). '+match_text)
    for name, source_name in OFFICIAL_SUBSETS.items():
        source_board, = [b for b in selected if b['name'] == source_name]
        entries = []
        for raw in source_board['results']:
            entry = {k: raw.get(k) for k in OFFICIAL_FIELDS}
            entry.update(id=raw['folder'], attempts=official_attempts(raw.get('tags', [])), mini=raw['agent'] == 'mini-SWE-agent')
            # Reject rather than silently omit an entry. Never echo unsafe text.
            try:
                safe_bytes(json_text(entry).encode())
                publication_guard(json_text(entry))
            except ValueError as exc:
                identity = f'{source_name}/{raw["folder"]} ({raw["name"]})'
                try:
                    safe_bytes(identity.encode())
                except ValueError:
                    identity = f'{source_name} entry sha256 {hashlib.sha256(json_text(raw).encode()).hexdigest()}'
                raise ValueError(f'Official entry rejected by publication guard: {identity}') from exc
            if type(entry['os_model']) is not bool or not isinstance(entry['resolved'], (int, float)) or not 0 <= entry['resolved'] <= 100:
                raise ValueError('Invalid official entry score or open-weight flag')
            entries.append(entry)
        entries.sort(key=lambda r: r['id'])
        if len({r['id'] for r in entries}) != len(entries):
            raise ValueError('Duplicate official entry id within subset')
        ours = [r['score'] for r in boards[name]['rows'] if r['score'] is not None]
        prefix = 'Provisional: ' if boards[name]['provisional'] else ''
        summaries = {}
        for mask in range(8):
            plotted = official_filter(entries, mask)
            scores = [r['resolved'] for r in plotted]
            median = statistics.median(scores) if scores else None
            task_count = boards[name]['rows'][0]['total']
            subset = 'the full test set' if name == 'Full' else f'SWE-bench {name} ({number(task_count)} tasks)'
            title = f'Where our {len(boards[name]["rows"])} models land among the {len(scores)} official entries for {subset}'
            caption = ('Each grey dot is one entry on the public SWE-bench leaderboard. '
                       f'Our models are the coloured dots below them. Scores show the share of {number(task_count)} tasks solved. ')
            caption += (f'Our scores run from {min(ours):.1f}% to {max(ours):.1f}%' if ours else
                        'Our results await grading')
            caption += (f'; the official entries run from {min(scores):.1f}% to {max(scores):.1f}%, '
                        f'with a middle value of {median:.1f}%.' if scores else
                        '; no official entries match these filters.')
            criteria = []
            if mask & 1: criteria.append('mini-SWE-agent')
            if mask & 2: criteria.append('an open-weight model')
            if mask & 4: criteria.append('a single attempt')
            usage = (' with ' if mask & 1 else ' and ').join(criteria[:2])
            if len(criteria) == 3: usage += ' and '+criteria[2]
            noun = 'entry' if len(scores) == 1 else 'entries'
            help_text = (f'Showing the {len(scores)} {noun} that used {usage}.' if criteria else
                         f'Showing all {len(scores)} official entries, with any agent, model or number of attempts.')
            above = sum(s > max(ours) for s in scores) if ours else None
            below = sum(s < min(ours) for s in scores) if ours else None
            footer = (f'{above} of {len(scores)} plotted entries score higher than our highest result; '
                      f'{below} of {len(scores)} score lower than our lowest result.' if ours else
                      'Counts relative to our results await grading.')
            summaries[str(mask)] = dict(count=len(scores), title=prefix+title, median=median, above=above, below=below,
                                        caption=prefix+caption, filter_help=help_text, footer=prefix+footer)
        result['subsets'][name] = dict(entries=entries, jitter={r['id']: official_jitter(r['id']) for r in entries},
                                       summaries=summaries, axis_max=min(100, max(10, math.ceil(max(ours+[r['resolved'] for r in entries]+[0])/10)*10)))
    return result


def official_section(context):
    tabs, panels = [], []
    for i, (name, board) in enumerate(context['subsets'].items()):
        tabs.append(f'<button type="button" class="sk-btn sk-btn-md sk-btn-quiet" role="tab" '
                    f'id="official-tab-{name}" aria-controls="official-panel-{name}" data-official-subset="{name}" '
                    f'aria-selected="{str(i == 0).lower()}" tabindex="{0 if i == 0 else -1}">{name}</button>')
        rows = [cells([E(r['name']), E(r['agent']), E(r['model_display']), f'{r["resolved"]:.2f}%', E(r['date']), E(r['attempts'])])
                for r in sorted(board['entries'], key=lambda r: (-r['resolved'], r['id']))]
        headings = ['Name', 'Agent', 'Model', 'Score', 'Date', 'Attempts']
        ths = ''.join('<th scope="col" aria-sort="descending"><button type="button" class="sort" data-official-sort="'+name+'">Score</button></th>'
                      if h == 'Score' else f'<th scope="col">{h}</th>' for h in headings)
        panels.append(f'<div id="official-panel-{name}" role="tabpanel" aria-labelledby="official-tab-{name}">'
                      f'<div class="table-scroll" tabindex="0" role="region" aria-label="{name} official entries">'
                      f'<table><caption>{name} official entries · All entries</caption><thead><tr>{ths}</tr></thead>'
                      f'<tbody id="official-rows-{name}">{"".join(rows)}</tbody>'
                      f'<tfoot><tr><td colspan="6" id="official-footer-{name}">{E(board["summaries"]["0"]["footer"])}</td></tr></tfoot></table></div></div>')
    summary = context['subsets']['Full']['summaries']['0']
    filters = ''.join(f'<button type="button" class="family-toggle" data-official-filter="{mask}" aria-pressed="{str(mask == 0).lower()}">{label}</button>'
                      for mask, label in [(0, 'All entries'), (1, 'mini-SWE-agent only'), (2, 'Open-weight models only'), (4, 'Single attempt only')])
    return ('<section class="sk-card chart-card" id="card-official"><p class="sk-card-eyebrow">Our results beside the official leaderboard</p>'
            f'<h2 class="sk-card-title" id="title-official" aria-live="polite">{E(summary["title"])}</h2>'
            f'<p class="chart-caption" id="official-caption">{E(summary["caption"])}</p>'
            '<div class="tabs chart-tabs" role="tablist" aria-label="Official comparison subset">'+''.join(tabs)+'</div>'
            '<div class="official-filters" role="group" aria-label="Filter official entries">'+filters+'</div>'
            f'<p id="official-count" class="chart-caption" aria-live="polite">{E(summary["filter_help"])}</p>'
            '<div class="official-legend" aria-label="Official marker encodings"><span><i class="official-dot" aria-hidden="true"></i>Entry from another team</span>'
            '<span><i class="official-dot mini" aria-hidden="true"></i>Entry that used mini-SWE-agent, the same simple agent we used</span>'
            '<span><i class="official-dot diamond" aria-hidden="true"></i>Entry that used an open-weight model (diamond)</span></div>'
            '<div class="official-plot"><div class="chart-canvas" id="chart-official" role="img" '
            f'aria-label="{E(summary["title"])}" hidden></div><div id="official-focus" aria-label="Explore plotted entries"></div></div>'
            '<p class="chart-caption" id="official-help" hidden>Keyboard: Tab to a row, arrow keys to move between dots, Escape to close the card.</p>'
            '<div id="official-card" class="official-card" role="status" hidden></div>'
            '<div id="official-key-wrap" hidden><p class="chart-caption">Numbers match the model key. Nearby model markers are spaced apart for readability; exact scores are below. The light band shows where official entries cluster.</p>'
            '<ol id="official-key" class="official-key" aria-label="Our models and scores"></ol></div>'
            f'<p class="chart-caption">{OFFICIAL_CAUTION}</p><p class="chart-caption">{E(context["snapshot"])}</p>'
            '<details open class="chart-data" id="official-table"><summary>Show the official entries as a table</summary>'
            +''.join(panels)+'<a href="https://www.swebench.com/">Official SWE-bench leaderboard</a></details></section>')


def chart_sections(site, metrics):
    charts = chart_data(site.data, metrics,
                        read_json(site.source/'artifacts/report/timeout-adjudications.json'), site.limit)
    comparison = read_json(site.source/'artifacts/official-comparison.json')
    raw = (site.source/'artifacts/leaderboards.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != comparison['sha256']:
        raise ValueError('Official snapshot checksum mismatch')
    site.official = official_context(json.loads(raw), comparison, charts['leaderboards'], site.data['models'])
    charts['official'] = site.official
    site.json('data/charts.json', charts)

    def data_table(caption, headings, values):
        rows = ['<tr><th scope="row">'+E(row[0])+'</th>'+''.join(f'<td>{E(v)}</td>' for v in row[1:])+'</tr>'
                for row in values]
        return '<details open class="chart-data"><summary>Show the data as a table</summary>'+table(caption, headings, rows)+'</details>'

    def card(key, eyebrow, title, caption, tables, source, attempts, extra='', after=''):
        tables = tables.replace('</details>', f'<p class="muted">Source: {E(source)}.</p></details>')
        basis = attempt_basis(charts['model_count'], charts['task_count'])
        if key == 'scatter':
            basis += f' Step counts are available for {number(attempts)} inspected attempts.'
        return (f'<section class="sk-card chart-card" id="card-{key}"><p class="sk-card-eyebrow">{eyebrow}</p>'
                f'<h2 class="sk-card-title" id="title-{key}" aria-live="polite">{E(title)}</h2>'
                f'<p class="chart-caption" id="caption-{key}">{E(caption)}</p>{extra}' +
                (f'<div class="scatter-layout"><div><div class="chart-canvas" id="chart-{key}" role="img" aria-label="{E(title)}" hidden></div></div><ol class="scatter-key" id="scatter-key" aria-label="All models, steps and scores"></ol></div>' if key == 'scatter' else
                 f'<div class="chart-canvas" id="chart-{key}" role="img" aria-label="{E(title)}" hidden></div>') +
                f'{tables}{after}<p class="chart-source" id="source-{key}">{basis}</p></section>')

    board_tables = ''
    tabs = '<div class="tabs chart-tabs" role="tablist" aria-label="Chart benchmark subset">'
    for idx, (name, board) in enumerate(charts['leaderboards'].items()):
        tabs += (f'<button type="button" class="sk-btn sk-btn-md sk-btn-quiet" role="tab" id="chart-tab-{name}" '
                 f'aria-controls="chart-panel-{name}" aria-selected="{str(idx == 0).lower()}" tabindex="{0 if idx == 0 else -1}" '
                 f'data-chart-subset="{name}">{name}</button>')
        values = [[r['rank'] if r['score'] is not None else '—', r['model'],
                   percent(r['score']/100) if r['score'] is not None else 'Unavailable',
                   '–'.join(percent(v/100) for v in r['interval']) if r['interval'] else 'Unavailable',
                   f'{number(r["resolved"])} / {number(r["graded"])}', percent(r['coverage']/100)] for r in board['rows']]
        board_tables += (f'<div id="chart-panel-{name}" role="tabpanel" aria-labelledby="chart-tab-{name}">'
                         +data_table(name+' scores', ['Rank', 'Model', 'Resolved', 'Wilson interval', 'Resolved / graded', 'Coverage'], values)+'</div>')
    tabs += '</div>'
    body = ('<div class="chart-dashboard" data-charts="data/charts.json">'
            '<p class="chart-fallback">Charts need JavaScript. You can read every plotted value in the open tables below.</p>')
    board = charts['leaderboards']['Full']
    body += card('leaderboard', 'Resolved tasks', board['title'],
                 f'The bars show the share of tasks each model solved among its graded attempts. The lines show a {CONFIDENCE*100:g}% confidence interval (Wilson): a range describing uncertainty from the choice of tasks, not repeated attempts. '+charts['family_note'],
                 board_tables, 'summary.json and subsets.json', board['attempts'], tabs)
    o = charts['outcomes']
    body += card('outcomes', 'Attempt outcomes', o['title'],
                 o['caption'],
                 data_table('Full attempt outcomes · counts and shares', ['Model']+[c['label'] for c in o['categories']]+['Total'],
                            [[r['model']]+[f'{number(r["counts"][c["key"]])} ({percent(r["percentages"][c["key"]]/100)})' for c in o['categories']]+[number(r['total'])] for r in o['rows']]),
                 'instances.csv, grade reasons and timeout-adjudications.json', o['attempts'], '<p><a href="methodology.html#reviewed-timeouts">How we count timeouts</a></p>')
    h = charts['difficulty']
    examples = '<div class="difficulty-examples">'
    for example in h['examples']:
        examples += (f'<figure><figcaption><strong>{E(example["label"])}</strong><br>'
                     f'<a href="{E(example["href"])}">{E(example["instance_id"])}</a><br>{E(example["repo"])}</figcaption>'
                     f'<blockquote>{E(example["quote"])}</blockquote></figure>')
    examples += '</div>'
    tabs = '<div class="tabs accumulation-tabs" role="tablist" aria-label="Model combination order">'
    tables = ''
    for key, label in [('score', 'Best score first'), ('greedy', 'Most new tasks first')]:
        tabs += (f'<button type="button" class="sk-btn sk-btn-md sk-btn-quiet" role="tab" id="accumulation-tab-{key}" '
                 f'aria-controls="accumulation-panel-{key}" aria-selected="{str(key == "score").lower()}" '
                 f'tabindex="{0 if key == "score" else -1}" data-accumulation-order="{key}">{label}</button>')
        tables += (f'<div role="tabpanel" id="accumulation-panel-{key}" aria-labelledby="accumulation-tab-{key}">'
                   +data_table(label, ['Number of models combined', 'Model added', 'New tasks solved', 'Tasks solved by at least one model'],
                               [[r['models'], r['model'] or 'No models', number(r['new']), number(r['solved'])] for r in h['orders'][key]])
                   .replace('</details>', '<p class="muted">Source: instances.csv and public SWE-bench issue text.</p></details>')+'</div>')
    body += (f'<section class="sk-card chart-card" id="card-difficulty"><p class="sk-card-eyebrow">How many tasks the models can solve together</p>'
             f'<h2 class="sk-card-title" id="title-difficulty">{E(h["title"])}</h2>'
             f'<p class="chart-caption" id="caption-difficulty">{E(h["caption"])}</p>'+tabs+'</div>'
             '<p class="chart-caption accumulation-help">Each step adds one model. Scroll across the chart on a small screen to read every model.</p>'
             '<div class="accumulation-scroll" role="region" tabindex="0" aria-label="Cumulative tasks solved chart, scroll to see all models">'
             f'<div class="chart-canvas" id="chart-accumulation" role="img" aria-label="{E(h["title"])}" hidden></div></div>'
             +tables+examples+f'<p class="chart-source">{attempt_basis(charts["model_count"], charts["task_count"])}</p></section>')
    u = charts['unique']
    body += card('unique', 'Where models differ · Full', u['title'], u['caption'],
                 data_table('Tasks solved by just one model', ['Model', 'Tasks no other model solved'],
                            [[r['model'], f'{number(r["tasks"])} tasks'] for r in u['rows']]),
                 'instances.csv', charts['graded'])
    h = charts['heatmap']
    project_table = table('Projects represented in the Full set', ['Project', 'What it is', 'Number of tasks'],
                          [f'<tr><th scope="row">{E(p["repo"])}</th><td>{E(p["description"])}</td><td>{number(p["tasks"])}</td></tr>' for p in h['projects']])
    body += card('heatmap', 'Where models win and lose', h['title'],
                 h['caption'],
                 data_table('Full scores by model and repository', ['Model', 'Repository', 'Resolved', 'Resolved / total', 'Graded / total'],
                            [[r['model'], r['repo'], percent(r['score']/100) if r['score'] is not None else 'Unavailable',
                              f'{number(r["resolved"])} / {number(r["total"])}', f'{number(r["graded"])} / {number(r["total"])}'] for r in h['cells']]),
                 'repositories.json and instances.csv', h['attempts'],
                 after=f'<details><summary>What the {len(h["projects"])} projects are</summary>{project_table}</details>')
    s = charts['scatter']
    caption = s['caption']
    if site.limit is not None:
        caption += f' Usage preview: at most {number(site.limit)} trajectories per model; sample medians are not full-run estimates.'
    if s['omitted']:
        caption += ' Omitted because steps or a graded score are unavailable: '+', '.join(s['omitted'])+'.'
    body += card('scatter', 'Steps versus score', s['title'], caption,
                 data_table("Steps are the number of model calls in an attempt; the median is taken over all of that model's attempts, whatever the outcome.", ['Model', 'Steps per attempt (median)', 'Solved', 'Attempts with steps'],
                            [[r['model'], number(r['steps']), percent(r['score']/100), number(r['samples'])] for r in s['points']]),
                 'trajectory model_stats.api_calls and summary.json', s['attempts'], f'<p class="chart-caption">{E(s["evidence"])}</p>')
    return body+'</div>'


def build_leaderboard(site, metrics):
    d = site.data
    full = d['boards']['Full']
    total = sum(r['total'] for r in full.values())
    graded = sum(r['graded'] for r in full.values())
    generated = sum(r['total']-r['missing'] for r in full.values())
    cards = ''.join(f'<article class="sk-card"><p class="sk-card-eyebrow">{label}</p><p class="stat">{value}</p></article>'
                    for label, value in [('Models', number(len(full))), ('Tasks', number(len(d['tasks']))),
                                         ('Attempts', number(total)), ('Attempts graded', f'{number(graded)} ({graded/total:.0%})')])
    body = f'<p class="lede">We ran {number(len(full))} models through the same agent, the same gateway and the official SWE-bench grader. Every score links to the evidence behind it.</p>'
    body += glossary(d)
    body += '<p class="muted">Model names are the gateway\'s route names.</p>'
    body += '<div class="cards">'+cards+'</div>'
    incomplete = sum(not r['complete'] for b in d['boards'].values() for r in b.values())
    if incomplete:
        body += '<aside class="sk-callout sk-callout-review"><div><h2 class="sk-callout-title">Grading is still incomplete.</h2><p class="sk-callout-text">Provisional scores use only graded attempts. Pending attempts may change the score and rank. Coverage is shown for every model and subset; a final badge means that row is fully graded.</p></div></aside>'
    if site.limit is not None:
        body += f'<p class="notice">Usage preview: at most {number(site.limit)} trajectories per model, selected by instance ID. Sample medians are not full-run estimates. Scores and coverage use all report rows.</p>'
    body += chart_sections(site, metrics)
    body += '<aside class="sk-card research-invite"><h2 class="sk-card-title">Open evidence for research</h2><p>We publish trajectories, patches and grading logs so you can check the scores and compare how models work on the same tasks. You can use the evidence to study failure modes, editing choices and differences between models.</p><div><a class="sk-btn sk-btn-md sk-btn-quiet" href="research.html">Explore the evidence</a></div></aside>'
    body += '<h2>Leaderboard data</h2>'
    body += '<div class="tabs" role="tablist" aria-label="Benchmark subset">'
    for idx, (name, ids) in enumerate(d['subsets'].items()):
        body += f'<button class="sk-btn sk-btn-md sk-btn-quiet" type="button" role="tab" id="tab-{name}" aria-controls="panel-{name}" aria-selected="{str(idx == 0).lower()}" tabindex="{0 if idx == 0 else -1}">{name} ({number(len(ids))})</button>'
    body += '</div>'
    for idx, (name, board) in enumerate(d['boards'].items()):
        rows = []
        ordered = sorted(board, key=lambda m: (-(board[m]['score'] if board[m]['score'] is not None else -1), m))
        for m in ordered:
            c = board[m]
            rank = 1+sum(1 for other in board.values() if other['score'] is not None and c['score'] is not None and other['score'] > c['score']) if c['score'] is not None else '—'
            selected = {i: r for i, r in metrics[m].items() if i in d['subsets'][name]}
            known = [r for r in selected.values() if r['exit_status'] is not None]
            submitted = sum(r['exit_status'] == 'Submitted' for r in known)
            med = distribution(r.get('usage', {}).get('steps') for r in selected.values())
            submit = percent(submitted/len(known)) if known else 'Unavailable'
            fields = [str(rank), f'<a href="models/{slug(m)}.html">{E(m)}</a>', score_bar(c),
                      f'{number(c["resolved"])} / {number(c["graded"])}', percent(c['coverage']),
                      f'{submit}<small>{number(len(known))} outcomes observed</small>',
                      f'{number(med["median"])}<small>{number(med["n"])} trajectories</small>', badge(c['complete'])]
            keys = [rank if isinstance(rank, int) else -1, m, c['score'] if c['score'] is not None else -1,
                    c['resolved'], c['coverage'], submitted/len(known) if known else -1,
                    med['median'] if med['median'] is not None else -1, int(c['complete'])]
            rows.append('<tr>'+''.join(f'<{"th scope="+chr(34)+"row"+chr(34) if j == 1 else "td"} data-sort="{E(keys[j])}">{v}</{"th" if j == 1 else "td"}>' for j, v in enumerate(fields))+'</tr>')
        body += f'<section role="tabpanel" id="panel-{name}" aria-labelledby="tab-{name}"{ " hidden" if idx else ""}>'
        body += table(f'{name} · resolved / graded; interval reflects task sampling only',
                      ['Rank', 'Model', f'Resolved · Wilson {CONFIDENCE*100:g}% interval', 'Resolved / graded',
                       'Coverage', 'Submit rate', 'Median steps', 'Status'], rows, True) + '</section>'
    body += '<p class="muted">Ranks follow the displayed score; ties share rank. Submit rate is Submitted exits / observed generation outcomes, including empty submissions. Steps are recorded model API calls. Missing usage is excluded, never counted as zero. Intervals do not capture gateway, scaffold or repeated-run variability.</p>'
    body += '<aside class="sk-card thanks"><h2 class="sk-card-title">Thanks</h2><p>We at Spec Kitty could run the same agent across the model routes because TokenFactory gave us a shared API. exe.dev gave us machines we could resize and a way to keep the gateway key off every worker. Thank you to both teams for making this run possible.</p><p><a href="about.html">Who made this</a> · <a href="methodology.html#infrastructure">How the infrastructure worked</a> · <a href="research.html">For researchers</a></p></aside>'
    comparison = read_json(site.source/'artifacts/official-comparison.json')
    body += official_section(site.official)
    matches = sum(bool(r.get('matches')) for r in comparison['models'] if r['model'] in d['models'])
    body += '<section><h2>Official leaderboard</h2>'
    if not matches:
        body += f'<p>The saved official snapshot contains no exact model-name matches for our {number(len(d["models"]))} included models. We do not substitute base models for modified or quantized routes.</p>'
    else:
        body += f'<p>The saved comparison contains {number(matches)} exact matches. See the saved comparison data for the matching entries.</p>'
    body += f'<p>Official entries can use different agents, budgets, tools and test subsets. These results are not an official leaderboard submission or a controlled comparison against those entries. Snapshot retrieved {E(comparison["retrieved_at"])} at commit <code>{E(comparison["commit"])}</code>.</p><p><a href="{E(comparison["source"])}">Official SWE-bench leaderboard</a> · <a href="data/official-comparison.json">Saved comparison</a> · <a href="methodology.html">Read the protocol</a></p></section>'
    site.json('data/official-comparison.json', comparison)
    site.json('data/leaderboard.json', d['boards'])
    site.page('index.html', HEADLINE, body)


def histogram(title, dist):
    if not dist['n']:
        return f'<section><h3>{E(title)}</h3><p>No recorded usage.</p></section>'
    bars = ''
    max_count = max(b[2] for b in dist['bins'])
    width = 480/len(dist['bins'])
    for idx, (low, high, count) in enumerate(dist['bins']):
        height = count/max_count*100
        bars += f'<rect x="{idx*width+10:.2f}" y="{120-height:.2f}" width="{width-4:.2f}" height="{height:.2f}" fill="var(--model-color, var(--ink-muted))"><title>{number(low)} to {number(high)}: {number(count)} attempts</title></rect>'
    bins_text = '; '.join(f'{number(low)}–{number(high)}: {number(count)}' for low, high, count in dist['bins'])
    return (f'<section class="sk-card"><h3 class="sk-card-title">{E(title)}</h3><p>Median {number(dist["median"])} · {number(dist["n"])} observed</p>'
            f'<svg viewBox="0 0 500 145" role="img" aria-label="{E(title)} counts. {E(bins_text)}">{bars}'
            f'<text x="10" y="140">{number(dist["min"])}</text><text x="490" y="140" text-anchor="end">{number(dist["max"])}</text></svg>'
            f'<details><summary>Read bin counts</summary><p>{E(bins_text)}</p></details></section>')


def build_models(site, metrics):
    d = site.data
    timeouts = read_json(site.source/'artifacts/report/timeout-adjudications.json')
    reviews = read_json(site.source/'artifacts/report/test-timeout-reviews.json')
    pauses = read_json(site.source/'artifacts/report/model-pauses.json')
    nonces = read_json(site.source/'configs/request-nonce.json')
    for model in d['models']:
        c = d['boards']['Full'][model]
        records = metrics[model]
        distributions = usage_summary(records)
        adjudicated = sum(t.get('original_queue', {}).get('model', t.get('model')) == model for t in timeouts)
        reviewed = sum(t['model'] == model for t in reviews)
        empty = sum(r['grade_reason'] == 'empty_patch' for r in records.values())
        body = f'<p class="headline-score">{percent(c["score"])} {badge(c["complete"])}</p><p>{number(c["resolved"])} tasks solved. {number(c["graded"])} of {number(c["total"])} Full attempts graded ({percent(c["coverage"])}).</p>'
        body += f'<div data-model-palette="{E(model)}" data-model-list="{E(json.dumps(site.data["models"]))}">'+score_bar(c)+'</div>'
        body += '<h2>Outcome mix</h2><p>Report statuses partition the Full set. Empty patches and reviewed timeouts overlap unresolved outcomes; they are not extra attempts. Incident reruns are not an outcome category.</p>'
        rows = [cells([E(s.capitalize()), number(c[s])]) for s in STATUSES]
        rows += [cells(['Empty patches (grade reason)', number(empty)]), cells(['Adjudicated outer timeouts', number(adjudicated)]),
                 cells(['Reviewed test timeouts', number(reviewed)]), cells(['Outage reruns', 'Unavailable: no active-attempt rerun manifest in the supplied inputs'])]
        body += table('Full outcomes and overlapping evidence annotations', ['Outcome', 'Count'], rows)
        body += '<h2>By repository</h2>'
        body += table('Full tasks by repository', ['Repository', 'Resolved / graded', 'Resolved', 'Coverage'],
                      [cells([E(repo), f'{number(rc["resolved"])} / {number(rc["graded"])}', percent(rc['score']), percent(rc['coverage'])])
                       for repo, rc in d['repository_counts'][model].items()])
        body += '<h2>Tokens and steps</h2>'
        trajectory_count = sum('usage' in r for r in records.values())
        body += f'<p>Read {number(trajectory_count)} trajectories from {number(len(records))} collected attempt directories. Steps use <code>info.model_stats.api_calls</code>. Tokens sum recorded assistant response usage per attempt; prompt tokens include repeated context. Missing fields remain unknown. Partial attempts and partial usage are included as observed totals.</p>'
        partial = sum(any(u['usage_responses'].get(k, 0) < max(u['responses'], u['steps'] or 0) for k in ('prompt_tokens', 'completion_tokens'))
                      for r in records.values() if (u := r.get('usage')))
        body += f'<p>{number(partial)} inspected trajectories lack prompt or completion usage for some recorded calls. These totals are lower bounds. <a href="../data/models/{slug(model)}.json">Download usage summaries and per-attempt metrics</a>.</p>'
        if site.limit is not None:
            body += f'<p class="notice">Sample only: first {number(site.limit)} available trajectories by instance ID. This sample is not random.</p>'
        body += f'<div class="charts" data-model-palette="{E(model)}" data-model-list="{E(json.dumps(site.data["models"]))}">'+''.join(histogram(label, distributions[k]) for k, label in
                                               [('steps', 'Steps'), ('prompt_tokens', 'Prompt tokens'), ('completion_tokens', 'Completion tokens'), ('total_tokens', 'Total tokens')])+'</div>'
        body += '<h2>Notable events</h2>'
        if model in nonces:
            note = nonces[model]
            body += f'<p><strong>Restart with a per-request nonce.</strong> {E(note["reason"])} {E(note["applies_to"])} The current scores exclude archived pre-restart attempts.</p>'
        if model in pauses:
            body += f'<p>{E(pauses[model]["reason"])}</p>'
        exits = Counter(r['exit_status'] for r in records.values() if r['exit_status'])
        if model.startswith('kimi'):
            body += f'<p>Gateway-stall timeout attribution is unavailable in the supplied report. We observed {number(exits["OuterProcessTimeout"])} outer-process timeout exits and {number(exits["TimeExceeded"])} wall-budget exits; {number(adjudicated)} outer timeouts have explicit adjudications. These counts do not prove that every timeout was caused by the gateway.</p>'
        if model == 'glm-5.3-uncensored-fp8':
            body += '<p>The experiment context reports a backend outage followed by fresh reruns. Active-attempt exports do not identify the affected rerun population, so its count is unavailable. Superseded attempts are excluded.</p>'
        if model not in nonces and model not in pauses and not model.startswith('kimi') and model != 'glm-5.3-uncensored-fp8':
            body += '<p>Task-wide grading amendments and reviewed timeout policies apply. See the methodology and each attempt’s evidence.</p>'
        body += table('Recorded generation exits', ['Exit status', 'Count'], [cells([E(k), number(v)]) for k, v in sorted(exits.items())])
        body += '<h2>Attempt evidence</h2><p>Files become downloadable when the evidence packer has produced them. Paths follow <code>evidence/models/&lt;model&gt;/attempts/&lt;repo-slug&gt;/&lt;instance_id&gt;.json.gz</code>. Repository slugs use the SWE-bench double-underscore form. <a href="../evidence.html">Evidence and verification</a>.</p>'
        for repo in d['repos']:
            selected = sorted(i for i, r in d['tasks'].items() if r == repo)
            body += f'<details><summary>{E(repo)} · {number(len(selected))} tasks</summary><ul class="evidence-list">'
            body += ''.join(f'<li>{site.evidence_link(model, i, "../../")} · {E(d["statuses"][model][i])}</li>' for i in selected)+'</ul></details>'
        site.json(f'data/models/{slug(model)}.json', {'model': model, 'distributions': distributions,
                  'trajectory_limit_per_model': site.limit, 'outage_reruns': None, 'adjudicated_timeouts': adjudicated,
                  'attempts': records})
        site.page(f'models/{slug(model)}.html', model, body)


def build_compare(site):
    d = site.data
    models = sorted(d['models'])
    pairs = {}
    for a in models:
        for b in models:
            shared = [i for i in d['tasks'] if d['statuses'][a][i] in STATUSES[:2] and d['statuses'][b][i] in STATUSES[:2]]
            only_a = sum(d['statuses'][a][i] == 'resolved' and d['statuses'][b][i] != 'resolved' for i in shared)
            only_b = sum(d['statuses'][b][i] == 'resolved' and d['statuses'][a][i] != 'resolved' for i in shared)
            pairs[a+'|'+b] = dict(a=a, b=b, paired=len(shared), only_a=only_a, only_b=only_b, p=mcnemar_exact(only_a, only_b))
    body = '<p class="lede">Compare where models solve the same tasks, and where their results differ.</p><h2>Resolved by repository</h2><p>Cells show resolved / graded as a percentage. Each cell includes its graded denominator. Pending attempts are excluded. Ink density follows the percentage; text carries the value.</p>'
    width = 390+len(d['repos'])*105
    height = 210+len(models)*44
    svg = f'<svg class="heatmap" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Resolved percentages by model and repository; full values follow in the table"><rect width="{width}" height="{height}" fill="var(--surface)"/>'
    for j, repo in enumerate(d['repos']):
        svg += f'<text transform="translate({390+j*105+48},190) rotate(-55)">{E(repo)}</text>'
    for i, model in enumerate(models):
        y = 208+i*44
        svg += f'<text x="380" y="{y+25}" text-anchor="end">{E(model)}</text>'
        for j, repo in enumerate(d['repos']):
            c = d['repository_counts'][model][repo]
            opacity = .04+(c['score'] or 0)*.3
            x = 390+j*105
            svg += f'<g><title>{E(model)} · {E(repo)}: {percent(c["score"])}; {c["graded"]}/{c["total"]} graded</title><rect x="{x}" y="{y}" width="100" height="40" fill="var(--ink)" opacity="{opacity:.3f}"/><text x="{x+50}" y="{y+25}" text-anchor="middle" style="fill:var(--{ "surface" if opacity > .5 else "ink"})">{percent(c["score"])}</text></g>'
    svg += '</svg>'
    body += '<div class="table-scroll" tabindex="0" role="region" aria-label="Repository heatmap">'+svg+'</div><details><summary>Read repository values and coverage</summary>'
    body += table('Heatmap values: resolved / graded; coverage', ['Model', *d['repos']],
                  [cells([E(m), *[f'{percent(c["score"])}<small>{c["resolved"]}/{c["graded"]}; {percent(c["coverage"])} coverage</small>' for c in d['repository_counts'][m].values()]]) for m in models])+'</details>'
    body += '<h2>Paired differences</h2><p>Exact two-sided McNemar tests use only tasks with graded attempts from both models. The null gives each discordant direction equal probability. We double the smaller binomial tail and cap it at unity; no continuity correction or multiple-comparison adjustment. These exploratory tests do not estimate repeat-run reliability. Pending attempts are not failures.</p>'
    rows = []
    for a in models:
        vals = [E(a)]
        for b in models:
            r = pairs[a+'|'+b]
            if a == b:
                vals.append('—')
                continue
            detail = f'Only row model solves: {r["only_a"]}; only column model solves: {r["only_b"]}; paired tasks: {r["paired"]}'
            vals.append(f'<span title="{E(detail)}">{r["p"]:.4g}</span><small>A only {r["only_a"]} · B only {r["only_b"]}<br>Paired {r["paired"]}</small>')
        rows.append(cells(vals))
    body += table('McNemar p-values: A = row; B = column', ['Model A / model B', *models], rows)
    body += '<p><a href="data/comparisons.json">Download paired counts and p-values</a></p>'
    site.json('data/comparisons.json', list(pairs.values()))
    site.page('compare.html', 'Compare paired results', body)


def build_instances(site):
    d = site.data
    models, repos = sorted(d['models']), d['repos']
    rows = []
    for instance in sorted(d['tasks']):
        statuses = [STATUSES.index(d['statuses'][m][instance]) for m in models]
        available = [int((ROOT/site.evidence_path(m, instance)).is_file()) for m in models]
        rows.append([instance, repos.index(d['tasks'][instance]), statuses, available])
    site.json('data/instances.json', dict(models=models, repos=repos, statuses=STATUSES,
              columns=['instance_id', 'repo_index', 'status_indices_by_model', 'evidence_available_by_model'], rows=rows,
              evidence_template='evidence/models/{model}/attempts/{repo_slug}/{instance_id}.json.gz'))
    repo_options = ''.join(f'<option value="{i}">{E(r)}</option>' for i, r in enumerate(repos))
    model_options = ''.join(f'<option value="{i}">{E(m)}</option>' for i, m in enumerate(models))
    status_options = ''.join(f'<option value="{i}">{s.capitalize()}</option>' for i, s in enumerate(STATUSES))
    counts = ''.join(f'<option value="{i}">{i}</option>' for i in range(len(models)+1))
    body = f'''<p class="lede">Explore {number(len(d['tasks']))} Full tasks. Status filters apply to the selected model, or to any model when no model is selected.</p>
<div id="explorer" data-source="data/instances.json"><button id="load-instances" class="sk-btn sk-btn-md sk-btn-primary" type="button">Load task explorer</button>
<div class="filters" hidden><label class="sk-field"><span class="sk-label">Search task ID</span><input id="search" class="sk-input" type="search"></label>
<label class="sk-field"><span class="sk-label">Repository</span><select id="repo-filter" class="sk-input"><option value="">All repositories</option>{repo_options}</select></label>
<label class="sk-field"><span class="sk-label">Model for status</span><select id="model-filter" class="sk-input"><option value="">Any model</option>{model_options}</select></label>
<label class="sk-field"><span class="sk-label">Status</span><select id="status-filter" class="sk-input"><option value="">All statuses</option>{status_options}</select></label>
<label class="sk-field"><span class="sk-label">Number of models resolving</span><select id="solved-filter" class="sk-input"><option value="">Any count</option>{counts}</select></label></div>
<p id="explorer-status" role="status" aria-live="polite">Task data loads when you open the explorer.</p>
<div id="instance-results"></div><div class="pager" hidden><button id="previous" class="sk-btn sk-btn-md sk-btn-quiet" type="button">Previous tasks</button><button id="next" class="sk-btn sk-btn-md sk-btn-quiet" type="button">Next tasks</button></div></div>
<noscript><p>The explorer needs JavaScript. You can download the full results below or use the model pages to inspect task evidence.</p></noscript>
<p><a href="data/results.csv" download>Download all results as CSV</a> · <a href="data/instances.json">Download compact task data</a></p>'''
    site.page('instances.html', 'Inspect every task', body)


def build_about(site):
    paragraphs = [
        'We chose the protocol, operated the run and graded predictions with the official SWE-bench harness. We publish the result matrix and trajectories so you can follow a score back to the work that produced it. The evidence page shows what is packaged, and grading coverage shows how much has been graded.',
        f'TokenFactory gave us one OpenAI-compatible endpoint and one API shape for {number(len(site.data["models"]))} models, with tool calling across every route. We could keep the same request machinery as we moved between models. When we found serving issues, we reported them with evidence so the gateway team could act. You can get access through the TokenFactory portal linked in the footer.',
        'exe.dev gave us named Linux VMs we could reach over plain SSH, resize in place and run with Docker and systemd. Its integration kept our gateway credential off every worker. We retained our queues through resizing and used familiar tools to collect the results. Thank you for making it possible to keep working on the same machines as the run grew.',
    ]
    body = '<p class="lede">We ran this benchmark with TokenFactory and exe.dev. Their gateway, machines and credential integration let us put our protocol to work and bring the results back for you to inspect.</p>'
    for partner, paragraph in zip(site.partners, paragraphs):
        body += f'<section><h2>{E(partner["name"])}</h2><p>{paragraph}</p><p>{site.partner_link(partner)}</p></section>'
    body += '<section><h2>How we worked together</h2><p>We at Spec Kitty wrote the scheduling, recovery and grading logic and prepared this publication. TokenFactory carried the model requests, and exe.dev ran the machines behind them. Thank you to both teams for the concrete things that made this work possible. You can read how we used them in the <a href="methodology.html#infrastructure">infrastructure account</a> and follow the run’s interruptions in the <a href="methodology.html#incidents">incident notes</a>.</p></section>'
    body += f'<p>{JOINT_PROJECT} <a href="research.html">For researchers: what you can do with the evidence</a>.</p>'
    site.page('about.html', 'Who made this', body)


def infrastructure_section(site):
    facts = infrastructure_facts(site.source, site.data)
    partner_facts = read_json(ROOT/'tools/partners.json')['facts']
    sourced = {fact['id']: fact for fact in partner_facts}
    site.json('data/infrastructure.json', dict(facts, partner_facts=partner_facts))
    sources = [
        ('Fleet creation times and SSH destinations', ['artifacts/fleet.json', 'scripts/fleet.py']),
        ('Worker setup, systemd and dependency bootstrap', ['scripts/fleet.py', 'scripts/bootstrap.sh', 'README.md']),
        ('Resource settings, per-VM drain checks and retained queues', ['scripts/fleet.py', 'scripts/upgrade_fleet.py', 'artifacts/upgrade-v2.json']),
        ('Credential integration and placeholder key', ['README.md', 'scripts/run_job.py']),
        ('Matrix, concurrency, isolation, image reuse and architecture', ['configs/experiment.json', 'configs/protocol.json', 'scripts/upgrade_fleet.py', 'scripts/worker_v2.py']),
        ('Clean-experiment observation window', ['artifacts/telemetry-history.jsonl']),
        ('Collection and recovery mechanisms', ['scripts/fleet.py', 'scripts/upgrade_fleet.py', 'README.md']),
    ]
    citations = '<details><summary>Where these facts come from</summary><p>Paths refer to the collected source tree unless marked as publication tooling. Source hashes are in <a href="data/build-info.json">build provenance</a>; derived values are in <a href="data/infrastructure.json">infrastructure data</a>. Durations are windows read from recorded timestamps. Source scripts are read, never executed by this build.</p><ul>'
    citations += (f'<li>Fleet creation: {number(facts["provision_seconds"])} seconds, from {E(facts["provision_first"])} to {E(facts["provision_last"])}.</li>'
                  f'<li>Clean-experiment observations: {facts["observed_hours"]} hours, from {E(facts["observed_first"])} to {E(facts["observed_last"])}.</li>')
    for claim, paths in sources:
        citations += '<li>'+E(claim)+': '+', '.join(f'<code>{E(p)}</code>' for p in paths)+'.</li>'
    for fact in partner_facts:
        citations += f'<li id="fact-{E(fact["id"])}">{E(fact["source"])} (recorded in publication tooling: <code>tools/partners.json</code>).</li>'
    citations += '<li>Publication tooling: <a href="../tools/pack_evidence.py" data-repo-file="tools/pack_evidence.py">evidence packer</a>. Its exact-value check uses the supplied credential value.</li></ul></details>'
    values = {k: E(number(v) if isinstance(v, (int, float)) else v) for k, v in facts.items()}
    values.update(provision_minutes=f'{facts["provision_seconds"]/60:.1f}',
                  observed_hours=f'{facts["observed_hours"]:.0f}', citations=citations,
                  vm_tag=E(sourced['vm-tag']['value']))
    return (ROOT/'tools/site_assets/infrastructure.html').read_text().format_map(values)


def build_methodology(site, metrics):
    s, d = site.source, site.data
    protocol = read_json(s/'configs/protocol.json')
    experiment = d['experiment']
    versions = sorted({r['usage']['mini_version'] for records in metrics.values() for r in records.values()
                       if r.get('usage', {}).get('mini_version')})
    amendments = read_json(s/'artifacts/report/grading-amendments.json')
    reviews = read_json(s/'artifacts/report/test-timeout-reviews.json')
    timeouts = read_json(s/'artifacts/report/timeout-adjudications.json')
    transport = read_json(s/'artifacts/report/transport-amendments.json')
    nonces = read_json(s/'configs/request-nonce.json')
    body = '<p class="lede">We evaluate the model, agent and gateway together. Here is what ran, how we count outcomes, and where interpretation needs care.</p>' + glossary(d) + '<h2>Protocol</h2>'
    body += f'<p>mini-SWE-agent version {E(", ".join(versions) or "unavailable in inspected trajectories")}, pinned commit <code>{E(experiment["mini_commit"])}</code>. Official SWE-bench harness {E(experiment["harness_version"])} at <code>{E(experiment["harness_commit"])}</code>. We use {number(experiment["attempts_per_instance"])} scored attempt per model per task, after explicitly disclosed incident restarts.</p>'
    limits = [('Agent steps', 'step_limit'), ('Wall check (seconds)', 'wall_time_seconds'),
              ('Outer process limit (seconds)', 'outer_process_timeout_seconds'), ('Request timeout (seconds)', 'transport_timeout_seconds'),
              ('Maximum output tokens per call', 'max_output_tokens_per_call'), ('Completion tokens per attempt', 'max_completion_tokens_per_attempt'),
              ('Context proxy token cap', 'context_proxy_limit'), ('Harness timeout (seconds)', 'grader_timeout_seconds'),
              ('Temperature', 'temperature'), ('Container CPUs', 'container_cpus')]
    body += table('Frozen protocol budgets', ['Setting', 'Value'], [cells([label, number(protocol[key])]) for label, key in limits])
    body += f'<p>Context proxy: {E(protocol["context_proxy_tokenizer"])}. Scaffold: {E(protocol["scaffold"])}. Container network: {E(protocol["container_network"])}; memory: {E(protocol["container_memory"])}. The wall limit is checked between calls, so a slow call can extend elapsed time up to the outer process limit.</p>'
    body += f'<p>History isolation: {E(protocol["repository_history"])}. A fresh object store exposes only the dataset base commit; ancestor and future commits and remotes are unavailable. Each prediction needs matching isolation evidence.</p>'
    body += infrastructure_section(site)
    body += f'<h2>A shared gateway and an inspectable result</h2><p>TokenFactory gave us one OpenAI-compatible endpoint and one API shape for {number(len(d["models"]))} models, with tool calling across every route. We could use the same request machinery throughout the run. When we found serving issues, we reported them with evidence so the gateway team could act. Thank you for giving us a shared way to reach these models. You can get access through the TokenFactory portal linked in the footer.</p><p>We at Spec Kitty ran the benchmark and graded predictions with the official SWE-bench harness. We publish results and trajectories alongside the protocol and incident notes so you can trace a score back to an attempt. The evidence page shows what has been packaged, and grading coverage stays visible with the scores.</p>'
    body += '<h2>Outcome definitions</h2><dl><dt>Resolved</dt><dd>Completed grading with a resolved result, prediction identity and required harness evidence validated by the source report.</dd><dt>Unresolved</dt><dd>Completed grading without resolution, including validated empty patches, patch-apply failures and explicitly reviewed patch-induced test timeouts.</dd><dt>Ungraded</dt><dd>A prediction without a completed accepted grade, or a grade whose required evidence or current amendment is missing. A test timeout remains ungraded until reviewed.</dd><dt>Missing</dt><dd>No prediction and no grade in the collected report. This can include pending, paused or uncollected work; it is not a failure result.</dd></dl>'
    body += f'<p>The site consumes <code>scripts/report.py</code> exports and checks summary and repository counts against every CSV row. <code>scripts/subsets.py</code> supplies the Verified counts: <code>astropy__astropy-7606</code> has a different PASS_TO_PASS contract and needs supplemental grading. We never borrow its Full result. Lite uses matching Full contracts. Wilson intervals use {CONFIDENCE*100:g}% confidence and the graded denominator; the benchmark is a fixed task set, so these are descriptive sampling intervals, not uncertainty over model randomness.</p>'
    body += '<h2>Grading amendments</h2><p>The following task-wide amendments set <code>OMP_NUM_THREADS=1</code> for all nonempty submissions, including previously completed grades. Official tests and the harness time limit stay unchanged. Original evidence remains archived; diagnostic tests are unscored and inference is not repeated.</p>'
    body += table('Task-wide amendments and their recorded reasons', ['Task', 'Amendment', 'Reason'],
                  [cells([E(a['instance']), E(a['id']), E(a['reason'])]) for a in amendments])
    body += '<p>The outcome chart counts each attempt once, testing groups in this order: resolved; ungraded or missing; reviewed timeout (an outer-process adjudication or a reviewed patch-induced test timeout); empty patch; remaining unresolved patch. A timeout-created empty prediction belongs only to the timeout group. An unreviewed timeout stays in the waiting group.</p>'
    body += f'<h2 id="reviewed-timeouts">Reviewed timeouts</h2><p>The exported report contains {number(len(timeouts))} outer-process timeout adjudications and {number(len(reviews))} test-timeout reviews. Reviewed outer timeouts with no submission produce an empty prediction under the existing budget; no inference is repeated. A confirmed patch-induced test hang counts as unresolved under the original harness limit. Unreviewed timeouts remain ungraded. Original grades, logs, control diagnostics and hashes remain part of the evidence.</p>'
    for r in reviews:
        body += f'<h3>{E(r["model"])} · {E(r["instance"])}</h3><p>{E(r["rationale"])}</p>'
    body += '<h2 id="incidents">Gateway incidents and recovery</h2>'
    for excluded in experiment.get('excluded_models', []):
        body += f'<p><strong>{E(excluded["model"])} excluded.</strong> {E(excluded["reason"])} ({E(excluded.get("date", ""))}). The experiment context reports that this route is now absent from the gateway; this offline build does not query live availability.</p>'
    body += '<p><strong>GLM uncensored backend outage.</strong> The experiment context reports a backend outage on <code>glm-5.3-uncensored-fp8</code> and fresh reruns. The named report/config inputs do not supply an attributable rerun count. We exclude superseded attempts and leave that count unavailable rather than infer it from failure exits.</p>'
    for model, event in nonces.items():
        body += f'<p><strong>{E(model)} serving fault and restart.</strong> {E(event["reason"])} {E(event["applies_to"])} A unique leading token is added to every request. This changes the prompt prefix and is a disclosed exception to identical scaffolding. Earlier attempts are archived and excluded from these scores.</p>'
    for event in transport:
        body += f'<p><strong>Request timeout amendment ({E(event["date"])}).</strong> {number(event["previous_timeout_seconds"])} to {number(event["timeout_seconds"])} seconds. {E(event["reason"])} Scope: {E(event["scope"])}. {E(event["recovery"])}.</p>'
        if 'partial_recovery' in event:
            body += '<dl>'+''.join(f'<dt>{E(k.replace("_", " ").capitalize())}</dt><dd>{E(v)}</dd>' for k, v in event['partial_recovery'].items())+'</dl>'
    body += '<p>Kimi timeout exits are reported on the model pages. Outer timeout adjudications establish exhausted budgets without submission; they do not alone establish gateway-stall causation. We do not equate all wall-budget exits with transport failure.</p>'
    body += '<h2 id="invalidated-history">Invalidated history</h2>'
    body += f'<p>{E(experiment["supersedes"])}. The earlier image checkout exposed later Git commits, including a task solution observed in a trajectory. Its scores are excluded entirely. The clean run starts afresh with base-only shallow history. This site does not read the invalidated run or the superseded-attempt archives.</p>'
    body += '<h2>Limits and caveats</h2><ul><li>One scored attempt does not measure run-to-run variance. Gateway aliases and modified routes are not interchangeable with base models.</li><li>Resource contention, transport amendments, explicitly reviewed recovery and the nonce restart affect interpretation.</li><li>Partial coverage may be nonrandom. A provisional rank can change when pending attempts are graded.</li><li>API calls are the recorded step proxy. Missing usage, failed calls and unfinished trajectories can understate total token consumption.</li><li>Evidence availability and benchmark coverage are separate. A final score badge does not certify that the public evidence archive is complete.</li><li>We use saved official comparison metadata; no live leaderboard or gateway query is performed.</li></ul>'
    site.json('data/protocol.json', {'experiment': {k: v for k, v in experiment.items() if k != 'api_base'}, 'protocol': protocol,
                                   'amendments': amendments, 'nonce': nonces})
    site.page('methodology.html', 'How we ran the benchmark', body)


def evidence_inventory(site):
    root = ROOT/'evidence'
    # The packer atomically replaces .pack-* staging files. They are neither
    # published evidence nor stable paths on which to base archive totals.
    files = sorted(p for p in root.rglob('*') if not p.name.startswith('.pack-') and p.is_file()) if root.exists() else []
    present = set(files)
    size = sum(p.stat().st_size for p in files)
    expected = len(site.data['models'])*len(site.data['tasks'])
    available = sum(ROOT/site.evidence_path(m, i) in present for m in site.data['models'] for i in site.data['tasks'])
    trajectories = messages = indexed = 0
    for model in site.data['models']:
        index = root/'models'/model/'results.json'
        if index not in present:
            continue
        for instance, row in read_json(index).items():
            if instance not in site.data['tasks'] or ROOT/site.evidence_path(model, instance) not in present:
                continue
            indexed += 1
            count = row.get('messages')
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                trajectories += 1
                messages += count
    return dict(available=available, expected=expected, files=len(files), bytes=size,
                compressed_bytes=sum(p.stat().st_size for p in files if p.suffix == '.gz'),
                indexed=indexed, trajectories=trajectories, messages=messages)


def build_evidence(site):
    inventory = evidence_inventory(site)
    available, expected = inventory['available'], inventory['expected']
    size = inventory['bytes']
    body = '<p class="lede">Follow a result back to the submitted patch, trajectory and grading records. The scored table and public archive have separate completeness checks.</p>'
    body += f'<p>{number(available)} / {number(expected)} expected attempts have bundles present locally. Evidence tree: {number(inventory["files"])} files, {number(size)} bytes ({size/(1024**2):.2f} MiB). These sizes describe files present at build time, not a promised final download.</p>'
    body += '<p><a href="research.html">For researchers: what you can do with the evidence</a> describes paired comparisons, research questions and examples you can run.</p>'
    if not available:
        body += '<aside class="sk-callout sk-callout-review"><div><h2 class="sk-callout-title">The evidence archive is not packaged yet.</h2><p class="sk-callout-text">Scores use validated source reports. Task downloads will appear after the evidence packer creates the archive and you rebuild this site.</p></div></aside>'
    body += '<h2>Layout and schema</h2><pre><code>evidence/\n  MANIFEST.sha256\n  models/&lt;model&gt;/attempts/&lt;repo-slug&gt;/&lt;instance_id&gt;.json.gz</code></pre><p>Repository slugs use the SWE-bench double-underscore convention. Each compressed JSON attempt bundle is intended to preserve prediction, generation result, trajectory, grade, isolation and protocol records, plus available official harness artifacts. Optional evidence includes timeout adjudication and grading history. Empty patches, rejected patches and reviewed timeouts can lack some harness files.</p>'
    body += '<p>The packer schema includes identity and status, <code>prediction</code>, <code>result</code>, <code>grade</code>, <code>isolation</code>, <code>config_sha256</code>, <code>protocol_amendment</code>, generation and grade logs, <code>trajectory</code>, <code>grading</code>, amendment/adjudication records and grading history. The <code>grading</code> object holds the evaluation script, applied patch, parsed report, test output and run log; absent files are null. Supplemental Verified evidence stays separate in <code>supplemental_verified</code>.</p><p>Large trajectories may move to a sibling compressed file; the bundle then references its evidence-relative filename and SHA-256. <code>configs.json</code> deduplicates configurations by canonical JSON hash. Model directories contain <code>predictions.jsonl</code> and <code>results.json</code> indexes. The packer owns the exact versioned schema; the site does not create substitute bundles.</p>'
    body += '<h2>Verify a repository checkout</h2><pre><code>(cd evidence &amp;&amp; sha256sum -c MANIFEST.sha256)\npython3 tools/pack_evidence.py --source /path/to/collected-source --verify</code></pre><p>Run from the publication repository root after packing. The packer writes evidence-relative manifest entries, so <code>sha256sum -c evidence/MANIFEST.sha256</code> from the root would look in the wrong directory; change into <code>evidence</code> as shown. On macOS, use <code>shasum -a 256 -c MANIFEST.sha256</code> there. Packer verification requires the collected source path. These commands verify the archive; the site generator never runs the packer or contacts the fleet.</p>'
    for path, label in [('evidence/MANIFEST.sha256', 'Download the SHA-256 manifest'), ('tools/pack_evidence.py', 'Read the evidence packer')]:
        if (ROOT/path).is_file():
            body += f'<p><a href="../{E(path)}" data-repo-file="{E(path)}">{label}</a></p>'
        else:
            body += f'<p><code>{E(path)}</code> is not present in this checkout.</p>'
    body += '<h2>Reproduce the analysis</h2><p>The source project README describes <code>configs/experiment.json</code> for upstream pins, <code>configs/datasets.lock.json</code> for dataset revisions and hashes, and <code>requirements.freeze.txt</code> for the dependency freeze. <code>scripts/snapshot.py</code> records datasets; <code>scripts/preflight.py</code> checks gateway/tool behavior; <code>scripts/isolate_repository.py</code> enforces base-only history. The source project fleet scripts collect the raw artifacts. Those operations require the original environment and are outside this offline publication build.</p>'
    body += '<p>On an existing collected snapshot, the source project’s <code>scripts/report.py</code> validates grading evidence, <code>scripts/subsets.py</code> handles subset contracts, and <code>scripts/render_report.py</code> renders its simple report. We consume their exports without executing or changing them.</p><pre><code>python3 tools/build_site.py --source /path/to/collected-source\npython3 -m unittest discover -s tests -v\npython3 tools/check_links.py docs\npython3 -m http.server --directory .</code></pre><p>For a usage preview, add <code>--limit</code> with a positive per-model trajectory count. The score matrix remains complete. Serve the repository root and open <code>/docs/</code> so relative evidence links also work. For GitHub Pages, build with <code>--publish</code> to link evidence downloads directly to GitHub; the archive is outside the Pages document root. Add <code>--staging</code> for a partner-review preview that asks search engines not to index the pages.</p>'
    body += '<h2>Machine-readable site data</h2><p><code>results.csv</code> has model, instance_id, repo and status columns. <code>instances.json</code> stores task rows as compact arrays with model/repository/status dictionaries and availability flags. Model JSON contains safe numeric usage summaries and generation/grade labels; it does not copy raw messages or credentials. <code>comparisons.json</code> contains paired denominators, discordant counts and exact p-values. Build provenance lists source hashes and metric sampling scope.</p>'
    site.json('data/evidence.json', inventory)
    site.page('evidence.html', 'Read and verify the evidence', body)
    return inventory


def research_examples(site):
    """Executable examples use the packer's actual schema, including split files."""
    first = next(((m, i) for m in sorted(site.data['models']) for i in sorted(site.data['tasks'])
                  if site.data['statuses'][m][i] == 'resolved'), None)
    attempt = ''
    if first:
        attempt = '''import gzip
import hashlib
import json
from pathlib import Path

root = Path("evidence")
path = Path(PATH_LITERAL)
with gzip.open(path, "rt", encoding="utf-8") as stream:
    attempt = json.load(stream)
print(sorted(attempt))
trajectory = attempt.get("trajectory") or {}
if "file" in trajectory and "sha256" in trajectory:
    raw = (root / trajectory["file"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != trajectory["sha256"]:
        raise ValueError("Trajectory checksum mismatch")
    trajectory = json.loads(gzip.decompress(raw))
print("Messages:", len(trajectory.get("messages", [])))
print("Status:", attempt["status"])
print("Exit status:", (attempt.get("result") or {}).get("exit_status"))
print("\\n".join((attempt.get("prediction") or {}).get("model_patch", "").splitlines()[:10]))
'''.replace('PATH_LITERAL', repr(site.evidence_path(*first)))
    matrix = '''import json
from pathlib import Path

rows = {p.parent.name: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(Path("evidence/models").glob("*/results.json"))}
expected_models = EXPECTED_MODELS
expected_tasks = EXPECTED_TASKS
if set(rows) != set(expected_models) or any(set(r) != set(expected_tasks) for r in rows.values()):
    raise ValueError("Incomplete pack: model/task coverage differs from this release")
if any(r["status"] not in ("resolved", "unresolved") for tasks in rows.values() for r in tasks.values()):
    raise ValueError("Provisional grades: unique-solve counts can change")
models = sorted(rows)
solved_by = {task: [rows[m][task]["status"] == "resolved" for m in models]
             for task in sorted(expected_tasks)}
for column, model in enumerate(models):
    unique = sum(values[column] and sum(values) == 1 for values in solved_by.values())
    print(model, unique)
'''
    # Read task IDs from the release CSV instead of embedding a large ID list.
    matrix = matrix.replace('import json\n', 'import csv\nimport json\n', 1)
    matrix = matrix.replace('expected_tasks = EXPECTED_TASKS',
        'with Path("docs/data/results.csv").open(newline="", encoding="utf-8") as stream:\n'
        '    expected_tasks = {row["instance_id"] for row in csv.DictReader(stream)}')
    matrix = matrix.replace('EXPECTED_MODELS', repr(sorted(site.data['models'])))
    return dict(attempt=attempt, matrix=matrix, first=first)


def research_licence():
    path = ROOT/'LICENSE'
    if not path.is_file():
        return ''
    copyright_line = next((line.strip() for line in path.read_text().splitlines()
                           if line.strip().startswith('Copyright (c) ')), None)
    if not copyright_line:
        raise ValueError('LICENSE has no copyright line')
    return (f'<p class="muted">Licence: MIT, {E(copyright_line.rstrip("."))}. '
            'See <a href="../LICENSE">LICENSE</a> and <a href="../NOTICE">NOTICE</a>.</p>')


def build_research(site, inventory):
    d = site.data
    models, tasks = len(d['models']), len(d['tasks'])
    solved = solve_counts(d)
    graded = sum(r['graded'] for r in d['boards']['Full'].values())
    attempts = models*tasks
    examples = research_examples(site)
    config = read_json(ROOT/'tools/partners.json')
    checked = datetime.fromisoformat(config['research_sources_checked_at'])
    facts = dict(models=models, tasks=tasks, attempts=attempts, graded=graded,
                 provisional=graded != attempts, none=solved[0], every=solved[models],
                 exactly_one=solved[1], evidence=inventory, example=examples['first'],
                 sources_checked_at=checked.date().isoformat())
    coverage = (f'<p class="notice">Archive coverage: {number(inventory["available"])} / '
                f'{number(attempts)} attempts have bundles packaged at build time. ')
    coverage += ('The archive is not packaged yet. ' if not inventory['available'] else
                 'The archive is incomplete. ' if inventory['available'] < attempts else '')
    coverage += 'See <a href="evidence.html">evidence availability and verification</a> before running the examples.</p>'
    paired = (f'<p class="notice">Provisional paired counts: {number(graded)} / {number(attempts)} '
              'attempts graded. Pending and missing results can change these counts; '
              'a task with no recorded resolution is not necessarily a failure for every model.</p>') if facts['provisional'] else ''
    archive = (f'{number(inventory["files"])} files are present at build time; compressed files total '
               f'{inventory["compressed_bytes"]/1_000_000_000:.6f} GB '
               f'({number(inventory["compressed_bytes"])} bytes).')
    if inventory['indexed']:
        archive += (f' The packaged indexes cover {number(inventory["indexed"])} attempts and record '
                    f'these totals: trajectories, {number(inventory["trajectories"])}; '
                    f'trajectory messages, {number(inventory["messages"])}.')
    attempt_example = ('<pre id="read-attempt"><code>'+E(examples['attempt'])+'</code></pre>'
                       if examples['first'] else '<p>No resolved attempt is recorded yet; the example will appear after grading.</p>')
    citation = ('@misc{spec_kitty_swe_bench,\n'
                f'  title = {{{HEADLINE}}},\n'
                '  author = {{Spec Kitty} and {TokenFactory} and {exe.dev}},\n'
                f'  year = {{{checked.year}}},\n'
                f'  url = {{{config["repository_url"]}}}\n'
                '}')
    body = Template((ROOT/'tools/site_assets/research.html').read_text()).substitute(
        glossary=glossary(d), attempts=number(attempts), models=number(models), tasks=number(tasks),
        none=number(solved[0]), every=number(solved[models]), exactly_one=number(solved[1]),
        archive=E(archive), coverage=coverage, paired=paired, attempt_example=attempt_example,
        matrix_example=E(examples['matrix']), citation=E(citation),
        checked=f'{checked.day} {checked.strftime("%B")} {checked.year}',
        licence=research_licence())
    site.json('data/research.json', facts)
    site.page('research.html', 'For researchers: what you can do with the evidence', body)


def source_commit(source):
    result = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    value = result.stdout.strip()
    return value if result.returncode == 0 and re.fullmatch(r'[0-9a-f]{40,64}', value) else 'unavailable (no source Git commit)'


def build(source=DEFAULT_SOURCE, out=ROOT/'docs', limit=None, generated_at=None, publish=False, staging=False):
    source, out = Path(source).resolve(), Path(out).resolve()
    if not out.is_relative_to(ROOT) or out == ROOT or out.is_relative_to(ROOT/'vendor'):
        raise ValueError('Output must be a dedicated directory inside the publication repository')
    if limit is not None and limit <= 0:
        raise ValueError('Trajectory limit must be positive')
    require_sources(source)
    snapshot = FrozenSource(source)
    fingerprints = snapshot.fingerprints
    data = load_data(snapshot)
    # Default timestamp is deterministic for an unchanged source snapshot.
    epoch = snapshot.epoch
    generated = generated_at or datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec='seconds')
    datetime.fromisoformat(generated.replace('Z', '+00:00'))
    commit = source_commit(source)
    metrics = collect_metrics(snapshot, data, ROOT/'.cache/build-site/metrics.sqlite3', limit)
    site = Site(snapshot, out, data, generated, commit, limit, publish=publish, staging=staging)
    site.assets()
    build_leaderboard(site, metrics)
    build_models(site, metrics)
    build_compare(site)
    build_instances(site)
    build_methodology(site, metrics)
    inventory = build_evidence(site)
    build_research(site, inventory)
    build_about(site)
    buf = io.StringIO(newline='')
    writer = csv.writer(buf, lineterminator='\n')
    writer.writerow(['model', 'instance_id', 'repo', 'status'])
    for model in sorted(data['models']):
        for instance in sorted(data['tasks']):
            writer.writerow([model, instance, data['tasks'][instance], data['statuses'][model][instance]])
    site.write('data/results.csv', buf.getvalue())
    site.page('404.html', 'This page is missing', '<p>The link may be out of date. <a href="index.html">Return to the leaderboard</a> or <a href="instances.html">find a task</a>.</p>')
    site.write('.nojekyll', '')
    site.write('robots.txt', 'User-agent: *\n' + ('Disallow' if staging else 'Allow') + ': /\n')
    site.json('data/build-info.json', {'generated_for_snapshot': generated, 'source_commit': commit,
              'source_hashes': fingerprints, 'trajectory_limit_per_model': limit,
              'publish': publish, 'staging': staging,
              'publication_hashes': {p: digest(ROOT/p) for p in (
                  'tools/partners.json', 'tools/projects.json', 'tools/build_site.py', 'tools/site_assets/infrastructure.html',
                  'tools/site_assets/research.html',
                  'tools/pack_evidence.py', 'tools/site_assets/charts.js', 'tools/site_assets/site.css',
                  'tools/site_assets/site.js', 'tools/site_assets/theme.js', 'vendor/echarts/VENDORED.json')},
              'metric_definition': 'API calls; sums of observed assistant response usage, missing is null',
              'confidence': CONFIDENCE, 'source_policy': 'Validated report exports; no source scripts executed',
              'verified_policy': 'subsets.py export; supplemental astropy__astropy-7606 contract',
              'evidence_repo_slug': 'owner__repository',
              'unavailable': ['outage rerun attribution', 'gateway-stall timeout attribution']})
    # Delete only obsolete files owned by a previous successful build.
    manifest_path = out/'data/site-files.json'
    previous = read_json(manifest_path) if manifest_path.exists() else []
    site.json('data/site-files.json', sorted(site.files | {'data/site-files.json'}))
    for relative in set(previous)-site.files:
        p = (out/relative).resolve()
        if p.is_relative_to(out) and p.is_file():
            p.unlink()
    for relative in sorted(site.files):
        safe_bytes((out/relative).read_bytes(), relative)
    guard_docs(out)
    print(f'Built {len(site.files)} files. Credential-marker and publication language scans passed. Output: {out}')
    return site


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--output', type=Path, default=ROOT/'docs')
    parser.add_argument('--limit', type=int, help='Maximum trajectories per model; never limits score rows')
    parser.add_argument('--generated-at', help='Explicit ISO-8601 timestamp; default uses latest report mtime')
    parser.add_argument('--check-only', action='store_true', help='Scan every existing output text file without rebuilding')
    parser.add_argument('--publish', action='store_true', help='Use GitHub download/source links and project-site metadata')
    parser.add_argument('--staging', action='store_true', help='Ask search engines not to index any page')
    args = parser.parse_args()
    try:
        if args.check_only:
            guard_docs(args.output)
            print('Publication guards passed.')
        else:
            if args.publish and not args.staging:
                print('Warning: --publish without --staging allows search indexing; use --staging for partner review.', file=sys.stderr)
            build(args.source, args.output, args.limit, args.generated_at, publish=args.publish, staging=args.staging)
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        # Avoid propagating any source text in diagnostics.
        message = str(exc)
        try:
            safe_bytes(message.encode(), 'error')
        except ValueError:
            message = 'Input error; details withheld by credential-marker scan'
        print('Build failed: '+message, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
