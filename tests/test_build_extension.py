import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "build_extension", ROOT / "tools" / "build_extension.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ExtensionRuntimeTests(unittest.TestCase):
    def test_scipy_is_downloaded_and_bundled_for_the_blender_runtime(self):
        runtime = {
            "blender": [5, 0, 1],
            "python": [3, 11],
            "numpy": "1.26.4",
            "platform": "linux",
            "machine": "x86_64",
        }
        wheel_name = "scipy-1.14.1-cp311-cp311-manylinux_2_17_x86_64.whl"

        def run(command, **kwargs):
            if command[1:3] == ["-m", "pip"]:
                self.assertIn("scipy>=1.14", command)
                self.assertIn("numpy==1.26.4", command)
                self.assertEqual(command[command.index("--python-version") + 1], "3.11")
                wheels = Path(command[command.index("--dest") + 1])
                wheels.mkdir()
                (wheels / wheel_name).touch()
            return SimpleNamespace(stdout="BMB_RUNTIME=" + json.dumps(runtime))

        with TemporaryDirectory() as directory, patch.object(
            builder.subprocess, "run", side_effect=run
        ) as subprocess_run:
            archive = builder.build_extension("blender", Path(directory) / "output")
            self.assertEqual(subprocess_run.call_count, 3)
            with zipfile.ZipFile(archive) as package:
                self.assertIn(f"wheels/{wheel_name}", package.namelist())
                manifest = package.read("blender_manifest.toml").decode()
                self.assertIn(f'"./wheels/{wheel_name}"', manifest)
            self.assertEqual(
                subprocess_run.call_args.args[0],
                ["blender", "--command", "extension", "validate", str(archive)],
            )

    def test_blender_four_is_rejected_before_downloading_dependencies(self):
        runtime = {
            "blender": [4, 5, 0],
            "python": [3, 11],
            "numpy": "1.26.4",
            "platform": "linux",
            "machine": "x86_64",
        }
        with TemporaryDirectory() as directory, patch.object(
            builder.subprocess,
            "run",
            return_value=SimpleNamespace(stdout="BMB_RUNTIME=" + json.dumps(runtime)),
        ) as run:
            with self.assertRaisesRegex(ValueError, "Blender 5.0"):
                builder.build_extension("blender", Path(directory) / "output")
            run.assert_called_once()
            self.assertFalse((Path(directory) / "output").exists())


if __name__ == "__main__":
    unittest.main()
