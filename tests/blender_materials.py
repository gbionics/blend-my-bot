"""Installed-extension tests for URDF color fallback and material preservation."""

import importlib
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from tempfile import TemporaryDirectory

import bpy
import numpy as np

archive = Path(sys.argv[sys.argv.index("--") + 1]).resolve()


def assert_color(mesh, rgba):
    assert len(mesh.data.materials) == 1, f"No URDF material on {mesh.name}"
    material = mesh.data.materials[0]
    node = material.node_tree.nodes.get("Principled BSDF")
    np.testing.assert_allclose(material.diffuse_color, rgba, atol=1e-6)
    np.testing.assert_allclose(node.inputs["Base Color"].default_value, rgba, atol=1e-6)
    assert abs(node.inputs["Alpha"].default_value - rgba[3]) < 1e-6
    np.testing.assert_allclose(mesh.color, rgba, atol=1e-6)
    return material


with TemporaryDirectory(prefix="blend-my-bot-materials-") as directory:
    root = Path(directory)
    bpy.ops.preferences.extension_repo_add(
        name="URDF Materials Test",
        type="LOCAL",
        use_custom_directory=True,
        custom_directory=str(root / "extension"),
    )
    repo = bpy.context.preferences.extensions.repos[-1]
    assert bpy.ops.extensions.package_install_files(
        filepath=str(archive), repo=repo.module, enable_on_install=True
    ) == {"FINISHED"}
    module_name = f"bl_ext.{repo.module}.blend_my_bot"
    addon = importlib.import_module(module_name)
    triangle = root / "triangle.stl"
    triangle.write_text(
        "solid triangle\nfacet normal 0 0 1\nouter loop\n"
        "vertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\n"
        "endloop\nendfacet\nendsolid triangle\n"
    )
    source = root / "robot.urdf"
    source.write_text(
        '<robot name="colors"><material name="dark"><color rgba="0.2 0.2 0.2 1"/></material>'
        '<link name="base">'
        '<visual><geometry><mesh filename="triangle.stl"/></geometry><material name="dark"/></visual>'
        '<visual><geometry><mesh filename="triangle.stl"/></geometry><material name="dark"/></visual>'
        '<visual><geometry><mesh filename="triangle.stl"/></geometry>'
        '<material name="inline"><color rgba="0.1 0.4 0.8 0.35"/></material></visual>'
        '<visual><geometry><mesh filename="triangle.stl"/></geometry></visual>'
        "</link></robot>"
    )
    original = source.read_bytes()
    collection = addon.import_robot(bpy.context, str(source), "Colors")
    model = addon.motion.restore_model(collection)
    dark = assert_color(model.links["base"].mesh, (0.2, 0.2, 0.2, 1))
    assert assert_color(model.links["base_1"].mesh, (0.2, 0.2, 0.2, 1)) == dark
    assert_color(model.links["base_2"].mesh, (0.1, 0.4, 0.8, 0.35))
    assert not model.links["base_3"].mesh.data.materials
    assert source.read_bytes() == original
    duplicate = addon.import_robot(bpy.context, str(source), "Colors")
    duplicate_model = addon.motion.restore_model(duplicate)
    assert assert_color(duplicate_model.links["base"].mesh, (0.2, 0.2, 0.2, 1)) != dark
    assert all(
        mesh.type == "MESH" and mesh.parent is None for mesh in collection.objects
    )

    with addon.resolved_urdf(source) as resolved:
        scripted = addon.ModelImporter.build_model("Color Script", str(resolved))
        assert_color(scripted.links["base"].mesh, (0.2, 0.2, 0.2, 1))
        scripted.links["base"].mesh.data.materials.clear()
        custom = bpy.data.materials.new("User material")
        scripted.links["base"].mesh.data.materials.append(custom)
        reused = addon.ModelImporter.build_model("Color Script", str(resolved))
        assert reused.links["base"].mesh == scripted.links["base"].mesh
        assert reused.links["base"].mesh.data.materials[0] == custom
        assert len(reused.links["base"].mesh.data.materials) == 1

    multipart = root / "multipart.obj"
    multipart.write_text(
        "mtllib multipart.mtl\n"
        "o First\nv 0 0 0\nv 1 0 0\nv 0 1 0\nusemtl Embedded\nf 1 2 3\n"
        "o Second\nv 0 0 0\nv 0 1 0\nv 0 0 1\nusemtl Embedded\nf 4 5 6\n"
    )
    (root / "multipart.mtl").write_text("newmtl Embedded\nKd 0.6 0.3 0.1\n")
    obj_source = root / "obj.urdf"
    obj_source.write_text(
        '<robot name="obj"><link name="base"><visual><geometry>'
        '<mesh filename="multipart.obj"/></geometry>'
        '<material name="fallback"><color rgba="0 1 0 1"/></material>'
        "</visual></link></robot>"
    )
    obj_collection = addon.import_robot(bpy.context, str(obj_source), "Embedded OBJ")
    assert len(obj_collection.objects) == 2
    for mesh in obj_collection.objects:
        assert len(mesh.data.materials) == 1
        assert mesh.data.materials[0].name.startswith("Embedded")
        node = mesh.data.materials[0].node_tree.nodes.get("Principled BSDF")
        np.testing.assert_allclose(
            node.inputs["Base Color"].default_value[:3], [0.6, 0.3, 0.1], atol=1e-6
        )

    uncolored = root / "uncolored.obj"
    uncolored.write_text(
        multipart.read_text()
        .replace("mtllib multipart.mtl\n", "")
        .replace("usemtl Embedded\n", "")
    )
    obj_source.write_text(
        obj_source.read_text().replace("multipart.obj", "uncolored.obj")
    )
    obj_collection = addon.import_robot(bpy.context, str(obj_source), "Fallback OBJ")
    assert len(obj_collection.objects) == 2
    for mesh in obj_collection.objects:
        assert_color(mesh, (0, 1, 0, 1))

    sys.path.insert(0, str(Path(__file__).parent))
    from collada_fixture import make_collada

    dae = root / "uncolored.dae"
    make_collada(dae)
    tree = ET.parse(dae)
    for element in tree.iter():
        if element.tag.rsplit("}", 1)[-1] in {"triangles", "polylist"}:
            element.attrib.pop("material", None)
    tree.write(dae, encoding="utf-8", xml_declaration=True)
    dae_source = root / "dae.urdf"
    dae_source.write_text(
        obj_source.read_text().replace("uncolored.obj", "uncolored.dae")
    )
    dae_collection = addon.import_robot(bpy.context, str(dae_source), "Fallback DAE")
    assert len(dae_collection.objects) == 4
    for mesh in dae_collection.objects:
        assert_color(mesh, (0, 1, 0, 1))

    failed = root / "failed.urdf"
    empty = root / "empty.obj"
    empty.write_text("")
    failed.write_text(
        source.read_text().replace(
            '<visual><geometry><mesh filename="triangle.stl"/></geometry></visual>',
            '<visual><geometry><mesh filename="empty.obj"/></geometry></visual>',
        )
    )
    before = {
        name: set(getattr(bpy.data, name))
        for name in ("objects", "meshes", "materials", "collections")
    }
    selected = set(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    try:
        addon.import_robot(bpy.context, str(failed), "Failed Colors")
    except (ValueError, RuntimeError):
        pass
    else:
        raise AssertionError("Empty mesh was accepted after creating URDF materials")
    for name, blocks in before.items():
        assert set(getattr(bpy.data, name)) == blocks, name
    assert set(bpy.context.selected_objects) == selected
    assert bpy.context.view_layer.objects.active == active
    for invalid in (
        source.read_text().replace('rgba="0.2 0.2 0.2 1"', 'rgba="nan 0.2 0.2 1"'),
        source.read_text().replace(
            '<material name="dark"/>', '<material name="undefined"/>'
        ),
    ):
        failed.write_text(invalid)
        try:
            addon.import_robot(bpy.context, str(failed), "Invalid Colors")
        except ValueError as error:
            assert "RGBA" in str(error) or "undefined" in str(error)
        else:
            raise AssertionError("Invalid URDF material was accepted")
        for name, blocks in before.items():
            assert set(getattr(bpy.data, name)) == blocks, name
        assert set(bpy.context.selected_objects) == selected
        assert bpy.context.view_layer.objects.active == active
        try:
            addon.ModelImporter.build_model("Invalid Script", str(failed))
        except ValueError as error:
            assert "RGBA" in str(error) or "undefined" in str(error)
        else:
            raise AssertionError("Scripting API accepted an invalid URDF material")

    data = {
        "joints_list": [],
        "fps": 50,
        "joint_positions": np.empty((2, 0)),
        "root_position": np.array([[0, 0, 0], [0.1, 0.2, 0.3]]),
        "root_quaternion": np.array([[1, 0, 0, 0]] * 2),
    }
    motion = root / "motion.npy"
    np.save(motion, data)
    addon.motion.apply_motion(bpy.context, collection, motion, trusted=True)
    collection_name = collection.name
    saved = root / "materials.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(saved))
    source.unlink()
    triangle.unlink()
    bpy.ops.wm.open_mainfile(filepath=str(saved))
    restored = addon.motion.restore_model(bpy.data.collections[collection_name])
    bpy.context.scene.frame_set(2)
    bpy.context.view_layer.update()
    for key in ("base", "base_1", "base_2", "base_3"):
        np.testing.assert_allclose(
            restored.links[key].mesh.location, [0.1, 0.2, 0.3], atol=1e-6
        )
    assert_color(restored.links["base"].mesh, (0.2, 0.2, 0.2, 1))
    assert_color(restored.links["base_2"].mesh, (0.1, 0.4, 0.8, 0.35))
    bpy.ops.preferences.addon_disable(module=module_name)
    print("BLEND_MY_BOT_MATERIALS_OK", flush=True)
