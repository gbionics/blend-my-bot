import logging
from pathlib import Path
import shutil
import subprocess
import sys
from time import monotonic
import xml.etree.ElementTree as ET

import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty

from .blend_my_bot.online_catalog import (
    DownloadJob,
    cached_robot,
    catalog_robots,
)

logger = logging.getLogger(__name__)
DOWNLOAD_TIMER_INTERVAL = 0.1
DOWNLOAD_TIMEOUT = 600
PROGRESS_TAIL_BYTES = 512
STATUS_TEXT_LENGTH = 160
_robots = catalog_robots()
_items = [
    (
        robot.identifier,
        f"{robot.name} ({robot.identifier})",
        f"{robot.identifier}; {robot.maker}; {robot.license}; "
        f"{'Blender-tested' if robot.blender_tested else 'Not yet Blender-tested'}",
    )
    for robot in _robots
]
_active_download = None


def cache_directory() -> Path:
    return Path(bpy.utils.extension_path_user(__package__, path="robots", create=True))


class BMB_OnlineSettings(bpy.types.PropertyGroup):
    robot: EnumProperty(name="Robot", items=_items, default="bolt_description")
    downloading: BoolProperty(default=False, options={"SKIP_SAVE"})
    status: StringProperty(default="", options={"SKIP_SAVE"})


class BMB_OT_SearchOnlineRobots(bpy.types.Operator):
    bl_idname = "blend_my_bot.search_online_robots"
    bl_label = "Search Robots"
    bl_description = "Search all URDF descriptions by robot name and identifier"
    bl_property = "robot"

    robot: EnumProperty(name="Robot", items=_items)

    @classmethod
    def poll(cls, context):
        return not context.window_manager.blend_my_bot_online.downloading

    def invoke(self, context, event):
        self.robot = context.window_manager.blend_my_bot_online.robot
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        context.window_manager.blend_my_bot_online.robot = self.robot
        return {"FINISHED"}


def import_cached(context, identifier, robot):
    from . import import_robot

    name = next(entry.name for entry in _robots if entry.identifier == identifier)
    collection = import_robot(context, str(robot.urdf_path), name, robot.search_paths)
    collection["blend_my_bot_description"] = identifier
    return collection


class BMB_OT_ImportOnlineRobot(bpy.types.Operator):
    bl_idname = "blend_my_bot.import_online_robot"
    bl_label = "Download & Import Robot"
    bl_description = (
        "Download the selected robot if needed, then import its URDF meshes"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return not context.window_manager.blend_my_bot_online.downloading

    def prepare(self, context):
        self._job = None
        self._timer = None
        self._cancelled = False
        self._identifier = context.window_manager.blend_my_bot_online.robot
        robot = cached_robot(cache_directory(), self._identifier)
        if robot is not None:
            return robot
        if not bpy.app.online_access:
            raise ValueError(
                "Blender online access is disabled. Enable it in Preferences > "
                "System > Network to download a robot, or use a cached/local model."
            )
        if shutil.which("git") is None:
            raise RuntimeError(
                "Online robot downloads require Git. Install Git and restart "
                "Blender so it is available on PATH. Local and cached imports "
                "do not require Git."
            )
        self._job = DownloadJob(
            cache_directory(),
            self._identifier,
            sys.executable,
            Path(__file__).with_name("download_robot.py"),
        )
        self._job.start()
        self._deadline = monotonic() + DOWNLOAD_TIMEOUT
        context.window_manager.blend_my_bot_online.status = (
            "Downloading robot; press Esc or Cancel to stop"
        )
        return None

    def failed(self, context, error):
        logger.exception("Online robot import failed")
        context.window_manager.blend_my_bot_online.status = str(error)
        self.report({"ERROR"}, str(error))
        return {"CANCELLED"}

    def import_result(self, context, robot):
        collection = import_cached(context, self._identifier, robot)
        status = f"Imported robot into collection '{collection.name}'"
        context.window_manager.blend_my_bot_online.status = status
        self.report({"INFO"}, status)
        return {"FINISHED"}

    def finish_download(self, context):
        global _active_download
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        if self._job is not None:
            self._job.close()
            self._job = None
        context.window_manager.blend_my_bot_online.downloading = False
        _active_download = None

    def execute(self, context):
        try:
            robot = self.prepare(context)
            if robot is None:
                self._job.process.wait(timeout=DOWNLOAD_TIMEOUT)
                robot = self._job.finish()
            return self.import_result(context, robot)
        except subprocess.TimeoutExpired:
            return self.failed(
                context,
                RuntimeError(f"Robot download timed out after {DOWNLOAD_TIMEOUT}s"),
            )
        except (OSError, ValueError, RuntimeError, ET.ParseError) as error:
            return self.failed(context, error)
        finally:
            self.finish_download(context)

    def invoke(self, context, event):
        global _active_download
        if bpy.app.background:
            return self.execute(context)
        try:
            robot = self.prepare(context)
            if robot is not None:
                return self.import_result(context, robot)
            self._timer = context.window_manager.event_timer_add(
                DOWNLOAD_TIMER_INTERVAL, window=context.window
            )
            context.window_manager.modal_handler_add(self)
            context.window_manager.blend_my_bot_online.downloading = True
            _active_download = self
            return {"RUNNING_MODAL"}
        except (OSError, ValueError, RuntimeError, ET.ParseError) as error:
            self.finish_download(context)
            return self.failed(context, error)

    def cancel(self, context):
        self._cancelled = True
        self.finish_download(context)
        context.window_manager.blend_my_bot_online.status = (
            "Download cancelled; existing cached robots kept"
        )

    def modal(self, context, event):
        if self._cancelled:
            return {"CANCELLED"}
        if event.type == "ESC":
            self.cancel(context)
            self.report({"INFO"}, "Robot download cancelled")
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        finished = False
        try:
            if self._job.process.poll() is None:
                if not bpy.app.online_access:
                    raise RuntimeError(
                        "Blender online access was disabled; robot download stopped"
                    )
                if monotonic() >= self._deadline:
                    raise RuntimeError(
                        f"Robot download timed out after {DOWNLOAD_TIMEOUT}s"
                    )
                lines = (
                    self._job.output_tail(PROGRESS_TAIL_BYTES)
                    .replace("\r", "\n")
                    .splitlines()
                )
                if lines:
                    context.window_manager.blend_my_bot_online.status = lines[-1][
                        -STATUS_TEXT_LENGTH:
                    ]
                if context.area:
                    context.area.tag_redraw()
                return {"RUNNING_MODAL"}
            finished = True
            robot = self._job.finish()
            return self.import_result(context, robot)
        except (OSError, ValueError, RuntimeError, ET.ParseError) as error:
            finished = True
            return self.failed(context, error)
        finally:
            if finished:
                self.finish_download(context)
                if context.area:
                    context.area.tag_redraw()


class BMB_OT_CancelRobotDownload(bpy.types.Operator):
    bl_idname = "blend_my_bot.cancel_robot_download"
    bl_label = "Cancel Download"

    @classmethod
    def poll(cls, context):
        return _active_download is not None

    def execute(self, context):
        _active_download.cancel(context)
        return {"FINISHED"}


def draw_online(layout, context):
    settings = context.window_manager.blend_my_bot_online
    box = layout.box()
    box.label(text=f"Online Robot Catalog ({len(_robots)} URDFs)")
    selection = box.column()
    selection.enabled = not settings.downloading
    selection.operator("blend_my_bot.search_online_robots", icon="VIEWZOOM")
    selection.prop(settings, "robot")
    entry = next(robot for robot in _robots if robot.identifier == settings.robot)
    box.label(text=f"{entry.maker} | {entry.license}")
    box.label(
        text="Blender-tested" if entry.blender_tested else "Not yet Blender-tested",
        icon="CHECKMARK" if entry.blender_tested else "INFO",
    )
    if not entry.blender_tested:
        box.label(text="Requires static URDF and OBJ/STL/DAE visuals")
    try:
        cached = cached_robot(cache_directory(), entry.identifier) is not None
    except ValueError as error:
        box.label(text="Invalid cache; remove this robot's cache folder", icon="ERROR")
        box.label(text=str(error))
        cached = False
    selection.operator(
        "blend_my_bot.import_online_robot",
        text="Import Cached Robot" if cached else "Download & Import Robot",
        icon="IMPORT",
    )
    if settings.downloading:
        box.operator("blend_my_bot.cancel_robot_download", icon="CANCEL")
    elif cached:
        box.label(text="Cached locally; no network needed", icon="CHECKMARK")
    else:
        box.label(text="First import downloads the model")
        if shutil.which("git") is None:
            box.label(text="Downloads require Git on PATH", icon="ERROR")
        if not bpy.app.online_access:
            box.label(text="Enable Blender online access to download", icon="ERROR")
    if settings.status:
        box.label(text=settings.status)


classes = (
    BMB_OnlineSettings,
    BMB_OT_SearchOnlineRobots,
    BMB_OT_ImportOnlineRobot,
    BMB_OT_CancelRobotDownload,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.blend_my_bot_online = PointerProperty(
        type=BMB_OnlineSettings
    )


def unregister():
    if _active_download is not None:
        _active_download.cancel(bpy.context)
    del bpy.types.WindowManager.blend_my_bot_online
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
