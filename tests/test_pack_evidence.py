"""Offline standard-library tests for the publication packer."""
import contextlib
import csv
import gzip
import importlib.util
import io
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch


MODULE = Path(__file__).resolve().parents[1] / "tools/pack_evidence.py"
spec = importlib.util.spec_from_file_location("pack_evidence", MODULE)
pe = importlib.util.module_from_spec(spec)
import sys as _sys
_sys.modules['pack_evidence'] = pe
spec.loader.exec_module(pe)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.out = self.root / "evidence"
        self.cache = self.root / "cache"
        self.rows = [
            {"model": "model-a", "instance_id": "org__repo-1", "status": "resolved"},
            {"model": "model-a", "instance_id": "org__repo-2", "status": "unresolved"},
            {"model": "model-b", "instance_id": "org__repo-3", "status": "ungraded"},
            {"model": "model-b", "instance_id": "org__repo-4", "status": "missing"},
        ]
        self.write_statuses()
        data = [{"instance_id": f"org__repo-{i}", "repo": "org/repo", "base_commit": f"commit-{i}"}
                for i in range(1, 5)]
        self.write("artifacts/datasets/agent-input.jsonl", b"".join(pe.encoded(r) + b"\n" for r in data))
        self.amendment = {"id": "thread-fix", "instance": "org__repo-1", "reason": "Thread control"}
        self.review = {"model": "model-a", "instance": "org__repo-2", "classification": "timeout"}
        self.write_json("artifacts/report/grading-amendments.json", [self.amendment])
        self.write_json("artifacts/report/test-timeout-reviews.json", [self.review])
        self.attempts = {}
        for number, row in enumerate(self.rows[:3]):
            model, instance = row["model"], row["instance_id"]
            worker = "worker-1" if number < 2 else "worker-2"
            relative = f"artifacts/fleet-backups/{worker}/runs/v2/{model}/{instance}"
            self.attempts[(model, instance)] = self.source / relative
            files = {
                "prediction.json": {"model_name_or_path": model, "instance_id": instance, "model_patch": "diff\r\n+change\r\n"},
                "result.json": {"exit_status": "Submitted"},
                "config.json": {"agent": {"budget": 42}, "protocol_amendment": {"id": "protocol-update"}},
                "isolation.json": {"base_commit": f"commit-{number + 1}"},
                "trajectory.json": {"info": {"model_stats": {"api_calls": 2}}, "messages": [
                    {"role": "assistant", "content": "first", "extra": {"response": {"usage": {"completion_tokens": 5}}}},
                    {"role": "assistant", "content": "second", "extra": {"response": {"usage": {"completion_tokens": 0}}}},
                ]},
            }
            if number < 2:
                files["grade.json"] = {"run_id": f"run-{number}", "result": {"completed": True, "resolved": number == 0}}
            if number == 0:
                files["grade.json"]["grading_amendment"] = "thread-fix"
                self.write(f"{relative}/grading-history/nested/original.txt", b"original\r\nwith CR\rand LF\n")
            if number == 1:
                files["grade.json"]["reason"] = "reviewed_test_timeout"
                files["timeout-adjudication.json"] = {"reason": "outer_timeout", "inference_repeated": False}
            for name, value in files.items():
                self.write_json(f"{relative}/{name}", value)
            self.write(f"{relative}/generate.log", b"generated\r\nexact\rtext\n")
            self.write(f"{relative}/grade.log", b"graded\n")
            if number == 0:
                logs = f"artifacts/fleet-backups/{worker}/logs/run_evaluation/run-{number}/{model}/{instance}"
                for name in pe.GRADING_FILES.values():
                    self.write(f"{logs}/{name}", pe.encoded({instance: {"resolved": True}})
                               if name == "report.json" else b"evidence\r\n")
        # This archived attempt must never be traversed, parsed, scanned or counted.
        self.write("artifacts/fleet-backups/worker-1/runs/v2-superseded/model-a/org__repo-1/trajectory.json", b"broken")

    def write(self, relative, data):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def write_json(self, relative, data):
        self.write(relative, pe.encoded(data))

    def write_statuses(self):
        path = self.source / "artifacts/report/instances.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["model", "instance_id", "status"])
            writer.writeheader()
            writer.writerows(self.rows)

    def pack(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return pe.pack(self.source, self.out, cache=self.cache, **kwargs)

    def verify(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return pe.verify(self.source, self.out, **kwargs)

    def payload_path(self, model="model-a", instance="org__repo-1"):
        return self.out / f"models/{model}/attempts/org__repo/{instance}.json.gz"

    def payload(self, **kwargs):
        return pe.unpack(self.payload_path(**kwargs), self.out)

    def snapshot(self):
        return {p.relative_to(self.out).as_posix(): p.read_bytes() for p in self.out.rglob("*") if p.is_file()}

    def remanifest(self):
        files = pe.output_files(self.out)
        manifest = "".join(f"{pe.file_digest(p)}  {name}\n" for name, p in files.items() if name != "MANIFEST.sha256")
        (self.out / "MANIFEST.sha256").write_text(manifest)

    def rewrite_payload(self, mutate):
        path = self.payload_path()
        payload = json.loads(gzip.decompress(path.read_bytes()))
        mutate(payload)
        path.write_bytes(pe.compressed(payload))
        self.remanifest()

    def test_pack_schema_indexes_and_verify(self):
        source_before = {p: p.read_bytes() for p in self.source.rglob("*") if p.is_file()}
        summary = self.pack(jobs=2)
        self.assertEqual(summary["attempts"], 3)
        self.assertEqual(summary["split_trajectories"], 0)
        amended = self.payload()
        self.assertEqual(amended["grading_amendment"], self.amendment)
        self.assertEqual(amended["generate_log"], "generated\r\nexact\rtext\n")
        self.assertEqual(amended["grading_history"]["nested/original.txt"], "original\r\nwith CR\rand LF\n")
        adjudicated = self.payload(instance="org__repo-2")
        self.assertIsNotNone(adjudicated["adjudication"])
        self.assertEqual(adjudicated["reviewed_test_timeout"], self.review)
        self.assertTrue(all(v is None for v in adjudicated["grading"].values()))
        self.assertIsNone(self.payload(model="model-b", instance="org__repo-3")["grade"])
        self.assertFalse(self.payload_path(model="model-b", instance="org__repo-4").exists())
        configs = json.loads((self.out / "configs.json").read_bytes())
        self.assertEqual(len(configs), 1)
        self.assertEqual(next(iter(configs.values()))["models"], ["model-a", "model-b"])
        results = json.loads((self.out / "models/model-a/results.json").read_bytes())
        self.assertEqual(results["org__repo-1"]["completion_tokens"], 5)
        self.assertEqual(results["org__repo-1"]["messages"], 2)
        self.assertEqual(results["org__repo-1"]["api_calls"], 2)
        self.assertTrue(results["org__repo-1"]["amended"])
        self.assertTrue(results["org__repo-2"]["adjudicated"])
        predictions = [json.loads(line) for line in (self.out / "models/model-a/predictions.jsonl").read_bytes().splitlines()]
        self.assertEqual([r["instance_id"] for r in predictions], ["org__repo-1", "org__repo-2"])
        self.assertEqual(self.verify(), 3)
        self.assertIn("provisional", (self.out / "README.md").read_text())
        self.assertEqual(source_before, {p: p.read_bytes() for p in self.source.rglob("*") if p.is_file()})

    def test_determinism_resume_and_corrupt_output_repair(self):
        self.pack(jobs=1)
        first = self.snapshot()
        times = {p: p.stat().st_mtime_ns for p in self.out.rglob("*") if p.is_file()}
        summary = self.pack(jobs=3)
        self.assertEqual(summary["reused"], 3)
        self.assertEqual(self.snapshot(), first)
        self.assertEqual(times, {p: p.stat().st_mtime_ns for p in times})
        self.payload_path().write_bytes(b"corrupted")
        self.assertEqual(self.pack()["reused"], 2)
        self.assertEqual(self.snapshot(), first)
        # Rebuild without cache also produces identical gzip bytes and indexes.
        with contextlib.redirect_stdout(io.StringIO()):
            pe.pack(self.source, self.out, cache=self.root / "fresh-cache", jobs=2)
        self.assertEqual(self.snapshot(), first)

    def test_input_change_invalidates_fingerprint_even_same_size_and_mtime(self):
        self.pack()
        path = self.attempts[("model-a", "org__repo-1")] / "generate.log"
        before = path.stat()
        path.write_bytes(path.read_bytes().replace(b"exact", b"other"))
        import os
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual(self.pack()["reused"], 2)
        self.assertIn("other", self.payload()["generate_log"])
        self.assertEqual(self.verify(), 3)

    def test_verify_detects_checksum_identity_status_index_and_missing_file(self):
        self.pack()
        original = self.snapshot()
        mutations = [
            lambda: self.payload_path().write_bytes(b"bad"),
            lambda: self.rewrite_payload(lambda p: p.update(model="other-model")),
            lambda: self.rewrite_payload(lambda p: p.update(instance_id="org__repo-2")),
            lambda: self.rewrite_payload(lambda p: p.update(status="unresolved")),
            lambda: (self.out / "models/model-a/results.json").write_text("{}"),
            lambda: self.payload_path().unlink(),
            lambda: (self.out / "extra.txt").write_text("extra"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                for p in self.out.rglob("*"):
                    if p.is_file() and p.relative_to(self.out).as_posix() not in original:
                        p.unlink()
                for relative, data in original.items():
                    (self.out / relative).write_bytes(data)
                mutate()
                with self.assertRaises(pe.PackError):
                    self.verify()

    def test_verify_detects_source_status_change(self):
        self.pack()
        self.rows[0]["status"] = "unresolved"
        self.write_statuses()
        with self.assertRaisesRegex(pe.PackError, "status"):
            self.verify()

    def test_secrets_abort_without_echoing_or_publishing(self):
        for marker in pe.FORBIDDEN:
            with self.subTest(marker_index=pe.FORBIDDEN.index(marker)):
                path = self.attempts[("model-a", "org__repo-1")] / "generate.log"
                path.write_bytes(b"private " + marker.upper() + b"sensitive-value")
                output = io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    code = pe.main(["--source", str(self.source), "--out", str(self.out), "--jobs", "1"])
                self.assertEqual(code, 1)
                self.assertNotIn(marker, output.getvalue().lower().encode())
                self.assertNotIn("sensitive-value", output.getvalue())
                self.assertFalse(self.payload_path().exists())
                self.assertFalse((self.out / "MANIFEST.sha256").exists())

    def test_scan_is_credential_shaped_not_substring(self):
        pe.load_secret_values(self.source)
        for innocent in (b"img.sk-who-uses-carousel-img {", b"sk-estimator-doc-link", b"Authorization: Bearer", b"def task-list and risk-free mask-all disk-usage", b"the bearer of news"):
            pe.scan(innocent)
        for secret in (b"sk-" + b"a" * 24, b"Authorization: Bearer " + b"A1b2" * 8, b"ghp_" + b"x" * 30):
            with self.assertRaises(pe.PackError):
                pe.scan(secret)

    def test_exact_env_secret_value_is_rejected_without_echo(self):
        (self.source / ".env").write_text("TF_API_KEY=abcdefghijklmnop12345\n")
        pe.load_secret_values(self.source)
        try:
            with self.assertRaises(pe.PackError) as caught:
                pe.scan(b"log line abcdefghijklmnop12345 more")
            self.assertNotIn("abcdefghijklmnop12345", str(caught.exception))
        finally:
            pe._SECRET_VALUES[:] = []

    def test_escaped_json_secret_and_cached_source_secret_abort(self):
        self.pack()
        path = self.attempts[("model-a", "org__repo-1")] / "trajectory.json"
        path.write_bytes(b'{"messages":[],"private":"\\u0062earer ' + b"A1b2" * 8 + b'"}')
        with self.assertRaisesRegex(pe.PackError, "Secret scan"):
            self.pack()
        self.assertNotIn(b"A1b2A1b2", gzip.decompress(self.payload_path().read_bytes()))

    def test_limit_models_and_changed_selection_remove_stale_outputs(self):
        self.pack()
        self.pack(models=["model-a"], limit=1)
        self.assertEqual(self.verify(), 1)
        self.assertFalse(self.payload_path(instance="org__repo-2").exists())
        self.assertFalse((self.out / "models/model-b/results.json").exists())
        with self.assertRaises(pe.PackError):
            self.verify(limit=2)
        with self.assertRaises(pe.PackError):
            self.pack(models=["absent"])

    def test_duplicate_attempts_fail_and_archives_are_ignored(self):
        self.pack()
        path = self.source / "artifacts/fleet-backups/worker-duplicate/runs/v2/model-a/org__repo-1"
        path.mkdir(parents=True)
        with self.assertRaisesRegex(pe.PackError, "Duplicate"):
            self.pack()

    def test_supplemental_verified_evidence_is_preserved(self):
        attempt = self.attempts[("model-a", "org__repo-1")]
        (attempt / "verified-grade.json").write_bytes(pe.encoded({"run_id": "verified-run", "result": {"completed": True, "resolved": False}}))
        self.write("artifacts/fleet-backups/worker-1/logs/run_evaluation/verified-run/model-a/org__repo-1/test_output.txt", b"supplemental\r\n")
        self.pack()
        payload = self.payload()
        self.assertEqual(payload["status"], "resolved")
        self.assertEqual(payload["supplemental_verified"]["grading"]["test_output"], "supplemental\r\n")
        self.assertEqual(self.verify(), 3)

    def test_trajectory_split_resume_verify_and_cleanup(self):
        rng = random.Random(7)
        trajectory = {"messages": [{"role": "assistant", "content": "".join(rng.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=9000))}]}
        attempt = self.attempts[("model-a", "org__repo-1")]
        (attempt / "trajectory.json").write_bytes(pe.encoded(trajectory))
        self.pack(models=["model-a"], limit=1)
        full_size = self.payload_path().stat().st_size
        trajectory_size = len(pe.compressed(trajectory))
        self.assertLess(trajectory_size, full_size)
        with patch.object(pe, "MAX_COMPRESSED", (full_size + trajectory_size) // 2):
            summary = self.pack(models=["model-a"], limit=1)
            self.assertEqual(summary["split_trajectories"], 1)
            self.assertEqual(self.payload()["trajectory"], trajectory)
            self.assertEqual(self.verify(), 1)
            first = self.snapshot()
            self.assertEqual(self.pack(models=["model-a"], limit=1)["reused"], 1)
            self.assertEqual(first, self.snapshot())
            sidecar = self.payload_path().with_name("org__repo-1.trajectory.json.gz")
            sidecar.write_bytes(b"corrupt")
            with self.assertRaises(pe.PackError):
                self.verify()
            self.assertEqual(self.pack(models=["model-a"], limit=1)["reused"], 0)
        self.pack(models=["model-a"], limit=1)
        self.assertFalse(sidecar.exists())
        self.assertEqual(self.verify(), 1)

    def test_multipart_pack_resume_verify_tamper_and_cleanup(self):
        rng = random.Random(11)
        trajectory = {"info": {"model_stats": {"api_calls": 40}}, "other": {"kept": True},
                      "messages": [{"role": "assistant", "content": "".join(
                          rng.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=3000))}
                          for _ in range(40)]}
        attempt = self.attempts[("model-a", "org__repo-1")]
        (attempt / "trajectory.json").write_bytes(pe.encoded(trajectory))
        with patch.object(pe, "MAX_COMPRESSED", 6000):
            summary = self.pack(models=["model-a"], limit=1)
            self.assertEqual(summary["split_trajectories"], 1)
            stored = json.loads(gzip.decompress(self.payload_path().read_bytes()))
            reference = stored["trajectory"]
            self.assertGreater(reference["parts"], 2)
            self.assertEqual(reference["parts"], len(reference["files"]))
            for number, ref in enumerate(reference["files"], 1):
                part = self.out / ref["file"]
                self.assertTrue(part.name.endswith(f".trajectory.part{number:03d}.json.gz"))
                self.assertLessEqual(part.stat().st_size, pe.MAX_COMPRESSED)
            first_part = json.loads(gzip.decompress((self.out / reference["files"][0]["file"]).read_bytes()))
            self.assertEqual(first_part, dict(trajectory, messages=[]))
            self.assertEqual(self.payload()["trajectory"], trajectory)
            self.assertEqual(self.verify(), 1)
            first = self.snapshot()
            self.assertEqual(self.pack(models=["model-a"], limit=1)["reused"], 1)
            self.assertEqual(first, self.snapshot())
            with contextlib.redirect_stdout(io.StringIO()):
                pe.pack(self.source, self.out, models=["model-a"], limit=1,
                        cache=self.root / "fresh-cache", jobs=2)
            self.assertEqual(first, self.snapshot())
            part = self.out / reference["files"][1]["file"]
            part.write_bytes(pe.compressed({"messages": []}))
            # Even updating the manifest cannot hide a broken attempt-to-part digest.
            self.remanifest()
            with self.assertRaisesRegex(pe.PackError, "part checksum"):
                self.verify()
            self.assertEqual(self.pack(models=["model-a"], limit=1)["reused"], 0)
            self.assertEqual(first, self.snapshot())
            self.rewrite_payload(lambda p: p["trajectory"].update(parts=999))
            with self.assertRaisesRegex(pe.PackError, "part count"):
                self.verify()
        self.pack(models=["model-a"], limit=1)
        self.assertFalse(list(self.out.rglob("*.trajectory.part*.json.gz")))
        self.assertEqual(self.verify(), 1)

    def test_multipart_large_message_is_lossless(self):
        rng = random.Random(19)
        message = {"role": "assistant", "content": "".join(
            rng.choices("abcdef0123456789\n\t\"\\é😀", k=30000)),
            "extra": {"response": {"usage": {"completion_tokens": 37}}}}
        trajectory = {"messages": [{"content": "before"}, message, {"content": "after"}]}
        attempt = self.attempts[("model-a", "org__repo-1")]
        (attempt / "trajectory.json").write_bytes(pe.encoded(trajectory))
        with patch.object(pe, "MAX_COMPRESSED", 12000):
            self.pack(models=["model-a"], limit=1)
            self.assertEqual(self.payload()["trajectory"], trajectory)
            self.assertEqual(self.verify(), 1)
            parts = [json.loads(gzip.decompress(p.read_bytes()))
                     for p in sorted(self.out.rglob("*.trajectory.part*.json.gz"))]
            fragments = [p["message_fragment"] for p in parts if "message_fragment" in p]
            self.assertGreater(len(fragments), 1)
            self.assertEqual(json.loads("".join(f["text"] for f in fragments)), message)
            self.assertTrue(fragments[-1]["final"])
            self.assertTrue(all(f["index"] == 1 for f in fragments))

    def test_streamed_encoding_matches_existing_format(self):
        value = {"z": "é😀\n\t\"\\" * 20000, "a": [None, True, 1.5, {"b": 2}]}
        self.assertEqual(b"".join(pe.json_chunks(value)), pe.encoded(value))
        stream = io.BytesIO()
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, compresslevel=9, mtime=0) as gz:
            gz.write(pe.encoded(value))
        self.assertEqual(pe.compressed(value), stream.getvalue())

    def test_oversize_split_fails(self):
        with patch.object(pe, "MAX_COMPRESSED", 10):
            with self.assertRaises(pe.PackError):
                self.pack(models=["model-a"], limit=1)

    def test_readonly_verify_does_not_repair(self):
        self.pack()
        before = self.snapshot()
        with patch.object(pe, "atomic_write", side_effect=AssertionError("verify wrote files")):
            self.assertEqual(self.verify(), 3)
        self.assertEqual(before, self.snapshot())

    def test_manifest_order_with_model_name_prefixes(self):
        old = self.attempts[("model-b", "org__repo-3")].parent
        new = old.with_name("model-a-extra")
        old.rename(new)
        prediction = new / "org__repo-3/prediction.json"
        value = json.loads(prediction.read_bytes())
        value["model_name_or_path"] = new.name
        prediction.write_bytes(pe.encoded(value))
        for row in self.rows:
            if row["model"] == "model-b":
                row["model"] = new.name
        self.write_statuses()
        self.pack()
        self.assertEqual(self.verify(), 3)
        names = [line.split("  ", 1)[1] for line in (self.out / "MANIFEST.sha256").read_text().splitlines()]
        self.assertEqual(names, sorted(names))

    def test_source_output_and_symlinks_rejected(self):
        with self.assertRaises(pe.PackError):
            pe.pack(self.source, self.source / "evidence", cache=self.cache)
        publication = self.source / "publication"
        publication.mkdir()
        with patch.object(pe, "REPO", publication), self.assertRaises(pe.PackError):
            pe.pack(self.source, publication / "../forbidden", cache=self.cache)
        target = self.attempts[("model-a", "org__repo-1")] / "generate.log"
        target.unlink()
        target.symlink_to(self.source / "artifacts/report/instances.csv")
        with self.assertRaisesRegex(pe.PackError, "Symlink"):
            self.pack()


if __name__ == "__main__":
    unittest.main()
