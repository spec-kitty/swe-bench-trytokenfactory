#!/usr/bin/env python3
"""Pack collected SWE-bench evidence, without executing source scripts or using a network."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
from collections import deque
import multiprocessing
from concurrent.futures import ProcessPoolExecutor

_FORK = multiprocessing.get_context('fork')


REPO = Path(__file__).resolve().parents[1]
SCHEMA = 1
MAX_COMPRESSED = 90_000_000
STATUSES = {"resolved", "unresolved", "ungraded", "missing"}
# Literal markers that have no innocent use in this evidence: fail closed.
FORBIDDEN = (b"tf_api_key", b"exe-integration")
# Credential-shaped tokens. A bare word such as "Bearer" appears in ordinary source code
# the models edited (HTTP auth in psf/requests), so only token-shaped values are rejected.
FORBIDDEN_PATTERNS = (
    # API keys are one unbroken run of letters and digits after an optional vendor prefix.
    # Hyphenated words such as the CSS class sk-who-uses-carousel-img in scikit-learn do not match.
    re.compile(rb"\bsk-(?:proj-|ant-|live-|test-)?[A-Za-z0-9]{20,}"),
    re.compile(rb"\bbearer\s+[A-Za-z0-9._~+/=-]{24,}", re.IGNORECASE),
    re.compile(rb"\b(?:ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
)
_SECRET_VALUES: list = []


def load_secret_values(source):
    """Exact credential values from <source>/.env and PACK_EXTRA_SECRETS; never printed."""
    values = [v.encode() for v in os.environ.get("PACK_EXTRA_SECRETS", "").split(",") if len(v) >= 12]
    env = Path(source) / ".env"
    if env.is_file():
        for line in env.read_text(errors="replace").splitlines():
            name, sep, value = line.partition("=")
            value = value.strip().strip("\"'")
            if sep and re.search(r"KEY|TOKEN|SECRET|PASSWORD", name, re.IGNORECASE) and len(value) >= 12:
                values.append(value.encode())
    _SECRET_VALUES[:] = values
ATTEMPT_JSON = {
    "prediction": "prediction.json", "result": "result.json", "grade": "grade.json",
    "isolation": "isolation.json", "trajectory": "trajectory.json",
    "adjudication": "timeout-adjudication.json",
}
GRADING_FILES = {
    "eval_script": "eval.sh", "applied_patch": "patch.diff", "report": "report.json",
    "test_output": "test_output.txt", "run_instance_log": "run_instance.log",
}
SELECTION_PREFIX = "<!-- pack-evidence-selection: "


class PackError(Exception):
    """An error whose message contains no collected source text."""


def require(condition, message):
    if not condition:
        raise PackError(message)


def scan(data: bytes):
    """Never print a match, surrounding text, or source filename on rejection."""
    lowered = data.lower()
    bad = (any(marker in lowered for marker in FORBIDDEN)
           or any(pattern.search(data) for pattern in FORBIDDEN_PATTERNS)
           or any(secret in data for secret in _SECRET_VALUES))
    require(not bad, "Secret scan rejected content; no matching text was printed.")


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def component(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", value)
            and value not in {".", ".."}, "Unsafe path component.")
    return value


def repo_slug(repo):
    require(isinstance(repo, str) and len(repo.split("/")) == 2, "Invalid repository name.")
    return "__".join(component(part) for part in repo.split("/"))


def read_bytes(path):
    # Do not follow links out of collected evidence (including parent links).
    require(not any(p.is_symlink() for p in (path, *path.parents)), "Symlink in input path.")
    if not path.exists():
        return None
    require(path.is_file(), "Expected an input file.")
    return path.read_bytes()


def parse(raw):
    return None if raw is None else json.loads(raw)


def text_value(raw):
    # decode() preserves CRLF, bare CR, trailing newlines, and all collected text.
    return None if raw is None else raw.decode("utf-8")


def atomic_write(path, data):
    if path.name.endswith(".gz"):
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            for _ in scan_chunks(iter(lambda: stream.read(65536), b"")):
                pass
    else:
        scan(data)
    require(not any(p.is_symlink() for p in (path, *path.parents)), "Symlink in output path.")
    if path.is_file() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pack-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def json_chunks(value):
    """Canonical JSON without allocating an encoded copy of large strings/containers."""
    if isinstance(value, str):
        yield b'"'
        for start in range(0, len(value), 65536):
            yield encoded(value[start:start + 65536])[1:-1]
        yield b'"'
    elif isinstance(value, (list, dict)):
        mapping = isinstance(value, dict)
        yield b"{" if mapping else b"["
        for index, item in enumerate(sorted(value) if mapping else value):
            if index:
                yield b","
            if mapping:
                yield from json_chunks(item)
                yield b":"
                item = value[item]
            yield from json_chunks(item)
        yield b"}" if mapping else b"]"
    else:
        yield encoded(value)


def scan_chunks(chunks):
    overlap = max([512, *(len(v) for v in _SECRET_VALUES)])
    tail = b""
    for chunk in chunks:
        scan(tail + chunk)
        tail = (tail + chunk)[-overlap:]
        yield chunk


def compressed(value, limit=None):
    stream = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=stream, compresslevel=9, mtime=0) as gz:
        for chunk in scan_chunks(json_chunks(value)):
            gz.write(chunk)
            if limit is not None and stream.tell() > limit:
                break
    return stream.getvalue()


def multipart(trajectory, relative, out):
    """Consecutive message batches; oversized messages use lossless canonical JSON fragments."""
    require(isinstance(trajectory, dict) and isinstance(trajectory.get("messages"), list),
            "Multipart trajectory requires a messages list.")
    references = []
    prefix = relative.removesuffix(".json.gz") + ".trajectory.part"

    def emit(value):
        data = compressed(value, MAX_COMPRESSED)
        if len(data) > MAX_COMPRESSED:
            return False
        name = f"{prefix}{len(references) + 1:03d}.json.gz"
        atomic_write(out / name, data)
        references.append({"file": name, "sha256": digest(data)})
        return True

    # Metadata stays in the first part, including an empty messages list.
    require(emit(dict(trajectory, messages=[])), "Trajectory metadata exceeds compressed size limit.")

    def batch(messages, start):
        if emit({"messages": messages}):
            return
        if len(messages) > 1:
            middle = len(messages) // 2
            batch(messages[:middle], start)
            batch(messages[middle:], start + middle)
            return
        # Spool canonical ASCII JSON to disk instead of duplicating a huge message in RAM.
        with tempfile.TemporaryFile() as stream:
            for chunk in scan_chunks(json_chunks(messages[0])):
                stream.write(chunk)
            total = stream.tell()
            stream.seek(0)
            offset = 0
            size = max(1, MAX_COMPRESSED // 4)
            while fragment := stream.read(size):
                value = {"message_fragment": {"index": start, "offset": offset,
                         "text": fragment.decode("ascii"), "final": stream.tell() == total}}
                require(emit(value), "Message fragment exceeds compressed size limit.")
                offset += len(fragment)

    messages = trajectory["messages"]
    for start in range(0, len(messages), 128):
        batch(messages[start:start + 128], start)
    return {"files": references, "parts": len(references)}


def load_context(source):
    with (source / "artifacts/report/instances.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    statuses = {}
    for row in rows:
        key = (component(row["model"]), component(row["instance_id"]))
        require(key not in statuses, "Duplicate status row.")
        require(row["status"] in STATUSES, "Unknown status.")
        statuses[key] = row["status"]
    dataset = {}
    with (source / "artifacts/datasets/agent-input.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            instance = component(row["instance_id"])
            require(instance not in dataset, "Duplicate dataset instance.")
            repo_slug(row["repo"])
            dataset[instance] = {k: row[k] for k in ("repo", "base_commit")}
    amendments = parse(read_bytes(source / "artifacts/report/grading-amendments.json")) or []
    reviews = parse(read_bytes(source / "artifacts/report/test-timeout-reviews.json")) or []
    require(isinstance(amendments, list) and isinstance(reviews, list), "Invalid report metadata.")
    amend_index = {r["instance"]: r for r in amendments}
    review_index = {(r["model"], r["instance"]): r for r in reviews}
    require(len(amend_index) == len(amendments) and len(review_index) == len(reviews),
            "Duplicate report metadata.")
    return statuses, dataset, amend_index, review_index


def select(statuses, models=None, limit=None):
    available = sorted({model for model, _ in statuses})
    models = available if models is None else sorted(set(models))
    require(bool(models) and set(models) <= set(available), "Unknown or empty model selection.")
    require(limit is None or limit > 0, "Limit must be positive.")
    keys = []
    for model in models:
        ids = sorted(i for (m, i), status in statuses.items() if m == model and status != "missing")
        keys.extend((model, i) for i in (ids if limit is None else ids[:limit]))
    return keys, {"models": models, "limit": limit}


def locate(source, keys):
    """Visit each worker's v2 tree once; never inspect v1 or superseded attempts."""
    wanted = set(keys)
    models = {m for m, _ in keys}
    found = {}
    for worker in sorted((source / "artifacts/fleet-backups").iterdir()):
        root = worker / "runs/v2"
        if not root.is_dir():
            continue
        for model in sorted(root.iterdir()):
            if model.name not in models or not model.is_dir():
                continue
            for attempt in sorted(model.iterdir()):
                key = (model.name, attempt.name)
                if key in wanted and attempt.is_dir():
                    require(key not in found, "Duplicate collected attempt.")
                    found[key] = (attempt, worker)
    require(set(found) == wanted, "A selected nonmissing attempt has no collected directory.")
    return found


TRUST_CACHE = False  # --trust-cache: accept cached outputs whose bytes verify, skipping the multi-GB source re-read


def gather(attempt, worker, model, instance, skip_trajectory=False):
    raw = {}
    for name in [*ATTEMPT_JSON.values(), "config.json", "generate.log", "grade.log", "verified-grade.json"]:
        raw[name] = None if skip_trajectory and name == "trajectory.json" else read_bytes(attempt / name)
    for label, grade_name in [("grading", "grade.json"), ("verified_grading", "verified-grade.json")]:
        grade = parse(raw[grade_name]) or {}
        run_id = grade.get("run_id")
        root = (worker / "logs/run_evaluation" / component(run_id) / model / instance) if run_id else None
        for name in GRADING_FILES.values():
            raw[f"{label}/{name}"] = read_bytes(root / name) if root else None
    history = attempt / "grading-history"
    if history.exists():
        for path in sorted(history.rglob("*")):
            require(not path.is_symlink(), "Symlink in grading history.")
            if path.is_file():
                relative = path.relative_to(attempt).as_posix()
                for part in path.relative_to(attempt).parts:
                    component(part)
                raw[relative] = read_bytes(path)
    for value in raw.values():
        if value is not None:
            for _ in scan_chunks(memoryview(value)[i:i + 65536].tobytes()
                                 for i in range(0, len(value), 65536)):
                pass
    return raw


def grading_values(raw, label):
    return {key: (parse if key == "report" else text_value)(raw[f"{label}/{name}"])
            for key, name in GRADING_FILES.items()}


def metrics(payload):
    trajectory = payload.get("trajectory") or {}
    messages = trajectory.get("messages", [])
    stats = (trajectory.get("info") or {}).get("model_stats") or {}
    responses = [m.get("extra", {}).get("response") for m in messages if m.get("extra")]
    responses = [r for r in responses if isinstance(r, dict)]
    tokens = [(r.get("usage") or {}).get("completion_tokens") for r in responses]
    tokens = [t for t in tokens if t is not None]
    return {
        "status": payload["status"], "exit_status": (payload["result"] or {}).get("exit_status"),
        "grade_reason": (payload["grade"] or {}).get("reason"),
        "amended": bool((payload["grade"] or {}).get("grading_amendment")),
        "adjudicated": payload["adjudication"] is not None,
        "messages": len(messages) if payload["trajectory"] is not None else None,
        "api_calls": stats.get("api_calls", len(responses) if responses else None),
        "completion_tokens": sum(tokens) if tokens else None,
        "completion_token_usage_records": len(tokens),
    }


def prediction_row(payload):
    prediction = payload["prediction"]
    if prediction is None:
        return None
    require(prediction.get("instance_id") == payload["instance_id"]
            and prediction.get("model_name_or_path") == payload["model"], "Prediction identity mismatch.")
    require(isinstance(prediction.get("model_patch"), str), "Invalid prediction patch.")
    return {key: prediction[key] for key in ("instance_id", "model_name_or_path", "model_patch")}


def unpack(path, out):
    payload = json.loads(gzip.decompress(path.read_bytes()))
    reference = payload.get("trajectory")
    if isinstance(reference, dict) and "file" in reference and "sha256" in reference:
        expected = path.with_name(path.name.removesuffix(".json.gz") + ".trajectory.json.gz")
        require(reference["file"] == expected.relative_to(out).as_posix(), "Invalid trajectory reference.")
        require(file_digest(expected) == reference["sha256"], "Trajectory checksum mismatch.")
        payload["trajectory"] = json.loads(gzip.decompress(expected.read_bytes()))
    elif isinstance(reference, dict) and "files" in reference:
        refs = reference["files"]
        require(isinstance(refs, list) and refs and reference.get("parts") == len(refs),
                "Invalid trajectory part count.")
        trajectory = None
        fragment = None
        for number, ref in enumerate(refs, 1):
            expected = path.with_name(path.name.removesuffix(".json.gz") + f".trajectory.part{number:03d}.json.gz")
            require(ref["file"] == expected.relative_to(out).as_posix(), "Invalid trajectory part reference.")
            require(expected.is_file() and file_digest(expected) == ref["sha256"], "Trajectory part checksum mismatch.")
            require(expected.stat().st_size <= MAX_COMPRESSED, "Trajectory part exceeds compressed size limit.")
            with gzip.open(expected, "rb") as stream:
                part = json.load(stream)
            if number == 1:
                require(isinstance(part.get("messages"), list) and not part["messages"], "Invalid first trajectory part.")
                trajectory = part
            elif "message_fragment" in part:
                item = part["message_fragment"]
                if fragment is None:
                    fragment = tempfile.TemporaryFile(mode="w+", encoding="ascii", newline="")
                require(item["index"] == len(trajectory["messages"]) and item["offset"] == fragment.tell(),
                        "Invalid message fragment sequence.")
                fragment.write(item["text"])
                if item["final"]:
                    fragment.seek(0)
                    trajectory["messages"].append(json.load(fragment))
                    fragment.close()
                    fragment = None
            else:
                require(fragment is None and set(part) == {"messages"} and isinstance(part["messages"], list),
                        "Invalid trajectory messages part.")
                trajectory["messages"].extend(part["messages"])
        require(fragment is None, "Incomplete message fragments.")
        payload["trajectory"] = trajectory
    for _ in scan_chunks(json_chunks(payload)):
        pass
    return payload


_LARGE_ATTEMPT_LOCK = _FORK.Lock()


def pack_one(key, location, context, out, cache, tool_hash):
    trajectory = location[0] / "trajectory.json"
    if trajectory.exists() and trajectory.stat().st_size > 64_000_000:
        with _LARGE_ATTEMPT_LOCK:
            return _pack_one(key, location, context, out, cache, tool_hash)
    return _pack_one(key, location, context, out, cache, tool_hash)


def _pack_one(key, location, context, out, cache, tool_hash):
    model, instance = key
    statuses, dataset, amendments, reviews = context
    attempt, worker = location
    require(instance in dataset, "Attempt absent from dataset.")
    metadata = dict(schema=SCHEMA, model=model, instance_id=instance, **dataset[instance],
                    worker=component(worker.name), status=statuses[key],
                    reviewed_test_timeout=reviews.get(key))
    cache_path = cache / f"{digest(encoded(key))}.json"
    trusted = TRUST_CACHE and cache_path.exists()
    raw = gather(attempt, worker, model, instance, skip_trajectory=trusted)
    grade = parse(raw["grade.json"])
    amendment = amendments.get(instance) if (grade or {}).get("grading_amendment") else None
    require(not (grade or {}).get("grading_amendment") or amendment is not None,
            "Amended grade has no report amendment entry.")
    metadata["grading_amendment"] = amendment
    scan(encoded(metadata))
    fingerprint = digest(encoded({"tool": tool_hash, "metadata": metadata,
                                  "files": {n: digest(v) if v is not None else None for n, v in raw.items()}}))
    relative = f"models/{model}/attempts/{repo_slug(metadata['repo'])}/{instance}.json.gz"
    path = out / relative
    old = parse(read_bytes(cache_path)) if cache_path.exists() else None
    reused = False
    if old and (trusted or old.get("input") == fingerprint):
        outputs = old["outputs"]
        allowed = {relative, relative.removesuffix(".json.gz") + ".trajectory.json.gz"}
        allowed.update(p for p in outputs if re.fullmatch(
            re.escape(relative.removesuffix(".json.gz")) + r"\.trajectory\.part[0-9]{3,}\.json\.gz", p))
        if relative in outputs and set(outputs) <= allowed and all(
                (out / p).is_file() and file_digest(out / p) == sha for p, sha in outputs.items()):
            raw.pop("trajectory.json", None)
            payload = unpack(path, out)
            config = parse(raw["config.json"])
            reused = True
    if not reused:
        if trusted:
            raw = gather(attempt, worker, model, instance)
        config = parse(raw["config.json"])
        payload = dict(metadata, **{key: parse(raw[name]) for key, name in ATTEMPT_JSON.items()},
                       config_sha256=digest(encoded(config)) if config is not None else None,
                       protocol_amendment=(config or {}).get("protocol_amendment"),
                       generate_log=text_value(raw["generate.log"]), grade_log=text_value(raw["grade.log"]),
                       grading=grading_values(raw, "grading"),
                       grading_history={n.removeprefix("grading-history/"): text_value(v)
                                        for n, v in raw.items() if n.startswith("grading-history/")})
        if raw["verified-grade.json"] is not None:
            payload["supplemental_verified"] = {
                "grade": parse(raw["verified-grade.json"]), "grading": grading_values(raw, "verified_grading")}
        raw.pop("trajectory.json", None)
        prediction_row(payload)
        # Scan decoded strings too: JSON escapes must not conceal a forbidden marker.
        scan(encoded(config))
        for _ in scan_chunks(json_chunks(payload)):
            pass
        packed = compressed(payload, MAX_COMPRESSED)
        outputs = {}
        if len(packed) > MAX_COMPRESSED:
            require(payload["trajectory"] is not None, "Oversize attempt has no trajectory to split.")
            trajectory_path = relative.removesuffix(".json.gz") + ".trajectory.json.gz"
            trajectory_bytes = compressed(payload["trajectory"], MAX_COMPRESSED)
            if len(trajectory_bytes) <= MAX_COMPRESSED:
                reference = {"file": trajectory_path, "sha256": digest(trajectory_bytes)}
                atomic_write(out / trajectory_path, trajectory_bytes)
                outputs[trajectory_path] = digest(trajectory_bytes)
            else:
                del trajectory_bytes
                reference = multipart(payload["trajectory"], relative, out)
                outputs.update((ref["file"], ref["sha256"]) for ref in reference["files"])
            split_payload = dict(payload, trajectory=reference)
            packed = compressed(split_payload, MAX_COMPRESSED)
            require(len(packed) <= MAX_COMPRESSED, "Attempt still exceeds compressed size limit after splitting.")
        atomic_write(path, packed)
        outputs[relative] = digest(packed)
        atomic_write(cache_path, encoded({"input": fingerprint, "outputs": outputs}))
    return {"key": key, "prediction": prediction_row(payload), "metrics": metrics(payload),
            "config": config, "config_sha256": payload["config_sha256"],
            "outputs": outputs, "reused": reused}


def output_files(out):
    files = {}
    for path in sorted(out.rglob("*")):
        require(not path.is_symlink(), "Symlink in evidence tree.")
        if path.is_file():
            relative = path.relative_to(out).as_posix()
            scan(relative.encode())
            require("\n" not in relative and "\\" not in relative, "Unsafe manifest filename.")
            files[relative] = path
    # Path ordering compares components; manifest ordering compares whole strings.
    return dict(sorted(files.items()))


def size_summary(out):
    files = output_files(out)
    by_model = {}
    for name, path in files.items():
        if name.startswith("models/"):
            model = name.split("/")[1]
            by_model[model] = by_model.get(model, 0) + path.stat().st_size
    sizes = {name: p.stat().st_size for name, p in files.items()}
    largest = max(sizes, key=lambda name: (sizes[name], name)) if sizes else None
    return {"bytes_per_model": by_model, "total_bytes": sum(sizes.values()),
            "largest_file": largest, "largest_file_bytes": sizes.get(largest, 0),
            "split_trajectories": sum(n.endswith((".trajectory.json.gz", ".trajectory.part001.json.gz")) for n in files)}


def readme(selection, context, records, out):
    statuses = context[0]
    chosen = selection["models"]
    full = [s for (m, _), s in statuses.items() if m in chosen]
    graded = sum(s in {"resolved", "unresolved"} for s in full)
    sizes = size_summary(out)
    lines = ["# SWE-bench evidence", "", "We preserve the collected evidence for each included attempt. You can browse the model indexes and verify every published file.", "",
             f"Schema: {SCHEMA}. Included attempts: {len(records)}. Eligible attempts in selected models: {sum(s != 'missing' for s in full)}.",
             f"Full grading coverage in selected models: {graded}/{len(full)} ({100 * graded / len(full):.3f}%). "
             + ("Results are provisional while grading coverage is incomplete." if graded != len(full) else "Full grading coverage is complete."),
             "This tree is a limited sample." if selection["limit"] is not None else "This tree includes every eligible attempt in the selected models.", "",
             SELECTION_PREFIX + encoded(selection).decode() + " -->", "",
             "## Files and schema", "",
             "- `models/<model>/predictions.jsonl`: submitted predictions in SWE-bench format, sorted by instance ID. Attempts without a prediction have no prediction row.",
             "- `models/<model>/results.json`: instance ID to status, exit status, grade reason, amendment/adjudication flags, message count, API calls, and completion tokens. Missing observations are null. Completion tokens sum available response usage records; the usage-record count exposes partial reporting. API calls use trajectory model statistics, falling back to recorded responses.",
             "- `configs.json`: canonical JSON SHA-256 to `{config, models}`; identical config objects share an entry. Hashes cover compact, sorted-key, ASCII-escaped JSON without a trailing newline.",
             "- `models/<model>/attempts/<repo-slug>/<instance_id>.json.gz`: schema, model, instance_id, repo, base_commit, worker, status, prediction, result, grade, isolation, config_sha256, protocol_amendment, generate_log, grade_log, trajectory, grading, grading_amendment, adjudication, grading_history, reviewed_test_timeout.",
             "- `grading` contains eval_script, applied_patch, report (parsed JSON), test_output and run_instance_log. Absent files are null. Text is UTF-8, untruncated, with original line endings. Invalid UTF-8 fails packing. grading_history maps relative filenames to collected text.",
             "- `supplemental_verified`, when present, preserves verified-grade.json and its harness evidence separately. Full statuses always come directly from report/instances.csv, following report.py; subset verdicts are not inferred from Full. subsets.py handles the supplemental Verified contract.",
             f"- Gzip uses level 9 and mtime=0. Attempts above {MAX_COMPRESSED} compressed bytes move trajectory to a sibling `.trajectory.json.gz`; trajectory becomes `{{file, sha256}}` with an evidence-relative path and compressed-file digest. Larger trajectories use `{{files:[{{file, sha256}}, ...], parts:N}}` referencing consecutive `.trajectory.partNNN.json.gz` files. The first part preserves all non-message fields with an empty messages list; concatenate messages from subsequent parts. Oversized individual messages use `message_fragment` objects with zero-based message index, ASCII byte offset, text, and final flag: concatenate text and JSON-decode to restore the original message. No message is truncated. Metadata or the remaining attempt exceeding the limit fails packing.",
             "- `MANIFEST.sha256` lists every evidence file except itself, sorted by evidence-relative path. Resume fingerprints live outside this tree under the repository's ignored `.cache/`.", "",
             "## Verify and reproduce", "", "From the repository root:", "", "```sh",
             "python3 tools/pack_evidence.py --source /Users/robert/spec-kitty-evals --out " + out.name + " --verify",
             "cd " + out.name + " && shasum -a 256 -c MANIFEST.sha256", "```", "",
             "Verification is read-only and uses the selection recorded above; it checks every file, manifest membership, identity, source statuses, indexes and references. To rebuild, omit --verify and use the same --models and --limit selection. Without source data, the manifest still checks file integrity; hashes are not an independent authenticity signature.",
             "Packing into an existing generated tree replaces its selection and removes obsolete generated files after successful packing. Interrupted runs can resume from per-attempt content fingerprints and output checksums. A source-content change always invalidates its attempt cache. Forbidden publication markers abort packing without printing matched content.", "",
             "## Sizes", "", "Sizes below include model evidence and indexes, excluding this README, configs and manifest.", "", "| Model | Bytes |", "| --- | ---: |"]
    lines.extend(f"| {m} | {sizes['bytes_per_model'].get(m, 0)} |" for m in chosen)
    lines += ["", f"Model files total: {sum(sizes['bytes_per_model'].values())} bytes.",
              f"Split trajectories: {sizes['split_trajectories']}.", ""]
    return "\n".join(lines).encode()


def pack(source, out, models=None, limit=None, jobs=8, cache=None):
    source, out = Path(source).resolve(), Path(out).absolute()
    require(not any(p.is_symlink() for p in (out, *out.parents)), "Symlink in output path.")
    out = out.resolve()
    cache = Path(cache) if cache else REPO / ".cache/pack-evidence" / digest(str(out).encode())
    # Cache may be inside this publication repository, which itself is under source.
    require(out != source and (source not in out.parents or (REPO in out.parents and out != REPO)),
            "Output must not modify the read-only source tree.")
    require(out != REPO and out not in source.parents, "Unsafe output location.")
    require(source not in cache.resolve().parents or REPO in cache.resolve().parents,
            "Cache must not modify the read-only source tree.")
    require(jobs > 0, "Jobs must be positive.")
    context = load_context(source)
    keys, selection = select(context[0], models, limit)
    locations = locate(source, keys)
    tool_hash = digest(Path(__file__).read_bytes() + encoded(MAX_COMPRESSED))
    records = []
    print(f"Packing {len(keys)} attempts across {len(selection['models'])} models.", flush=True)
    with ProcessPoolExecutor(max_workers=jobs, mp_context=_FORK) as pool:
        # Bound work in flight: fail quickly, and do not retain every raw trajectory.
        pending = deque()
        remaining = iter(keys)
        def submit_next():
            key = next(remaining, None)
            if key is not None:
                pending.append(pool.submit(pack_one, key, locations[key], context, out, cache, tool_hash))
        for _ in range(jobs * 2):
            submit_next()
        try:
            while pending:
                records.append(pending.popleft().result())
                if len(records) % 25 == 0 or len(records) == len(keys):
                    print(f"Packed {len(records)}/{len(keys)}; reused {sum(r['reused'] for r in records)}.", flush=True)
                submit_next()
        except BaseException:
            for future in pending:
                future.cancel()
            raise
    expected = {"README.md", "MANIFEST.sha256", "configs.json"}
    configs = {}
    for model in selection["models"]:
        model_records = [r for r in records if r["key"][0] == model]
        predictions = b"".join(encoded(r["prediction"]) + b"\n" for r in model_records if r["prediction"] is not None)
        result_index = {r["key"][1]: r["metrics"] for r in model_records}
        for name, data in [("predictions.jsonl", predictions), ("results.json", encoded(result_index))]:
            relative = f"models/{model}/{name}"
            atomic_write(out / relative, data)
            expected.add(relative)
        for record in model_records:
            expected.update(record["outputs"])
            sha = record["config_sha256"]
            if sha is not None:
                entry = configs.setdefault(sha, {"config": record["config"], "models": []})
                if model not in entry["models"]:
                    entry["models"].append(model)
    atomic_write(out / "configs.json", encoded(configs))
    for relative, path in output_files(out).items():
        if relative not in expected:
            require(relative.startswith("models/") and (relative.endswith(".json.gz") or
                    relative.endswith("/results.json") or relative.endswith("/predictions.jsonl")),
                    "Unexpected file in output tree; refusing to remove it.")
            path.unlink()
    atomic_write(out / "README.md", readme(selection, context, records, out))
    manifest = "".join(f"{file_digest(path)}  {relative}\n" for relative, path in output_files(out).items()
                       if relative != "MANIFEST.sha256")
    atomic_write(out / "MANIFEST.sha256", manifest.encode())
    summary = size_summary(out)
    summary["attempts"] = len(records)
    summary["reused"] = sum(r["reused"] for r in records)
    print(encoded(summary).decode(), flush=True)
    return summary


def verify(source, out, models=None, limit=None):
    out = Path(out)
    context = load_context(Path(source))
    files = output_files(out)
    require("MANIFEST.sha256" in files and "README.md" in files, "Missing manifest or README.")
    manifest = {}
    lines = (out / "MANIFEST.sha256").read_text().splitlines()
    for line in lines:
        require(re.fullmatch(r"[0-9a-f]{64}  .+", line) is not None, "Invalid manifest line.")
        sha, relative = line.split("  ", 1)
        require(relative not in manifest, "Duplicate manifest entry.")
        manifest[relative] = sha
    require(list(manifest) == sorted(manifest), "Manifest is not sorted.")
    require(set(manifest) == set(files) - {"MANIFEST.sha256"}, "Manifest file membership mismatch.")
    for relative, sha in manifest.items():
        require(file_digest(files[relative]) == sha, "Manifest checksum mismatch.")
        if relative.endswith(".gz"):
            require(files[relative].stat().st_size <= MAX_COMPRESSED, "Evidence file exceeds compressed size limit.")
        else:
            scan(files[relative].read_bytes())
    readme_text = (out / "README.md").read_text()
    selections = [line for line in readme_text.splitlines() if line.startswith(SELECTION_PREFIX)]
    require(len(selections) == 1 and selections[0].endswith(" -->"), "Missing or invalid selection metadata.")
    selection = json.loads(selections[0][len(SELECTION_PREFIX):-4])
    if models is not None:
        require(sorted(set(models)) == selection["models"], "Requested models differ from packed selection.")
    if limit is not None:
        require(limit == selection["limit"], "Requested limit differs from packed selection.")
    keys, _ = select(context[0], selection["models"], selection["limit"])
    configs = json.loads((out / "configs.json").read_bytes())
    expected = {"README.md", "MANIFEST.sha256", "configs.json"}
    config_models = {}
    for sha, entry in configs.items():
        require(digest(encoded(entry["config"])) == sha, "Config digest mismatch.")
    for model in selection["models"]:
        metrics_index, predictions = {}, []
        for m, instance in keys:
            if m != model:
                continue
            metadata = context[1][instance]
            relative = f"models/{model}/attempts/{repo_slug(metadata['repo'])}/{instance}.json.gz"
            require(relative in files, "Selected attempt is missing from evidence tree.")
            expected.add(relative)
            stored = json.loads(gzip.decompress(files[relative].read_bytes()))
            if isinstance(stored.get("trajectory"), dict) and "file" in stored["trajectory"]:
                expected.add(stored["trajectory"]["file"])
            if isinstance(stored.get("trajectory"), dict) and "files" in stored["trajectory"]:
                expected.update(ref["file"] for ref in stored["trajectory"]["files"])
            payload = unpack(files[relative], out)
            require(payload["schema"] == SCHEMA and payload["model"] == model and payload["instance_id"] == instance,
                    "Attempt schema or path identity mismatch.")
            require(payload["status"] == context[0][(model, instance)], "Attempt status disagrees with instances.csv.")
            require(all(payload[k] == metadata[k] for k in ("repo", "base_commit")), "Dataset metadata mismatch.")
            require(payload["reviewed_test_timeout"] == context[3].get((model, instance)), "Timeout review mismatch.")
            amendment = context[2].get(instance) if (payload["grade"] or {}).get("grading_amendment") else None
            require(payload["grading_amendment"] == amendment, "Amendment mismatch.")
            sha = payload["config_sha256"]
            require(sha is None or sha in configs, "Unknown config reference.")
            if sha is not None:
                config_models.setdefault(sha, set()).add(model)
                require(payload["protocol_amendment"] == configs[sha]["config"].get("protocol_amendment"),
                        "Protocol amendment mismatch.")
            metrics_index[instance] = metrics(payload)
            prediction = prediction_row(payload)
            if prediction is not None:
                predictions.append(prediction)
            for group in [payload["grading"], *([payload["supplemental_verified"]["grading"]]
                          if "supplemental_verified" in payload else [])]:
                require(set(group) == set(GRADING_FILES), "Invalid grading schema.")
        result_path = f"models/{model}/results.json"
        prediction_path = f"models/{model}/predictions.jsonl"
        expected.update([result_path, prediction_path])
        require(json.loads((out / result_path).read_bytes()) == metrics_index, "Results index mismatch.")
        actual = [json.loads(line) for line in (out / prediction_path).read_bytes().splitlines()]
        require(actual == predictions, "Predictions index mismatch.")
    require(set(files) == expected, "Unexpected evidence files.")
    require(set(configs) == set(config_models) and all(configs[sha]["models"] == sorted(ms)
                                                    for sha, ms in config_models.items()), "Config model index mismatch.")
    print(f"Verified {len(keys)} attempts and {len(files)} files.", flush=True)
    print(encoded(size_summary(out)).decode(), flush=True)
    return len(keys)


def main(argv=None):
    global TRUST_CACHE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("evidence"))
    parser.add_argument("--models", nargs="+")
    parser.add_argument("--limit", type=int, help="First N eligible instances per model, sorted by ID")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--trust-cache", action="store_true", help="Reuse cached outputs whose digests verify, without re-reading source trajectories")
    parser.add_argument("--verify", action="store_true", help="Read-only verification; never repairs files")
    args = parser.parse_args(argv)
    load_secret_values(args.source)
    try:
        if args.verify:
            verify(args.source, args.out, args.models, args.limit)
        else:
            TRUST_CACHE = args.trust_cache
            pack(args.source, args.out, args.models, args.limit, args.jobs)
    except Exception as error:
        # Parser exceptions can contain collected data. Only our fixed messages are printable.
        message = str(error) if isinstance(error, PackError) else f"Invalid or unreadable evidence ({type(error).__name__})."
        print(f"Error: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
