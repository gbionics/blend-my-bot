from dataclasses import dataclass
from pathlib import Path

import collada
import numpy as np

AXIS_ROTATIONS = {
    "Z_UP": np.eye(3),
    "Y_UP": np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]]),
    "X_UP": np.array([[0, 0, -1], [0, 1, 0], [1, 0, 0]]),
}


@dataclass(frozen=True)
class ColladaPart:
    name: str
    vertices: np.ndarray
    faces: tuple[tuple[int, ...], ...]
    edges: tuple[tuple[int, int], ...]
    normals: np.ndarray | None
    texcoords: tuple[np.ndarray, ...]
    texcoord_sets: tuple[int, ...]
    material: collada.material.Material | None
    material_inputs: dict
    double_sided: bool


def _finite(array: np.ndarray, name: str) -> None:
    if not np.all(np.isfinite(array)) or np.any(
        np.abs(array) > np.finfo(np.float32).max
    ):
        raise ValueError(f"DAE {name} are outside Blender's finite numeric range")


def asset_matrix(asset) -> np.ndarray:
    meter = 1.0 if asset.unitmeter is None else asset.unitmeter
    if not np.isfinite(meter) or meter <= 0:
        raise ValueError("DAE asset units must be positive and finite")
    if asset.upaxis not in AXIS_ROTATIONS:
        raise ValueError(f"Unsupported DAE up-axis: {asset.upaxis}")
    matrix = np.eye(4)
    matrix[:3, :3] = AXIS_ROTATIONS[asset.upaxis] * meter
    return matrix


def decode_primitive(geometry, primitive, matrix) -> ColladaPart:
    original = primitive.original
    edges = ()
    if isinstance(primitive, collada.triangleset.BoundTriangleSet):
        faces = tuple(tuple(row) for row in primitive.vertex_index)
    elif isinstance(primitive, collada.polylist.BoundPolylist):
        if original.xmlnode.find(f".//{collada.common.tag('ph')}") is not None:
            raise ValueError("DAE polygons with holes are not supported")
        faces = tuple(
            tuple(primitive.vertex_index[start:end])
            for start, end in primitive.polyindex
        )
    elif isinstance(primitive, collada.lineset.BoundLineSet):
        faces = ()
        edges = tuple(tuple(row) for row in primitive.vertex_index)
        if original.normal is not None or original.texcoordset:
            raise ValueError(
                "DAE line normals/UVs are unsupported; export polygon geometry"
            )
        if any(first == second for first, second in edges):
            raise ValueError("DAE edges must reference two distinct vertices")
    else:
        raise ValueError(f"Unsupported DAE primitive: {type(primitive).__name__}")
    if (not faces and not edges) or any(len(face) < 3 for face in faces):
        raise ValueError("DAE mesh primitives must contain polygon faces")
    indices = np.array([index for primitive in (faces or edges) for index in primitive])
    if np.any(indices < 0) or np.any(indices >= len(original.vertex)):
        raise ValueError("DAE faces contain invalid vertex indices")
    _finite(matrix, "node transforms")
    if not np.allclose(matrix[3], [0, 0, 0, 1]):
        raise ValueError("DAE node transforms must be affine")
    if np.linalg.det(matrix[:3, :3]) == 0:
        raise ValueError("DAE node transform is singular")
    vertices = (
        np.asarray(original.vertex, dtype=float) @ matrix[:3, :3].T + matrix[:3, 3]
    )
    _finite(vertices, "vertices")
    normals = None
    if original.normal is not None:
        normal_indices = original.normal_index.ravel()
        if np.any(normal_indices < 0) or np.any(normal_indices >= len(original.normal)):
            raise ValueError("DAE faces contain invalid normal indices")
        try:
            inverse = np.linalg.inv(matrix[:3, :3])
        except np.linalg.LinAlgError as error:
            raise ValueError("DAE node transform is singular") from error
        normals = np.asarray(original.normal[normal_indices], dtype=float) @ inverse
        _finite(normals, "normals")
        lengths = np.linalg.norm(normals, axis=1)
        if np.any(lengths == 0):
            raise ValueError("DAE normals must be nonzero")
        normals /= lengths[:, None]
    texcoords = []
    for coordinates, uv_indices in zip(
        original.texcoordset, original.texcoord_indexset
    ):
        if np.any(uv_indices < 0) or np.any(uv_indices >= len(coordinates)):
            raise ValueError("DAE faces contain invalid texture-coordinate indices")
        uv = np.asarray(coordinates[uv_indices.ravel()], dtype=float)
        if uv.ndim != 2 or uv.shape[1] not in (2, 3):
            raise ValueError(
                "DAE texture coordinates must contain two or three components"
            )
        _finite(uv, "texture coordinates")
        texcoords.append(uv[:, :2])
    sets = tuple(int(source[3] or 0) for source in original.sources.get("TEXCOORD", ()))
    if faces and np.linalg.det(matrix[:3, :3]) < 0:
        # Baking a reflection requires winding and all corner attributes to flip together.
        order = np.concatenate(
            [
                np.arange(start, start + len(face))[::-1]
                for start, face in zip(
                    np.cumsum([0, *(len(face) for face in faces[:-1])]), faces
                )
            ]
        )
        faces = tuple(tuple(reversed(face)) for face in faces)
        normals = None if normals is None else normals[order]
        texcoords = [uv[order] for uv in texcoords]
    used = np.unique(indices)
    remap = {index: new for new, index in enumerate(used)}
    faces = tuple(tuple(remap[index] for index in face) for face in faces)
    edges = tuple((remap[first], remap[second]) for first, second in edges)
    return ColladaPart(
        geometry.original.name or geometry.original.id,
        vertices[used],
        faces,
        edges,
        normals,
        tuple(texcoords),
        sets,
        primitive.material,
        primitive.inputmap or {},
        geometry.original.double_sided
        or (primitive.material is not None and primitive.material.effect.double_sided),
    )


def read_collada(path: str | Path) -> tuple[ColladaPart, ...]:
    try:
        document = collada.Collada(str(path))
        if document.animations:
            raise ValueError(
                "Animated DAE assets are not supported; export a static mesh"
            )
        if document.scene is not None:
            if next(document.scene.objects("controller"), None) is not None:
                raise ValueError(
                    "Skinned/morphed DAE assets are not supported; export a static mesh"
                )
            geometries = document.scene.objects("geometry")
        elif document.scenes:
            raise ValueError("DAE document has no active visual scene")
        else:
            materials = {
                material.id: collada.scene.MaterialNode(material.id, material, [])
                for material in document.materials
            }
            geometries = (
                geometry.bind(np.eye(4), materials) for geometry in document.geometries
            )
        asset = asset_matrix(document.assetInfo)
        parts = []
        for geometry in geometries:
            for primitive in geometry.primitives():
                if primitive.material is None and primitive.original.material:
                    raise ValueError(
                        f"DAE material '{primitive.original.material}' has no scene binding"
                    )
                parts.append(
                    decode_primitive(geometry, primitive, asset @ geometry.matrix)
                )
        if not parts:
            raise ValueError("DAE document contains no static mesh geometry")
        return tuple(parts)
    except (collada.common.DaeError, SyntaxError, IndexError, TypeError) as error:
        raise ValueError(f"Cannot read DAE mesh '{path}': {error}") from error
