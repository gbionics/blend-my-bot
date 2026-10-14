# Motion datasets

[README](../README.md) | [Installation](./installation.md) | [Motion datasets](./motion-dataset.md) | [Python API](./python-api.md) | [Development](./development.md)

Load recorded motion onto an imported robot, or export your own compatible
`.npy` dataset. [Install and import a robot](./installation.md) first.

- [Load a recording](#load-recorded-robot-motion)
- [Create a dataset](#create-a-motion-dataset-npy)

## Load recorded robot motion

1. Import the matching robot URDF. Imports create only meshes: no rig or IK.
2. In the **Blend My Bot** sidebar's **Robot Motion** section, select its
   **Robot** collection. The most recently imported robot is selected automatically.
3. Click **Load Robot Motion (.npy)** and choose your file.
4. Enable **I Trust This File** only if you trust its source. NumPy object files
   contain pickle payloads, which can execute Python code.
5. Select the quaternion order and start frame, then load. **wxyz (scalar first)**
   is the default and the convention used by `dataset_00.npy`.
6. Play the timeline or save the `.blend` normally. The motion is baked onto
   mesh location/quaternion channels; playback needs no live Python solver.

For the supplied `dataset_00.npy`, import
`gene/robots/gene01_paxini_hand/model.urdf`. Its 86 named joints match that model.
The file contains **1,228 samples at 50 FPS**, including the last sample, spanning
**24.54 seconds**. With the default start frame, keyframes run from **1 to 1228**.
Other Gene variants lack some recorded joints and are rejected rather than
silently applying the wrong motion.

**Use Motion FPS** changes the scene frame rate to match the recording; this
also affects other animation in the scene. Disable it to keep the current scene
FPS: fractional keyframe positions preserve the recording's duration.
The playback range is extended to include the clip without shrinking an existing
range. **Replace Existing Animation** is disabled by default. Enable it to
replace the selected robot's active actions; other robots and shared old actions
are not modified. Drivers, NLA tracks, constraints and parented meshes must be
removed explicitly before motion import.

The supported file is a scalar NumPy object containing a dictionary:
See [Create a motion dataset](#create-a-motion-dataset-npy) below for a complete
export example.

```python
{
    "joints_list": ["joint_a", "joint_b"],  # column order, not URDF order
    "fps": 50.0,                           # scalar or one-element array
    "joint_positions": ...,               # (N, J), radians/metres
    "root_position": ...,                 # (N, 3), world position in metres
    "root_quaternion": ...,               # (N, 4), unit quaternions
    "duration": ...,                      # optional: (N - 1) / fps
}
```

`root_position`/`root_quaternion` describe the URDF root link's world pose.
The loader maps every recorded joint by name and validates names, dimensions,
finite values, quaternion lengths, FPS and duration before adding animation.
Unrecorded joints use the URDF zero position, with a warning. Recorded values
are visualized as supplied; joint limits and mimic coupling are not enforced.
Optional `body_links_list`, `body_links_pos_w` and `body_links_quat_w` are not
needed for playback: the selected URDF and recorded joint values provide FK.
The supplied recording has small differences between its recorded body poses
and reconstructed FK, mainly in the fingers. Playback intentionally uses **joint
values plus URDF FK**, not the optional recorded world poses.

All visual parts, visual origins, mesh scales and materials are retained.
Linear mesh-transform interpolation is used between samples, with quaternion
sign continuity to prevent flips. This is motion playback, not retargeting,
collision checking or physics simulation. Loading may take a few seconds;
failed imports keep the robot's prior actions and scene timing.

New imports save their kinematic description and mesh bindings into the `.blend`,
so motion can be loaded after reopening without the original URDF or mesh files.
Reimport older collections with this version before loading motion; existing
rigged scenes are not automatically converted. NumPy pickle archives also
require a runtime compatible with their producer's NumPy version.

## Create a motion dataset (.npy)

You can generate this format from a simulator, controller log, trajectory
optimizer, or a Python script. Creating the file needs **NumPy**, not Blender,
Conda, or a rig. It describes robot joint positions and the root link's world
pose at uniformly spaced times. Blender reconstructs the visual poses using
the matching URDF's forward kinematics.

### 1. Choose the robot and joint columns

Use the **same robot variant and URDF** for recording and Blender import.
`joints_list` contains exact URDF joint names, not link names or mesh names.
Only one-DOF movable joints are accepted: revolute, continuous and prismatic
joints. Do not include fixed joints or put the floating base in this list.

Column `j` of `joint_positions` must describe `joints_list[j]` at every sample.
You may use any column order, but do not sort the names without also reordering
the columns. Names must be unique. Unknown names are rejected; movable joints
omitted from the recording use **zero**, not their current Blender pose, with
a warning. To preserve the whole robot configuration, record all movable joints.

### 2. Prepare synchronized samples

Let `N` be the number of samples and `J = len(joints_list)`.

| Field | Shape/type | Meaning |
| --- | --- | --- |
| `joints_list` | List of `J` strings | Joint names in matrix-column order |
| `fps` | Positive finite number | Sampling rate in samples per second |
| `joint_positions` | `(N, J)` numeric array | Revolute/continuous angles in **radians**; prismatic displacements in **metres** |
| `root_position` | `(N, 3)` numeric array | URDF root link's world position `[x, y, z]` in **metres** |
| `root_quaternion` | `(N, 4)` numeric array | Root link's orientation in the world; unit quaternions |
| `duration` | Optional number | Time from first to last sample: `(N - 1) / fps` seconds |

Use real numeric arrays, preferably `float64`, with no NaN or infinity.
All arrays must have the same `N`, with at least one sample. Sample `i` occurs
at `i / fps` seconds; the first sample is at zero. If your log has irregular
timestamps or separately sampled joint/base data, resample and synchronize it
before export. Timestamp fields in the dictionary do not control playback.

Record the pose of the **URDF root link**, not a sensor frame or the mesh's
visual origin. Convert your producer's frame and coordinate conventions first;
URDF visual offsets are applied by the importer and must not be added again.
For a stationary base, repeat its actual position and orientation for every
sample. Set the root's height appropriately for the robot rather than assuming
that zero places its feet on the floor.

The default quaternion order is **wxyz**, with identity `[1, 0, 0, 0]`.
If your producer supplies **xyzw**, either select **xyzw** in the motion import
dialog or convert before saving:

```python
root_quaternion = root_quaternion_xyzw[:, [3, 0, 1, 2]]
```

Quaternion order is not auto-detected. Each quaternion's length must be within
`1e-3` of one; normalize valid nonzero quaternions before export if necessary.
Euler angles and all-zero quaternions are not valid replacements.

### 3. Generate and save a file

Set `urdf_path` to your robot's URDF and run this in a Python environment with
NumPy installed. The example reads the movable joint names automatically,
creates **501 samples at 50 FPS** (10 seconds), and writes `robot_motion.npy`.

```python
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

urdf_path = Path("path/to/robot.urdf")  # Use the URDF imported into Blender.
output_path = Path("robot_motion.npy")

robot = ET.parse(urdf_path).getroot()
joints = [
    joint
    for joint in robot.findall("joint")
    if joint.get("type") in {"revolute", "continuous", "prismatic"}
]
joints_list = [joint.attrib["name"] for joint in joints]

fps = 50.0
samples = 501
time = np.arange(samples, dtype=np.float64) / fps

joint_positions = np.zeros((samples, len(joints)), dtype=np.float64)
for column, joint in enumerate(joints):
    if joint.get("type") in {"revolute", "continuous"}:
        joint_positions[:, column] = 0.1 * np.sin(2 * np.pi * 0.5 * time)

root_position = np.zeros((samples, 3), dtype=np.float64)
root_position[:, 0] = 0.02 * time
root_quaternion = np.tile([1.0, 0.0, 0.0, 0.0], (samples, 1))

dataset = {
    "joints_list": joints_list,
    "fps": fps,
    "joint_positions": joint_positions,
    "root_position": root_position,
    "root_quaternion": root_quaternion,
    "duration": (samples - 1) / fps,
}

np.save(output_path, dataset, allow_pickle=True)
print(
    f"Saved {output_path}: {samples} samples, "
    f"{len(joints_list)} joints, {dataset['duration']:.2f} seconds"
)
```

These are **synthetic visualization trajectories**, not a physically valid or
joint-limit-checked robot motion. Replace `joint_positions`, `root_position`
and `root_quaternion` with your recorded or planned arrays before constructing
`dataset`; derive `samples` from their length. For recorded data, use its actual
joint-column names/order rather than assuming it matches the URDF's XML order.
The loader does not enforce joint limits or mimic coupling.

`np.save(path, dataset)` creates the required **scalar object array containing
one dictionary**. Do not save just `joint_positions`, wrap the dictionary in
a list, or use `np.savez`: those produce different layouts.

For base-only motion, use `joints_list = []` and a `(N, 0)` `joint_positions`
array; the root arrays are still required. Optional body-world poses are not
needed: `body_links_list`, `body_links_pos_w` and `body_links_quat_w` are ignored
for playback. You do not need every extra field present in `dataset_00.npy`.

To match that recording's dimensions, use its matching Gene Paxini URDF,
`N = 1228`, `J = 86` and `fps = 50`: the span is **24.54 seconds**, not
`1228 / 50`. Matching these dimensions alone does not reproduce its trajectory;
the recorded joint and root values must also come from that motion.

### 4. Validate and play it in Blender

Use a NumPy version compatible with the target Blender runtime when exporting.
Check `import numpy; print(numpy.__version__)` in Blender's Python Console
after enabling the extension. A NumPy 2-produced pickle may need modules that
are unavailable in a NumPy 1 runtime; changing array dtype does not fix that.

For a format check, run this in Blender's Python Console after enabling the
extension (replace `user_default` if your extension repository has another ID):

```python
from bl_ext.user_default.blend_my_bot.blend_my_bot.motion_data import load_motion

motion = load_motion(
    "/absolute/path/to/robot_motion.npy",
    trusted=True,
    quaternion_order="WXYZ",
)
print(motion.samples, motion.fps, motion.duration, motion.joints)
```

This validates the file's schema, values and timing, **not** whether its joint
names belong to the selected robot. To check that and bake playback, follow
[Load recorded robot motion](#load-recorded-robot-motion): import the matching
URDF, select its collection, load the file and choose the correct quaternion
order. With **Use Motion FPS** enabled and start frame 1, the example occupies
frames **1–501**; all samples, including the last, are included.

Only enable **I Trust This File** or use `trusted=True` for files whose source
you trust. This dictionary format uses Python pickle internally, and loading it
can execute code. The provided dataset is user-supplied and is not bundled with
the extension.
