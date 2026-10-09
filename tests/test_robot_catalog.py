import importlib.util
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "robot_catalog", ROOT / "src" / "blend_my_bot" / "robot_catalog.py"
)
catalog = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = catalog
spec.loader.exec_module(catalog)


class RobotCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def make_urdf(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('<robot name="test"/>')
        return path

    def entries(self, roots=()):
        return [
            entry
            for _, batch in catalog.iter_robot_descriptions(roots)
            for entry in batch
        ]

    def test_package_root_and_parent_discover_nested_variants(self):
        package = self.root / "my_robot"
        first = self.make_urdf(package / "robots" / "v1" / "model.urdf")
        second = self.make_urdf(package / "robots" / "v2" / "model.URDF")
        for root in (package, self.root):
            with self.subTest(root=root):
                entries = self.entries([root])
                self.assertEqual(
                    {entry.urdf_path for entry in entries}, {first, second}
                )
                self.assertEqual(
                    {entry.package_directory for entry in entries}, {package}
                )
                self.assertEqual(
                    {entry.label for entry in entries},
                    {"robots/v1/model.urdf", "robots/v2/model.URDF"},
                )

    def test_package_manifests_define_nested_package_boundaries(self):
        package = self.root / "workspace" / "src" / "my_robot"
        urdf = self.make_urdf(package / "config" / "description.urdf")
        for manifest in ("package.xml", "model.config"):
            with self.subTest(manifest=manifest):
                marker = package / manifest
                marker.write_text("")
                entries = self.entries([self.root])
                self.assertEqual(entries[0].package_directory, package)
                self.assertEqual(entries[0].urdf_path, urdf)
                marker.unlink()

    def test_repository_share_layout_groups_by_resource_package(self):
        first = self.make_urdf(
            self.root / "share" / "gene" / "robots" / "gene01" / "model.urdf"
        )
        second = self.make_urdf(self.root / "share" / "other_robot" / "model.urdf")
        for search_root in (self.root, self.root / "share"):
            with self.subTest(search_root=search_root):
                entries = self.entries([search_root])
                self.assertEqual(
                    {entry.package_directory for entry in entries},
                    {self.root / "share" / "gene", second.parent},
                )
                self.assertEqual(
                    {entry.urdf_path for entry in entries}, {first, second}
                )
                gene = next(entry for entry in entries if entry.urdf_path == first)
                self.assertEqual(gene.label, "robots/gene01/model.urdf")

    def test_ros_and_ament_resource_paths(self):
        shared = self.root / "install" / "share"
        urdf = self.make_urdf(shared / "my_robot" / "model.urdf")
        for variable, directory in (
            ("ROS_PACKAGE_PATH", shared),
            ("AMENT_PREFIX_PATH", shared.parent),
        ):
            with self.subTest(variable=variable):
                with patch.dict(os.environ, {variable: str(directory)}):
                    self.assertEqual(
                        [entry.urdf_path for entry in self.entries()], [urdf]
                    )

    def test_symlink_packages_cycles_and_overlapping_roots_are_deduplicated(self):
        source = self.root / "source" / "robot"
        urdf = self.make_urdf(source / "model.urdf")
        source.joinpath("loop").symlink_to(source, target_is_directory=True)
        shared = self.root / "share"
        shared.mkdir()
        shared.joinpath("robot").symlink_to(source, target_is_directory=True)
        entries = self.entries([shared, source, shared / "robot"])
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].urdf_path.resolve(), urdf)
        self.assertEqual(entries[0].package_directory, shared / "robot")

    def test_duplicate_package_names_remain_separate(self):
        first = self.make_urdf(self.root / "one" / "robot" / "model.urdf")
        second = self.make_urdf(self.root / "two" / "robot" / "model.urdf")
        entries = self.entries([first.parent, second.parent])
        self.assertEqual(
            {entry.package_directory for entry in entries},
            {first.parent, second.parent},
        )

    def test_hidden_directories_and_xacro_templates_are_not_listed(self):
        self.make_urdf(self.root / ".git" / "hidden.urdf")
        self.make_urdf(self.root / "template.urdf.xacro")
        with patch.object(catalog, "get_default_search_paths", return_value=[]):
            self.assertEqual(self.entries([self.root]), [])

    def test_invalid_search_folder_and_scan_errors_are_explicit(self):
        with self.assertRaisesRegex(NotADirectoryError, "does not exist"):
            self.entries([self.root / "missing"])
        with self.assertRaises(PermissionError):
            catalog.raise_scan_error(PermissionError("Not readable"))


if __name__ == "__main__":
    unittest.main()
