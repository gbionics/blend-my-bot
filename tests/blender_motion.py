"""Installed mesh-only motion tests, optionally including the full Gene dataset."""

import importlib
from math import floor
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

import bpy
from mathutils import Matrix, Quaternion
import numpy as np

arguments = sys.argv[sys.argv.index("--") + 1 :]
archive = Path(arguments[0]).resolve()


def curves(mesh):
    animation = mesh.animation_data
    if hasattr(animation.action, "layers"):
        return (
            animation.action.layers[0]
            .strips[0]
            .channelbag(animation.action_slot)
            .fcurves
        )
    return animation.action.fcurves


def assert_pose(model, motion, sample, start_frame, scene_fps):
    frames = motion.frame_numbers(start_frame, scene_fps)
    frame = frames[sample]
    bpy.context.scene.frame_set(floor(frame), subframe=frame - floor(frame))
    positions = addon.motion.map_joint_positions(model, motion)
    expected = dict(
        model.visual_transforms(motion.base_transforms()[sample], positions[sample])
    )
    bpy.context.view_layer.update()
    for key, link in model.links.items():
        world = Matrix(expected[key].asHomogeneousTransform().toNumPy())
        scale = Matrix.Diagonal((*link.mesh.scale, 1))
        error = np.max(
            np.abs(np.array(link.mesh.matrix_world) - np.array(world @ scale))
        )
        assert error < 1e-5, (key, sample, error)


with TemporaryDirectory(prefix="blend-my-bot-motion-") as directory:
    bpy.ops.preferences.extension_repo_add(
        name="Mesh Motion Test",
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
    data_module = importlib.import_module(module_name + ".blend_my_bot.motion_data")
    assert not hasattr(addon, "ik")
    assert not hasattr(bpy.types.Object, "blend_my_bot_ik")
    assert not (Path(addon.__file__).parent / "blend_my_bot" / "robot_rig.py").exists()
    cube = Path(__file__).parent / "fixtures" / "cube.obj"
    multipart = Path(directory) / "multipart.obj"
    multipart.write_text(
        "o First\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
        "o Second\nv 0 0 0\nv 0 1 0\nv 0 0 1\nf 4 5 6\n"
    )
    long_name = "a_long_robot_link_name_" * 4
    fixture = Path(directory) / "robot.urdf"
    fixture.write_text(
        '<robot name="motion"><link name="base">'
        f'<visual><geometry><mesh filename="{cube}" scale="0.6 0.4 0.2"/></geometry></visual>'
        f'<visual><origin xyz="0.2 0.3 0.4" rpy="0.2 0.3 0.1"/>'
        f'<geometry><mesh filename="{cube}" scale="0.1 0.2 0.3"/></geometry></visual></link>'
        f'<link name="{long_name}"><visual><origin xyz="0 0 0.2" rpy="0.2 0.1 0.3"/>'
        f'<geometry><mesh filename="{cube}" scale="0.2 0.1 0.6"/></geometry></visual></link>'
        '<link name="invisible"/><link name="slider"><visual><origin xyz="0.1 0.2 0.3"/>'
        f'<geometry><mesh filename="{multipart}" scale="0.3 0.4 0.5"/></geometry></visual></link>'
        f'<joint name="first" type="continuous"><parent link="base"/><child link="{long_name}"/>'
        '<origin xyz="0.3 0.2 0.1" rpy="0.1 0.3 0.2"/><axis xyz="0 0 1"/></joint>'
        f'<joint name="hidden" type="fixed"><parent link="{long_name}"/><child link="invisible"/>'
        '<origin xyz="0 0 0.1"/></joint>'
        '<joint name="second" type="prismatic"><parent link="invisible"/><child link="slider"/>'
        '<axis xyz="0 1 0"/><limit lower="-1" upper="1" effort="10" velocity="1"/>'
        "</joint></robot>"
    )
    data = {
        "joints_list": ["second", "first"],
        "fps": np.array([50], dtype=np.float32),
        "duration": 0.06,
        "joint_positions": np.array([[0, 3], [0.1, 3.1], [0.2, 3.2], [0.3, 3.3]]),
        "root_position": np.array(
            [[0, 0, 1], [0.1, 0.2, 1.1], [0.2, 0.3, 1.2], [0.3, 0.4, 1.3]]
        ),
        "root_quaternion": np.array(
            [Quaternion((0, 0, 1), angle) for angle in [0, 0.1, 0.2, 0.3]]
        ),
    }
    data["root_quaternion"][1] *= -1
    motion_path = Path(directory) / "motion.npy"
    np.save(motion_path, data)
    collection = addon.import_robot(bpy.context, str(fixture), "Robot")
    assert len(collection.objects) == 5
    assert all(obj.type == "MESH" and obj.parent is None for obj in collection.objects)
    assert bpy.context.scene.blend_my_bot_motion.robot == collection
    duplicate = addon.import_robot(bpy.context, str(fixture), "Robot")
    bpy.context.view_layer.update()
    duplicate_matrices = {
        obj.name: obj.matrix_world.copy() for obj in duplicate.objects
    }
    bpy.context.scene.blend_my_bot_motion.robot = collection
    for index, mesh in enumerate(collection.objects):
        mesh.name = f"Renamed visual {index}"
    model = addon.motion.restore_model(collection)
    assert long_name in {link.name for link in model.links.values()}
    kinematics = model.kindyn.model()
    mapped = addon.motion.map_joint_positions(model, data_module.parse_motion(data))
    assert (
        mapped[
            -1, kinematics.getJoint(kinematics.getJointIndex("first")).getDOFsOffset()
        ]
        == 3.3
    )
    assert (
        mapped[
            -1, kinematics.getJoint(kinematics.getJointIndex("second")).getDOFsOffset()
        ]
        == 0.3
    )
    previous_actions = set(bpy.data.actions)
    try:
        bpy.ops.blend_my_bot.load_motion(filepath=str(motion_path))
    except RuntimeError as error:
        assert "trust" in str(error)
    else:
        raise AssertionError("Untrusted motion was deserialized")
    assert set(bpy.data.actions) == previous_actions
    assert bpy.ops.blend_my_bot.load_motion(
        filepath=str(motion_path), trust_file=True
    ) == {"FINISHED"}
    motion = data_module.parse_motion(data)
    scene = bpy.context.scene
    assert scene.render.fps / scene.render.fps_base == 50
    for mesh in collection.objects:
        assert len(curves(mesh)) == 7
        assert all(len(curve.keyframe_points) == 4 for curve in curves(mesh))
        assert all(
            point.interpolation == "LINEAR"
            for curve in curves(mesh)
            for point in curve.keyframe_points
        )
        assert all(
            np.allclose([point.co.x for point in curve.keyframe_points], [1, 2, 3, 4])
            for curve in curves(mesh)
        )
        quaternion_curves = sorted(
            (
                curve
                for curve in curves(mesh)
                if curve.data_path == "rotation_quaternion"
            ),
            key=lambda curve: curve.array_index,
        )
        quaternions = np.array(
            [
                [point.co.y for point in curve.keyframe_points]
                for curve in quaternion_curves
            ]
        ).T
        assert np.all(np.sum(quaternions[:-1] * quaternions[1:], axis=1) >= 0)
    for sample in range(motion.samples):
        assert_pose(model, motion, sample, 1, 50)
    for name, matrix in duplicate_matrices.items():
        np.testing.assert_allclose(
            np.array(bpy.data.objects[name].matrix_world), np.array(matrix), atol=1e-6
        )
    actions = set(bpy.data.actions)
    before_animation = {
        mesh.name: mesh.animation_data.action for mesh in collection.objects
    }
    try:
        addon.motion.apply_motion(bpy.context, collection, motion_path, trusted=True)
    except ValueError as error:
        assert "Replace Existing Animation" in str(error)
    else:
        raise AssertionError("Existing animation was overwritten without permission")
    assert set(bpy.data.actions) == actions
    invalid = Path(directory) / "invalid.npy"
    bad_data = dict(data, joints_list=["missing", "first"])
    np.save(invalid, bad_data)
    try:
        addon.motion.apply_motion(
            bpy.context, collection, invalid, trusted=True, replace_animation=True
        )
    except ValueError as error:
        assert "missing" in str(error)
    else:
        raise AssertionError("Unknown motion joint was accepted")
    assert set(bpy.data.actions) == actions
    scene.frame_set(3, subframe=0.2)
    extreme = Path(directory) / "extreme.npy"
    np.save(extreme, dict(data, root_position=np.full((4, 3), 1e40)))
    try:
        addon.motion.apply_motion(
            bpy.context, collection, extreme, trusted=True, replace_animation=True
        )
    except ValueError as error:
        assert "finite keyframe range" in str(error)
    else:
        raise AssertionError("Transforms outside Blender's numeric range were accepted")
    assert set(bpy.data.actions) == actions
    before_fps = scene.render.fps, scene.render.fps_base
    create = addon.motion.build_action
    calls = 0

    def fail_during_build(*args):
        global calls
        calls += 1
        if calls == 2:
            raise RuntimeError("Injected action creation failure")
        return create(*args)

    with patch.object(addon.motion, "build_action", side_effect=fail_during_build):
        try:
            addon.motion.apply_motion(
                bpy.context,
                collection,
                motion_path,
                trusted=True,
                replace_animation=True,
            )
        except RuntimeError as error:
            assert "Injected" in str(error)
        else:
            raise AssertionError("Action creation failure was not propagated")
    assert set(bpy.data.actions) == actions
    assert (scene.render.fps, scene.render.fps_base) == before_fps
    assert scene.frame_current == 3 and abs(scene.frame_subframe - 0.2) < 1e-6
    assert all(
        mesh.animation_data.action == before_animation[mesh.name]
        for mesh in collection.objects
    )
    attach = addon.motion.attach_action
    calls = 0

    def fail_during_commit(*args):
        global calls
        calls += 1
        attach(*args)
        if calls == 2:
            raise RuntimeError("Injected action assignment failure")

    with patch.object(addon.motion, "attach_action", side_effect=fail_during_commit):
        try:
            addon.motion.apply_motion(
                bpy.context,
                collection,
                motion_path,
                trusted=True,
                replace_animation=True,
            )
        except RuntimeError as error:
            assert "Injected" in str(error)
        else:
            raise AssertionError("Action assignment failure was not propagated")
    assert set(bpy.data.actions) == actions
    assert all(
        mesh.animation_data.action == before_animation[mesh.name]
        for mesh in collection.objects
    )
    assert (scene.render.fps, scene.render.fps_base) == before_fps
    assert scene.frame_current == 3 and abs(scene.frame_subframe - 0.2) < 1e-6
    shared_source = list(collection.objects)[0]
    shared_target = list(duplicate.objects)[0]
    shared_action = shared_source.animation_data.action
    shared_slot = (
        shared_source.animation_data.action_slot
        if hasattr(shared_source.animation_data, "action_slot")
        else None
    )
    attach(shared_target, shared_action, shared_slot)
    shared_coordinates = [
        np.array([tuple(point.co) for point in curve.keyframe_points])
        for curve in curves(shared_target)
    ]
    scene.render.fps = 24
    scene.render.fps_base = 1
    loaded = addon.motion.apply_motion(
        bpy.context,
        collection,
        motion_path,
        trusted=True,
        replace_animation=True,
        start_frame=7,
        use_motion_fps=False,
    )
    assert scene.render.fps == 24 and scene.render.fps_base == 1
    for sample in range(loaded.samples):
        assert_pose(model, loaded, sample, 7, 24)
    assert all(
        mesh.animation_data.action != before_animation[mesh.name]
        for mesh in collection.objects
    )
    assert shared_target.animation_data.action == shared_action
    for curve, expected in zip(curves(shared_target), shared_coordinates):
        np.testing.assert_array_equal(
            np.array([tuple(point.co) for point in curve.keyframe_points]), expected
        )
    # Reopening must keep baked playback and restore bindings without source files.
    collection_name = collection.name
    project = Path(directory) / "motion.blend"
    assert bpy.ops.wm.save_as_mainfile(filepath=str(project)) == {"FINISHED"}
    fixture.unlink()
    multipart.unlink()
    bpy.ops.preferences.addon_disable(module=module_name)
    assert not hasattr(bpy.types.Scene, "blend_my_bot_motion")
    bpy.ops.preferences.addon_enable(module=module_name)
    assert bpy.ops.wm.open_mainfile(filepath=str(project)) == {"FINISHED"}
    collection = bpy.data.collections[collection_name]
    assert bpy.context.scene.blend_my_bot_motion.robot == collection
    model = addon.motion.restore_model(collection)
    assert_pose(model, loaded, loaded.samples - 1, 7, 24)
    assert bpy.ops.blend_my_bot.load_motion(
        filepath=str(motion_path), trust_file=True, replace_animation=True
    ) == {"FINISHED"}

    if len(arguments) == 3:
        real_motion_path, models_root = (
            Path(value).resolve() for value in arguments[1:]
        )
        urdf = models_root / "share/gene/robots/gene01_paxini_hand/model.urdf"
        source = urdf.read_bytes()
        real_collection = addon.import_robot(
            bpy.context, str(urdf), "Gene Motion", [models_root]
        )
        start = perf_counter()
        real_motion = addon.motion.apply_motion(
            bpy.context, real_collection, real_motion_path, trusted=True
        )
        assert real_motion.samples == 1228 and real_motion.fps == 50
        assert abs(real_motion.duration - 24.54) < 1e-6
        real_model = addon.motion.restore_model(real_collection)
        for sample in (0, 1, 614, 1227):
            assert_pose(real_model, real_motion, sample, 1, 50)
        assert bpy.context.scene.frame_end == 1228
        assert len(real_collection.objects) == 93
        assert not any(obj.type == "ARMATURE" for obj in real_collection.objects)
        assert all(
            len(curve.keyframe_points) == 1228
            for mesh in real_collection.objects
            for curve in curves(mesh)
        )
        assert urdf.read_bytes() == source
        body_data = np.load(real_motion_path, allow_pickle=True).item()
        indices = {
            name: index for index, name in enumerate(body_data["body_links_list"])
        }
        max_body_error = 0.0
        for sample in (0, 614, 1227):
            bpy.context.scene.frame_set(sample + 1)
            bpy.context.view_layer.update()
            for link in real_model.links.values():
                index = indices[link.name]
                body = (
                    Quaternion(body_data["body_links_quat_w"][sample, index])
                    .to_matrix()
                    .to_4x4()
                )
                body.translation = body_data["body_links_pos_w"][sample, index]
                offset = Matrix(link.link_H_geometry.asHomogeneousTransform().toNumPy())
                expected = body @ offset @ Matrix.Diagonal((*link.mesh.scale, 1))
                max_body_error = max(
                    max_body_error,
                    float(
                        np.max(
                            np.abs(
                                np.array(link.mesh.matrix_world) - np.array(expected)
                            )
                        )
                    ),
                )
        print(
            f"BMB_REAL_MOTION_OK samples=1228 meshes=93 recorded_body_difference={max_body_error:.3g} seconds={perf_counter() - start:.2f}",
            flush=True,
        )
    print("BLEND_MY_BOT_MOTION_OK", flush=True)
