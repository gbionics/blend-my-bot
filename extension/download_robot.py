"""Isolated download entry point, launched using Blender's bundled Python."""

from pathlib import Path
import sys


def main():
    extension = Path(__file__).resolve().parent
    sys.path[:0] = [str(path) for path in sorted((extension / "wheels").glob("*.whl"))]
    sys.path.insert(0, str(extension / "blend_my_bot"))
    from online_catalog import download_robot
    from urdf_paths import resolved_urdf

    identifier, destination = sys.argv[sys.argv.index("--") + 1 :]
    directory = Path(destination)
    directory.mkdir()
    robot = download_robot(identifier, directory)
    with resolved_urdf(robot.urdf_path, robot.search_paths):
        pass


if __name__ == "__main__":
    main()
