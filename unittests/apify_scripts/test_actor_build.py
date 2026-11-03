"""
Unit tests for scripts/apify-scripts/actor_build.py.

Run from repo root:
    python -m unittest unittests.apify_scripts.test_actor_build

No Docker and no Apify calls. The smoke gate is tested through evaluate().
"""
import importlib.util
import io
import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[2]
_PATH = _REPO / "scripts" / "apify-scripts" / "actor_build.py"
_spec = importlib.util.spec_from_file_location("cjm_actor_build", _PATH)
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)

ACTORS = (
    "city-data",
    "contractor-license",
    "google-business",
    "home-services",
    "new-business",
    "permits",
    "zillow",
)

BUDGET = {
    "memoryMbytes": 1024,
    "maxDurationSecs": 300,
    "minItems": 1,
    "maxItems": 5,
    "maxChargeUsd": 0.25,
    "maxUsageUsd": 0.05,
}


def _result(**overrides):
    result = {
        "status": "SUCCEEDED",
        "durationSecs": 60.0,
        "memoryMaxMbytes": 400.0,
        "itemCount": 3,
        "chargeUsd": Decimal("0.15"),
        "usageUsd": 0.01,
    }
    result.update(overrides)
    return result


class TestRepoActors(unittest.TestCase):
    def test_every_listed_actor_has_a_build_folder(self):
        names = [actor.name for actor in build.actor_dirs()]
        self.assertEqual(sorted(set(names) - {"_template"}), sorted(ACTORS))
        self.assertIn("_template", names)

    def test_repo_passes_check(self):
        for actor in build.actor_dirs():
            with self.subTest(actor=actor.name):
                errors = (
                    build.drift_errors(actor)
                    + build.build_errors(actor)
                    + build.schema_errors(actor)
                    + build.budget_errors(actor)
                )
                self.assertEqual(errors, [])
        self.assertEqual(build.readme_errors(), [])

    def test_no_actor_uses_a_repo_wide_context(self):
        for actor in build.actor_dirs():
            config = json.loads((actor / ".actor" / "actor.json").read_text(encoding="utf-8"))
            self.assertNotIn("dockerContextDir", config, actor.name)

    def test_template_matches_the_actor_dockerfiles(self):
        template = (build.HERE / "_template" / "Dockerfile").read_text(encoding="utf-8")
        body = template[template.index("FROM ") :]
        for name in ACTORS:
            text = (build.HERE / name / "Dockerfile").read_text(encoding="utf-8")
            self.assertEqual(text[text.index("FROM ") :], body, name)

    def test_dockerfiles_keep_the_base_image_workdir(self):
        for actor in build.actor_dirs():
            text = (actor / "Dockerfile").read_text(encoding="utf-8")
            with self.subTest(actor=actor.name):
                self.assertFalse(any(line.startswith("WORKDIR") for line in text.splitlines()))
                self.assertIn("CJM_REPO_ROOT=/usr/src/app/platform_bundle", text)


class TestDrift(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.actor = self.tmp / "contractor-license"
        shutil.copytree(build.HERE / "contractor-license", self.actor)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clean_copy_has_no_drift(self):
        self.assertEqual(build.drift_errors(self.actor), [])

    def test_edited_copy_is_drift(self):
        copy = self.actor / build.BUNDLE_DIR / "scripts" / "apify-scripts" / "runtime.py"
        copy.write_text(copy.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
        errors = build.drift_errors(self.actor)
        self.assertTrue(any("differs" in error for error in errors), errors)

    def test_missing_and_extra_files_are_drift(self):
        (self.actor / build.BUNDLE_DIR / "helper_scripts" / "http" / "client.py").unlink()
        (self.actor / build.BUNDLE_DIR / "stray.py").write_text("", encoding="utf-8")
        errors = build.drift_errors(self.actor)
        self.assertTrue(any("client.py is missing" in error for error in errors), errors)
        self.assertTrue(any("stray.py is not listed" in error for error in errors), errors)

    def test_bundle_rewrites_the_copy(self):
        (self.actor / build.BUNDLE_DIR / "stray.py").write_text("", encoding="utf-8")
        build.bundle(self.actor)
        self.assertEqual(build.drift_errors(self.actor), [])

    def test_repo_wide_context_and_outside_copy_are_rejected(self):
        config_path = self.actor / ".actor" / "actor.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["dockerContextDir"] = "../../../.."
        config_path.write_text(json.dumps(config), encoding="utf-8")
        dockerfile = self.actor / "Dockerfile"
        dockerfile.write_text(
            dockerfile.read_text(encoding="utf-8")
            + "\nCOPY --chown=myuser:myuser helper_scripts/http/client.py /x\n",
            encoding="utf-8",
        )
        errors = build.build_errors(self.actor)
        self.assertTrue(any("dockerContextDir" in error for error in errors), errors)
        self.assertTrue(any("outside the Actor folder" in error for error in errors), errors)

    def test_unbounded_limit_is_rejected(self):
        path = self.actor / ".actor" / "input_schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        schema["properties"]["maxResults"].pop("maximum")
        schema["properties"]["names"] = {"type": "array", "editor": "stringList"}
        path.write_text(json.dumps(schema), encoding="utf-8")
        errors = build.schema_errors(self.actor)
        self.assertIn("input maxResults has no maximum", errors)
        self.assertIn("input names is a free-form list with no maxItems", errors)

    def test_budget_outside_actor_memory_is_rejected(self):
        path = self.actor / build.BUDGET
        budget = json.loads(path.read_text(encoding="utf-8"))
        budget["memoryMbytes"] = 16384
        path.write_text(json.dumps(budget), encoding="utf-8")
        errors = build.budget_errors(self.actor)
        self.assertTrue(any("outside actor.json" in error for error in errors), errors)


class TestEvaluate(unittest.TestCase):
    def test_inside_budget(self):
        self.assertEqual(build.evaluate(BUDGET, _result()), [])

    def test_each_overrun_is_reported(self):
        cases = {
            "status": _result(status="FAILED (out of memory)"),
            "memory": _result(memoryMaxMbytes=1500.0),
            "duration": _result(durationSecs=301.0),
            "rows": _result(itemCount=6),
            "charge": _result(chargeUsd=Decimal("0.26")),
            "usage": _result(usageUsd=0.06),
        }
        for label, result in cases.items():
            with self.subTest(label):
                self.assertEqual(len(build.evaluate(BUDGET, result)), 1)

    def test_empty_dataset_fails_when_rows_are_required(self):
        self.assertEqual(len(build.evaluate(BUDGET, _result(itemCount=0))), 1)

    def test_missing_memory_reading_is_not_a_failure(self):
        self.assertEqual(build.evaluate(BUDGET, _result(memoryMaxMbytes=None)), [])

    def test_local_charging_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Path(tmp)
            log = storage / "datasets" / "charging-log"
            rows = storage / "datasets" / "default"
            log.mkdir(parents=True)
            rows.mkdir(parents=True)
            (log / "__metadata__.json").write_text("{}", encoding="utf-8")
            (rows / "__metadata__.json").write_text("{}", encoding="utf-8")
            entries = [
                ("apify-default-dataset-item", 1.0, 1),
                ("result", 0.01, 1),
                ("result", 0.01, 2),
                ("proxy", 0.01, 1),
            ]
            for number, (event, price, count) in enumerate(entries, 1):
                payload = {"event_name": event, "event_price_usd": price, "charged_count": count}
                (log / f"{number:09d}.json").write_text(json.dumps(payload), encoding="utf-8")
                (rows / f"{number:09d}.json").write_text("{}", encoding="utf-8")
            charge, charged = build.read_charging_log(storage)
            self.assertEqual(charge, Decimal("0.04"))
            self.assertEqual(charged, {"result": 3, "proxy": 1})
            self.assertEqual(build.count_items(storage), 4)

    def test_docker_memory_text(self):
        self.assertAlmostEqual(build._parse_mem("512MiB / 1GiB"), 512.0)
        self.assertAlmostEqual(build._parse_mem("1.5GiB / 2GiB"), 1536.0)


class TestImportProbe(unittest.TestCase):
    def _imports(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mod.py"
            path.write_text(textwrap.dedent(source), encoding="utf-8")
            return build.collect_imports(path)

    def test_guarded_imports_are_skipped(self):
        found = self._imports(
            """
            import json
            from helper_scripts.http.client import fetch_url_text
            from . import sibling
            try:
                from optional_mod import thing
            except ImportError:
                thing = None
            try:
                import other_optional
            except Exception:
                pass
            if TYPE_CHECKING:
                from typing_only import Thing

            def later():
                from lazy_mod import value
                return value
            """
        )
        self.assertEqual(found, {"json", "helper_scripts.http.client", "lazy_mod"})

    def test_unguarded_handler_does_not_skip(self):
        found = self._imports(
            """
            try:
                import needed
            except KeyError:
                pass
            """
        )
        self.assertEqual(found, {"needed"})

    def test_manifest_exclusions(self):
        self.assertEqual(build.unbundled_imports(build.HERE / "new-business"), {"leadgen"})
        self.assertNotIn("!leadgen", build.read_manifest(build.HERE / "new-business"))


class TestSmokeReport(unittest.TestCase):
    def test_failed_docker_prints_stderr(self):
        def fake_run(cmd, check, capture_output, text):
            raise subprocess.CalledProcessError(127, cmd, output="stdout-text", stderr="exec: not found")

        with patch.object(build.subprocess, "run", fake_run):
            with redirect_stderr(buf := io.StringIO()):
                with self.assertRaises(subprocess.CalledProcessError):
                    build._docker("run", "-d", "img")
        self.assertIn("exec: not found", buf.getvalue())
        self.assertIn("stdout-text", buf.getvalue())

    def test_report_is_written_when_smoke_raises(self):
        def boom(*_args, **_kwargs):
            raise subprocess.CalledProcessError(127, ["docker", "run"], stderr="not found")

        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "smoke-city-data.json"
            with patch.object(build, "smoke_docker", boom):
                code = build.smoke(build.HERE / "city-data", image="img", report=report)
            self.assertEqual(code, 1)
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "FAILED (CalledProcessError)")
            self.assertTrue(payload["problems"])
            self.assertIn("not found", report.with_suffix(".log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
