# Testing the latest open-weight models against SWE-bench

We ran 12 models through the same agent, the same gateway and the official SWE-bench grader: 2,294 tasks each, 27,528 attempts, one attempt per model per task. This repository holds the results site and the evidence behind every number on it.

A joint project of [Spec Kitty](https://spec-kitty.ai), [TokenFactory](https://portal.trytokenfactory.dev/) and [exe.dev](https://exe.dev). Spec Kitty ran and graded the benchmark, TokenFactory provided the inference gateway, and exe.dev provided the VMs it ran on.

## What is here

| Path | What it holds |
| --- | --- |
| `docs/` | The static site, served by GitHub Pages. Generated; do not edit by hand. |
| `evidence/` | One gzip file per attempt (trajectory, patch, grade and harness logs), per-model `predictions.jsonl` and `results.json`, and a SHA-256 manifest. |
| `tools/` | `build_site.py` generates the site, `pack_evidence.py` builds the evidence tree, `check_links.py` and `check_license.py` are the checks. |
| `tests/` | Unit tests for the tools. |
| `vendor/` | The Spec Kitty design system and Apache ECharts, bundled unmodified. See `NOTICE`. |

## Verify the evidence

```bash
cd evidence
sha256sum -c MANIFEST.sha256        # on macOS: shasum -a 256 -c MANIFEST.sha256
```

Each attempt file is gzip-compressed JSON. The schema and a few starter snippets are on the site's *For researchers* and *Evidence* pages.

## Rebuild

The generators read the raw run data, which is not in this repository. With the source tree available:

```bash
python3 tools/pack_evidence.py --source /path/to/source-tree --out evidence --verify
python3 tools/build_site.py
python3 -m unittest discover -s tests
python3 tools/check_links.py docs
python3 tools/check_license.py
```

## Licence

MIT, Copyright (c) 2026 Spec Kitty, Inc. See `LICENSE`. Bundled third-party code, and the third-party text that the evidence files quote, are covered in `NOTICE`. A GitHub Actions workflow runs `tools/check_license.py` on every push so the licence, the notice and the bundled files cannot drift apart.
