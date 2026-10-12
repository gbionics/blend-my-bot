import logging
from pathlib import Path
from time import perf_counter
import xml.etree.ElementTree as ET

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy_extras.io_utils import ImportHelper

from .blend_my_bot import ModelImporter
from .blend_my_bot.robot_catalog import RobotDescription, iter_robot_descriptions
from .blend_my_bot.urdf_paths import resolved_urdf
from . import motion

logger = logging.getLogger(__name__)
SCAN_TIME_SLICE = 0.02
SCAN_TIMER_INTERVAL = 0.05
EMPTY_ITEMS = [("NONE", "Refresh to discover robots", "", 0)]
_catalog = ()
_package_items = EMPTY_ITEMS
_urdf_items = {}
_active_scan = None


def package_items(self, context):
    return _package_items


def urdf_items(self, context):
    return _urdf_items.get(self.package, EMPTY_ITEMS)


def update_package(self, context):
    self.urdf = urdf_items(self, context)[0][0]


class BMB_Catalog(bpy.types.PropertyGroup):
    package: EnumProperty(
        name="Package",
        items=package_items,
        update=update_package,
        options={"SKIP_SAVE"},
    )
    urdf: EnumProperty(name="URDF", items=urdf_items, options={"SKIP_SAVE"})
    scanning: BoolProperty(default=False, options={"SKIP_SAVE"})
    status: StringProperty(
        default="Refresh to find available robot descriptions", options={"SKIP_SAVE"}
    )


def package_search_paths(context):
    preferences = context.preferences.addons[__package__].preferences
    return [
        Path(bpy.path.abspath(entry.directory)).expanduser()
        for entry in preferences.search_paths
        if entry.directory
    ]


def set_catalog(context, entries):
    global _catalog, _package_items, _urdf_items
    settings = context.window_manager.blend_my_bot_catalog
    previous_package = settings.package
    previous_urdf = settings.urdf
    _catalog = tuple(sorted(entries, key=lambda entry: str(entry.urdf_path)))
    packages = sorted({entry.package_directory for entry in _catalog})
    _package_items = [
        (
            str(package),
            (
                package.name
                if sum(other.name == package.name for other in packages) == 1
                else f"{package.name} ({package.parent})"
            ),
            str(package),
            index,
        )
        for index, package in enumerate(packages)
    ] or EMPTY_ITEMS
    _urdf_items = {
        str(package): [
            (str(entry.urdf_path), entry.label, str(entry.urdf_path), index)
            for index, entry in enumerate(
                item for item in _catalog if item.package_directory == package
            )
        ]
        for package in packages
    }
    settings.package = (
        previous_package if previous_package in _urdf_items else _package_items[0][0]
    )
    available = urdf_items(settings, context)
    settings.urdf = (
        previous_urdf
        if any(item[0] == previous_urdf for item in available)
        else available[0][0]
    )
    settings.status = (
        f"Found {len(packages)} packages and {len(_catalog)} URDFs"
        if _catalog
        else "No URDFs found; add package search folders and refresh"
    )


def selected_description(context):
    settings = context.window_manager.blend_my_bot_catalog
    return next(
        (
            entry
            for entry in _catalog
            if str(entry.package_directory) == settings.package
            and str(entry.urdf_path) == settings.urdf
        ),
        None,
    )


class BMB_OT_RefreshCatalog(bpy.types.Operator):
    bl_idname = "blend_my_bot.refresh_catalog"
    bl_label = "Refresh Available Robots"
    bl_description = "Find URDF files in saved folders and robotics resource paths"

    @classmethod
    def poll(cls, context):
        return not context.window_manager.blend_my_bot_catalog.scanning

    def execute(self, context):
        try:
            entries = [
                entry
                for _, batch in iter_robot_descriptions(package_search_paths(context))
                for entry in batch
            ]
        except OSError as error:
            return self.scan_failed(context, error)
        set_catalog(context, entries)
        self.report({"INFO"}, context.window_manager.blend_my_bot_catalog.status)
        return {"FINISHED"}

    def invoke(self, context, event):
        global _active_scan
        if bpy.app.background:
            return self.execute(context)
        self._entries = []
        self._iterator = iter_robot_descriptions(package_search_paths(context))
        self._cancelled = False
        self._timer = context.window_manager.event_timer_add(
            SCAN_TIMER_INTERVAL, window=context.window
        )
        _active_scan = self
        settings = context.window_manager.blend_my_bot_catalog
        settings.scanning = True
        settings.status = "Scanning packages; press Esc to cancel"
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def finish_scan(self, context):
        global _active_scan
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        context.window_manager.blend_my_bot_catalog.scanning = False
        self._iterator.close()
        _active_scan = None

    def cancel(self, context):
        self._cancelled = True
        self.finish_scan(context)
        context.window_manager.blend_my_bot_catalog.status = (
            "Scan cancelled; previous results kept"
        )

    def scan_failed(self, context, error):
        logger.error("Robot catalog scan failed: %s", error)
        context.window_manager.blend_my_bot_catalog.status = str(error)
        self.report({"ERROR"}, str(error))
        return {"CANCELLED"}

    def modal(self, context, event):
        if self._cancelled:
            return {"CANCELLED"}
        if event.type == "ESC":
            self.cancel(context)
            self.report({"INFO"}, "Robot discovery cancelled")
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        deadline = perf_counter() + SCAN_TIME_SLICE
        try:
            while perf_counter() < deadline:
                _, entries = next(self._iterator)
                self._entries.extend(entries)
        except StopIteration:
            self.finish_scan(context)
            set_catalog(context, self._entries)
            self.report({"INFO"}, context.window_manager.blend_my_bot_catalog.status)
            if context.area:
                context.area.tag_redraw()
            return {"FINISHED"}
        except OSError as error:
            self.finish_scan(context)
            return self.scan_failed(context, error)
        context.window_manager.blend_my_bot_catalog.status = (
            f"Found {len(self._entries)} URDFs; scanning (Esc to cancel)"
        )
        if context.area:
            context.area.tag_redraw()
        return {"RUNNING_MODAL"}


class BMB_OT_ImportAvailableRobot(bpy.types.Operator):
    bl_idname = "blend_my_bot.import_available_robot"
    bl_label = "Import Selected Robot"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (
            not context.window_manager.blend_my_bot_catalog.scanning
            and selected_description(context) is not None
        )

    def execute(self, context):
        entry = selected_description(context)
        if entry is None:
            self.report({"ERROR"}, "Refresh available robots and select a URDF")
            return {"CANCELLED"}
        return bpy.ops.blend_my_bot.import_robot(
            filepath=str(entry.urdf_path),
            robot_name=f"{entry.package_directory.name}_{entry.urdf_path.stem}",
            package_directory=str(entry.package_directory),
        )


class BMB_SearchPath(bpy.types.PropertyGroup):
    directory: StringProperty(name="Package folder", subtype="DIR_PATH")


class BMB_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    search_paths: CollectionProperty(type=BMB_SearchPath)

    def draw(self, context):
        self.layout.label(text="Package folders or folders containing robot packages")
        for index, entry in enumerate(self.search_paths):
            row = self.layout.row(align=True)
            row.prop(entry, "directory", text="")
            operator = row.operator(
                "blend_my_bot.remove_search_path", text="", icon="X"
            )
            operator.index = index
        self.layout.operator("blend_my_bot.add_search_path", icon="ADD")


class BMB_OT_AddSearchPath(bpy.types.Operator):
    bl_idname = "blend_my_bot.add_search_path"
    bl_label = "Add Package Search Folder"

    def execute(self, context):
        context.preferences.addons[__package__].preferences.search_paths.add()
        context.preferences.is_dirty = True
        return {"FINISHED"}


class BMB_OT_RemoveSearchPath(bpy.types.Operator):
    bl_idname = "blend_my_bot.remove_search_path"
    bl_label = "Remove Package Search Folder"

    index: IntProperty()

    def execute(self, context):
        context.preferences.addons[__package__].preferences.search_paths.remove(
            self.index
        )
        context.preferences.is_dirty = True
        return {"FINISHED"}


def import_robot(
    context,
    filepath: str,
    robot_name: str,
    additional_search_paths=(),
) -> bpy.types.Collection:
    search_paths = [*package_search_paths(context), *additional_search_paths]
    source = Path(bpy.path.abspath(filepath)).expanduser().resolve()
    with resolved_urdf(source, search_paths) as resolved:
        previous_objects = set(bpy.data.objects)
        previous_meshes = set(bpy.data.meshes)
        previous_materials = set(bpy.data.materials)
        previous_collections = set(bpy.data.collections)
        selected = list(context.selected_objects)
        active = context.view_layer.objects.active
        mode = active.mode if active else "OBJECT"
        completed = False
        try:
            name = robot_name.strip() or source.stem
            if mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            collection = bpy.data.collections.new(name)
            context.scene.collection.children.link(collection)
            model = ModelImporter.build_model(
                collection.name, str(resolved), collection=collection
            )
            if not model.links:
                raise ValueError("The robot has no supported visual meshes")
            collection["blend_my_bot_urdf"] = str(source)
            tree = ET.parse(resolved)
            for link in tree.getroot().findall("link"):
                for element in list(link):
                    if element.tag in {"visual", "collision"}:
                        link.remove(element)
            collection["blend_my_bot_model_xml"] = ET.tostring(
                tree.getroot(), encoding="unicode"
            )
            collection["blend_my_bot_visual_count"] = len(model.links)
            collection["blend_my_bot_joint_count"] = (
                model.kindyn.getNrOfDegreesOfFreedom()
            )
            context.scene.blend_my_bot_motion.robot = collection
            completed = True
        finally:
            if not completed:
                if context.object and context.object.mode != "OBJECT":
                    bpy.ops.object.mode_set(mode="OBJECT")
                for obj in set(bpy.data.objects) - previous_objects:
                    bpy.data.objects.remove(obj, do_unlink=True)
                for data, previous in (
                    (bpy.data.meshes, previous_meshes),
                    (bpy.data.materials, previous_materials),
                ):
                    for block in set(data) - previous:
                        if block.users == 0:
                            data.remove(block)
                for collection in set(bpy.data.collections) - previous_collections:
                    bpy.data.collections.remove(collection)
                bpy.ops.object.select_all(action="DESELECT")
                for obj in selected:
                    obj.select_set(True)
                context.view_layer.objects.active = active
                if mode != "OBJECT":
                    bpy.ops.object.mode_set(mode=mode)
    return collection


class BMB_OT_ImportRobot(bpy.types.Operator, ImportHelper):
    bl_idname = "blend_my_bot.import_robot"
    bl_label = "Import Robot (URDF)"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".urdf"

    filter_glob: StringProperty(default="*.urdf", options={"HIDDEN"})
    robot_name: StringProperty(
        name="Robot name", description="Defaults to the filename"
    )
    package_directory: StringProperty(options={"HIDDEN"})

    def draw(self, context):
        self.layout.prop(self, "robot_name")

    def execute(self, context):
        try:
            collection = import_robot(
                context,
                self.filepath,
                self.robot_name,
                [Path(self.package_directory)] if self.package_directory else (),
            )
        except (OSError, ValueError, RuntimeError, ET.ParseError) as error:
            logger.exception("Robot import failed: %s", self.filepath)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Imported robot into collection '{collection.name}'")
        return {"FINISHED"}


class BMB_PT_RobotPanel(bpy.types.Panel):
    bl_label = "Blend My Bot"
    bl_idname = "BMB_PT_robot"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Blend My Bot"

    def draw(self, context):
        settings = context.window_manager.blend_my_bot_catalog
        box = self.layout.box()
        box.label(text="Available Robots")
        box.operator("blend_my_bot.refresh_catalog", icon="FILE_REFRESH")
        box.label(text=settings.status)
        selection = box.column()
        selection.enabled = bool(_catalog) and not settings.scanning
        selection.prop(settings, "package")
        selection.prop(settings, "urdf")
        selection.operator("blend_my_bot.import_available_robot", icon="IMPORT")
        self.layout.operator(
            "blend_my_bot.import_robot", text="Browse URDF File", icon="FILE_FOLDER"
        )
        operator = self.layout.operator(
            "preferences.addon_show", text="Package Search Folders"
        )
        operator.module = __package__
        self.layout.label(text="OBJ/STL visuals; mesh-only import")
        motion.draw_motion(self.layout, context)


def import_menu(self, context):
    self.layout.operator(BMB_OT_ImportRobot.bl_idname, text="Robot (.urdf)")


classes = (
    BMB_Catalog,
    BMB_SearchPath,
    BMB_Preferences,
    BMB_OT_AddSearchPath,
    BMB_OT_RemoveSearchPath,
    BMB_OT_RefreshCatalog,
    BMB_OT_ImportAvailableRobot,
    BMB_OT_ImportRobot,
    BMB_PT_RobotPanel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.blend_my_bot_catalog = PointerProperty(type=BMB_Catalog)
    bpy.types.TOPBAR_MT_file_import.append(import_menu)
    motion.register()


def unregister():
    global _catalog, _package_items, _urdf_items
    if _active_scan is not None:
        _active_scan.cancel(bpy.context)
    motion.unregister()
    bpy.types.TOPBAR_MT_file_import.remove(import_menu)
    del bpy.types.WindowManager.blend_my_bot_catalog
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    _catalog = ()
    _package_items = EMPTY_ITEMS
    _urdf_items = {}
