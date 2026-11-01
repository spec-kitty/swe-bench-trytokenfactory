import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import check_license as gate  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


class LicenseGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "LICENSE").write_text(gate.MIT_TEXT, encoding="utf-8")
        (self.tmp / "NOTICE").write_text(
            "Project\n=======\n\nThis repository is licensed under the MIT License (see LICENSE),\n"
            f"Copyright (c) {gate.YEAR} {gate.HOLDER}\n\nBundled: Demo 1.2.3\nDemo notice line\n", encoding="utf-8")
        vendor = self.tmp / "vendor" / "demo"
        vendor.mkdir(parents=True)
        (vendor / "demo.min.js").write_text("code", encoding="utf-8")
        (vendor / "LICENSE").write_text("Apache", encoding="utf-8")
        (vendor / "NOTICE").write_text("Demo notice line", encoding="utf-8")
        (vendor / "VENDORED.json").write_text(json.dumps({"package": "demo", "version": "1.2.3", "file": "dist/demo.min.js",
                                                          "sha256": gate.hashlib.sha256(b"code").hexdigest()}), encoding="utf-8")

    def problems(self):
        return gate.run(self.tmp)

    def test_clean_tree_passes(self):
        self.assertEqual(self.problems(), [])

    def test_real_repository_passes(self):
        self.assertEqual(gate.run(REPO), [])

    def test_contributors_holder_is_rejected(self):
        text = gate.MIT_TEXT.replace(gate.HOLDER, "Contributors")
        (self.tmp / "LICENSE").write_text(text, encoding="utf-8")
        found = " ".join(self.problems())
        self.assertIn("verbatim MIT", found)
        self.assertIn("Contributors", found)

    def test_any_edit_to_the_license_text_is_rejected(self):
        (self.tmp / "LICENSE").write_text(gate.MIT_TEXT.replace("without restriction", "with restriction"), encoding="utf-8")
        self.assertTrue(any("verbatim MIT" in p for p in self.problems()))

    def test_missing_license_or_notice_is_rejected(self):
        (self.tmp / "LICENSE").unlink()
        (self.tmp / "NOTICE").unlink()
        found = " ".join(self.problems())
        self.assertIn("LICENSE is missing", found)
        self.assertIn("NOTICE is missing", found)

    def test_package_metadata_must_match(self):
        manifest = self.tmp / "package.json"
        manifest.write_text(json.dumps({"name": "x", "license": "ISC"}), encoding="utf-8")
        self.assertTrue(any("package.json license" in p for p in self.problems()))
        manifest.write_text(json.dumps({"name": "x", "license": "MIT", "author": "Someone Else"}), encoding="utf-8")
        self.assertTrue(any("package.json author" in p for p in self.problems()))
        manifest.write_text(json.dumps({"name": "x", "license": "MIT"}), encoding="utf-8")
        self.assertEqual(self.problems(), [])
        pyproject = self.tmp / "pyproject.toml"
        pyproject.write_text('[project]\nname="x"\nlicense = "GPL-3.0"\n', encoding="utf-8")
        self.assertTrue(any("pyproject.toml license" in p for p in self.problems()))

    def test_notice_must_cover_each_bundled_component(self):
        (self.tmp / "NOTICE").write_text(
            f"licensed under the MIT License (see LICENSE)\nCopyright (c) {gate.YEAR} {gate.HOLDER}\n", encoding="utf-8")
        found = " ".join(self.problems())
        self.assertIn("does not mention bundled demo", found)
        self.assertIn("upstream notice", found)

    def test_bundled_file_checksum_drift_is_rejected(self):
        (self.tmp / "vendor" / "demo" / "demo.min.js").write_text("changed", encoding="utf-8")
        self.assertTrue(any("checksum" in p for p in self.problems()))

    def test_published_copy_must_match_vendored_copy(self):
        published = self.tmp / "docs" / "assets" / "vendor" / "demo"
        published.mkdir(parents=True)
        (published / "demo.min.js").write_text("other", encoding="utf-8")
        self.assertTrue(any("published copy differs" in p for p in self.problems()))

    def test_other_copyright_holder_in_first_party_files_is_rejected_but_vendor_is_exempt(self):
        (self.tmp / "tools").mkdir()
        (self.tmp / "tools" / "x.py").write_text("# Copyright (c) 2026 The Contributors\n", encoding="utf-8")
        self.assertTrue(any("tools/x.py" in p for p in self.problems()))
        (self.tmp / "tools" / "x.py").write_text(f"# Copyright (c) 2026 {gate.HOLDER}\n", encoding="utf-8")
        (self.tmp / "vendor" / "demo" / "readme.md").write_text("Copyright (c) 2020 Someone", encoding="utf-8")
        self.assertEqual(self.problems(), [])


if __name__ == "__main__":
    unittest.main()
