# Development

[README](../README.md) | [Installation](./installation.md) | [Motion datasets](./motion-dataset.md) | [Python API](./python-api.md) | [Development](./development.md)

Run the shell commands below from the repository root. Use an isolated
Blender profile for tests so your normal preferences and model cache are not changed.

## Build the extension from source

Use a build-time Python environment with pip and the target Blender executable:

```bash
python -m venv .venv
source .venv/bin/activate
python tools/build_extension.py --blender /path/to/blender
```

The builder downloads iDynTree, resolve-robotics-uri-py, robot_descriptions,
pycollada and their dependencies, plus the
NumPy version used by that Blender runtime, copies the scripting API library, and
produces a self-contained ZIP under `dist/`. Installation requires no network
access. The manifest limits installation to the Blender major.minor release
used to build it, preventing installation with an incompatible Python ABI.
Blender 5.0 or later is required; the builder rejects Blender 4.x before downloads.

## Run tests

To validate locally without changing your normal Blender preferences:

```bash
python -m pip install resolve-robotics-uri-py==0.5.1 numpy robot_descriptions==3.2.0 pycollada==0.9.3
python -m unittest discover -s tests -p 'test_*.py'
BLENDER_USER_RESOURCES="$PWD/.blender-test-profile" blender --background \
  --factory-startup --python-exit-code 1 --python tests/blender_smoke.py -- \
  dist/blend_my_bot-0.1.0-blender-5.0-linux-x64.zip
BLENDER_USER_RESOURCES="$PWD/.blender-test-profile" blender --background \
  --factory-startup --python-exit-code 1 --python tests/blender_motion.py -- \
  dist/blend_my_bot-0.1.0-blender-5.0-linux-x64.zip
BLENDER_USER_RESOURCES="$PWD/.blender-test-profile" blender --background \
  --factory-startup --python-exit-code 1 --python tests/blender_online.py -- \
  dist/blend_my_bot-0.1.0-blender-5.0-linux-x64.zip
BLENDER_USER_RESOURCES="$PWD/.blender-test-profile" blender --background \
  --factory-startup --python-exit-code 1 --python tests/blender_collada.py -- \
  dist/blend_my_bot-0.1.0-blender-5.0-linux-x64.zip
BLENDER_USER_RESOURCES="$PWD/.blender-test-profile" blender --background \
  --factory-startup --python-exit-code 1 --python tests/blender_materials.py -- \
  dist/blend_my_bot-0.1.0-blender-5.0-linux-x64.zip
```

Use your actual ZIP filename. The smoke test installs the extension into a
temporary repository, imports a test fixture twice, checks geometry and error handling,
tests package discovery and selected-URDF imports, tests the scripting API, and
disables/re-enables the extension.
The motion test checks named-joint mapping, quaternion conventions, exact sample
poses and timing, the final sample, multiple visual parts, long/renamed mesh
names, independent instances, replacement protection, rollback and save/reopen.
It exercises real Blender operators in background mode, not visual GUI playback.
The online test uses local fixtures to verify cached/offline imports, missing Git,
disabled network access, modal progress/cancellation/timeouts, download errors and
extension shutdown without making network requests. Add `--download` after its ZIP
argument and pass `--online-mode` to Blender to download and import the
**Blender-tested** robots, check motion playback, and repeat each import offline.
Catalog tests compare the complete selectable set with the library's URDF
metadata and verify that untested entries are not blocked. Downloads use a
temporary test cache rather than modifying your regular model cache.
The COLLADA test checks units, node transforms, URDF scaling, normals, UV
bindings, materials, packed textures, motion, import rollback and save/reopen
without source assets.
The materials test covers inline/named RGBA colors, OBJ/DAE material precedence,
multipart fallback, independent imports, scripting reuse, malformed materials,
rollback, motion and save/reopen.
Add `--download-dae` to the online test's ZIP argument and pass `--online-mode`
to Blender to test real ANYmal B DAE assets, their packed textures, posed FK,
motion and offline cache reuse.
Use `--download-colors` instead to verify G1's 36 visuals against its source URDF
colors, plus motion and offline reuse.
Use `--download-go2` to test Go2's DAE meshes with zero-length source normals,
posed FK, motion and offline cache reuse.

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
