# Build the benchmark site

Run from this publication repository with Python 3.11 or later. The builder uses only the standard library, reads the collected source tree, and never executes source scripts, contacts the gateway, or changes Git history.

```sh
python3 tools/build_site.py --source /Users/robert/spec-kitty-evals
python3 -m unittest discover -s tests -v
python3 tools/check_links.py docs
```

For a faster preview, add `--limit 3`. This caps trajectory inspection per model, in sorted instance-ID order. Benchmark scores, coverage, outcomes and paired comparisons still use the full report. The page labels sampled medians explicitly. Omit the limit for publication.

Choose one of three build modes:

| Mode | Command | Links and indexing |
| --- | --- | --- |
| Local preview | `python3 tools/build_site.py --output preview-local` | Document-relative links, including checkout evidence and source files; indexing allowed. Serve the repository root. |
| Public release | `python3 tools/build_site.py --publish --output preview-public` | GitHub downloads and source links; canonical and Open Graph URLs; indexing allowed. Prints a warning because partner review needs staging. |
| Partner review | `python3 tools/build_site.py --publish --staging --output preview-staging` | Same publish links; every page has `noindex,nofollow` and `robots.txt` disallows crawling. |

Preview output folders must be dedicated directories inside this repository. These commands leave `docs/` intact. `--staging` also works with local builds. Without staging, the robots meta tag is omitted and `robots.txt` allows crawling. Rebuilding in another mode replaces these settings deterministically. Staging is a search-engine instruction, not access control.

`tools/partners.json` defines `repository_url`, `branch` and `site_url`. GitHub Pages serves `docs/` from `main` at `https://spec-kitty.github.io/swe-bench-trytokenfactory/`. Publish mode maps evidence downloads to GitHub `/raw/<branch>/` URLs and source files or folders to `/blob/<branch>/` or `/tree/<branch>/`. These links work without JavaScript. Ordinary pages retain document-relative site links; the 404 page prefixes internal links and assets with the configured site sub-path so it works at any missing URL depth. Canonical and `og:url` values identify each HTML file under `site_url`.

Check a publish output offline:

```sh
python3 tools/check_links.py --publish preview-staging
python3 tools/build_site.py --check-only --output preview-staging
python3 tools/check_license.py
node --check preview-staging/assets/site.js
```

The publish-aware checker maps configured GitHub raw/blob/tree URLs back to files in this checkout, checks internal links and rejects relative paths outside the Pages root. It never fetches external links. Use `--repository-root` when checking against another checkout. The licence gate also requires the configured repository URL to match the repository named in `README.md`.

After review, the owner can generate the first committed preview with `python3 tools/build_site.py --publish --staging` and check it with `python3 tools/check_links.py --publish docs`. Omit `--limit` for that build.

The builder validates the Full CSV against summary and repository exports. Verified uses the authoritative `subsets.py` export; only its supplemental `astropy__astropy-7606` contract may differ from Full. It checks generation exit counts against `generation-outcomes.json`. Report inputs are frozen in memory before inspecting attempts. Conflicting source exports fail the build instead of producing a mixed checkpoint; later report updates do not change a captured checkpoint. Attempts still marked missing in that checkpoint are excluded from usage inspection. Source scripts are read for provenance hashes, never executed.

Trajectory metrics are cached in `.cache/build-site/metrics.sqlite3`. Cache entries contain safe scalar metadata, keyed by extraction semantics and input content hashes. Transactions checkpoint during inspection, so an interrupted build can resume. Changed input bytes invalidate the entry even if file size and timestamp are unchanged. The cache is local and should remain ignored.

Outputs use stable ordering and atomic per-file replacement. Unchanged files retain their timestamps. The generated file manifest removes only obsolete builder-owned outputs. By default, the displayed generation timestamp is anchored to the latest source report timestamp; use `--generated-at` with an ISO-8601 value to supply a reproducible release timestamp. Build provenance records source commit and hashes; an uncommitted source change remains visible through its file hash.

Evidence paths match `tools/pack_evidence.py`. Absent bundles show “Evidence not packaged” rather than dead links. Rebuild after packing to expose downloads and update archive size. The evidence page documents the bundle schema, split trajectories, configuration hashes and verification. The packer’s manifest entries are relative to `evidence/`, so checksum verification must run inside that directory. Packer verification also requires `--source`.

For local viewing, serve the repository root and open `/docs/` (or the chosen output folder). Publish mode emits GitHub evidence links in the HTML and supplies the same configured download base to the task explorer. Evidence is outside the Pages document root. No browser/network operation is required to build or check links. Google Fonts links are included as requested; system fallbacks work offline.

All generated files and cached metric text pass the credential-marker scanner before writing. Exact public design-system class names are allowlisted because their required namespace overlaps the short key-prefix marker; arbitrary strings with that prefix still fail. Word-internal occurrences in ordinary prose are not key prefixes. No raw trajectories, configuration objects, prompts, logs or environment values are copied into site data. The evidence packer has its own stricter archive scanner.

Known data limits: supplied inputs do not identify the backend-outage rerun population or establish gateway-stall causation for each Kimi timeout. Those counts remain unavailable; outer timeout and wall-budget exit counts are shown separately. The site uses saved official comparison metadata, never a live lookup. Scores describe the collected scaffold/gateway run, not interchangeable base models.

Partner publication is configured in `tools/partners.json`. Names, URLs and footer roles live there; `{model_count}` expands from the validated experiment. The shared page shell includes the partner strip, footer, metadata and about-page navigation on every page, including model pages and the missing-page fallback. Spec Kitty uses the vendored Day/Night head marks and spectacles favicon; partner wordmarks use ink.

The infrastructure account lives in `tools/site_assets/infrastructure.html`. The builder derives fleet size and creation span from `artifacts/fleet.json`, checks every member against `artifacts/upgrade-v2.json`, reads resource and concurrency settings from source scripts without executing them, and computes the clean-experiment telemetry window from `artifacts/telemetry-history.jsonl`. An observation qualifies when any worker's `experiments` list contains the exact configured experiment identifier. This is an observed window, not elapsed completion time. These inputs join the frozen checkpoint and provenance hashes; derived values are exported to `docs/data/infrastructure.json`.

Partner facts in `tools/partners.json` record the operators' VM-list observation and whole-collection exact-key search, with their dates and sources. The shared project tag comes from that VM-list observation; `tagged_workers` retains the count from the older fleet export. These partner facts are included in the infrastructure data and source detail. Prose rounds the creation and observation windows; the data and source detail retain exact values and timestamps. Upgrades may overlap across independently drained VMs, image pulls may recur after restarts, and moving hosts requires adapting provisioning and credential attachment. The packer's exact-value rejection is inspectable in its source. No integration endpoint is published.

Every generated text output passes a no-pricing language guard before writing. The final scan also covers unowned or stale HTML, JSON, CSV, JS, CSS and TXT files under the output directory. Dollar amounts and prohibited commercial words fail the build without echoing matching content. HTML entities and decoded JSON strings are checked. Financial fields containing `cost` anywhere in their key are removed recursively from exports; existing files with such fields fail validation. This does not modify the evidence packer's independent archive schema. Run both publication guards without rebuilding:

```sh
python3 tools/build_site.py --check-only --output docs
```

Regression tests cover the shared shell, partner links and metadata, source-derived counts and time windows, infrastructure prose length, both themes' text contrast, and language-guard failures. The infrastructure account is added to the existing methodology; incident disclosures remain intact. The about page increases the original site by one page.

The front page exports `docs/data/charts.json` and renders SVG charts with the locally vendored Apache ECharts library. Leaderboard tabs use the same Full, Verified and Lite boards as the table, including the supplemental Verified contract. Scores use resolved / graded; Wilson bounds use the existing confidence setting. Repository medians include observed scores only.

The accumulating step-area chart uses the union of resolved Full task IDs. Its `difficulty.orders` entries include a zero-model origin and each model's new and cumulative task counts. `score` follows Full leaderboard order; `greedy` repeatedly chooses the model adding the most unseen tasks, breaking ties by leaderboard score and then model ID. The top line is the complete task count; a hatched band identifies tasks no model solved. Both orders have HTML table fallbacks, and the keyboard-operated tabs animate between them unless reduced motion is requested. Phone layouts shorten model names and keep the chart horizontally scrollable so every step remains legible. Literal first-line issue quotes link to `instances.html?task=<instance_id>`, which loads that exact task automatically. The smaller chart counts tasks solved by just one model, including zero-count models. Both charts remain provisional while any Full result is pending.

The front page, methodology and research pages share the “Three words we use” strip. A task is a benchmark problem; an attempt is one model's try at one task; solved means the project's tests pass after the patch. Chart footers state the computed model × task total, while source filenames stay inside the table details. Step summaries explicitly name their inspected-attempt sample when a trajectory limit is used.

Outcome bars partition model/task slots in this order: resolved, pending or missing, adjudicated timeout, empty patch, remaining unresolved patch. Outer-process adjudications are deduplicated by model and instance; reviewed test timeouts join the timeout category. This prevents the empty predictions created by timeout adjudication from counting twice. The pending category appears only on provisional builds. Scatter medians call the same `usage_summary` function as model pages; missing values are omitted and named, and `--limit` is disclosed beside the chart.

Each chart has an accessible table that is open in the generated HTML. Tables remain open if JavaScript or local chart data is unavailable. Chart tabs have independent arrow-key, Home and End navigation. Theme changes and debounced resize events update existing SVG instances; reduced-motion preference disables animation. Chart colours come from computed design-system tokens. Mid-ramp heatmap numerals use token-derived ink/paper shades when the base token colours would fall below text contrast requirements.

The shared `modelFamily` function in `charts.js` maps DeepSeek to `build`, GLM to `role-frame`, Kimi to `factory`, Nemotron to `brain`, and MiniMax to `role-move`; unknown families use `ink-muted`. A Flash route uses the lighter fill only if the model list contains the same base without a Flash token; the current list makes only GLM Flash routes lighter. These routes mix the family colour with the surface in linear light, and uncensored/abliterated variants carry diagonal marks. Model-page SVG bars inherit the same function's CSS variable. Native legend buttons synchronise family dimming across the leaderboard, outcomes, heatmap and scatter; pressed means dimmed, and “Show all” resets every family. Outcomes use solid success, outlined accent-soft, warning-soft with a thin warning-ink hatch, and solid danger-ink with a two-pixel minimum width. Only no-patch segments carry a pattern. The exact accent-soft and warning-soft backgrounds have near-equal luminance; tests record that limitation and check adjacent area-averaged hatch treatments separately, rather than claiming the bare backgrounds meet a contrast threshold. Heatmap cells and their visual-map legend use a linear-light blue ramp clamped to observed scores, ordered from lighter to darker in both themes so the caption remains true. `tests/test_chart_palette.py` checks all real model IDs and samples the production ramp against both themes' CSS tokens for text contrast.

The build copies `echarts.min.js`, `LICENSE` and `NOTICE` verbatim to `docs/assets/vendor/echarts/`. The existing publication language guard's text-extension scope is unchanged. Its sole new exemption is the relative path `assets/vendor/echarts/echarts.min.js`, and only when the bytes match `vendor/echarts/VENDORED.json`'s SHA-256. The credential scan still checks the library and both legal files. A modified library or the same bytes at any other guarded path fails. Chart assets and the vendoring record join build provenance.

`tests/test_charts.py` checks chart math, real-data reconciliation, source parity, accessible fallbacks, local assets and the exact checksum exception. When Node is installed, `tests/charts_runtime.cjs` renders actual ECharts SVGs offline in both themes at the actual card widths for 375, 768 and 1280 px pages, exercises tabs, keyboard tooltips, resize and theme events, and checks heatmap text contrast. Geometry tests check every chart’s text bounds, rotated header separation, and scatter label separation. It makes no network requests. To save temporary SVG previews:

```sh
CHART_PREVIEW_DIR=/tmp/chart-previews node tests/charts_runtime.cjs
```

The research page uses `tools/site_assets/research.html` and exports its derived facts to `docs/data/research.json`. Its paired counts share the front-page cumulative-union and single-resolver calculations over Full report statuses. Counts remain provisional until every attempt is graded. Archive coverage is separate: the inventory counts existing bundles and compressed bytes, ignores atomic staging files, and reads message totals from packaged model indexes when available. It does not unpack trajectories just to count messages.

The examples select the first resolved attempt by model name and task ID, handle sibling trajectory files and their checksums, and refuse unique-solve counts when the pack is incomplete or grades are pending. Run them from the publication repository root after packing. `tests/test_research.py` executes the Python examples against inline and split bundles and complete, incomplete and pending result indexes; it also reconciles the built page against the real report and checks navigation, source links, guards and local links.

The research comparison copy and primary-source URLs are the supplied editorial snapshot; this build never fetches them. `research_sources_checked_at` and `repository_url` live in `tools/partners.json`. The citation uses that publication year and configured URL. The research licence line reads the year and holder from the first copyright line of `LICENSE` and links to `LICENSE` and `NOTICE`; it is omitted when `LICENSE` is absent. Publish footers also mention MIT and link to the configured repository. Local research footers point to the checkout README. The builder does not assign a separate data licence. Vendored chart assets are unchanged.

The official context strip sits directly above the existing official-leaderboard caveat. It reads only the saved Test (shown as Full), Verified and Lite boards, verifies their snapshot checksum, and exports a strict whitelist of entry fields. No official financial, image, or harness-artifact fields are copied. Snapshot attribution and exact route-name matches are recomputed; matches check both model display names and model tags, case-insensitively. Rejected entry text stops publication and identifies the entry without exposing credential markers.

The independent comparison tabs reuse our existing score boards and intervals. Three toggles combine with AND; All entries resets them. The generator computes each filter state's count, range, median and strict above/below counts. Empty filters and pending grades have explicit wording. A SHA-256-derived jitter map keeps dots in the same position across builds and filter changes; each subset retains its unfiltered percentage domain. Neutral official circles become diamonds for open-weight models, and mini-SWE-agent entries use solid ink. Our numbered markers reuse the family palette in two alternating rank rows. Only the leader and lowest score have direct labels; the key below lists every exact score. Minimal horizontal spacing prevents collisions and is disclosed beside the key. Official dots retain their exact scores and deterministic jitter, with a light frequency band and a median tick recomputed for the plotted entries.

Official tables are open without JavaScript, sortable by score, and update with the filters. Keyboard users can focus each dot row, then use arrow keys, Home and End to inspect entries; Escape closes the detail card. Runtime tests exercise the real vendored SVG renderer at phone and desktop widths, in both themes, including filter intersections, sorting, focus cards, tab independence and empty filters. Run all checks offline:

```sh
python3 -m unittest discover -s tests -v
python3 tools/build_site.py --check-only --output docs
python3 tools/check_links.py docs
node --check docs/assets/charts.js
python3 tools/check_license.py
```

Project descriptions live in `tools/projects.json`. Chart headings and captions derive their counts from the report. The steps headline uses Spearman correlation with average ranks for ties; undefined correlation uses the no-clear-link headline. A numbered model key stays beside the scatter on wide pages and below it on narrow pages. Reference captions sit outside the data area. These SVG and geometry checks complement, but do not replace, a real-browser check of full-page scroll and CSS layout.

To prepare a real-browser review without a server or any network requests, run
`python3 tests/browser_review.py --output /tmp/official-review.html` and open that
file in a browser. It embeds the complete generated page, local chart library,
styles and data in six fixed-width frames (375, 768 and 1280 px, both themes).
A content-security policy blocks network assets; fonts use offline fallbacks.
The page reports actual browser checks for horizontal scroll, control decoration
and bounds, model-key layout, label separation and keyboard cards. This review
complements the automated SVG and pure-geometry tests; generating it does not
mean its browser checks have run.

Limit effects are exported to `docs/data/limits.json` for Full, Verified and Lite.
An attempt counts only when `grade_reason == empty_patch` and its exit is
`ContextBudgetExceeded`, `TimeExceeded` or `OuterProcessTimeout`. Time combines
the latter two; shares use all subset tasks, including pending/missing tasks.
`LIMIT_CONSTRAINED_THRESHOLD` controls the inclusive marker threshold. All active
attempts are read even with `--limit`; supplemental Verified grading does not
change generation cut-offs. Incomplete coverage is labelled provisional.
The authors' separate sample observation is recorded in `tools/limit-observation.json`,
exported with provenance and hashed in build metadata; it is not recomputed from
sampled usage. The methodology explicitly describes the rerun as planned.
