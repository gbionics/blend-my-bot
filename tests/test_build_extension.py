import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "build_extension", ROOT / "tools" / "build_extension.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ExtensionRuntimeTests(unittest.TestCase):
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
