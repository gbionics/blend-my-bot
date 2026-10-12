"""Installed catalog tests; --download[-dae/-colors] also test real robots."""

import importlib
import json
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET
from tempfile import TemporaryDirectory
from time import monotonic
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

import bpy
import numpy as np


def operator_instance(online):
    operator = SimpleNamespace(report=Mock())
    for name in (
        "prepare",
        "failed",
        "import_result",
        "finish_download",
        "execute",
        "invoke",
        "cancel",
        "modal",
    ):
        setattr(
            operator,
            name,
            MethodType(getattr(online.BMB_OT_ImportOnlineRobot, name), operator),
        )
    return operator


arguments = sys.argv[sys.argv.index("--") + 1 :]
archive = Path(arguments[0]).resolve()
with TemporaryDirectory(prefix="blend-my-bot-online-") as directory:
    root = Path(directory)
    bpy.ops.preferences.extension_repo_add(
        name="Blend My Bot Online Test",
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
    from robot_descriptions import DESCRIPTIONS, __version__

    online = addon.online
    assert Path(sys.executable).is_file()
    assert online.cache_directory().is_dir()
    assert bpy.context.window_manager.blend_my_bot_catalog.source == "LOCAL"
    bpy.context.window_manager.blend_my_bot_catalog.source = "ONLINE"
    settings = bpy.context.window_manager.blend_my_bot_online
    assert {item[0] for item in online._items} == {
        name for name, description in DESCRIPTIONS.items() if description.has_urdf
    }
    assert len(online._items) > 2
    assert len({item[0] for item in online._items}) == len(online._items)
    assert settings.robot == "bolt_description"
    assert bpy.ops.blend_my_bot.search_online_robots(robot="panda_description") == {
        "FINISHED"
    }
    assert settings.robot == "panda_description"
    assert not next(
        robot for robot in online._robots if robot.identifier == settings.robot
    ).blender_tested
    assert "Not yet Blender-tested" in next(
        item[2] for item in online._items if item[0] == settings.robot
    )
    assert all(
        robot.identifier in item[1]
        for robot, item in zip(online._robots, online._items)
    )
    popup = SimpleNamespace(
        window_manager=SimpleNamespace(
            blend_my_bot_online=settings,
            invoke_search_popup=Mock(),
        )
    )
    search = SimpleNamespace(robot="")
    assert online.BMB_OT_SearchOnlineRobots.invoke(search, popup, None) == {
        "RUNNING_MODAL"
    }
    assert search.robot == settings.robot
    popup.window_manager.invoke_search_popup.assert_called_once_with(search)
    settings.robot = "cassie_description"
    cache = root / "cache"
    fixture_cache = cache / settings.robot
    fixture_cache.mkdir(parents=True)
    fixture = Path(__file__).parent / "fixtures"
    shutil.copy2(fixture / "robot.urdf", fixture_cache)
    shutil.copy2(fixture / "cube.obj", fixture_cache)
    (fixture_cache / "robot.json").write_text(
        json.dumps(
            {
                "description": settings.robot,
                "version": __version__,
                "urdf": "robot.urdf",
                "search_paths": ["."],
            }
        )
    )
    offline_bpy = SimpleNamespace(app=SimpleNamespace(online_access=False))
    with patch.object(online, "cache_directory", return_value=cache):
        with (
            patch.object(online, "bpy", offline_bpy),
            patch.object(online.shutil, "which", return_value=None),
            patch.object(online, "DownloadJob") as downloader,
        ):
            assert bpy.ops.blend_my_bot.import_online_robot() == {"FINISHED"}
            downloader.assert_not_called()
        collection = bpy.data.collections["Cassie"]
        assert len(collection.objects) == 2
        assert collection["blend_my_bot_description"] == settings.robot
        assert bpy.context.scene.blend_my_bot_motion.robot == collection
        assert (
            addon.motion.restore_model(collection).kindyn.getNrOfDegreesOfFreedom() == 1
        )
        assert bpy.ops.blend_my_bot.import_online_robot() == {"FINISHED"}
        assert len(bpy.data.collections["Cassie.001"].objects) == 2
        untested = cache / "panda_description"
        shutil.copytree(fixture_cache, untested)
        manifest = json.loads((untested / "robot.json").read_text())
        manifest["description"] = "panda_description"
        (untested / "robot.json").write_text(json.dumps(manifest))
        settings.robot = "panda_description"
        with (
            patch.object(online, "bpy", offline_bpy),
            patch.object(online, "DownloadJob") as downloader,
        ):
            assert bpy.ops.blend_my_bot.import_online_robot() == {"FINISHED"}
            downloader.assert_not_called()
        assert (
            bpy.data.collections["Panda"]["blend_my_bot_description"]
            == "panda_description"
        )
        settings.robot = "bolt_description"
        before = set(bpy.data.collections)
        with patch.object(online, "bpy", offline_bpy):
            operator = operator_instance(online)
            assert operator.execute(bpy.context) == {"CANCELLED"}
            assert "online access is disabled" in settings.status
        assert set(bpy.data.collections) == before
        available_bpy = SimpleNamespace(
            app=SimpleNamespace(online_access=True, background=False)
        )
        with (
            patch.object(online, "bpy", available_bpy),
            patch.object(online.shutil, "which", return_value=None),
        ):
            operator = operator_instance(online)
            assert operator.execute(bpy.context) == {"CANCELLED"}
            assert "require Git" in settings.status
        manager = SimpleNamespace(
            blend_my_bot_online=settings,
            event_timer_add=Mock(return_value=object()),
            event_timer_remove=Mock(),
            modal_handler_add=Mock(),
        )
        context = SimpleNamespace(window_manager=manager, window=None, area=Mock())
        job = Mock()
        job.process.poll.return_value = None
        job.output_tail.return_value = (
            "Receiving objects: 50%\rReceiving objects: 75%\n"
        )
        with (
            patch.object(online, "bpy", available_bpy),
            patch.object(online.shutil, "which", return_value="/usr/bin/git"),
            patch.object(online, "DownloadJob", return_value=job),
        ):
            operator = operator_instance(online)
            assert operator.invoke(context, None) == {"RUNNING_MODAL"}
            assert settings.downloading
            assert operator.modal(context, SimpleNamespace(type="MOUSEMOVE")) == {
                "PASS_THROUGH"
            }
            assert operator.modal(context, SimpleNamespace(type="TIMER")) == {
                "RUNNING_MODAL"
            }
            assert "75%" in settings.status
            assert online.BMB_OT_CancelRobotDownload.execute(None, context) == {
                "FINISHED"
            }
            assert operator.modal(context, SimpleNamespace(type="TIMER")) == {
                "CANCELLED"
            }
            assert not settings.downloading
            assert online._active_download is None
            job.close.assert_called_once()
            assert fixture_cache.is_dir()
            manager.event_timer_remove.assert_called_once()
            job.reset_mock()
            manager.event_timer_remove.reset_mock()
            operator = operator_instance(online)
            assert operator.invoke(context, None) == {"RUNNING_MODAL"}
            job.process.poll.return_value = 1
            job.finish.side_effect = RuntimeError("network unavailable")
            assert operator.modal(context, SimpleNamespace(type="TIMER")) == {
                "CANCELLED"
            }
            assert "network unavailable" in settings.status
            assert not settings.downloading
            job.close.assert_called_once()
            job.reset_mock()
            job.process.poll.return_value = None
            job.finish.side_effect = None
            operator = operator_instance(online)
            assert operator.invoke(context, None) == {"RUNNING_MODAL"}
            operator._deadline = monotonic() - 1
            assert operator.modal(context, SimpleNamespace(type="TIMER")) == {
                "CANCELLED"
            }
            assert "timed out" in settings.status
            assert not settings.downloading
            job.close.assert_called_once()
            job.reset_mock()
            operator = operator_instance(online)
            assert operator.invoke(context, None) == {"RUNNING_MODAL"}
            available_bpy.app.online_access = False
            assert operator.modal(context, SimpleNamespace(type="TIMER")) == {
                "CANCELLED"
            }
            assert "online access was disabled" in settings.status
            assert not settings.downloading
            job.close.assert_called_once()
            available_bpy.app.online_access = True
            job.reset_mock()
            operator = operator_instance(online)
            assert operator.invoke(context, None) == {"RUNNING_MODAL"}
            job.process.poll.side_effect = [None, 0]
            robot = addon.online.cached_robot(cache, "cassie_description")
            job.finish.return_value = robot
            with patch.object(online, "import_cached", return_value=collection):
                assert operator.modal(context, SimpleNamespace(type="TIMER")) == {
                    "RUNNING_MODAL"
                }
                job.close.assert_not_called()
                assert operator.modal(context, SimpleNamespace(type="TIMER")) == {
                    "FINISHED"
                }
            job.process.poll.side_effect = None
            assert not settings.downloading
            job.close.assert_called_once()
        settings.robot = "cassie_description"
        (fixture_cache / "robot.urdf").unlink()
        operator = operator_instance(online)
        assert operator.execute(bpy.context) == {"CANCELLED"}
        assert "Cached URDF is missing" in settings.status
        assert set(bpy.data.collections) == before

    if any(
        flag in arguments
        for flag in ("--download", "--download-dae", "--download-colors")
    ):
        assert bpy.app.online_access, "Use Blender --online-mode for real downloads"
        dae_robots = (
            {"anymal_b_description"} if "--download-dae" in arguments else set()
        )
        color_robots = {"g1_description"} if "--download-colors" in arguments else set()
        real_cache = root / "real-cache"
        with patch.object(online, "cache_directory", return_value=real_cache):
            for entry in online.catalog_robots():
                if entry.identifier not in dae_robots | color_robots and not (
                    "--download" in arguments and entry.blender_tested
                ):
                    continue
                settings.robot = entry.identifier
                before = set(bpy.data.collections)
                assert bpy.ops.blend_my_bot.import_online_robot() == {"FINISHED"}
                created = set(bpy.data.collections) - before
                assert len(created) == 1
                collection = created.pop()
                assert collection["blend_my_bot_description"] == entry.identifier
                assert all(
                    mesh.type == "MESH"
                    and mesh.parent is None
                    and (mesh.data.polygons or mesh.data.edges)
                    for mesh in collection.objects
                )
                model = addon.motion.restore_model(collection)
                if entry.identifier == "g1_description":
                    source = ET.parse(
                        online.cached_robot(real_cache, entry.identifier).urdf_path
                    ).getroot()
                    named = {
                        material.get("name"): material
                        for material in source.findall("material")
                    }
                    checked = []
                    for link in source.findall("link"):
                        for index, visual in enumerate(link.findall("visual")):
                            reference = visual.find("material")
                            material = (
                                reference
                                if reference.find("color") is not None
                                else named[reference.get("name")]
                            )
                            rgba = [
                                float(value)
                                for value in material.find("color").get("rgba").split()
                            ]
                            key = link.get("name") + (f"_{index}" if index else "")
                            mesh = model.links[key].mesh
                            assert len(mesh.data.materials) == 1
                            shader = mesh.data.materials[0].node_tree.nodes.get(
                                "Principled BSDF"
                            )
                            np.testing.assert_allclose(
                                shader.inputs["Base Color"].default_value,
                                rgba,
                                atol=1e-6,
                            )
                            assert (
                                abs(shader.inputs["Alpha"].default_value - rgba[3])
                                < 1e-6
                            )
                            checked.append(tuple(rgba))
                    assert len(checked) == 36
                    assert len(set(checked)) == 2
                    print(
                        f"BMB_URDF_COLORS_OK {entry.identifier} visuals={len(checked)} colors={len(set(checked))}",
                        flush=True,
                    )
                kinematics = model.kindyn.model()
                joints = [
                    kinematics.getJointName(index)
                    for index in range(kinematics.getNrOfJoints())
                    if kinematics.getJoint(index).getNrOfDOFs() == 1
                ]
                assert len(joints) == collection["blend_my_bot_joint_count"]
                if entry.identifier in dae_robots:
                    assert any(
                        node.type == "TEX_IMAGE" and node.image.packed_file
                        for mesh in collection.objects
                        for material in mesh.data.materials
                        for node in material.node_tree.nodes
                    ), "Real ANYmal DAE textures were not packed"
                data = {
                    "joints_list": joints,
                    "fps": 50,
                    "joint_positions": np.zeros((2, len(joints))),
                    "root_position": np.array([[0, 0, 0], [0.1, 0.2, 0.3]]),
                    "root_quaternion": np.array([[1, 0, 0, 0]] * 2),
                }
                data["joint_positions"][1] = np.linspace(0.1, 0.3, len(joints))
                motion = root / "motion.npy"
                np.save(motion, data)
                addon.motion.apply_motion(bpy.context, collection, motion, trusted=True)
                bpy.context.scene.frame_set(2)
                bpy.context.view_layer.update()
                for key, transform in model.visual_transforms(
                    np.array(
                        [[1, 0, 0, 0.1], [0, 1, 0, 0.2], [0, 0, 1, 0.3], [0, 0, 0, 1]]
                    ),
                    data["joint_positions"][1],
                ):
                    matrix = transform.asHomogeneousTransform().toNumPy()
                    matrix[:3, :3] *= np.array(model.links[key].mesh.scale)
                    np.testing.assert_allclose(
                        model.links[key].mesh.matrix_world,
                        matrix,
                        atol=1e-5,
                    )
                with (
                    patch.object(online, "bpy", offline_bpy),
                    patch.object(online.shutil, "which", return_value=None),
                    patch.object(online, "DownloadJob") as downloader,
                ):
                    assert bpy.ops.blend_my_bot.import_online_robot() == {"FINISHED"}
                    downloader.assert_not_called()
                print(
                    f"BMB_ONLINE_ROBOT_OK {entry.identifier} "
                    f"meshes={len(collection.objects)} joints={len(joints)}",
                    flush=True,
                )

    settings = bpy.context.window_manager.blend_my_bot_online
    settings.downloading = True
    pending = operator_instance(online)
    pending._cancelled = False
    pending._timer = None
    pending._job = Mock()
    online._active_download = pending
    bpy.ops.preferences.addon_disable(module=module_name)
    pending._job = None
    assert pending._cancelled
    assert online._active_download is None
    assert not hasattr(bpy.types.WindowManager, "blend_my_bot_online")
    bpy.ops.preferences.addon_enable(module=module_name)
    assert not bpy.context.window_manager.blend_my_bot_online.downloading
    bpy.ops.preferences.addon_disable(module=module_name)
    print(f"BLEND_MY_BOT_ONLINE_OK catalog={len(online._items)}", flush=True)
