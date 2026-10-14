"""Run with factory-startup Blender and an isolated BLENDER_USER_RESOURCES."""

import importlib
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

import bpy

archive = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
with TemporaryDirectory(prefix="blend-my-bot-smoke-") as directory:
    bpy.ops.preferences.extension_repo_add(
        name="Blend My Bot Test",
        type="LOCAL",
        use_custom_directory=True,
        custom_directory=directory,
    )
    repo = bpy.context.preferences.extensions.repos[-1]
    result = bpy.ops.extensions.package_install_files(
        filepath=str(archive), repo=repo.module, enable_on_install=True
    )
    assert result == {"FINISHED"}, result
    module_name = f"bl_ext.{repo.module}.blend_my_bot"
    assert module_name in bpy.context.preferences.addons
    addon = importlib.import_module(module_name)
    fixture = Path(__file__).parent / "fixtures" / "robot.urdf"
    assert not hasattr(addon, "BMB_OT_ImportDemo")
    assert not (Path(addon.__file__).parent / "demo" / "robot.urdf").exists()
    assert bpy.ops.blend_my_bot.import_robot(
        filepath=str(fixture), robot_name="Test Robot"
    ) == {"FINISHED"}
    first = bpy.data.collections["Test Robot"]
    assert len(first.objects) == 2
    base = next(obj for obj in first.objects if "_base_" in obj.name)
    arm = next(obj for obj in first.objects if "_arm_" in obj.name)
    assert abs(base.scale.x - 0.6) < 1e-6
    assert abs(arm.location.z - 0.5) < 1e-6
    assert bpy.ops.blend_my_bot.import_robot(
        filepath=str(fixture), robot_name="Test Robot"
    ) == {"FINISHED"}
    assert len(bpy.data.collections["Test Robot.001"].objects) == 2
    assert len(first.objects) == 2

    preferences = bpy.context.preferences.addons[module_name].preferences
    bpy.ops.blend_my_bot.add_search_path()
    preferences.search_paths[-1].directory = directory
    assert len(preferences.search_paths) == 1
    bpy.ops.blend_my_bot.remove_search_path(index=0)
    assert len(preferences.search_paths) == 0

    broken = Path(directory) / "broken.urdf"
    broken.write_text(fixture.read_text().replace("cube.obj", "missing.obj"))
    before = set(bpy.data.objects)
    try:
        addon.import_robot(bpy.context, str(broken), "Broken Robot")
    except FileNotFoundError as error:
        assert "Mesh not found" in str(error)
    else:
        raise AssertionError("Missing mesh was silently accepted")
    assert set(bpy.data.objects) == before
    assert bpy.data.collections.get("Broken Robot") is None

    multiple = Path(directory) / "multiple.urdf"
    mesh_path = str(fixture.parent / "cube.obj")
    multiple.write_text(
        '<robot name="multiple"><link name="base">'
        f'<visual><geometry><mesh filename="{mesh_path}"/></geometry></visual>'
        f'<visual><origin xyz="1 0 0"/><geometry><mesh filename="{mesh_path}"/>'
        "</geometry></visual></link></robot>"
    )
    collection = addon.import_robot(bpy.context, str(multiple), "Multiple Visuals")
    assert len(collection.objects) == 2
    assert sorted(round(obj.location.x) for obj in collection.objects) == [0, 1]

    multipart_mesh = Path(directory) / "multipart.obj"
    multipart_mesh.write_text(
        "o First\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
        "o Second\nv 0 0 0\nv 0 1 0\nv 0 0 1\nf 4 5 6\n"
    )
    multipart = Path(directory) / "multipart.urdf"
    multipart.write_text(
        '<robot name="multipart"><link name="base"><visual><geometry>'
        f'<mesh filename="{multipart_mesh}"/></geometry></visual></link></robot>'
    )
    collection = addon.import_robot(bpy.context, str(multipart), "Multipart")
    assert len(collection.objects) == 2
    model = addon.ModelImporter.build_model("Multipart Script", str(multipart))
    original_parts = {key: link.mesh for key, link in model.links.items()}
    model = addon.ModelImporter.build_model("Multipart Script", str(multipart))
    assert {key: link.mesh for key, link in model.links.items()} == original_parts
    assert len(model.links) == 2

    stl_mesh = Path(directory) / "triangle.stl"
    stl_mesh.write_text(
        "solid triangle\nfacet normal 0 0 1\nouter loop\n"
        "vertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\n"
        "endloop\nendfacet\nendsolid triangle\n"
    )
    stl_robot = Path(directory) / "stl.urdf"
    stl_robot.write_text(
        '<robot name="stl"><link name="base"><visual><geometry>'
        f'<mesh filename="{stl_mesh}"/></geometry></visual></link></robot>'
    )
    assert (
        len(addon.import_robot(bpy.context, str(stl_robot), "STL Robot").objects) == 1
    )

    empty_mesh = Path(directory) / "empty.obj"
    empty_mesh.write_text("")
    failed = Path(directory) / "failed.urdf"
    failed.write_text(
        multiple.read_text().replace(
            f'<visual><origin xyz="1 0 0"/><geometry><mesh filename="{mesh_path}"/>',
            f'<visual><origin xyz="1 0 0"/><geometry><mesh filename="{empty_mesh}"/>',
        )
    )
    previous_objects = set(bpy.data.objects)
    previous_meshes = set(bpy.data.meshes)
    try:
        addon.import_robot(bpy.context, str(failed), "Failed Robot")
    except (ValueError, RuntimeError):
        pass
    else:
        raise AssertionError("Empty visual mesh was silently accepted")
    assert set(bpy.data.objects) == previous_objects
    assert set(bpy.data.meshes) == previous_meshes
    assert bpy.data.collections.get("Failed Robot") is None

    package = Path(directory) / "my_robot"
    package.mkdir()
    (package / "cube.obj").write_text((fixture.parent / "cube.obj").read_text())
    urdf_directory = Path(directory) / "urdfs"
    urdf_directory.mkdir()
    packaged = urdf_directory / "packaged.urdf"
    packaged.write_text(
        fixture.read_text().replace("cube.obj", "package://my_robot/cube.obj")
    )
    bpy.ops.blend_my_bot.add_search_path()
    preferences.search_paths[-1].directory = str(package)
    assert (
        len(addon.import_robot(bpy.context, str(packaged), "Package Robot").objects)
        == 2
    )
    bpy.ops.blend_my_bot.remove_search_path(index=0)

    with patch.dict(os.environ, {"RRU_ADDITIONAL_PATHS": directory}):
        assert (
            len(
                addon.import_robot(
                    bpy.context, str(packaged), "Environment Robot"
                ).objects
            )
            == 2
        )

    (package / "package.xml").write_text("<package><name>my_robot</name></package>")
    variants = []
    for name in ("v1", "v2"):
        variant = package / "urdf" / name / "model.urdf"
        variant.parent.mkdir(parents=True)
        variant.write_text(packaged.read_text())
        variants.append(variant)
    bpy.ops.blend_my_bot.add_search_path()
    preferences.search_paths[-1].directory = str(package)
    assert bpy.ops.blend_my_bot.refresh_catalog() == {"FINISHED"}
    settings = bpy.context.window_manager.blend_my_bot_catalog
    settings.package = str(package)
    settings.urdf = str(variants[1])
    assert bpy.ops.blend_my_bot.refresh_catalog() == {"FINISHED"}
    assert settings.package == str(package)
    assert settings.urdf == str(variants[1])
    assert addon.selected_description(bpy.context).label == "urdf/v2/model.urdf"
    bpy.ops.blend_my_bot.remove_search_path(index=0)
    assert bpy.ops.blend_my_bot.import_available_robot() == {"FINISHED"}
    selected = bpy.data.collections["my_robot_model"]
    assert not hasattr(settings, "create_rig")
    assert len(selected.objects) == 2
    assert all(obj.type == "MESH" and obj.parent is None for obj in selected.objects)
    assert not hasattr(addon, "ik")
    assert selected["blend_my_bot_urdf"] == str(variants[1].resolve())
    assert bpy.ops.blend_my_bot.import_available_robot() == {"FINISHED"}
    assert len(bpy.data.collections["my_robot_model.001"].objects) == 2

    with patch.dict(os.environ, {"RRU_ADDITIONAL_PATHS": directory}):
        assert bpy.ops.blend_my_bot.refresh_catalog() == {"FINISHED"}
        assert settings.urdf == str(variants[1])

    bpy.ops.blend_my_bot.add_search_path()
    preferences.search_paths[-1].directory = str(Path(directory) / "missing")
    try:
        bpy.ops.blend_my_bot.refresh_catalog()
    except RuntimeError as error:
        assert "does not exist" in str(error)
    else:
        raise AssertionError("Invalid catalog search folder was silently ignored")
    assert settings.urdf == str(variants[1])
    bpy.ops.blend_my_bot.remove_search_path(index=0)

    catalog_module = importlib.import_module(
        module_name + ".blend_my_bot.robot_catalog"
    )
    with patch.object(catalog_module, "get_default_search_paths", return_value=[]):
        assert bpy.ops.blend_my_bot.refresh_catalog() == {"FINISHED"}
    assert not bpy.ops.blend_my_bot.import_available_robot.poll()
    assert settings.package == "NONE"
    assert settings.urdf == "NONE"

    addon.set_catalog(
        bpy.context,
        [addon.RobotDescription(package, variant) for variant in variants],
    )
    settings.urdf = str(variants[1])
    bpy.ops.blend_my_bot.add_search_path()
    preferences.search_paths[-1].directory = str(package)
    timer = object()
    timer_manager = SimpleNamespace(
        blend_my_bot_catalog=settings,
        event_timer_add=Mock(return_value=timer),
        event_timer_remove=Mock(),
        modal_handler_add=Mock(),
    )
    scan_context = SimpleNamespace(
        window_manager=timer_manager,
        preferences=bpy.context.preferences,
        window=bpy.context.window,
        area=None,
    )
    timer_event = Mock(spec_set=bpy.types.Event.bl_rna.properties.keys())
    timer_event.type = "TIMER"

    def scan_operator():
        operator = SimpleNamespace(report=Mock())
        for method in (
            "execute",
            "invoke",
            "modal",
            "cancel",
            "finish_scan",
            "scan_failed",
        ):
            setattr(
                operator,
                method,
                MethodType(getattr(addon.BMB_OT_RefreshCatalog, method), operator),
            )
        with patch.object(
            addon,
            "bpy",
            SimpleNamespace(app=SimpleNamespace(background=False), path=bpy.path),
        ):
            assert operator.invoke(scan_context, None) == {"RUNNING_MODAL"}
        return operator

    operator = scan_operator()
    assert not bpy.ops.blend_my_bot.refresh_catalog.poll()
    assert not bpy.ops.blend_my_bot.import_available_robot.poll()
    assert operator.modal(scan_context, SimpleNamespace(type="MOUSEMOVE")) == {
        "PASS_THROUGH"
    }
    with patch.object(addon, "perf_counter", side_effect=[0.0, 0.0, 0.03]):
        assert operator.modal(scan_context, timer_event) == {"RUNNING_MODAL"}
    assert settings.scanning
    assert operator.modal(scan_context, SimpleNamespace(type="ESC")) == {"CANCELLED"}
    assert not settings.scanning
    assert settings.urdf == str(variants[1])
    timer_manager.event_timer_remove.assert_called_once_with(timer)
    assert addon._active_scan is None

    operator = scan_operator()
    for _ in range(100):
        result = operator.modal(scan_context, timer_event)
        if result == {"FINISHED"}:
            break
        assert result == {"RUNNING_MODAL"}
    else:
        raise AssertionError("Timer-driven catalog scan did not finish")
    assert not settings.scanning
    assert settings.urdf == str(variants[1])
    assert addon._active_scan is None
    bpy.ops.blend_my_bot.remove_search_path(index=0)

    # The same library remains usable without extension operators.
    with addon.resolved_urdf(fixture) as resolved:
        model = addon.ModelImporter.build_model(
            "Script API", str(resolved), ["shoulder"]
        )
    import numpy as np

    bpy.context.scene.frame_set(7)
    model.update(np.eye(4), np.zeros(model.kindyn.getNrOfDegreesOfFreedom()))
    assert all(link.mesh.animation_data is not None for link in model.links.values())
    for link in model.links.values():
        animation = link.mesh.animation_data
        if hasattr(animation.action, "layers"):
            slot = animation.action_slot
            curves = animation.action.layers[0].strips[0].channelbag(slot).fcurves
        else:
            curves = animation.action.fcurves
        assert all(
            point.co.x == 7 for curve in curves for point in curve.keyframe_points
        )
    arm = model.links["arm"].mesh
    bpy.context.scene.frame_set(8)
    model.update(np.eye(4), np.array([0.5]))
    assert arm.rotation_quaternion.angle > 1e-4
    bpy.ops.preferences.addon_disable(module=module_name)
    assert module_name not in bpy.context.preferences.addons
    assert not hasattr(bpy.types.WindowManager, "blend_my_bot_catalog")
    bpy.ops.preferences.addon_enable(module=module_name)
    assert bpy.ops.blend_my_bot.import_robot(
        filepath=str(fixture), robot_name="Test Robot"
    ) == {"FINISHED"}
    assert bpy.context.object.type == "MESH"
    print("BLEND_MY_BOT_SMOKE_OK")
