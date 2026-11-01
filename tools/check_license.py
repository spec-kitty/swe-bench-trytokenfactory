#!/usr/bin/env python3
"""Licence drift gate: fails unless the repo meets the Spec Kitty licensing policy.

Policy: external distributions carry the verbatim MIT License with "Spec Kitty, Inc."
as the copyright holder (never "Contributors"), matching package metadata, a NOTICE
that reproduces the notices of bundled third-party code, and a gate that keeps all of
this from drifting. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path

HOLDER = "Spec Kitty, Inc."
YEAR = "2026"
MIT_TEXT = f"""MIT License

Copyright (c) {YEAR} {HOLDER}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".cache", "evidence", "evidence-sample", ".claude", ".agents", "agents"}
THIRD_PARTY_DIRS = (("vendor",), ("docs", "assets", "vendor"))
COPYRIGHT_LINE = re.compile(r"^\s*(?:#|//|\*|/\*)?\s*Copyright \(c\)[^\n]*$", re.IGNORECASE | re.MULTILINE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_third_party(rel: Path) -> bool:
    return any(rel.parts[: len(d)] == d for d in THIRD_PARTY_DIRS)


def check_license(root: Path, problems: list[str]) -> None:
    path = root / "LICENSE"
    if not path.is_file():
        problems.append("LICENSE is missing.")
        return
    text = path.read_text(encoding="utf-8")
    if text != MIT_TEXT:
        problems.append(f'LICENSE is not the verbatim MIT License with "Copyright (c) {YEAR} {HOLDER}".')
    if "Contributors" in text:
        problems.append('LICENSE names "Contributors" as the copyright holder; it must be "' + HOLDER + '".')


def check_metadata(root: Path, problems: list[str]) -> None:
    partners, readme = root / "tools/partners.json", root / "README.md"
    if not partners.is_file() or not readme.is_file():
        problems.append("tools/partners.json and README.md must identify the publication repository.")
    else:
        repository_url = json.loads(partners.read_text(encoding="utf-8")).get("repository_url")
        repositories = re.findall(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", readme.read_text(encoding="utf-8"))
        if not repository_url or repository_url not in repositories:
            problems.append("partners.json repository_url must match the repository named in README.md.")
    manifest = root / "package.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("license") != "MIT":
            problems.append('package.json license must be "MIT".')
        author = data.get("author")
        if author is not None and HOLDER not in (author if isinstance(author, str) else json.dumps(author)):
            problems.append(f'package.json author must be "{HOLDER}" when present.')
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
        lic = project.get("license")
        value = lic.get("text") if isinstance(lic, dict) else lic
        if value not in ("MIT", None) and "MIT" not in str(value):
            problems.append("pyproject.toml license must be MIT.")
        if value is None and "license-files" not in project:
            problems.append("pyproject.toml declares no license.")
        for author in project.get("authors", []):
            if HOLDER not in json.dumps(author):
                problems.append(f'pyproject.toml author must be "{HOLDER}".')
    for cff in (root / "CITATION.cff",):
        if cff.is_file() and "license: MIT" not in cff.read_text(encoding="utf-8"):
            problems.append("CITATION.cff must declare license: MIT.")


def bundled_components(root: Path):
    for manifest in sorted(root.glob("vendor/*/VENDORED.json")):
        yield manifest.parent, json.loads(manifest.read_text(encoding="utf-8"))


def check_notice(root: Path, problems: list[str]) -> None:
    path = root / "NOTICE"
    if not path.is_file():
        problems.append("NOTICE is missing.")
        return
    text = path.read_text(encoding="utf-8")
    if "licensed under the MIT License (see LICENSE)" not in text or f"Copyright (c) {YEAR} {HOLDER}" not in text:
        problems.append("NOTICE must state the MIT License and the Spec Kitty, Inc. copyright.")
    for folder, meta in bundled_components(root):
        name, version = meta.get("package", folder.name), meta.get("version", "")
        if name.lower() not in text.lower() or (version and version not in text):
            problems.append(f"NOTICE does not mention bundled {name} {version}.")
        upstream = folder / "NOTICE"
        if upstream.is_file():
            body = upstream.read_text(encoding="utf-8").strip()
            if body not in text:
                problems.append(f"NOTICE does not reproduce the upstream notice of {name}.")
        if not (folder / "LICENSE").is_file():
            problems.append(f"{folder.relative_to(root)}/LICENSE (upstream license text) is missing.")
        for relative in (meta.get("file"),):
            if not relative:
                continue
            artifact = next(iter(folder.glob(Path(relative).name)), None)
            recorded = meta.get("sha256")
            if artifact is None:
                problems.append(f"{name}: bundled file {Path(relative).name} is missing.")
            elif recorded and sha256(artifact) != recorded:
                problems.append(f"{name}: bundled file does not match the checksum in VENDORED.json.")
            published = root / "docs" / "assets" / "vendor" / folder.name / Path(relative).name
            if artifact is not None and published.is_file() and sha256(published) != sha256(artifact):
                problems.append(f"{name}: the published copy differs from the vendored copy.")


def check_copyright_lines(root: Path, problems: list[str]) -> None:
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if (set(rel.parts) & SKIP_DIRS) or not path.is_file() or is_third_party(rel):
            continue
        if rel.name in {"LICENSE", "NOTICE"} or path.suffix not in {".py", ".js", ".css", ".html", ".md", ".json", ".toml", ".yml", ".yaml", ".txt", ".sh"}:
            continue
        if rel == Path("tools/check_license.py") or rel == Path("tests/test_license.py"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line in COPYRIGHT_LINE.findall(text):
            if HOLDER not in line:
                problems.append(f"{rel}: copyright line names a holder other than {HOLDER}.")
                break


def run(root: Path) -> list[str]:
    problems: list[str] = []
    check_license(root, problems)
    check_metadata(root, problems)
    check_notice(root, problems)
    check_copyright_lines(root, problems)
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    problems = run(args.root)
    for problem in problems:
        print("licence gate:", problem, file=sys.stderr)
    if not problems:
        print("Licence gate passed.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
