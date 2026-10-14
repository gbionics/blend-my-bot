from dataclasses import dataclass
import os
from pathlib import Path
from typing import Iterator, Sequence, Tuple

from resolve_robotics_uri_py.resolve_robotics_uri_py import get_default_search_paths


@dataclass(frozen=True)
class RobotDescription:
    package_directory: Path
    urdf_path: Path

    @property
    def label(self) -> str:
        return str(self.urdf_path.relative_to(self.package_directory))


def package_directory(urdf: Path, search_root: Path) -> Path:
    directory = urdf.parent
    while directory != search_root:
        if (directory / "package.xml").is_file() or (
            directory / "model.config"
        ).is_file():
            return directory
        directory = directory.parent
    if (search_root / "package.xml").is_file() or (
        search_root / "model.config"
    ).is_file():
        return search_root
    relative = urdf.relative_to(search_root)
    if len(relative.parts) > 2 and relative.parts[0] == "share":
        return search_root / "share" / relative.parts[1]
    if len(relative.parts) == 1 or relative.parts[0].lower() in {
        "urdf",
        "urdfs",
        "robots",
        "models",
    }:
        return search_root
    return search_root / relative.parts[0]


def raise_scan_error(error: OSError) -> None:
    raise error


def iter_robot_descriptions(
    search_paths: Sequence[Path] = (),
) -> Iterator[Tuple[Path, Tuple[RobotDescription, ...]]]:
    """Yield per-directory batches so Blender can scan between UI events."""
    roots = dict.fromkeys(
        Path(path).expanduser().absolute()
        for path in (*search_paths, *sorted(get_default_search_paths()))
    )
    visited_directories = set()
    visited_files = set()
    for root in roots:
        if not root.is_dir():
            raise NotADirectoryError(f"Package search folder does not exist: {root}")
        for directory, directories, filenames in os.walk(
            root, followlinks=True, onerror=raise_scan_error
        ):
            directory = Path(directory)
            canonical = directory.resolve()
            if canonical in visited_directories:
                directories.clear()
                continue
            visited_directories.add(canonical)
            directories[:] = sorted(
                name
                for name in directories
                if not name.startswith(".") and name != "__pycache__"
            )
            entries = []
            for filename in sorted(filenames):
                path = directory / filename
                if path.suffix.lower() != ".urdf":
                    continue
                canonical = path.resolve()
                if canonical in visited_files or not path.is_file():
                    continue
                visited_files.add(canonical)
                entries.append(RobotDescription(package_directory(path, root), path))
            yield directory, tuple(entries)
