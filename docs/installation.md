# Installation and robot import

[README](../README.md) | [Installation](./installation.md) | [Motion datasets](./motion-dataset.md) | [Python API](./python-api.md) | [Development](./development.md)

## Requirements

For the Blender extension, you only need **Blender 5.0 or newer on
Linux x86-64**. Its ZIP includes iDynTree and matching dependency wheels; do not
replace Blender's Python or install `bpy` inside Blender.
Blender 4.x and older are no longer supported.
The optional **Online Catalog** additionally needs **Git available on PATH**
for downloads. Local packages, URDF files and already-cached robots do not need Git.

For scripting dependencies and legacy Conda/editor setup, see the
[Python API guide](./python-api.md#requirements).

## Install the Blender extension

1. Download the extension ZIP matching your Blender **major.minor** release.
   The [Blender extension workflow](https://github.com/gbionics/blend-my-bot/actions/workflows/blender-extension.yml)
   currently builds for **Blender 5.0** only. Unzip the downloaded artifact
   container to get the installable extension ZIP. For another Blender release,
   [build a matching ZIP locally](./development.md#build-the-extension-from-source).
2. In Blender, open **Edit → Preferences → Get Extensions**, open the top-right
   menu, and choose **Install from Disk**. Select the extension ZIP and enable it.
3. Choose **File → Import → Robot (.urdf)**, or open the 3D View sidebar with
   **N** and select the **Blend My Bot** tab.
4. Choose a **Robot Source**: **Local Packages**, **Online Catalog**, or **URDF File**.
   Select a package/URDF, download a catalog robot, or use **Browse URDF File**.

## Download a robot from the online catalog

1. In the **Blend My Bot** sidebar, select **Online Catalog** as the **Robot Source**.
2. Click **Search Robots**, or use the **Robot** dropdown, to choose any URDF
   description from the bundled `robot_descriptions` catalog.
3. Enable Blender's online access in **Preferences → System → Network**, and make
   sure Git is installed and available on PATH when Blender starts.
4. Click **Download & Import Robot**. The selected robot's upstream repository is
   downloaded using the bundled
   [`robot_descriptions`](https://github.com/robot-descriptions/robot_descriptions.py)
   library. The catalog itself can be browsed without network access or downloads.
5. Once cached, the button becomes **Import Cached Robot**. Further imports need
   neither internet access nor Git, and create independent mesh-only collections.
   [Load Robot Motion (.npy)](./motion-dataset.md#load-recorded-robot-motion)
   works exactly as for locally imported robots.

Downloads run in an isolated process using Blender's bundled Python; the UI stays
responsive and displays download status. Press **Esc** or **Cancel Download** to
stop. Failed, timed-out and cancelled downloads are not promoted to the completed
cache, and existing cached robots are kept. Downloads time out after ten minutes.
Disabling the extension also stops an active download.

The cache lives in Blender's writable extension-user directory, not inside the
installed ZIP, so reinstalling the extension does not discard it. Its location is
shown in the extension preferences. To recover a damaged cache or force a fresh
download, use **Open Robot Cache** there and remove only the affected robot's
subfolder.

The browser lists every description advertised as URDF by the pinned
`robot_descriptions` library (132 entries in version 3.2.0), without downloading
them. **Bolt**, **Cassie**, **ANYmal B**, **G1** and **Go2** are marked **Blender-tested**;
all other entries are
marked **Not yet Blender-tested**, but remain selectable. They can be imported
if they meet the compatibility requirements below. That label reports test
coverage, not a compatibility restriction.

Actual imports currently require a static URDF with OBJ/STL/DAE visual meshes.
MJCF-only descriptions are excluded. Xacro-backed entries remain visible but
report the need to generate a URDF and use **Browse URDF File**; Xacro generation
is not bundled. Unsupported visual primitives and mesh formats also produce
explicit errors rather than silently skipping geometry.
For example, ANYmal B's DAE visuals import successfully, while ANYmal C and
Upkie currently require visual primitive support and cannot be imported as-is.
Robot assets retain their upstream licenses, shown beside the selection; they are
downloaded on demand and are not bundled in the extension ZIP. Each cached entry
records the pinned catalog-library version; incompatible cache metadata is rejected
explicitly rather than silently loading another model.

## Choose a robot from installed packages

In the **Blend My Bot** sidebar, select **Local Packages**:

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

Local discovery does not download or install packages. It lists existing `.urdf` files
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

## Robot colors

Inline URDF `<material><color rgba="..."/></material>` colors and references to
named, robot-level materials become Principled materials on meshes without an
existing material. This restores colors for STL-based robots such as G1.
RGBA values must contain four finite numbers between zero and one; alpha is
preserved for transparent materials. Undefined material names and invalid colors
produce explicit errors instead of silently dropping visuals.

Embedded OBJ/DAE materials take precedence and are not overwritten. Parts of the
same import can share a color material; separate robot imports get independent
materials. Scripting reimports that reuse existing objects leave user-edited
materials untouched. URDF texture-only materials are not supported; textures
embedded in OBJ/DAE assets are handled by their mesh importers.

Use **Material Preview** or **Rendered** viewport shading to see the materials.
In **Solid** shading, choose **Color → Material** (or **Object** for URDF fallback
colors). Imports do not change your viewport shading settings. After installing
the updated extension, reimport older uncolored robots; existing scenes are not
automatically recolored. Materials survive motion playback and saving/reopening.

## COLLADA / DAE meshes

DAE visuals use a bundled reader, not Blender's removed COLLADA importer.
Asset units, X/Y/Z up axes, nested node transforms, geometry instances and
URDF visual origins/scales are retained. Triangles and polygon faces, custom
normals, UV sets and material bindings are imported as ordinary Blender meshes.
Zero-length source normals use Blender's automatic normals for those corners,
with a warning; valid custom normals are preserved. Nonfinite source data still
fails explicitly.
Only vertices used by each material group are retained.
Line primitives are preserved as loose mesh edges; they have no rendered
thickness. Line-specific normals/UVs are not supported.

Local diffuse, emission, specular and transparency textures are packed into the
`.blend`, so they survive saving and reopening without their source files.
Relative paths, URI-encoded filenames and local `file://` texture paths work;
remote texture downloads are not supported. Missing textures and missing UV
bindings produce explicit errors and roll back the failed robot import.

COMMON constant/Lambert/Phong/Blinn material properties are translated to
Principled materials. This is an approximation, not exact shader equivalence:
ambient/reflection shading and exporter-specific effects are not reproduced.
Bump maps, polygon holes, animated/skinned/morphed DAE assets and unsupported
primitive types are rejected explicitly. Export static meshes without those
features; the robot's motion still comes from URDF FK and `.npy` joint values.
No DAE armature or rig is generated.

**Current scope:** URDF import with OBJ/STL/DAE visual meshes, including
multiple visuals per link. Primitive visuals and other mesh formats produce
explicit errors. Mesh files referenced by collision geometry must also exist.
Recorded `.npy` motion loading is described in the [motion guide](./motion-dataset.md);
animation is also available through the [Python API](./python-api.md). Windows and macOS builds are not
yet provided because this release
uses Linux iDynTree wheels.
