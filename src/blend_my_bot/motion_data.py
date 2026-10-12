from dataclasses import dataclass
from pathlib import Path

import numpy as np

QUATERNION_NORM_TOLERANCE = 1e-3


def _numeric_array(value, name: str) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.kind not in "fiu" or not np.all(np.isfinite(array)):
        raise ValueError(f"Motion '{name}' must contain finite real numbers")
    return array.astype(float)


@dataclass(frozen=True)
class RobotMotion:
    joints: tuple[str, ...]
    fps: float
    joint_positions: np.ndarray
    root_positions: np.ndarray
    root_quaternions: np.ndarray

    @property
    def samples(self) -> int:
        return len(self.joint_positions)

    @property
    def duration(self) -> float:
        return (self.samples - 1) / self.fps

    def frame_numbers(self, start_frame: int, scene_fps: float) -> np.ndarray:
        if not np.isfinite(scene_fps) or scene_fps <= 0:
            raise ValueError("Scene FPS must be positive and finite")
        return start_frame + np.arange(self.samples) * scene_fps / self.fps

    def base_transforms(self) -> np.ndarray:
        w, x, y, z = self.root_quaternions.T
        matrices = np.broadcast_to(np.eye(4), (self.samples, 4, 4)).copy()
        matrices[:, 0, 0] = 1 - 2 * (y * y + z * z)
        matrices[:, 0, 1] = 2 * (x * y - w * z)
        matrices[:, 0, 2] = 2 * (x * z + w * y)
        matrices[:, 1, 0] = 2 * (x * y + w * z)
        matrices[:, 1, 1] = 1 - 2 * (x * x + z * z)
        matrices[:, 1, 2] = 2 * (y * z - w * x)
        matrices[:, 2, 0] = 2 * (x * z - w * y)
        matrices[:, 2, 1] = 2 * (y * z + w * x)
        matrices[:, 2, 2] = 1 - 2 * (x * x + y * y)
        matrices[:, :3, 3] = self.root_positions
        return matrices


def parse_motion(data, quaternion_order: str = "WXYZ") -> RobotMotion:
    if not isinstance(data, dict):
        raise ValueError("Motion must be a dictionary saved as a scalar NumPy object")
    required = {
        "joints_list",
        "fps",
        "joint_positions",
        "root_position",
        "root_quaternion",
    }
    missing = required - data.keys()
    if missing:
        raise ValueError(f"Motion is missing fields: {', '.join(sorted(missing))}")
    names = data["joints_list"]
    if (
        not isinstance(names, (list, tuple, np.ndarray))
        or (isinstance(names, np.ndarray) and names.ndim != 1)
        or any(not isinstance(name, str) or not name.strip() for name in names)
    ):
        raise ValueError("Motion 'joints_list' must contain nonempty joint names")
    joints = tuple(names)
    if len(set(joints)) != len(joints):
        raise ValueError("Motion contains duplicate joint names")
    fps_array = _numeric_array(data["fps"], "fps")
    if fps_array.size != 1 or fps_array.ndim > 1 or fps_array.item() <= 0:
        raise ValueError("Motion 'fps' must be a single positive number")
    fps = float(fps_array.item())
    positions = _numeric_array(data["joint_positions"], "joint_positions")
    if positions.ndim != 2 or positions.shape[1] != len(joints) or not len(positions):
        raise ValueError("Motion 'joint_positions' must have shape (samples, joints)")
    root_positions = _numeric_array(data["root_position"], "root_position")
    quaternions = _numeric_array(data["root_quaternion"], "root_quaternion")
    if root_positions.shape != (len(positions), 3):
        raise ValueError("Motion 'root_position' must have shape (samples, 3)")
    if quaternions.shape != (len(positions), 4):
        raise ValueError("Motion 'root_quaternion' must have shape (samples, 4)")
    if quaternion_order == "XYZW":
        quaternions = quaternions[:, [3, 0, 1, 2]]
    elif quaternion_order != "WXYZ":
        raise ValueError("Quaternion order must be WXYZ or XYZW")
    norms = np.linalg.norm(quaternions, axis=1)
    if np.any(np.abs(norms - 1) > QUATERNION_NORM_TOLERANCE):
        raise ValueError("Motion root quaternions must be unit length")
    quaternions /= norms[:, None]
    motion = RobotMotion(joints, fps, positions, root_positions, quaternions)
    if "duration" in data:
        duration = _numeric_array(data["duration"], "duration")
        if duration.size != 1 or not np.isclose(
            duration.item(), motion.duration, atol=1e-4, rtol=1e-5
        ):
            raise ValueError("Motion duration does not match (samples - 1) / fps")
    return motion


def load_motion(
    path: str | Path, *, trusted: bool = False, quaternion_order: str = "WXYZ"
) -> RobotMotion:
    if not trusted:
        raise ValueError(
            "Confirm that you trust this motion file: NumPy object files use "
            "pickle and can execute Python code"
        )
    path = Path(path)
    if path.suffix.lower() != ".npy":
        raise ValueError("Select a .npy motion file")
    try:
        array = np.load(path, allow_pickle=True)
    except ImportError as error:
        raise ValueError(
            f"Motion pickle needs an unavailable module ({error}); export it "
            "with a NumPy version compatible with this Blender runtime"
        ) from error
    if (
        not isinstance(array, np.ndarray)
        or array.shape != ()
        or not array.dtype.hasobject
    ):
        raise ValueError("Motion must be a dictionary saved as a scalar NumPy object")
    return parse_motion(array.item(), quaternion_order)
