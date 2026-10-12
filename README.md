# Blend My Bot

<div align="center">

**Import your robot in Blender and create a nice render of it!**

<https://github.com/ami-iit/blend-my-bot/assets/29798643/c224cd56-1d90-42dd-aec5-960a13690ce7>

</div>

## 🐍 Requirements

For the Blender extension, you only need a supported **Blender installation on
Linux x86-64**. Its ZIP includes iDynTree and matching dependency wheels; do not
replace Blender's Python or install `bpy` inside Blender.

For the Python scripting API:

- [`python3`](<https://wiki.python.org/moin/BeginnersGuide>)
- [`Blender 4`](<https://www.blender.org/download/>)
- [`iDynTree`](<https://github.com/robotology/idyntree>)
- [`numpy`](<https://numpy.org/>)
- [`resolve-robotics-uri-py`](<https://github.com/ami-iit/resolve-robotics-uri-py>)
- [`bpy 4`](<https://pypi.org/project/bpy/>)

> [!NOTE]
> You should use a Python version that matches the one supported by the Blender version.
> The Python version varies between Blender releases. Check the particular
> Blender installation rather than assuming all Blender 4 releases use the same version.

> [!NOTE]
> Robots are imported as meshes only. No armature or IK is generated; recorded
> motion is baked directly onto the meshes for normal Blender playback.

## 💾 Installation

### Recommended: Blender extension (Linux x86-64)

1. Download the extension ZIP matching your Blender **major.minor** release.
   The repository's **Blender extension** GitHub Actions workflow produces ZIPs
   as build artifacts when it runs. Unzip the downloaded artifact container to
   get the installable extension ZIP, or build one locally as described below.
2. In Blender, open **Edit → Preferences → Get Extensions**, open the top-right
   menu, and choose **Install from Disk**. Select the extension ZIP and enable it.
3. Choose **File → Import → Robot (.urdf)**, or open the 3D View sidebar with
   **N** and select the **Blend My Bot** tab.
4. Select an available robot package and URDF, or use **Browse URDF File**.

#### Choose a robot from installed packages

In the **Blend My Bot** sidebar:

1. Open **Package Search Folders** and add a robot package directory or the folder
   containing your packages, if they are not already in a robotics resource path.
2. Click **Refresh Available Robots**. Discovery also searches the resource paths
   used by resolve-robotics-uri-py, including ROS and Gazebo environment paths.
3. Choose a **Package**, then a **URDF**. URDF choices show relative paths, so
   variants with the same filename remain distinguishable.
4. Click **Import Selected Robot**.

Repository layouts such as `share/gene/robots/gene01/model.urdf` are supported:
you can add the repository root, its `share/` directory, or `share/gene/`.
The package selector shows **gene**, and `package://gene/...` meshes resolve
without installing the model package or activating a Conda environment.

Discovery does not download or install packages. It lists existing `.urdf` files
recursively, groups them by their nearest `package.xml` or `model.config`, and
otherwise uses their package folder. Symlinked packages are supported, duplicate
files and symlink cycles are avoided, and hidden subdirectories are skipped.
Xacro templates are not listed: generate their URDFs first.

The scan runs in short UI timer batches; press **Esc** to cancel and keep the
previous results. Refresh after changing search paths or adding/removing files.
If a scan raised a Python error, restart Blender to clear the failed scan before
installing an updated extension ZIP and refreshing again.
Catalogs are rebuilt on demand rather than saved into the Blender project.
You can still use **Browse URDF File** or **File → Import → Robot (.urdf)**.

Each import creates a separate collection, including when importing the same
robot twice. Blender's regular materials, camera, lighting, rendering, undo,
and project saving work normally. No Conda, terminal, symlink, administrator
access, or VS Code is needed by the user.

`package://` and `model://` mesh paths are resolved by
[`resolve-robotics-uri-py`](https://github.com/ami-iit/resolve-robotics-uri-py),
which is bundled with the extension. It searches robotics environment variables
such as `ROS_PACKAGE_PATH`, `AMENT_PREFIX_PATH` (under each prefix's `share/`),
`GAZEBO_MODEL_PATH`, `GZ_SIM_RESOURCE_PATH`, and `RRU_ADDITIONAL_PATHS`, as well
as its default Python-prefix resource directories.

You can also open **Package Search Folders** in the panel and add either the
package directory itself or its parent directory. These folders and the URDF
directory are passed to the resolver as additional search paths; no Conda or ROS
activation is required when your saved folders are sufficient. Environment
variables must be present in Blender's process: Blender launched from a desktop
icon does not automatically inherit a separately activated terminal environment.
The preferences use Blender's normal preference-saving behavior; save preferences
manually if auto-save is disabled. Relative mesh paths resolve against the URDF
directory, not the shell's working directory. Absolute paths and local `file://`
URIs are also supported. The original URDF is never modified.

#### Load recorded robot motion

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

**Current scope:** URDF import with OBJ/STL visual meshes, including
multiple visuals per link. Primitive visuals and other mesh formats produce
explicit errors. Mesh files referenced by collision geometry must also exist.
Recorded `.npy` motion loading is supported as described above; animation is
also available through the Python API below. Windows and macOS builds are not
yet provided because this release
uses Linux iDynTree wheels.

#### Build the extension from source

Use a build-time Python environment with pip and the target Blender executable:

```bash
python -m venv .venv
source .venv/bin/activate
python tools/build_extension.py --blender /path/to/blender
```

The builder downloads pinned iDynTree and resolve-robotics-uri-py wheels and the
NumPy version used by that Blender runtime, copies the scripting API library, and
produces a self-contained ZIP under `dist/`. Installation requires no network
access. The manifest limits installation to the Blender major.minor release
used to build it, preventing installation with an incompatible Python ABI.
Blender 4.2 or later is required.

To validate locally without changing your normal Blender preferences:

```bash
python -m pip install resolve-robotics-uri-py==0.5.1 numpy
python -m unittest discover -s tests -p 'test_*.py'
BLENDER_USER_RESOURCES="$PWD/.blender-test-profile" blender --background \
  --factory-startup --python-exit-code 1 --python tests/blender_smoke.py -- \
  dist/blend_my_bot-0.1.0-blender-4.2-linux-x64.zip
BLENDER_USER_RESOURCES="$PWD/.blender-test-profile" blender --background \
  --factory-startup --python-exit-code 1 --python tests/blender_motion.py -- \
  dist/blend_my_bot-0.1.0-blender-4.2-linux-x64.zip
```

Use your actual ZIP filename. The smoke test installs the extension into a
temporary repository, imports a test fixture twice, checks geometry and error handling,
tests package discovery and selected-URDF imports, tests the scripting API, and
disables/re-enables the extension.
The motion test checks named-joint mapping, quaternion conventions, exact sample
poses and timing, the final sample, multiple visual parts, long/renamed mesh
names, independent instances, replacement protection, rollback and save/reopen.
It exercises real Blender operators in background mode, not visual GUI playback.

To test a local robot model repository through the package browser:

```bash
BLENDER_USER_RESOURCES="$PWD/.blender-test-profile" blender --background \
  --factory-startup --python-exit-code 1 --python tests/blender_models.py -- \
  dist/blend_my_bot-0.1.0-blender-5.2-linux-x64.zip /path/to/gb-gene-models
```

This imports all discovered URDFs under the repository's `share/` directory in
mesh-only mode, checks mesh resolution, counts, bounding dimensions and posed FK
within `1e-5`, and cleans up each imported robot
before testing the next. Source URDFs are checked for changes.

To test the full supplied recording, run `tests/blender_motion.py` with the ZIP
path followed by `dataset_00.npy` and `/path/to/gb-gene-models`, using the same
isolated-profile Blender command. This bakes all 1,228 samples on Gene's Paxini
model, verifies representative poses against FK, and reports differences from
the optional recorded body poses without treating them as the playback source.

### Advanced: existing Conda scripting setup

The instructions below are retained for existing developer workflows. They
modify Blender's Python installation and are **not necessary for the extension**.

Create a conda environment and install the dependencies:

### Use the `setup_conda_blender.sh` script

You can use the `setup_conda_blender.sh` script to create a conda environment having the same python version as the one used by the Blender version you are using. This script will also create a symbolic link to the conda environment in the Blender python folder. Run the script from the root of the repository:

```bash
bash setup_conda_blender.sh folder/to/blender/executable
conda activate blender_env_version
pip install blend-my-bot
# or pip install -e .
```

### Manually

If you prefer to do it manually, you can follow these steps:

```bash
conda create -n blender_env python=3.10
conda activate blender_env
```

Create a backup of the python folder in the blender folder:

```bash
mv blender_folder/version/python blender_folder/version/python_backup
```

Run the command below in the blender python folder to create a symbolic link to the conda environment in the blender python folder:

```bash
sudo ln -s ~/mambaforge/envs/blender_env blender_folder/version/python
```

From the root of the repository install the package:

```bash
pip install blend-my-bot
```

When running Blender's Python API from a standalone Python environment rather
than inside Blender, install `pip install 'blend-my-bot[standalone]'` to also
install `bpy`. Inside Blender, use its existing `bpy` module.

If you want to run the scripts from `Visual Studio Code`, you need to install the `vscode python` extension and set the python interpreter to the already created conda environment.

You need an additional vscode extension: `Blender Development` which can be found [here](https://marketplace.visualstudio.com/items?itemName=JacquesLucke.blender-development).

Once installed, you can run Blender by typing `Ctrl+Shift+P` and then `Blender: Start`. It will ask you to select the blender executable: select the one in the folder where you extracted the blender archive (or the installed version if you installed it). Once Blender is running, you can run the script by typing `Ctrl+Shift+P` and then `Blender: Run Script`.

You can add objects, lights, and cameras as well as play with render parameters directly in Blender.
If you prefer, you can save the Blender project. Everything will be there, including the robot and its motion, so that it does not need to run your script again.

Note that you could also write a script directly in the `Scripting` tab of Blender and run it from there.

For possible issues when running the script see the [Troubleshooting](#troubleshooting) section.

## 🚀 Usage

```python
# import the library
from blend_my_bot import ModelImporter
# import the blender python API
import bpy

# ModelImporter needs 3 arguments:
# - the name you want to give to your robot
# - the path to the urdf file
# - the list of the joints you want to move in the animation

urdf_path = "path/to/urdf"
robot_name = "my_robot"
joints_list = ["joint1", "joint2", "joint3", "etc"]

# build the blender robot model
model = ModelImporter.build_model(robot_name, urdf_path, joints_list)

# you need to set the frame rate and the number of frames of the animation
# length of the animation in seconds
bpy.context.scene.render.fps_base = time_length
# number of frames
bpy.context.scene.render.fps = number_of_frames
# when the animation starts
bpy.context.scene.frame_start = 0
# when the animation ends
bpy.context.scene.frame_end = number_of_frames

# in Blender the effective frame rate is fps / fps_base

# you can now move the base and the joints of the robot
for k in range(number_of_frames):
    # jet the joint trajectory at time k
    s = joint_trajectory[k]
    # get the base pose described by a 4x4 homogeneous matrix at time k
    w_H_b = base_trajectory[k]
    # set the frame
    bpy.context.scene.frame_set(k)
    # update the robot model and insert keyframes at this frame
    model.update(w_H_b, s)
```

Have a look at the `examples` folder for more examples.

Within an installed extension, use its namespaced library from Blender's Python
console (the repository identifier may differ):

```python
from bl_ext.user_default.blend_my_bot.blend_my_bot import ModelImporter
```

### Motion through the existing Python example

`examples/jumping/main.py` loads the iCub `iCubGazeboV2_7` model, selects its
23-joint reduced model, and reads `examples/jumping/jumping.pickle`. For each
sample it sets the base pose and joint positions and inserts mesh location and
rotation keyframes. Playback then uses Blender's normal timeline; no rig is
required.

The supplied file contains 61 stored samples over approximately 5.63 seconds.
Its joint names are **not** stored in the pickle: the ordering is the
`joints_list` in the script. The current example loops over `knots` (60), so
the final stored sample is not baked. Do not apply this iCub trajectory directly
to a Gene robot without a compatible trajectory and explicit joint mapping.

To run the unchanged script:

1. Use the Python scripting setup described above, with `blend_my_bot`, NumPy,
   SciPy and `resolve_robotics_uri_py` available to Blender's Python.
2. Make the iCub model and mesh package available to the resolver, for example
   through `RRU_ADDITIONAL_PATHS` pointing to the folder containing `iCub`.
3. Run the script from the repository root using the Blender Development
   workflow, or paste it into Blender's Scripting workspace. When using the
   Scripting workspace, change `pickle_path` to the file's absolute path.
4. Play the timeline and save the animated scene as a `.blend` file.

Installing only the extension does not make the unchanged script's imports
available: its library lives under Blender's extension namespace rather than
the top-level `blend_my_bot`, and it does not bundle SciPy. The panel's new
loader accepts the named `.npy` dictionary format above, not this older unnamed
pickle format.

Only load pickle files you trust: deserialization can execute Python code.

In the `examples/jumping` folder you can find a script that generates a jumping animation of the `iCub` robot. Here the meshes are in a gray, `stl` format.

Having the meshes in an `obj` format, instead, will give a nicer and more colorful render! See the Readme of the following repository, for example!

[Whole-Body Trajectory Optimization for Robot Multimodal Locomotion](<https://github.com/ami-iit/paper_lerario_2022_humanoids_planning-multimodal-locomotion>)

## 🦿 Troubleshooting

#### FileNotFoundError when running the script

If you install a new package in the conda environment but it is not working as you expect when you run the script, try to activate it in a terminal **before** and then open `Visual Studio Code` from the terminal:

```bash
conda activate blender_env
code .
```

For example, when using [`resolve_robotics_uri_py`](https://github.com/ami-iit/resolve-robotics-uri-py) an error like the following one appears:

```
FileNotFoundError: resolve-robotics-uri-py: No file corresponding to uri "package://iCub/robots/iCubGazeboV2_7/model.urdf" found
```

This is due to the fact that environmental variables are not sourced. Activating the conda environment before opening `vscode` solves this issue!

#### Crush when running the script

If Blender crashes when running the script from `Visual Studio Code`, try to run the script from the `Scripting` tab of Blender.

## 🦸‍♂️ Contributing

`blend-my-bot` is an open-source project. Contributions are very welcome!

Open an issue with your feature request or if you spot a bug. Then, you can also proceed with a Pull-requests! 🚀

## 📝 Tips

Some tips to speed up your Cycle render:
<https://www.youtube.com/watch?v=FNiobzflmpA>

Feel free to add your own tips here!
