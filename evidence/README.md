# SWE-bench evidence

We preserve the collected evidence for each included attempt. You can browse the model indexes and verify every published file.

Schema: 1. Included attempts: 27528. Eligible attempts in selected models: 27528.
Full grading coverage in selected models: 27528/27528 (100.000%). Full grading coverage is complete.
This tree includes every eligible attempt in the selected models.

<!-- pack-evidence-selection: {"limit":null,"models":["deepseek-v4.1-flash-1017","deepseek-v4.1-flash-1017-uncensored-fp8","glm-5.3","glm-5.3-flash","glm-5.3-flash-uncensored-fp8","glm-5.3-uncensored-fp8","kimi-k3","kimi-k3-abliterated","minimax-m3.1-flash","nemotron-3-super","nemotron-3-ultra","nemotron-3.5-lightning"]} -->

## Files and schema

- `models/<model>/predictions.jsonl`: submitted predictions in SWE-bench format, sorted by instance ID. Attempts without a prediction have no prediction row.
- `models/<model>/results.json`: instance ID to status, exit status, grade reason, amendment/adjudication flags, message count, API calls, and completion tokens. Missing observations are null. Completion tokens sum available response usage records; the usage-record count exposes partial reporting. API calls use trajectory model statistics, falling back to recorded responses.
- `configs.json`: canonical JSON SHA-256 to `{config, models}`; identical config objects share an entry. Hashes cover compact, sorted-key, ASCII-escaped JSON without a trailing newline.
- `models/<model>/attempts/<repo-slug>/<instance_id>.json.gz`: schema, model, instance_id, repo, base_commit, worker, status, prediction, result, grade, isolation, config_sha256, protocol_amendment, generate_log, grade_log, trajectory, grading, grading_amendment, adjudication, grading_history, reviewed_test_timeout.
- `grading` contains eval_script, applied_patch, report (parsed JSON), test_output and run_instance_log. Absent files are null. Text is UTF-8, untruncated, with original line endings. Invalid UTF-8 fails packing. grading_history maps relative filenames to collected text.
- `supplemental_verified`, when present, preserves verified-grade.json and its harness evidence separately. Full statuses always come directly from report/instances.csv, following report.py; subset verdicts are not inferred from Full. subsets.py handles the supplemental Verified contract.
- Gzip uses level 9 and mtime=0. Attempts above 90000000 compressed bytes move trajectory to a sibling `.trajectory.json.gz`; trajectory becomes `{file, sha256}` with an evidence-relative path and compressed-file digest. Larger trajectories use `{files:[{file, sha256}, ...], parts:N}` referencing consecutive `.trajectory.partNNN.json.gz` files. The first part preserves all non-message fields with an empty messages list; concatenate messages from subsequent parts. Oversized individual messages use `message_fragment` objects with zero-based message index, ASCII byte offset, text, and final flag: concatenate text and JSON-decode to restore the original message. No message is truncated. Metadata or the remaining attempt exceeding the limit fails packing.
- `MANIFEST.sha256` lists every evidence file except itself, sorted by evidence-relative path. Resume fingerprints live outside this tree under the repository's ignored `.cache/`.

## Verify and reproduce

From the repository root:

```sh
python3 tools/pack_evidence.py --source /Users/robert/spec-kitty-evals --out evidence --verify
cd evidence && shasum -a 256 -c MANIFEST.sha256
```

Verification is read-only and uses the selection recorded above; it checks every file, manifest membership, identity, source statuses, indexes and references. To rebuild, omit --verify and use the same --models and --limit selection. Without source data, the manifest still checks file integrity; hashes are not an independent authenticity signature.
Packing into an existing generated tree replaces its selection and removes obsolete generated files after successful packing. Interrupted runs can resume from per-attempt content fingerprints and output checksums. A source-content change always invalidates its attempt cache. Forbidden publication markers abort packing without printing matched content.

## Sizes

Sizes below include model evidence and indexes, excluding this README, configs and manifest.

| Model | Bytes |
| --- | ---: |
| deepseek-v4.1-flash-1017 | 470086711 |
| deepseek-v4.1-flash-1017-uncensored-fp8 | 500365265 |
| glm-5.3 | 197521589 |
| glm-5.3-flash | 150968840 |
| glm-5.3-flash-uncensored-fp8 | 172784025 |
| glm-5.3-uncensored-fp8 | 236656938 |
| kimi-k3 | 193474175 |
| kimi-k3-abliterated | 132017296 |
| minimax-m3.1-flash | 304890013 |
| nemotron-3-super | 192251250 |
| nemotron-3-ultra | 267471613 |
| nemotron-3.5-lightning | 333932888 |

Model files total: 3152420603 bytes.
Split trajectories: 1.
