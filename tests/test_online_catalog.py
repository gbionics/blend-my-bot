import importlib.util
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from robot_descriptions import DESCRIPTIONS, __version__

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "online_catalog", ROOT / "src" / "blend_my_bot" / "online_catalog.py"
)
catalog = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = catalog
spec.loader.exec_module(catalog)
IDENTIFIER = "cassie_description"


def create_cache(directory):
    directory.mkdir(parents=True)
    (directory / "robot.urdf").write_text(
        '<robot name="fixture"><link name="base"/></robot>'
    )
    data = {
        "description": IDENTIFIER,
        "version": __version__,
        "urdf": "robot.urdf",
        "search_paths": ["."],
    }
    (directory / catalog.MANIFEST_NAME).write_text(json.dumps(data))
    return data


class OnlineCatalogTests(unittest.TestCase):
    def test_metadata_does_not_import_robot_modules(self):
        with patch.object(catalog, "import_module") as import_module:
            robots = catalog.catalog_robots()
            self.assertEqual(
                {robot.identifier for robot in robots},
                {
                    name
                    for name, description in DESCRIPTIONS.items()
                    if description.has_urdf
                },
            )
            self.assertGreater(len(robots), 2)
            self.assertTrue(all(robot.name and robot.license for robot in robots))
            self.assertEqual(
                [(robot.name.casefold(), robot.identifier) for robot in robots],
                sorted((robot.name.casefold(), robot.identifier) for robot in robots),
            )
            import_module.assert_not_called()

    def test_only_known_urdf_identifiers_are_accepted(self):
        for name, description in DESCRIPTIONS.items():
            if description.has_urdf:
                catalog.validate_identifier(name)
            else:
                with self.subTest(identifier=name), self.assertRaises(ValueError):
                    catalog.validate_identifier(name)
        for identifier in (
            "missing_description",
            "../cassie_description",
            "",
        ):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                catalog.validate_identifier(identifier)

    def test_tested_status_does_not_restrict_selection(self):
        robots = {robot.identifier: robot for robot in catalog.catalog_robots()}
        self.assertEqual(
            {name for name, robot in robots.items() if robot.blender_tested},
            set(catalog.BLENDER_TESTED_DESCRIPTIONS),
        )
        for name in ("panda_description", "upkie_description", "anymal_c_description"):
            self.assertIn(name, robots)
            self.assertFalse(robots[name].blender_tested)
            catalog.validate_identifier(name)

    def test_missing_cache_is_distinct_from_broken_cache(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(catalog.cached_robot(root, IDENTIFIER))
            (root / IDENTIFIER).mkdir()
            with self.assertRaisesRegex(ValueError, "remove this robot"):
                catalog.cached_robot(root, IDENTIFIER)

    def test_valid_cache_uses_only_local_paths(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_cache(root / IDENTIFIER)
            with patch.object(catalog, "import_module") as import_module:
                robot = catalog.cached_robot(root, IDENTIFIER)
                self.assertEqual(robot.urdf_path, root / IDENTIFIER / "robot.urdf")
                self.assertEqual(robot.search_paths, (root / IDENTIFIER,))
                import_module.assert_not_called()

    def test_corrupt_cache_manifest_is_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / IDENTIFIER
            data = create_cache(root)
            manifest = root / catalog.MANIFEST_NAME
            for changed in (
                {"description": "other"},
                {"version": "old"},
                {"urdf": "/tmp/outside.urdf"},
                {"urdf": "../outside.urdf"},
                {"search_paths": []},
                {"search_paths": [2]},
                {"search_paths": ["../outside"]},
                {"search_paths": ["missing"]},
                {"urdf": "missing.urdf"},
            ):
                manifest.write_text(json.dumps(dict(data, **changed)))
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    catalog.read_cached_robot(root, IDENTIFIER)
            manifest.write_text("{")
            with self.assertRaises(ValueError):
                catalog.read_cached_robot(root, IDENTIFIER)

    def test_cache_symlinks_cannot_escape(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / IDENTIFIER
            data = create_cache(root)
            (root / "outside").symlink_to(root.parent, target_is_directory=True)
            data["search_paths"] = ["outside"]
            (root / catalog.MANIFEST_NAME).write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "escapes"):
                catalog.read_cached_robot(root, IDENTIFIER)

    def test_downloader_imports_only_selected_robot_in_owned_cache(self):
        with TemporaryDirectory() as directory, patch.dict(
            os.environ, {"ROBOT_DESCRIPTION_COMMIT": "untrusted-override"}
        ):
            root = Path(directory)
            repository = root / "repo"
            package = repository / "package"
            package.mkdir(parents=True)
            urdf = package / "robot.urdf"
            urdf.write_text('<robot name="fixture"><link name="base"/></robot>')
            module = SimpleNamespace(
                URDF_PATH=urdf, PACKAGE_PATH=package, REPOSITORY_PATH=repository
            )
            for identifier in (IDENTIFIER, "panda_description"):
                with patch.object(
                    catalog, "import_module", return_value=module
                ) as loader:
                    robot = catalog.download_robot(identifier, root)
                    loader.assert_called_once_with(f"robot_descriptions.{identifier}")
            self.assertEqual(robot.urdf_path, urdf)
            self.assertIn(repository, robot.search_paths)
            self.assertEqual(os.environ["ROBOT_DESCRIPTIONS_CACHE"], directory)
            self.assertNotIn("ROBOT_DESCRIPTION_COMMIT", os.environ)
            self.assertEqual(os.environ["GIT_TERMINAL_PROMPT"], "0")

    def test_xacro_description_reports_generation_requirement(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ):
            with patch.object(
                catalog,
                "import_module",
                return_value=SimpleNamespace(XACRO_PATH="robot.xacro"),
            ):
                with self.assertRaisesRegex(ValueError, "Xacro generation"):
                    catalog.download_robot("fr3_description", Path(directory))
            self.assertFalse((Path(directory) / catalog.MANIFEST_NAME).exists())

    def test_missing_urdf_export_is_actionable(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ):
            with patch.object(catalog, "import_module", return_value=SimpleNamespace()):
                with self.assertRaisesRegex(
                    ValueError, "does not provide a static URDF"
                ):
                    catalog.download_robot("panda_description", Path(directory))

    def test_successful_job_promotes_complete_cache_atomically(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            worker = root / "worker.py"
            worker.write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "root=Path(sys.argv[-1]); root.mkdir()\n"
                "(root/'ready').write_text('ready')\n"
            )
            job = catalog.DownloadJob(
                root / "cache", IDENTIFIER, sys.executable, worker
            )
            try:
                job.start()
                self.assertFalse(job.destination.exists())
                self.assertEqual(job.process.wait(timeout=10), 0)
                data = create_cache(job.staging / "fixture")
                data["urdf"] = "fixture/robot.urdf"
                data["search_paths"] = ["fixture"]
                (job.staging / catalog.MANIFEST_NAME).write_text(json.dumps(data))
                robot = job.finish()
                self.assertEqual(
                    robot.urdf_path, job.destination / "fixture" / "robot.urdf"
                )
            finally:
                job.close()
            self.assertEqual(list(job.cache.iterdir()), [job.destination])

    def test_failed_job_never_promotes_partial_download(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            worker = root / "worker.py"
            worker.write_text("raise RuntimeError('network unavailable')\n")
            job = catalog.DownloadJob(
                root / "cache", IDENTIFIER, sys.executable, worker
            )
            try:
                job.start()
                job.process.wait(timeout=10)
                with self.assertRaisesRegex(RuntimeError, "network unavailable"):
                    job.finish()
            finally:
                job.close()
            self.assertEqual(list(job.cache.iterdir()), [])

    def test_cancellation_stops_worker_and_preserves_existing_cache(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            existing = cache / "keep"
            existing.mkdir(parents=True)
            worker = root / "worker.py"
            worker.write_text(
                "from pathlib import Path\n"
                "import subprocess,sys,time\n"
                "Path(sys.argv[-1]).mkdir()\n"
                "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
                "(Path(sys.argv[-1])/'child.pid').write_text(str(child.pid))\n"
                "print('Downloading', flush=True)\n"
                "time.sleep(60)\n"
            )
            job = catalog.DownloadJob(cache, IDENTIFIER, sys.executable, worker)
            try:
                job.start()
                deadline = monotonic() + 10
                while "Downloading" not in job.output_tail() and monotonic() < deadline:
                    sleep(0.01)
                self.assertIn("Downloading", job.output_tail())
                child = int((job.staging / "child.pid").read_text())
                with self.assertRaisesRegex(RuntimeError, "still running"):
                    job.finish()
            finally:
                job.close()
            self.assertIsNotNone(job.process.poll())
            child_status = Path(f"/proc/{child}/status")
            if child_status.exists():
                self.assertIn("State:\tZ", child_status.read_text())
            self.assertEqual(list(cache.iterdir()), [existing])

    def test_start_failure_cleans_owned_temporary_directory(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            job = catalog.DownloadJob(
                root, IDENTIFIER, "/missing/python", root / "worker"
            )
            with self.assertRaises(FileNotFoundError):
                job.start()
            self.assertEqual(list(root.iterdir()), [])

    def test_existing_cache_cannot_be_overwritten(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_cache(root / IDENTIFIER)
            job = catalog.DownloadJob(root, IDENTIFIER, sys.executable, root / "worker")
            with self.assertRaisesRegex(ValueError, "already exists"):
                job.start()
            self.assertTrue((root / IDENTIFIER / "robot.urdf").is_file())


if __name__ == "__main__":
    unittest.main()
