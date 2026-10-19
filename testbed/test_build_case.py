"""Unit tests for the pure parts of build_case.py. No Docker, no network."""

import json
import tempfile
import unittest
from pathlib import Path

import build_case

RECIPE = {
    "id": "osv:OSV-2026-1274", "project": "md4c", "source_dir": "/src/md4c",
    "platform": "linux/amd64", "repo": "https://github.com/mity/md4c.git",
    "vuln_commit": "a" * 40, "fix_commit": "b" * 40,
    "oss_fuzz_repo": "https://github.com/google/oss-fuzz.git", "oss_fuzz_commit": "c" * 40,
    "oss_fuzz_project": "md4c", "base_builder": "gcr.io/oss-fuzz-base/base-builder@sha256:" + "d" * 64,
    "fuzzing_language": "c", "sanitizer": "address", "harness": "fuzz-mdhtml",
    "build_script": "md4c-build.sh", "reference_url": "https://example.test/t",
    "reference_sha256": "e" * 64,
    "expected_crash": {"type": "heap-buffer-overflow", "file": "src/md4c.c", "line": 3409,
                       "function": "md_collect_marks"},
    "entry_point": "test/fuzzers/fuzz-mdhtml.c",
}


DEPENDENCY = {"name": "zlib", "repo": "https://github.com/madler/zlib.git",
              "commit": "f" * 40, "dest": "deps/zlib"}


class RecipeTests(unittest.TestCase):
    def test_loads_and_validates(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "r.json"
            path.write_text(json.dumps(RECIPE))
            self.assertEqual(build_case.load_recipe(path)["id"], RECIPE["id"])

    def test_missing_field_fails(self):
        with tempfile.TemporaryDirectory() as d:
            bad = dict(RECIPE)
            del bad["fix_commit"]
            path = Path(d) / "r.json"
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                build_case.load_recipe(path)

    def test_loads_dependencies(self):
        with tempfile.TemporaryDirectory() as d:
            recipe = dict(RECIPE, dependencies=[DEPENDENCY])
            path = Path(d) / "r.json"
            path.write_text(json.dumps(recipe))
            self.assertEqual(build_case.load_recipe(path)["dependencies"], [DEPENDENCY])

    def test_rejects_dependency_name_with_path(self):
        with tempfile.TemporaryDirectory() as d:
            bad = dict(RECIPE, dependencies=[dict(DEPENDENCY, name="../zlib")])
            path = Path(d) / "r.json"
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                build_case.load_recipe(path)

    def test_rejects_dependency_dest_outside_project(self):
        with tempfile.TemporaryDirectory() as d:
            bad = dict(RECIPE, dependencies=[dict(DEPENDENCY, dest="../zlib")])
            path = Path(d) / "r.json"
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                build_case.load_recipe(path)

    def test_content_key_is_stable_and_script_sensitive(self):
        key1 = build_case.content_key(RECIPE, "#!/bin/bash\necho a\n")
        key2 = build_case.content_key(RECIPE, "#!/bin/bash\necho a\n")
        key3 = build_case.content_key(RECIPE, "#!/bin/bash\necho b\n")
        self.assertEqual(key1, key2)
        self.assertNotEqual(key1, key3)

    def test_content_key_includes_dependencies(self):
        with_dep = dict(RECIPE, dependencies=[DEPENDENCY])
        self.assertNotEqual(build_case.content_key(RECIPE, "x"),
                            build_case.content_key(with_dep, "x"))

    def test_dockerfile_pins_base_and_env(self):
        text = build_case.dockerfile(RECIPE)
        self.assertIn(RECIPE["base_builder"], text)
        self.assertIn("FUZZING_ENGINE=libfuzzer", text)
        self.assertIn("SANITIZER=address", text)
        self.assertIn("COPY src /src/md4c", text)
        self.assertIn("RUN compile", text)

    def test_copy_source_tree_preserves_dangling_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "source"
            source.mkdir()
            (source / "real.txt").write_text("data")
            (source / "missing-link").symlink_to("../missing")
            dest = Path(d) / "dest"
            build_case.copy_source_tree(source, dest)
            self.assertTrue((dest / "missing-link").is_symlink())
            self.assertEqual((dest / "real.txt").read_text(), "data")


class CrashSignatureTests(unittest.TestCase):
    expected = RECIPE["expected_crash"]

    def test_matches_type_location_and_function(self):
        output = ("SUMMARY: AddressSanitizer: heap-buffer-overflow "
                  "/src/md4c/src/md4c.c:3409:54 in md_collect_marks")
        self.assertTrue(build_case.matches_crash(output, self.expected))

    def test_rejects_a_different_function(self):
        output = ("SUMMARY: AddressSanitizer: heap-buffer-overflow "
                  "/src/md4c/src/md4c.c:3409:54 in other_function")
        self.assertFalse(build_case.matches_crash(output, self.expected))

    def test_rejects_a_different_line(self):
        output = ("SUMMARY: AddressSanitizer: heap-buffer-overflow "
                  "/src/md4c/src/md4c.c:9999:54 in md_collect_marks")
        self.assertFalse(build_case.matches_crash(output, self.expected))


if __name__ == "__main__":
    unittest.main()
