import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build_extension(blender: str, output: Path) -> Path:
    expression = (
        "import bpy,json,numpy,sys,platform; "
        "print('BMB_RUNTIME='+json.dumps({"
        "'blender':list(bpy.app.version),"
        "'python':list(sys.version_info[:2]),"
        "'numpy':numpy.__version__,"
        "'platform':sys.platform,'machine':platform.machine()}))"
    )
    result = subprocess.run(
        [
            blender,
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python-expr",
            expression,
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    runtime_lines = [
        line.removeprefix("BMB_RUNTIME=")
        for line in result.stdout.splitlines()
        if line.startswith("BMB_RUNTIME=")
    ]
    if not runtime_lines:
        raise RuntimeError(f"Blender did not report its runtime:\n{result.stdout}")
    runtime = json.loads(runtime_lines[0])
    major, minor, _ = runtime["blender"]
    if runtime["platform"] != "linux" or runtime["machine"] != "x86_64":
        raise ValueError("Extension builds currently support Linux x86-64 only")
    if (major, minor) < (5, 0):
        raise ValueError("Blender 5.0 or newer is required; Blender 4.x is unsupported")
    python_version = ".".join(map(str, runtime["python"]))
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="blend-my-bot-build-") as directory:
        staging = Path(directory) / "extension"
        shutil.copytree(ROOT / "extension", staging)
        shutil.copytree(
            ROOT / "src" / "blend_my_bot",
            staging / "blend_my_bot",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        shutil.copy2(ROOT / "LICENSE", staging / "LICENSE")
        wheels = staging / "wheels"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--dest",
                str(wheels),
                "--only-binary=:all:",
                "--python-version",
                python_version,
                "--implementation",
                "cp",
                "--abi",
                "cp" + python_version.replace(".", ""),
                "--platform",
                "manylinux_2_28_x86_64",
                "--platform",
                "manylinux_2_17_x86_64",
                "idyntree==15.1.0",
                "resolve-robotics-uri-py==0.5.1",
                "numpy==" + runtime["numpy"],
            ],
            check=True,
        )
        manifest = staging / "blender_manifest.toml"
        content = manifest.read_text()
        content = content.replace(
            'blender_version_min = "5.0.0"',
            f'blender_version_min = "{major}.{minor}.0"\n'
            f'blender_version_max = "{major}.{minor + 1}.0"',
        )
        wheel_paths = [
            f'"./wheels/{wheel.name}"' for wheel in sorted(wheels.glob("*.whl"))
        ]
        content = content.replace(
            "[permissions]",
            "wheels = [" + ", ".join(wheel_paths) + "]\n\n[permissions]",
        )
        manifest.write_text(content)
        archive = output / f"blend_my_bot-0.1.0-blender-{major}.{minor}-linux-x64.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
            for path in sorted(staging.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    package.write(path, path.relative_to(staging))
    subprocess.run(
        [blender, "--command", "extension", "validate", str(archive)], check=True
    )
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build a self-contained Linux extension"
    )
    parser.add_argument("--blender", default="blender")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    arguments = parser.parse_args()
    print(build_extension(arguments.blender, arguments.output))
