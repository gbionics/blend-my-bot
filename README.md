# Blend My Bot

<div align="center">

**Import your robot in Blender and create a nice render of it!**

<https://github.com/ami-iit/blend-my-bot/assets/29798643/c224cd56-1d90-42dd-aec5-960a13690ce7>

</div>

Import URDF robots, preserve their materials, and play recorded motion directly
in Blender. The native extension needs no Conda environment, Python symlink,
or terminal setup.

## Features

- Import local URDF files or browse installed robot packages.
- Search the online robot catalog powered by
  [robot_descriptions](https://github.com/robot-descriptions/robot_descriptions.py).
- Load OBJ, STL and DAE visuals, including URDF colors and packed DAE textures.
- Bake named-joint `.npy` motion onto meshes and save it in a normal `.blend`.

Robots are **mesh-only**: no armature or IK is generated.

## Requirements

**Blender 5.0+ on Linux x86-64.** Install the extension ZIP matching your Blender
**major.minor** release. Blender 4.x and older are unsupported.

New online downloads also need **Git on PATH** and Blender's online access.
Local files and cached robots work offline without Git.

## Quick start

1. Download the Blender 5.0 extension ZIP from the
   [Blender extension workflow](https://github.com/gbionics/blend-my-bot/actions/workflows/blender-extension.yml).
   Unzip the downloaded artifact container first. For another Blender release,
   [build a matching ZIP](./docs/development.md#build-the-extension-from-source).
2. In Blender, choose **Edit → Preferences → Get Extensions → Install from Disk**
   from the top-right menu, select the ZIP, and enable it.
3. Open the 3D View sidebar with **N**, select **Blend My Bot**, and choose
   **Local Packages**, **Online Catalog**, or **URDF File**.
4. Import a robot. Use **Material Preview** to see its materials.
5. To animate it, choose its collection under **Robot Motion** and click
   **Load Robot Motion (.npy)**. Only load files whose source you trust.

See the [installation guide](./docs/installation.md) for package paths, online
downloads, caching, mesh compatibility and colors.

## Documentation

| Guide | What you will find |
| --- | --- |
| [Installation and robot import](./docs/installation.md) | Extension setup, local packages, online catalog, materials and supported meshes |
| [Motion datasets](./docs/motion-dataset.md) | Loading motion, dataset schema, units, quaternion conventions and a complete export example |
| [Python API](./docs/python-api.md) | Scripting dependencies, legacy Conda/editor setup, animation examples and troubleshooting |
| [Development](./docs/development.md) | Building extension ZIPs and running unit, Blender and real-robot tests |

## 🦸‍♂️ Contributing

`blend-my-bot` is an open-source project. Contributions are very welcome!

Open an issue with your feature request or if you spot a bug. Then, you can also proceed with a Pull-requests! 🚀

See the [development guide](./docs/development.md) to build and test changes.

## 📝 Tips

Some tips to speed up your Cycle render:
<https://www.youtube.com/watch?v=FNiobzflmpA>

Feel free to add your own tips here!
