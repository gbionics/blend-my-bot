import logging
from math import ceil
import pickle

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy_extras.io_utils import ImportHelper
import idyntree.bindings as idyntree
import numpy as np

from .blend_my_bot import BlenderModel, Link
from .blend_my_bot.motion_data import load_motion

logger = logging.getLogger(__name__)
MAX_SCENE_FPS = 32767


def robot_collection(self, collection):
    return "blend_my_bot_model_xml" in collection


class BMB_MotionSettings(bpy.types.PropertyGroup):
    robot: PointerProperty(
        name="Robot", type=bpy.types.Collection, poll=robot_collection
    )


def restore_model(collection) -> BlenderModel:
    if collection is None or "blend_my_bot_model_xml" not in collection:
        raise ValueError(
            "Select a mesh-only robot collection imported with this version"
        )
    loader = idyntree.ModelLoader()
    if not loader.loadModelFromString(collection["blend_my_bot_model_xml"]):
        raise ValueError("Cannot restore robot kinematics; reimport the URDF")
    model = loader.model().copy()
    kindyn = idyntree.KinDynComputations()
    if not kindyn.loadRobotModel(model):
        raise ValueError("Cannot initialize saved robot kinematics")
    if kindyn.getNrOfDegreesOfFreedom() != collection["blend_my_bot_joint_count"]:
        raise ValueError("Saved robot joint count changed; reimport the URDF")
    links = {}
    for mesh in collection.objects:
        if mesh.type != "MESH" or "blend_my_bot_link" not in mesh:
            raise ValueError("Robot bindings changed; reimport the mesh-only robot")
        if (
            mesh.parent is not None
            or mesh.constraints
            or mesh.rotation_mode != "QUATERNION"
        ):
            raise ValueError(
                "Motion requires unparented, unconstrained quaternion-mode meshes"
            )
        name = mesh["blend_my_bot_link"]
        if kindyn.model().getFrameIndex(name) < 0:
            raise ValueError(f"Robot link '{name}' is missing from saved kinematics")
        key = mesh["blend_my_bot_visual_key"]
        if key in links:
            raise ValueError("Robot contains duplicate visual bindings; reimport it")
        offset = np.array(mesh["blend_my_bot_link_H_geometry"]).reshape(4, 4)
        if not np.all(np.isfinite(offset)):
            raise ValueError(f"Invalid visual offset for '{mesh.name}'")
        transform = idyntree.Transform()
        transform.fromHomogeneousTransform(offset)
        links[key] = Link(name, mesh, transform)
    if not links or len(links) != collection["blend_my_bot_visual_count"]:
        raise ValueError(
            "Robot meshes were added or removed; reimport it before loading motion"
        )
    return BlenderModel(collection.name, links, kindyn, model)


def map_joint_positions(model, motion):
    kinematics = model.kindyn.model()
    indices = []
    for name in motion.joints:
        index = kinematics.getJointIndex(name)
        if index < 0:
            raise ValueError(
                f"Motion joint '{name}' is not in this robot; select the matching URDF"
            )
        joint = kinematics.getJoint(index)
        if joint.getNrOfDOFs() != 1:
            raise ValueError(f"Motion joint '{name}' must be a one-DOF movable joint")
        indices.append(joint.getDOFsOffset())
    positions = np.zeros((motion.samples, model.kindyn.getNrOfDegreesOfFreedom()))
    positions[:, indices] = motion.joint_positions
    return positions


def sample_visuals(model, motion, positions, window_manager):
    values = {key: np.empty((motion.samples, 7)) for key in model.links}
    bases = motion.base_transforms()
    window_manager.progress_begin(0, motion.samples)
    try:
        for sample, base in enumerate(bases):
            for key, transform in model.visual_transforms(base, positions[sample]):
                values[key][sample, :3] = transform.getPosition().toNumPy().ravel()
                quaternion = transform.getRotation().asQuaternion().toNumPy().ravel()
                if sample and values[key][sample - 1, 3:] @ quaternion < 0:
                    quaternion = -quaternion
                values[key][sample, 3:] = quaternion
            window_manager.progress_update(sample + 1)
    finally:
        window_manager.progress_end()
    for channels in values.values():
        if not np.all(np.isfinite(channels)) or np.any(
            np.abs(channels) > np.finfo(np.float32).max
        ):
            raise ValueError(
                "Motion transforms are outside Blender's finite keyframe range"
            )
    return values


def build_action(mesh, frames, values):
    action = bpy.data.actions.new(f"{mesh.name}_motion")
    completed = False
    try:
        slot = None
        if hasattr(action, "slots"):
            slot = action.slots.new("OBJECT", mesh.name)
            layer = action.layers.new("Robot Motion")
            strip = layer.strips.new(type="KEYFRAME")
            curves = strip.channelbags.new(slot).fcurves
        else:
            curves = action.fcurves
        linear = (
            bpy.types.Keyframe.bl_rna.properties["interpolation"]
            .enum_items["LINEAR"]
            .value
        )
        for column in range(7):
            path, index = (
                ("location", column)
                if column < 3
                else ("rotation_quaternion", column - 3)
            )
            curve = curves.new(path, index=index)
            curve.keyframe_points.add(len(frames))
            curve.keyframe_points.foreach_set(
                "co", np.column_stack((frames, values[:, column])).ravel()
            )
            curve.keyframe_points.foreach_set("interpolation", [linear] * len(frames))
            curve.update()
        completed = True
        return action, slot
    finally:
        if not completed:
            bpy.data.actions.remove(action)


def attach_action(mesh, action, slot):
    animation = mesh.animation_data_create()
    animation.action = action
    if slot is not None:
        animation.action_slot = slot
    animation.action_blend_type = "REPLACE"
    animation.action_influence = 1.0


def apply_motion(
    context,
    collection,
    filepath,
    *,
    trusted=False,
    quaternion_order="WXYZ",
    start_frame=1,
    use_motion_fps=True,
    replace_animation=False,
):
    if context.mode != "OBJECT":
        raise ValueError("Switch to Object Mode before loading robot motion")
    motion = load_motion(filepath, trusted=trusted, quaternion_order=quaternion_order)
    model = restore_model(collection)
    positions = map_joint_positions(model, motion)
    unrecorded = model.kindyn.getNrOfDegreesOfFreedom() - len(motion.joints)
    if unrecorded:
        logger.warning(
            "%s: %s unrecorded joints use their URDF zero position",
            collection.name,
            unrecorded,
        )
    meshes = [link.mesh for link in model.links.values()]
    for mesh in meshes:
        animation = mesh.animation_data
        if animation and (animation.drivers or animation.nla_tracks):
            raise ValueError(
                "Remove drivers/NLA tracks explicitly before loading robot motion"
            )
        if animation and animation.action and not replace_animation:
            raise ValueError(
                "Robot already has animation; enable Replace Existing Animation to overwrite it"
            )
    scene = context.scene
    fps, fps_base = scene.render.fps, scene.render.fps_base
    if use_motion_fps:
        fps = min(MAX_SCENE_FPS, max(1, round(motion.fps)))
        fps_base = fps / motion.fps
        limits = scene.render.bl_rna.properties["fps_base"]
        if not limits.hard_min <= fps_base <= limits.hard_max:
            raise ValueError("Motion FPS is outside Blender's supported range")
    frames = motion.frame_numbers(start_frame, fps / fps_base)
    frame_limits = scene.bl_rna.properties["frame_end"]
    if frames[0] < frame_limits.hard_min or frames[-1] > frame_limits.hard_max:
        raise ValueError("Motion frame range is outside Blender's supported range")
    values = sample_visuals(model, motion, positions, context.window_manager)
    old_scene = (
        scene.render.fps,
        scene.render.fps_base,
        scene.frame_start,
        scene.frame_end,
        scene.frame_current,
        scene.frame_subframe,
    )
    previous = []
    staged = []
    completed = False
    try:
        for key, link in model.links.items():
            mesh = link.mesh
            animation = mesh.animation_data
            previous.append(
                (
                    mesh,
                    animation is not None,
                    animation.action if animation else None,
                    (
                        animation.action_slot
                        if animation and hasattr(animation, "action_slot")
                        else None
                    ),
                    animation.action_blend_type if animation else "REPLACE",
                    animation.action_influence if animation else 1.0,
                    mesh.location.copy(),
                    mesh.rotation_quaternion.copy(),
                )
            )
            action, slot = build_action(mesh, frames, values[key])
            staged.append((mesh, action, slot))
        for mesh, action, slot in staged:
            attach_action(mesh, action, slot)
        scene.render.fps = fps
        scene.render.fps_base = fps_base
        scene.frame_start = min(scene.frame_start, start_frame)
        scene.frame_end = max(scene.frame_end, ceil(frames[-1]))
        scene.frame_set(start_frame)
        completed = True
    finally:
        if not completed:
            for (
                mesh,
                had_animation,
                action,
                slot,
                blend,
                influence,
                location,
                quaternion,
            ) in previous:
                if had_animation:
                    animation = mesh.animation_data_create()
                    animation.action = action
                    if slot is not None:
                        animation.action_slot = slot
                    animation.action_blend_type = blend
                    animation.action_influence = influence
                else:
                    mesh.animation_data_clear()
                mesh.location = location
                mesh.rotation_quaternion = quaternion
            for _, action, _ in staged:
                bpy.data.actions.remove(action)
            scene.render.fps, scene.render.fps_base = old_scene[:2]
            scene.frame_start, scene.frame_end = old_scene[2:4]
            scene.frame_set(old_scene[4], subframe=old_scene[5])
    return motion


class BMB_OT_LoadMotion(bpy.types.Operator, ImportHelper):
    bl_idname = "blend_my_bot.load_motion"
    bl_label = "Load Robot Motion (.npy)"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".npy"

    filter_glob: StringProperty(default="*.npy", options={"HIDDEN"})
    trust_file: BoolProperty(
        name="I Trust This File",
        description="NumPy object files use pickle and can execute Python code; enable only for trusted files",
        default=False,
        options={"SKIP_SAVE"},
    )
    quaternion_order: EnumProperty(
        name="Quaternion order",
        items=[("WXYZ", "wxyz (scalar first)", ""), ("XYZW", "xyzw (scalar last)", "")],
        default="WXYZ",
    )
    start_frame: IntProperty(name="Start frame", default=1, min=0)
    use_motion_fps: BoolProperty(
        name="Use Motion FPS",
        default=True,
        description="Change scene FPS to match the motion; affects other animation playback too",
    )
    replace_animation: BoolProperty(name="Replace Existing Animation", default=False)

    @classmethod
    def poll(cls, context):
        return context.scene.blend_my_bot_motion.robot is not None

    def draw(self, context):
        self.layout.label(text="Pickle files can execute Python code", icon="ERROR")
        for name in (
            "trust_file",
            "quaternion_order",
            "start_frame",
            "use_motion_fps",
            "replace_animation",
        ):
            self.layout.prop(self, name)
        if self.use_motion_fps:
            self.layout.label(text="Scene FPS changes affect all animation")

    def execute(self, context):
        try:
            motion = apply_motion(
                context,
                context.scene.blend_my_bot_motion.robot,
                bpy.path.abspath(self.filepath),
                trusted=self.trust_file,
                quaternion_order=self.quaternion_order,
                start_frame=self.start_frame,
                use_motion_fps=self.use_motion_fps,
                replace_animation=self.replace_animation,
            )
        except (
            OSError,
            ValueError,
            RuntimeError,
            KeyError,
            EOFError,
            pickle.UnpicklingError,
        ) as error:
            logger.exception("Robot motion import failed: %s", self.filepath)
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report(
            {"INFO"},
            f"Loaded {motion.samples} samples at {motion.fps:g} FPS ({motion.duration:.2f} seconds)",
        )
        robot = context.scene.blend_my_bot_motion.robot
        total = robot["blend_my_bot_joint_count"]
        if len(motion.joints) < total:
            self.report(
                {"WARNING"},
                f"{total - len(motion.joints)} unrecorded joints use their URDF zero position",
            )
        return {"FINISHED"}


def draw_motion(layout, context):
    box = layout.box()
    box.label(text="Robot Motion")
    box.prop(context.scene.blend_my_bot_motion, "robot")
    box.operator("blend_my_bot.load_motion", icon="FILE_FOLDER")
    box.label(text="Load motion, then play the timeline")


classes = (BMB_MotionSettings, BMB_OT_LoadMotion)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.blend_my_bot_motion = PointerProperty(type=BMB_MotionSettings)


def unregister():
    del bpy.types.Scene.blend_my_bot_motion
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
