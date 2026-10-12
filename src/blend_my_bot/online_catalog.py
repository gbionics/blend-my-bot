from dataclasses import dataclass
from importlib import import_module
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
from tempfile import TemporaryDirectory

from robot_descriptions import DESCRIPTIONS, __version__

BLENDER_TESTED_DESCRIPTIONS = (
    "anymal_b_description",
    "bolt_description",
    "cassie_description",
    "g1_description",
    "go2_description",
)
MANIFEST_NAME = "robot.json"
PROCESS_STOP_TIMEOUT = 5
ERROR_TAIL_BYTES = 4096
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CatalogRobot:
    identifier: str
    name: str
    maker: str
    license: str
    blender_tested: bool


@dataclass(frozen=True)
class CachedRobot:
    urdf_path: Path
    search_paths: tuple[Path, ...]


def catalog_robots() -> tuple[CatalogRobot, ...]:
    return tuple(
        CatalogRobot(
            identifier,
            DESCRIPTIONS[identifier].robot,
            DESCRIPTIONS[identifier].maker or "",
            DESCRIPTIONS[identifier].license_spdx or "See upstream license",
            identifier in BLENDER_TESTED_DESCRIPTIONS,
        )
        for identifier in sorted(
            (
                name
                for name, description in DESCRIPTIONS.items()
                if description.has_urdf
            ),
            key=lambda name: (DESCRIPTIONS[name].robot.casefold(), name),
        )
    )


def validate_identifier(identifier: str) -> None:
    description = DESCRIPTIONS.get(identifier)
    if description is None or not description.has_urdf:
        raise ValueError(f"Robot is not a known URDF catalog description: {identifier}")


def _cached_path(directory: Path, relative: str) -> Path:
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("Robot cache paths must be relative")
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("Robot cache path escapes its directory")
    return path


def read_cached_robot(directory: Path, identifier: str) -> CachedRobot:
    validate_identifier(identifier)
    try:
        data = json.loads((directory / MANIFEST_NAME).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Cannot read robot cache at {directory}; remove this robot's "
            "cache folder and download it again"
        ) from error
    if (
        not isinstance(data, dict)
        or data.get("description") != identifier
        or data.get("version") != __version__
        or not isinstance(data.get("urdf"), str)
        or not isinstance(data.get("search_paths"), list)
        or not data["search_paths"]
    ):
        raise ValueError(f"Invalid robot cache manifest at {directory}")
    urdf = _cached_path(directory, data["urdf"])
    paths = tuple(_cached_path(directory, item) for item in data["search_paths"])
    if not urdf.is_file() or urdf.suffix.lower() != ".urdf":
        raise ValueError(f"Cached URDF is missing or invalid: {urdf}")
    if any(not path.is_dir() for path in paths):
        raise ValueError(f"Cached robot package folders are missing at {directory}")
    return CachedRobot(urdf, paths)


def cached_robot(cache: Path, identifier: str) -> CachedRobot | None:
    validate_identifier(identifier)
    directory = cache / identifier
    return read_cached_robot(directory, identifier) if directory.exists() else None


def download_robot(identifier: str, directory: Path) -> CachedRobot:
    """Run only in an isolated worker: description imports clone repositories."""
    validate_identifier(identifier)
    os.environ["ROBOT_DESCRIPTIONS_CACHE"] = str(directory.resolve())
    os.environ.pop("ROBOT_DESCRIPTION_COMMIT", None)
    os.environ["GIT_TERMINAL_PROMPT"] = "0"
    module = import_module(f"robot_descriptions.{identifier}")
    urdf_path = getattr(module, "URDF_PATH", None)
    if urdf_path is None:
        if hasattr(module, "XACRO_PATH"):
            raise ValueError(
                f"'{identifier}' requires Xacro generation, which is not bundled. "
                "Generate its URDF first and use Browse URDF File."
            )
        raise ValueError(f"'{identifier}' does not provide a static URDF file")
    urdf = Path(urdf_path).resolve()
    package = Path(module.PACKAGE_PATH).resolve()
    repository = Path(module.REPOSITORY_PATH).resolve()
    paths = dict.fromkeys(
        (package, repository, package.parent, repository.parent, urdf.parent)
    )
    data = {
        "description": identifier,
        "version": __version__,
        "urdf": str(urdf.relative_to(directory.resolve())),
        "search_paths": [str(path.relative_to(directory.resolve())) for path in paths],
    }
    (directory / MANIFEST_NAME).write_text(json.dumps(data))
    return read_cached_robot(directory, identifier)


class DownloadJob:
    def __init__(self, cache: Path, identifier: str, python: str, worker: Path):
        validate_identifier(identifier)
        self.cache = cache
        self.identifier = identifier
        self.destination = cache / identifier
        self.python = python
        self.worker = worker
        self.process = None
        self._temporary = None
        self._log = None

    def start(self) -> None:
        if self.destination.exists():
            raise ValueError(f"Robot cache already exists: {self.destination}")
        self.cache.mkdir(parents=True, exist_ok=True)
        self._temporary = TemporaryDirectory(
            prefix=f".{self.identifier}-", dir=self.cache
        )
        self.directory = Path(self._temporary.name)
        self.staging = self.directory / "models"
        self.log_path = self.directory / "download.log"
        started = False
        try:
            self._log = self.log_path.open("wb")
            environment = dict(os.environ, GIT_TERMINAL_PROMPT="0")
            self.process = subprocess.Popen(
                [
                    self.python,
                    "-u",
                    str(self.worker),
                    "--",
                    self.identifier,
                    str(self.staging),
                ],
                stdout=self._log,
                stderr=subprocess.STDOUT,
                env=environment,
                start_new_session=True,
            )
            started = True
        finally:
            if not started:
                self.close()

    def output_tail(self, size: int = ERROR_TAIL_BYTES) -> str:
        with self.log_path.open("rb") as log:
            log.seek(max(0, self.log_path.stat().st_size - size))
            return log.read(size).decode("utf-8", errors="replace")

    def finish(self) -> CachedRobot:
        code = self.process.poll()
        if code is None:
            raise RuntimeError("Robot download is still running")
        if code != 0:
            output = self.output_tail().strip()
            logger.error("Robot download worker failed:\n%s", output)
            lines = output.replace("\r", "\n").splitlines()
            raise RuntimeError(
                f"Robot download failed (exit {code}): "
                f"{lines[-1] if lines else 'worker exited without diagnostic output'}"
            )
        read_cached_robot(self.staging, self.identifier)
        self.staging.rename(self.destination)
        return read_cached_robot(self.destination, self.identifier)

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                self.process.wait()
            try:
                self.process.wait(timeout=PROCESS_STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    self.process.wait()
                self.process.wait()
        if self._log is not None:
            self._log.close()
            self._log = None
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None
