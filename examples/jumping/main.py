from blend_my_bot import ModelImporter
import bpy
import numpy as np
import pickle

# if scipy is not installed on your system, you can install it with:
# pip install scipy
from scipy.spatial.transform import Rotation

# using resolve_robotics_uri_py to load the robot and its meshes
# if resolve_robotics_uri_py is not installed on your system, you can install it with:
# pip install resolve-robotics-uri-py
# or mamba install -c conda-forge resolve-robotics-uri-py

# if when you run the script you are not able to resolve the path to the robot,
# activate the conda environment from a terminal outside vscode
# and on open vscode from that terminal with the command: code .
import resolve_robotics_uri_py

# get the path to the robot urdf
urdf_path = str(
    resolve_robotics_uri_py.resolve_robotics_uri(
        "package://iCub/robots/iCubGazeboV2_7/model.urdf"
    )
)

# set the list of joints that we want to move in the animation
joints_list = [
    "torso_pitch",
    "torso_roll",
    "torso_yaw",
    "l_shoulder_pitch",
    "l_shoulder_roll",
    "l_shoulder_yaw",
    "l_elbow",
    "r_shoulder_pitch",
    "r_shoulder_roll",
    "r_shoulder_yaw",
    "r_elbow",
    "l_hip_pitch",
    "l_hip_roll",
    "l_hip_yaw",
    "l_knee",
    "l_ankle_pitch",
    "l_ankle_roll",
    "r_hip_pitch",
    "r_hip_roll",
    "r_hip_yaw",
    "r_knee",
    "r_ankle_pitch",
    "r_ankle_roll",
]

# set the name of the model
# this is useful to identify the meshes of the robot in blender
# and possibly load more than one robot in the same scene
model_name = "iCub"

# build the model of the robot
model = ModelImporter.build_model(model_name, urdf_path, joints_list)

# load the robot configuration evolution from a pickle file
pickle_path = "examples/jumping/jumping.pickle"
with open(pickle_path, "rb") as f:
    data = pickle.load(f)

# set the length of the animation
bpy.context.scene.render.fps_base = data["Time"]
# set the number of frames of the animation
bpy.context.scene.render.fps = data["knots"]
# set when the animation starts
bpy.context.scene.frame_start = 0
# set when the animation ends
bpy.context.scene.frame_end = data["knots"]

# in blender the effective frame rate is fps/fps_base


# start the animation
for k in range(data["knots"]):
    # get the joint positions at the current knot
    s = data["joint_pos"][:, k]
    # get the base pose at the current knot
    # in this particular test we stored position and orientation in quaternions
    # but the update method of the model accepts a homogeneous transformation
    p = data["position"][:, k]
    q = data["orientation"][:, k]
    w_H_b = np.eye(4)
    w_H_b[:3, 3] = p
    w_H_b[:3, :3] = Rotation.from_quat(q).as_matrix()
    # set the current frame before inserting keyframes
    bpy.context.scene.frame_set(k)
    # update the model
    # the update method inserts also keyframes of the meshes for the animation
    model.update(w_H_b, s)
