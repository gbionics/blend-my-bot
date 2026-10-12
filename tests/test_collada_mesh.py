import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from collada_fixture import make_collada

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "collada_mesh", ROOT / "src" / "blend_my_bot" / "collada_mesh.py"
)
reader = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reader
spec.loader.exec_module(reader)


class ColladaMeshTests(unittest.TestCase):
    def test_lines_preserve_transformed_edges_and_compact_vertices(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "lines.dae"
            make_collada(path, lines=True, instances=False)
            parts = reader.read_collada(path)
            self.assertEqual(len(parts), 3)
            self.assertEqual(parts[2].edges, ((0, 1),))
            self.assertEqual(parts[2].faces, ())
            self.assertIsNone(parts[2].normals)
            np.testing.assert_allclose(
                parts[2].vertices,
                [[0.01, 0.02, 0.03], [0.01, 2.02, 0.03]],
                atol=1e-7,
            )

    def test_units_nested_transforms_instances_materials_and_uv_sets(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "mesh.dae"
            make_collada(path)
            parts = reader.read_collada(path)
            self.assertEqual(len(parts), 4)
            np.testing.assert_allclose(
                parts[0].vertices,
                [[0.01, 0.02, 0.03], [0.01, 2.02, 0.03], [0.01, 0.02, 4.03]],
                atol=1e-7,
            )
            np.testing.assert_allclose(
                parts[2].vertices, parts[0].vertices + [0, 0, 2], atol=1e-7
            )
            self.assertEqual(parts[0].faces, ((0, 1, 2),))
            self.assertEqual(parts[1].faces, ((0, 1, 2, 3),))
            normal = np.array([-1 / 3, 1 / 2, 1 / 4])
            normal /= np.linalg.norm(normal)
            np.testing.assert_allclose(parts[0].normals[0], normal, atol=1e-7)
            self.assertEqual(parts[0].texcoord_sets, (0, 1))
            np.testing.assert_allclose(
                parts[1].texcoords[1],
                [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]],
            )
            self.assertEqual(parts[0].material.name, "Solid")
            self.assertEqual(parts[1].material_inputs["CHANNEL"], ("TEXCOORD", "1"))

    def test_reflections_flip_winding_normals_and_uv_corners_together(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "mesh.dae"
            make_collada(path, reflected=True, instances=False)
            parts = reader.read_collada(path)
            self.assertEqual(parts[0].faces, ((2, 1, 0),))
            np.testing.assert_allclose(
                parts[0].texcoords[0], [[0.5, 0.5], [1, 0], [0, 0]]
            )
            normal = np.array([-1 / 3, -1 / 2, 1 / 4])
            normal /= np.linalg.norm(normal)
            np.testing.assert_allclose(parts[0].normals[-1], normal, atol=1e-7)

    def test_all_declared_up_axes_convert_to_blender_z_up(self):
        for axis, expected in (
            ("Z_UP", [0.01, 2.02, 0.03]),
            ("Y_UP", [0.01, -0.03, 2.02]),
            ("X_UP", [-0.03, 2.02, 0.01]),
        ):
            with self.subTest(axis=axis), TemporaryDirectory() as directory:
                path = Path(directory) / "mesh.dae"
                make_collada(path, up_axis=axis, instances=False)
                np.testing.assert_allclose(
                    reader.read_collada(path)[0].vertices[1], expected, atol=1e-7
                )

    def test_invalid_units_axis_and_nonfinite_geometry_are_explicit(self):
        for meter in (0, -1, np.nan, np.inf):
            with self.subTest(meter=meter), self.assertRaisesRegex(ValueError, "units"):
                reader.asset_matrix(SimpleNamespace(unitmeter=meter, upaxis="Z_UP"))
        with self.assertRaisesRegex(ValueError, "up-axis"):
            reader.asset_matrix(SimpleNamespace(unitmeter=1, upaxis="BAD"))
        with self.assertRaisesRegex(ValueError, "finite"):
            reader._finite(np.array([np.nan]), "vertices")

    def test_malformed_empty_and_unbound_material_files_fail(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "mesh.dae"
            path.write_text("<COLLADA")
            with self.assertRaises(ValueError):
                reader.read_collada(path)
            document = make_collada(path)
            document.scene = None
            document.scenes.clear()
            document.geometries.clear()
            document.nodes.clear()
            with path.open("wb") as stream:
                document.write(stream)
            with self.assertRaisesRegex(ValueError, "no static mesh"):
                reader.read_collada(path)
            make_collada(path)
            path.write_text(
                path.read_text().replace('symbol="solid"', 'symbol="missing"')
            )
            with self.assertRaisesRegex(ValueError, "no scene binding"):
                reader.read_collada(path)

    def test_animation_and_skinning_are_not_silently_dropped(self):
        with patch.object(
            reader.collada,
            "Collada",
            return_value=SimpleNamespace(animations=[object()]),
        ):
            with self.assertRaisesRegex(ValueError, "Animated"):
                reader.read_collada("mesh.dae")
        document = SimpleNamespace(
            animations=[], scene=SimpleNamespace(objects=lambda kind: iter([object()]))
        )
        with patch.object(reader.collada, "Collada", return_value=document):
            with self.assertRaisesRegex(ValueError, "Skinned"):
                reader.read_collada("mesh.dae")


if __name__ == "__main__":
    unittest.main()
