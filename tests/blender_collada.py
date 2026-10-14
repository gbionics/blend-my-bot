"""Installed COLLADA meshes, shading, kinematics, rollback and persistence."""

import importlib
from dataclasses import replace
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

import bpy
from mathutils import Matrix
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
arguments = sys.argv[sys.argv.index("--") + 1 :]
archive = Path(arguments[0]).resolve()


def assert_vertices(mesh, expected):
    actual = np.array([mesh.matrix_world @ vertex.co for vertex in mesh.data.vertices])
    np.testing.assert_allclose(actual, expected, atol=1e-5)


with TemporaryDirectory(prefix="blend-my-bot-collada-") as directory:
    root = Path(directory)
    bpy.ops.preferences.extension_repo_add(
        name="COLLADA Test",
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
    importer = importlib.import_module(module_name + ".blend_my_bot.collada_importer")
    data_module = importlib.import_module(module_name + ".blend_my_bot.motion_data")
    from collada_fixture import make_collada

    dae = root / "mesh.dae"
    make_collada(dae)
    image = bpy.data.images.new("Source", width=2, height=2)
    image.pixels = [1, 0, 0, 1, 0, 1, 0, 1, 0, 0, 1, 1, 1, 1, 1, 1]
    image.filepath_raw = str(root / "tex with spaces.png")
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    urdf = root / "robot.urdf"
    urdf.write_text(
        '<robot name="collada"><link name="base">'
        '<visual><origin xyz="0.2 0.3 0.4" rpy="0.1 0.2 0.3"/>'
        '<geometry><mesh filename="mesh.dae" scale="2 3 4"/></geometry>'
        '<material name="fallback"><color rgba="0 1 0 1"/></material></visual></link>'
        '<link name="arm"><visual><origin xyz="0 0 0.5"/>'
        '<geometry><mesh filename="mesh.dae" scale="0.2 0.3 0.4"/></geometry></visual></link>'
        '<joint name="hinge" type="continuous"><parent link="base"/><child link="arm"/>'
        '<origin xyz="0 0 0.8"/><axis xyz="0 0 1"/></joint></robot>'
    )
    original = urdf.read_bytes()
    collection = addon.import_robot(bpy.context, str(urdf), "COLLADA")
    assert len(collection.objects) == 8
    assert collection["blend_my_bot_visual_count"] == 8
    assert all(
        mesh.type == "MESH" and mesh.parent is None for mesh in collection.objects
    )
    assert urdf.read_bytes() == original
    model = addon.motion.restore_model(collection)
    bpy.context.view_layer.update()
    base = model.links["base"].mesh
    local = np.array(
        [
            [0.01, 0.02, 0.03],
            [0.01, 2.02, 0.03],
            [0.01, 0.02, 4.03],
        ]
    )
    origin = Matrix(
        model.links["base"].link_H_geometry.asHomogeneousTransform().toNumPy()
    )
    scaled = local * [2, 3, 4]
    expected = scaled @ np.array(origin)[:3, :3].T + np.array(origin)[:3, 3]
    assert_vertices(base, expected)
    assert base.data.polygons[0].vertices[:] == (0, 1, 2)
    normal = np.array([-1 / 3, 1 / 2, 1 / 4])
    normal /= np.linalg.norm(normal)
    # Blender stores custom normals in a quantized representation.
    np.testing.assert_allclose(base.data.corner_normals[0].vector, normal, atol=1e-4)
    np.testing.assert_allclose(base.data.uv_layers["UV0"].data[0].uv, [0, 0], atol=1e-6)
    solid = base.data.materials[0]
    shader = solid.node_tree.nodes.get("Principled BSDF")
    np.testing.assert_allclose(
        shader.inputs["Base Color"].default_value, [0.25, 0.5, 0.75, 0.8], atol=1e-6
    )
    assert abs(shader.inputs["Alpha"].default_value - 0.375) < 1e-6
    textured = model.links["base_part_1"].mesh
    assert len(textured.data.polygons[0].vertices) == 4
    texture_material = textured.data.materials[0]
    texture = next(
        node for node in texture_material.node_tree.nodes if node.type == "TEX_IMAGE"
    )
    uv = next(node for node in texture_material.node_tree.nodes if node.type == "UVMAP")
    assert uv.uv_map == "UV1"
    assert texture.image.packed_file is not None
    np.testing.assert_allclose(
        textured.data.uv_layers["UV1"].data[0].uv, [0.25, 0.25], atol=1e-6
    )
    assert abs(shader.inputs["Roughness"].default_value - np.sqrt(2 / 52)) < 1e-6
    np.testing.assert_allclose(
        shader.inputs["Emission Color"].default_value, [0.1, 0.2, 0, 1], atol=1e-6
    )
    part = importer.read_collada(dae)[0]
    effect = part.material.effect
    effect.diffuse = effect.emission = effect.specular = None
    effect.transparent = (0.2, 0.4, 0.8, 0.5)
    effect.transparency = None
    material = importer.build_material(part, dae, {})
    node = material.node_tree.nodes.get("Principled BSDF")
    assert abs(node.inputs["Alpha"].default_value - 0.5) < 1e-6
    np.testing.assert_allclose(node.inputs["Base Color"].default_value, [0, 0, 0, 1])
    effect.opaque_mode = "RGB_ZERO"
    effect.transparency = 0.5
    material = importer.build_material(replace(part, double_sided=True), dae, {})
    node = material.node_tree.nodes.get("Principled BSDF")
    assert not material.use_backface_culling
    assert (
        abs(
            node.inputs["Alpha"].default_value
            - (1 - np.dot([0.2, 0.4, 0.8], [0.2126, 0.7152, 0.0722]) * 0.5)
        )
        < 1e-6
    )
    concave = root / "concave.dae"
    make_collada(concave, instances=False, concave=True)
    polygon = importer.import_collada(str(concave))[1].data
    polygon.calc_loop_triangles()
    assert len(polygon.polygons) == 1 and len(polygon.loop_triangles) == 2
    assert abs(sum(triangle.area for triangle in polygon.loop_triangles) - 2.1) < 1e-5
    reflected = root / "reflected.dae"
    make_collada(reflected, reflected=True, instances=False)
    reflected_mesh = importer.import_collada(str(reflected))[0].data
    assert reflected_mesh.polygons[0].vertices[:] == (2, 1, 0)
    np.testing.assert_allclose(reflected_mesh.uv_layers["UV0"].data[0].uv, [0.5, 0.5])
    lines = root / "lines.dae"
    make_collada(lines, lines=True, instances=False)
    line = importer.import_collada(str(lines))[2]
    assert len(line.data.vertices) == 2
    assert len(line.data.edges) == 1 and not line.data.polygons
    zero_sources = []
    repaired_normals = {}
    for reflection in (False, True):
        zero_path = root / f"zero-normals-{reflection}.dae"
        make_collada(
            zero_path, reflected=reflection, instances=False, zero_normals=True
        )
        zero_sources.append(zero_path)
        mesh = importer.import_collada(str(zero_path))[0]
        normals = np.array([normal.vector for normal in mesh.data.corner_normals])
        zero_index = 2 if reflection else 0
        np.testing.assert_allclose(
            normals[zero_index], mesh.data.polygons[0].normal, atol=1e-4
        )
        assert np.all(np.isfinite(normals))
        np.testing.assert_allclose(np.linalg.norm(normals, axis=1), 1, atol=1e-4)
        valid_index = 1
        expected = [0, -1 if reflection else 1, 0]
        np.testing.assert_allclose(normals[valid_index], expected, atol=1e-4)
        repaired_normals[mesh.name] = normals
    duplicate = addon.import_robot(bpy.context, str(urdf), "COLLADA")
    assert len(duplicate.objects) == 8
    assert set(duplicate.objects).isdisjoint(collection.objects)
    with addon.resolved_urdf(urdf) as resolved:
        script = addon.ModelImporter.build_model("COLLADA Script", str(resolved))
        reused = addon.ModelImporter.build_model("COLLADA Script", str(resolved))
    assert len(script.links) == len(reused.links) == 8
    assert {key: link.mesh for key, link in script.links.items()} == {
        key: link.mesh for key, link in reused.links.items()
    }
    bpy.context.view_layer.update()
    unchanged = {mesh.name: np.array(mesh.matrix_world) for mesh in duplicate.objects}
    data = {
        "joints_list": ["hinge"],
        "fps": 50,
        "joint_positions": np.array([[0], [0.3], [0.6]]),
        "root_position": np.array([[0, 0, 0], [0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]),
        "root_quaternion": np.array([[1, 0, 0, 0]] * 3),
    }
    motion = root / "motion.npy"
    np.save(motion, data)
    addon.motion.apply_motion(bpy.context, collection, motion, trusted=True)
    parsed = data_module.parse_motion(data)
    positions = addon.motion.map_joint_positions(model, parsed)
    for sample in (0, 2):
        bpy.context.scene.frame_set(sample + 1)
        bpy.context.view_layer.update()
        transforms = dict(
            model.visual_transforms(parsed.base_transforms()[sample], positions[sample])
        )
        for key, link in model.links.items():
            matrix = transforms[key].asHomogeneousTransform().toNumPy()
            vertices = np.array(
                [vertex.co for vertex in link.mesh.data.vertices]
            ) * np.array(link.mesh.scale)
            assert_vertices(link.mesh, vertices @ matrix[:3, :3].T + matrix[:3, 3])
        for mesh in duplicate.objects:
            np.testing.assert_allclose(
                mesh.matrix_world, unchanged[mesh.name], atol=1e-6
            )
    # A failure after creating packed images/materials must remove only new datablocks.
    before = {
        name: set(getattr(bpy.data, name))
        for name in ("objects", "meshes", "materials", "images", "collections")
    }
    selected = set(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active

    def assert_scene_unchanged():
        for name, blocks in before.items():
            assert set(getattr(bpy.data, name)) == blocks, name
        assert set(bpy.context.selected_objects) == selected
        assert bpy.context.view_layer.objects.active == active

    build_material = importer.build_material

    def fail_after_shader(*args):
        material = build_material(*args)
        if args[0].material.name == "Textured":
            raise RuntimeError("injected shader failure")
        return material

    try:
        with patch.object(importer, "build_material", side_effect=fail_after_shader):
            addon.import_robot(bpy.context, str(urdf), "Broken")
    except RuntimeError as error:
        assert "injected shader failure" in str(error)
    else:
        raise AssertionError("Failed DAE import was reported as successful")
    assert_scene_unchanged()
    (root / "tex with spaces.png").unlink()
    try:
        addon.import_robot(bpy.context, str(urdf), "Missing Texture")
    except FileNotFoundError as error:
        assert "DAE texture not found" in str(error)
    else:
        raise AssertionError("Missing DAE texture was silently ignored")
    assert_scene_unchanged()
    dae.write_text("<COLLADA")
    try:
        addon.import_robot(bpy.context, str(urdf), "Malformed DAE")
    except ValueError as error:
        assert "Cannot read DAE mesh" in str(error)
    else:
        raise AssertionError("Malformed DAE was silently ignored")
    assert_scene_unchanged()
    saved = root / "collada.blend"
    collection_name = collection.name
    bpy.ops.wm.save_as_mainfile(filepath=str(saved))
    dae.unlink()
    urdf.unlink()
    motion.unlink()
    concave.unlink()
    reflected.unlink()
    lines.unlink()
    for path in zero_sources:
        path.unlink()
    bpy.ops.wm.open_mainfile(filepath=str(saved))
    loaded = bpy.data.collections[collection_name]
    restored = addon.motion.restore_model(loaded)
    bpy.context.scene.frame_set(3)
    bpy.context.view_layer.update()
    assert len(restored.links) == 8
    np.testing.assert_allclose(
        [vertex.co for vertex in restored.links["base"].mesh.data.vertices],
        local,
        atol=1e-6,
    )
    for key, transform in restored.visual_transforms(
        parsed.base_transforms()[2], positions[2]
    ):
        mesh = restored.links[key].mesh
        matrix = transform.asHomogeneousTransform().toNumPy()
        vertices = np.array([vertex.co for vertex in mesh.data.vertices]) * np.array(
            mesh.scale
        )
        assert_vertices(mesh, vertices @ matrix[:3, :3].T + matrix[:3, 3])
    assert any(image.packed_file for image in bpy.data.images)
    for name, expected in repaired_normals.items():
        normals = [
            normal.vector for normal in bpy.data.objects[name].data.corner_normals
        ]
        np.testing.assert_allclose(normals, expected, atol=1e-4)
    assert all(
        mesh.animation_data and mesh.animation_data.action for mesh in loaded.objects
    )
    bpy.ops.preferences.addon_disable(module=module_name)
    print("BLEND_MY_BOT_COLLADA_OK", flush=True)
