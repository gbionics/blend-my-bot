import importlib.util
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "urdf_paths", ROOT / "src" / "blend_my_bot" / "urdf_paths.py"
)
urdf_paths = importlib.util.module_from_spec(spec)
spec.loader.exec_module(urdf_paths)


class UrdfPathsTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "my_robot"
        self.package.mkdir()
        self.mesh = self.package / "part.obj"
        self.mesh.write_text("o part\n")

    def test_package_parent_and_package_folder(self):
        for search_root in (self.root, self.package):
            with self.subTest(search_root=search_root):
                self.assertEqual(
                    urdf_paths.resolve_mesh_path(
                        "package://my_robot/part.obj",
                        self.root / "urdfs",
                        [search_root],
                    ),
                    self.mesh,
                )

    def test_relative_absolute_and_file_uri(self):
        for filename in ("part.obj", str(self.mesh), self.mesh.as_uri()):
            with self.subTest(filename=filename):
                self.assertEqual(
                    urdf_paths.resolve_mesh_path(filename, self.package, []), self.mesh
                )

    def test_model_uri_and_encoded_package_path(self):
        mesh = self.package / "part with spaces.obj"
        mesh.write_text("o part\n")
        for uri in (
            "model://my_robot/part.obj",
            "package://my_robot/part%20with%20spaces.obj",
        ):
            with self.subTest(uri=uri):
                expected = mesh if "%20" in uri else self.mesh
                self.assertEqual(
                    urdf_paths.resolve_mesh_path(uri, self.root, []), expected
                )

    def test_robotics_environment_search_paths(self):
        prefix = self.root / "ros_install"
        shared_package = prefix / "share" / "my_robot"
        shared_package.mkdir(parents=True)
        shared_mesh = shared_package / "part.obj"
        shared_mesh.write_text("o part\n")
        for variable, directory, expected in (
            ("ROS_PACKAGE_PATH", self.root, self.mesh),
            ("AMENT_PREFIX_PATH", prefix, shared_mesh),
            ("GAZEBO_MODEL_PATH", self.root, self.mesh),
            ("RRU_ADDITIONAL_PATHS", self.root, self.mesh),
        ):
            with self.subTest(variable=variable):
                with patch.dict(os.environ, {variable: str(directory)}):
                    self.assertEqual(
                        urdf_paths.resolve_mesh_path(
                            "package://my_robot/part.obj", self.root / "urdfs", []
                        ),
                        expected,
                    )

    def test_directory_is_not_a_mesh(self):
        with self.assertRaises(FileNotFoundError):
            urdf_paths.resolve_mesh_path("package://my_robot", self.root, [])

    def test_saved_package_folder_can_be_a_symlink(self):
        aliases = self.root / "aliases"
        aliases.mkdir()
        alias = aliases / "robot_alias"
        alias.symlink_to(self.package, target_is_directory=True)
        self.assertEqual(
            urdf_paths.resolve_mesh_path(
                "package://robot_alias/part.obj", self.root / "urdfs", [alias]
            ),
            self.mesh,
        )

    def test_repository_root_resolves_packages_under_share(self):
        package = self.root / "share" / "gene"
        package.mkdir(parents=True)
        mesh = package / "part.obj"
        mesh.write_text("o part\n")
        self.assertEqual(
            urdf_paths.resolve_mesh_path(
                "package://gene/part.obj",
                package / "robots" / "gene01",
                [self.root],
            ),
            mesh,
        )

    def test_missing_and_remote_meshes_are_explicit_errors(self):
        with self.assertRaisesRegex(FileNotFoundError, "Add its package folder"):
            urdf_paths.resolve_mesh_path("missing.obj", self.package, [])
        for filename in ("https://example.com/part.obj", "file://server/part.obj"):
            with self.subTest(filename=filename):
                with self.assertRaises(ValueError):
                    urdf_paths.resolve_mesh_path(filename, self.package, [])

    def test_resolved_copy_preserves_source_and_cleans_up(self):
        source = self.package / "robot.urdf"
        original = (
            '<robot name="test"><link name="base"><visual><geometry>'
            '<mesh filename="part.obj"/></geometry></visual></link></robot>'
        )
        source.write_text(original)
        with urdf_paths.resolved_urdf(source) as resolved:
            mesh = ET.parse(resolved).find("./link/visual/geometry/mesh")
            self.assertEqual(mesh.get("filename"), str(self.mesh))
            self.assertEqual(source.read_text(), original)
        self.assertFalse(resolved.exists())

    def test_primitives_and_unsupported_formats_are_rejected(self):
        source = self.package / "robot.urdf"
        source.write_text(
            '<robot name="test"><link name="base"><visual><geometry>'
            '<box size="1 1 1"/></geometry></visual></link></robot>'
        )
        with self.assertRaisesRegex(ValueError, "primitives"):
            with urdf_paths.resolved_urdf(source):
                self.fail("Primitive was accepted")
        (self.package / "part.fbx").write_text("")
        source.write_text(
            '<robot name="test"><link name="base"><visual><geometry>'
            '<mesh filename="part.fbx"/></geometry></visual></link></robot>'
        )
        with self.assertRaisesRegex(ValueError, "format"):
            with urdf_paths.resolved_urdf(source):
                self.fail("Unsupported format was accepted")

    def test_dae_visuals_are_resolved_without_modifying_the_source(self):
        mesh = self.package / "part.dae"
        mesh.write_text("<COLLADA/>")
        source = self.package / "robot.urdf"
        original = (
            '<robot name="test"><link name="base"><visual><geometry>'
            '<mesh filename="part.dae" scale="2 3 4"/></geometry></visual></link></robot>'
        )
        source.write_text(original)
        with urdf_paths.resolved_urdf(source) as resolved:
            visual = ET.parse(resolved).find("./link/visual/geometry/mesh")
            self.assertEqual(visual.get("filename"), str(mesh))
            self.assertEqual(visual.get("scale"), "2 3 4")
        self.assertEqual(source.read_text(), original)

    def test_collision_mesh_paths_are_resolved(self):
        source = self.package / "robot.urdf"
        source.write_text(
            '<robot name="test"><link name="base"><collision><geometry>'
            '<mesh filename="part.obj"/></geometry></collision></link></robot>'
        )
        with urdf_paths.resolved_urdf(source) as resolved:
            mesh = ET.parse(resolved).find("./link/collision/geometry/mesh")
            self.assertEqual(mesh.get("filename"), str(self.mesh))

    def test_invalid_description_and_missing_filename(self):
        source = self.package / "robot.urdf"
        for content, message in (
            ("<not_robot/>", "URDF"),
            (
                '<robot name="test"><link name="base"><visual><geometry>'
                "<mesh/></geometry></visual></link></robot>",
                "filename",
            ),
        ):
            with self.subTest(content=content):
                source.write_text(content)
                with self.assertRaisesRegex(ValueError, message):
                    with urdf_paths.resolved_urdf(source):
                        self.fail("Invalid description was accepted")


if __name__ == "__main__":
    unittest.main()
