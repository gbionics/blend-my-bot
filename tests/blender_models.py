"""Import every discovered model from a local asset repository in isolated Blender."""

import importlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
import xml.etree.ElementTree as ET

import bpy
from mathutils import Vector

arguments = sys.argv[sys.argv.index("--") + 1 :]
if len(arguments) != 2:
    raise ValueError("Expected extension ZIP and robot model repository paths")
archive, models_root = (Path(argument).resolve() for argument in arguments)
results = []
with TemporaryDirectory(prefix="blend-my-bot-models-") as directory:
    bpy.ops.preferences.extension_repo_add(
        name="Real Robot Models Test",
        type="LOCAL",
        use_custom_directory=True,
        custom_directory=directory,
    )
    repo = bpy.context.preferences.extensions.repos[-1]
    assert bpy.ops.extensions.package_install_files(
        filepath=str(archive), repo=repo.module, enable_on_install=True
    ) == {"FINISHED"}
    module_name = f"bl_ext.{repo.module}.blend_my_bot"
    addon = importlib.import_module(module_name)
    preferences = bpy.context.preferences.addons[module_name].preferences
    preferences.search_paths.add().directory = str(models_root)
    assert bpy.ops.blend_my_bot.refresh_catalog() == {"FINISHED"}
    entries = [
        entry for entry in addon._catalog if entry.urdf_path.is_relative_to(models_root)
    ]
    expected = set(models_root.glob("share/**/*.urdf"))
    assert {entry.urdf_path for entry in entries} == expected
    assert entries, f"No robots discovered in {models_root}"
    print(
        "BMB_REAL_CATALOG "
        + json.dumps(
            [
                {"package": str(entry.package_directory), "urdf": entry.label}
                for entry in entries
            ]
        ),
        flush=True,
    )
    settings = bpy.context.window_manager.blend_my_bot_catalog
    for entry in entries:
        start = perf_counter()
        row = {"model": str(entry.urdf_path.relative_to(models_root))}
        original = entry.urdf_path.read_bytes()
        previous_objects = set(bpy.data.objects)
        previous_collections = set(bpy.data.collections)
        previous_meshes = set(bpy.data.meshes)
        previous_materials = set(bpy.data.materials)
        try:
            try:
                with addon.resolved_urdf(entry.urdf_path, [models_root]):
                    row["repository_path_resolution"] = "PASS"
            except (OSError, ValueError, ET.ParseError) as error:
                row["repository_path_resolution"] = str(error)
            settings.package = str(entry.package_directory)
            settings.urdf = str(entry.urdf_path)
            assert bpy.ops.blend_my_bot.import_available_robot() == {"FINISHED"}
            created = set(bpy.data.collections) - previous_collections
            assert (
                len(created) == 1
            ), f"Expected one robot collection, got {len(created)}"
            collection = created.pop()
            assert collection["blend_my_bot_urdf"] == str(entry.urdf_path.resolve())
            visual_count = len(ET.fromstring(original).findall("./link/visual"))
            assert len(collection.objects) >= visual_count
            assert all(
                obj.type == "MESH" and len(obj.data.polygons) > 0
                for obj in collection.objects
            ), "Imported robot contains an empty or non-mesh object"
            bpy.context.view_layer.update()
            corners = [
                obj.matrix_world @ Vector(corner)
                for obj in collection.objects
                for corner in obj.bound_box
            ]
            dimensions = [
                max(point[axis] for point in corners)
                - min(point[axis] for point in corners)
                for axis in range(3)
            ]
            assert all(0.001 < value < 100 for value in dimensions), dimensions
            row.update(
                import_status="PASS",
                visuals=visual_count,
                objects=len(collection.objects),
                dimensions_m=[round(value, 3) for value in dimensions],
            )
        except (
            OSError,
            ValueError,
            RuntimeError,
            AssertionError,
            ET.ParseError,
        ) as error:
            row.update(import_status="FAIL", error=str(error))
        finally:
            assert entry.urdf_path.read_bytes() == original, "Source URDF was modified"
            for obj in set(bpy.data.objects) - previous_objects:
                bpy.data.objects.remove(obj, do_unlink=True)
            for collection in set(bpy.data.collections) - previous_collections:
                bpy.data.collections.remove(collection)
            for mesh in set(bpy.data.meshes) - previous_meshes:
                assert mesh.users == 0
                bpy.data.meshes.remove(mesh)
            for material in set(bpy.data.materials) - previous_materials:
                if material.users == 0:
                    bpy.data.materials.remove(material)
            row["seconds"] = round(perf_counter() - start, 2)
            results.append(row)
            print("BMB_REAL_RESULT " + json.dumps(row), flush=True)
    bpy.ops.preferences.addon_disable(module=module_name)
failed = [
    row
    for row in results
    if row["import_status"] != "PASS" or row["repository_path_resolution"] != "PASS"
]
print(
    "BMB_REAL_SUMMARY "
    + json.dumps(
        {
            "tested": len(results),
            "failed": len(failed),
        }
    ),
    flush=True,
)
if failed:
    raise AssertionError(f"{len(failed)} real-model tests failed; see BMB_REAL_RESULT")
