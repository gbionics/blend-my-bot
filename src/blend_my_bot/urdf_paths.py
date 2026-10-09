from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator, Sequence
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

from resolve_robotics_uri_py import resolve_robotics_uri


def resolve_mesh_path(
    filename: str, urdf_directory: Path, search_paths: Sequence[Path]
) -> Path:
    uri = urlsplit(filename)
    package_dirs = []
    if uri.scheme in {"package", "model"}:
        resource = f"{uri.scheme}://{unquote(uri.netloc + uri.path)}"
        for root in (urdf_directory, *search_paths):
            root = root.expanduser()
            package_dirs.append(str(root.resolve()))
            if (root / "share").is_dir():
                package_dirs.append(str((root / "share").resolve()))
            if root.name == uri.netloc:
                package_dirs.append(str(root.parent.resolve()))
    elif uri.scheme == "file":
        if uri.netloc not in {"", "localhost"}:
            raise ValueError(f"Remote file URI is not supported: {filename}")
        resource = str(Path(unquote(uri.path)))
    elif uri.scheme:
        raise ValueError(f"Unsupported mesh URI scheme: {filename}")
    else:
        path = Path(filename).expanduser()
        resource = str(path if path.is_absolute() else urdf_directory / path)
    try:
        resolved = resolve_robotics_uri(resource, package_dirs=package_dirs)
        if not resolved.is_file():
            raise FileNotFoundError(f"Mesh path is not a file: {resolved}")
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"Mesh not found: {filename}. Add its package folder or the folder "
            "containing that package to Blend My Bot preferences, or configure "
            "the robotics environment before launching Blender."
        ) from error
    return resolved.resolve()


@contextmanager
def resolved_urdf(urdf_path: Path, search_paths: Sequence[Path] = ()) -> Iterator[Path]:
    tree = ET.parse(urdf_path)
    root = tree.getroot()
    if root.tag != "robot":
        raise ValueError("The selected file must contain a URDF <robot> element")
    for visual in root.findall("./link/visual"):
        mesh = visual.find("./geometry/mesh")
        if mesh is None:
            raise ValueError(
                "Visual primitives are not yet supported; use OBJ/STL meshes"
            )
        filename = mesh.get("filename")
        if not filename:
            raise ValueError("A visual mesh is missing its filename")
        path = resolve_mesh_path(filename, urdf_path.resolve().parent, search_paths)
        if path.suffix.lower() not in {".obj", ".stl"}:
            raise ValueError(f"Unsupported visual mesh format: {path.suffix}")
        mesh.set("filename", str(path))
    for mesh in root.findall("./link/collision/geometry/mesh"):
        filename = mesh.get("filename")
        if not filename:
            raise ValueError("A collision mesh is missing its filename")
        mesh.set(
            "filename",
            str(resolve_mesh_path(filename, urdf_path.resolve().parent, search_paths)),
        )
    with TemporaryDirectory(prefix="blend-my-bot-") as directory:
        output = Path(directory) / urdf_path.name
        tree.write(output, encoding="utf-8", xml_declaration=True)
        yield output
