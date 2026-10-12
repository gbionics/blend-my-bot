# Python API

[README](../README.md) | [Installation](./installation.md) | [Motion datasets](./motion-dataset.md) | [Python API](./python-api.md) | [Development](./development.md)

Use this guide for direct Python control of robot imports and animation.
For the native sidebar workflow, use the [installation guide](./installation.md)
and [motion dataset guide](./motion-dataset.md) instead.

## Requirements

For the Python scripting API:
- [`python3`](<https://wiki.python.org/moin/BeginnersGuide>)
- [`Blender 5.0+`](<https://www.blender.org/download/>)
- [`iDynTree`](<https://github.com/robotology/idyntree>)
- [`numpy`](<https://numpy.org/>)
- [`resolve-robotics-uri-py`](<https://github.com/ami-iit/resolve-robotics-uri-py>)
- [`pycollada`](<https://pypi.org/project/pycollada/>)
- [`bpy 5.0+`](<https://pypi.org/project/bpy/>)

> [!NOTE]
> You should use a Python version that matches the one supported by the Blender version.
> The Python version varies between Blender releases. Check the particular
> Blender installation rather than assuming all Blender releases use the same version.

> [!NOTE]
> Robots are imported as meshes only. No armature or IK is generated; recorded
> motion is baked directly onto the meshes for normal Blender playback.

## Installation and editor setup

The instructions below are retained for existing developer workflows.

> [!WARNING]
> This legacy setup replaces Blender's bundled `python/` directory with a
> Conda symlink. It needs permission to modify the Blender installation and can
> break Blender if the environment is incompatible. Prefer the native extension;
> none of these steps are required for it.

Create a conda environment and install the dependencies:

### Use the setup_conda_blender.sh script

The [setup_conda_blender.sh script](../setup_conda_blender.sh) detects Blender's
Python version and creates a matching Conda environment. Run it from the repository
root, passing the **versioned directory containing `python/`**, not the Blender
executable. For example, for Blender 5.0 with Python 3.11:

```bash
bash setup_conda_blender.sh /path/to/blender/5.0
conda activate blender_env311
pip install blend-my-bot
# or pip install -e .
```

Use the environment name printed by the script: Python 3.11 produces
`blender_env311`, while Python 3.13 produces `blender_env313`.

### Manual setup

If you prefer to do it manually, you can follow these steps:

```bash
# Example for Blender 5.0; match your installed Blender's Python version.
conda create -n blender_env python=3.11
conda activate blender_env
```

Create a backup of Blender's Python directory, substituting your actual
installation path:

```bash
mv /path/to/blender/5.0/python /path/to/blender/5.0/python_backup
```

With the matching Conda environment still activated, create the symlink at
the original Python directory's path. `CONDA_PREFIX` points to the active
environment; you do not need to assume a particular Conda installation location.
Do not run this from inside the Python directory you just moved.

```bash
ln -s "$CONDA_PREFIX" /path/to/blender/5.0/python
```

The backup and symlink commands require write access to that installation.
For a protected installation, administrator permission is needed for both.

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

## Usage

```python
# import the library
from blend_my_bot import ModelImporter
# import the blender python API
import bpy

# ModelImporter takes 2 required arguments and an optional joint list:
# - the name you want to give to your robot
# - the path to the urdf file
# - optionally, the joints to retain in the reduced model

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

Have a look at the [examples folder](../examples/) for more examples.

Within an installed extension, use its namespaced library from Blender's Python
console (the repository identifier may differ):

```python
from bl_ext.user_default.blend_my_bot.blend_my_bot import ModelImporter
```

## Motion through the existing Python example

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

1. Use the [Python scripting setup](#installation-and-editor-setup), with `blend_my_bot`, NumPy,
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
loader accepts the [named `.npy` dictionary format](./motion-dataset.md), not this older unnamed
pickle format.

Only load pickle files you trust: deserialization can execute Python code.

The [jumping example](../examples/jumping/main.py) uses STL geometry. STL files
do not embed materials, but the importer can still apply colors declared in the
URDF; STL does not necessarily mean a gray robot. OBJ and DAE assets can carry
their own materials. See [Robot colors](./installation.md#robot-colors).

For another rendering example, see:

[Whole-Body Trajectory Optimization for Robot Multimodal Locomotion](<https://github.com/ami-iit/paper_lerario_2022_humanoids_planning-multimodal-locomotion>)

## Troubleshooting

### FileNotFoundError when running the script

If you install a new package in the conda environment but it is not working as you expect when you run the script, try to activate it in a terminal **before** and then open `Visual Studio Code` from the terminal:

```bash
conda activate blender_env
code .
```

For example, when using [`resolve_robotics_uri_py`](https://github.com/ami-iit/resolve-robotics-uri-py) an error like the following one appears:

```
FileNotFoundError: resolve-robotics-uri-py: No file corresponding to uri "package://iCub/robots/iCubGazeboV2_7/model.urdf" found
```

This error means the resolver cannot locate that robot resource; it does not
necessarily mean a Python dependency is missing. Activating the environment
before opening VS Code helps only if its activation sets the required resource
paths. Check that the package exists and set `RRU_ADDITIONAL_PATHS` to the folder
containing it. For the native extension, use
[Package Search Folders](./installation.md#choose-a-robot-from-installed-packages)
instead of changing Blender's Python.

### Crash when running the script

If Blender crashes when running the script from `Visual Studio Code`, try to run the script from the `Scripting` tab of Blender.
