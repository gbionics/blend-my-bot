import importlib.util
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "motion_data", ROOT / "src" / "blend_my_bot" / "motion_data.py"
)
motion_data = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = motion_data
spec.loader.exec_module(motion_data)


def sample_data():
    return {
        "joints_list": ["second", "first"],
        "fps": np.array([50], dtype=np.float32),
        "duration": 0.04,
        "joint_positions": np.array([[0, 0], [0.1, 0.2], [0.2, 0.4]]),
        "root_position": np.array([[0, 0, 1], [0.1, 0, 1], [0.2, 0, 1]]),
        "root_quaternion": np.array([[1, 0, 0, 0]] * 3, dtype=float),
    }


class MotionDataTests(unittest.TestCase):
    def test_named_samples_and_duration_include_last_sample(self):
        motion = motion_data.parse_motion(sample_data())
        self.assertEqual(motion.joints, ("second", "first"))
        self.assertEqual(motion.samples, 3)
        self.assertEqual(motion.fps, 50)
        self.assertAlmostEqual(motion.duration, 0.04)
        np.testing.assert_array_equal(motion.frame_numbers(7, 50), [7, 8, 9])
        np.testing.assert_allclose(
            motion.base_transforms()[:, :3, 3], sample_data()["root_position"]
        )

    def test_scene_fps_preserves_timing_with_fractional_frames(self):
        motion = motion_data.parse_motion(sample_data())
        np.testing.assert_allclose(motion.frame_numbers(1, 24), [1, 1.48, 1.96])
        self.assertAlmostEqual(
            (motion.frame_numbers(1, 24)[-1] - 1) / 24, motion.duration
        )

    def test_both_quaternion_conventions(self):
        data = sample_data()
        data["root_quaternion"][:] = [np.sqrt(0.5), 0, 0, np.sqrt(0.5)]
        motion = motion_data.parse_motion(data)
        expected = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
        np.testing.assert_allclose(
            motion.base_transforms()[0, :3, :3], expected, atol=1e-12
        )
        data["root_quaternion"] = data["root_quaternion"][:, [1, 2, 3, 0]]
        np.testing.assert_allclose(
            motion_data.parse_motion(data, "XYZW").base_transforms(),
            motion.base_transforms(),
        )

    def test_rounding_noise_normalized_without_modifying_input(self):
        for order in ("WXYZ", "XYZW"):
            for scale in (0.9999997, 0.9991, 1.0009):
                with self.subTest(order=order, scale=scale):
                    data = sample_data()
                    expected = np.array(
                        [[0.5, 0.5, 0.5, 0.5], [-1, 0, 0, 0], [0, 1, 0, 0]]
                    )
                    data["root_quaternion"] = expected * scale
                    if order == "XYZW":
                        data["root_quaternion"] = data["root_quaternion"][
                            :, [1, 2, 3, 0]
                        ]
                    original = data["root_quaternion"].copy()
                    motion = motion_data.parse_motion(data, order)
                    np.testing.assert_array_equal(data["root_quaternion"], original)
                    np.testing.assert_allclose(motion.root_quaternions, expected)

    def test_nonunit_quaternions_are_rejected_before_scipy_normalization(self):
        for order in ("WXYZ", "XYZW"):
            for scale in (0.9989, 1.0011):
                with self.subTest(order=order, scale=scale):
                    data = sample_data()
                    data["root_quaternion"] *= scale
                    if order == "XYZW":
                        data["root_quaternion"] = data["root_quaternion"][
                            :, [1, 2, 3, 0]
                        ]
                    with self.assertRaisesRegex(ValueError, "unit length"):
                        motion_data.parse_motion(data, order)

    def test_base_transforms_preserve_mixed_rotations_and_homogeneous_rows(self):
        data = sample_data()
        data["root_quaternion"] = np.array(
            [
                [0.5, 0.5, 0.5, 0.5],
                [-np.sqrt(0.5), 0, -np.sqrt(0.5), 0],
                [0, 1, 0, 0],
            ]
        )
        motion = motion_data.parse_motion(data)
        original = motion.root_quaternions.copy()
        matrices = motion.base_transforms()
        self.assertEqual(matrices.shape, (3, 4, 4))
        np.testing.assert_allclose(
            matrices[:, :3, :3],
            [
                [[0, 0, 1], [1, 0, 0], [0, 1, 0]],
                [[0, 0, 1], [0, 1, 0], [-1, 0, 0]],
                [[1, 0, 0], [0, -1, 0], [0, 0, -1]],
            ],
            atol=1e-12,
        )
        np.testing.assert_array_equal(matrices[:, :3, 3], data["root_position"])
        np.testing.assert_array_equal(matrices[:, 3], [[0, 0, 0, 1]] * 3)
        np.testing.assert_array_equal(motion.root_quaternions, original)

    def test_trust_required_before_deserialization(self):
        with patch.object(motion_data.np, "load") as load:
            with self.assertRaisesRegex(ValueError, "trust"):
                motion_data.load_motion("not_present.npy")
            load.assert_not_called()

    def test_trusted_round_trip(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "motion.npy"
            np.save(path, sample_data())
            loaded = motion_data.load_motion(path, trusted=True)
            self.assertEqual(loaded.samples, 3)
            numeric = Path(directory) / "numeric.npy"
            np.save(numeric, np.zeros((3, 2)))
            with self.assertRaisesRegex(ValueError, "scalar NumPy object"):
                motion_data.load_motion(numeric, trusted=True)

    def test_invalid_schema(self):
        for field in sample_data():
            data = sample_data()
            del data[field]
            if field == "duration":
                motion_data.parse_motion(data)
            else:
                with self.subTest(missing=field), self.assertRaises(ValueError):
                    motion_data.parse_motion(data)
        for field, value in [
            ("joints_list", ["first", "first"]),
            ("joints_list", ["first", ""]),
            ("joints_list", "first"),
            ("joints_list", np.array("first")),
            ("fps", 0),
            ("fps", -50),
            ("fps", [50, 50]),
            ("fps", np.nan),
            ("joint_positions", np.zeros((2, 3))),
            ("joint_positions", np.zeros((0, 2))),
            ("joint_positions", [["text", "text"]] * 3),
            ("joint_positions", np.ones((3, 2), dtype=complex)),
            ("root_position", np.zeros((3, 2))),
            ("root_position", np.full((3, 3), np.inf)),
            ("root_quaternion", np.zeros((3, 4))),
            ("root_quaternion", np.full((3, 4), 2)),
            ("duration", 3),
        ]:
            data = sample_data()
            data[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                motion_data.parse_motion(data)
        with self.assertRaises(ValueError):
            motion_data.parse_motion([])
        with self.assertRaises(ValueError):
            motion_data.parse_motion(sample_data(), "UNKNOWN")
        with self.assertRaises(ValueError):
            motion_data.parse_motion(sample_data()).frame_numbers(1, 0)

    def test_base_only_motion(self):
        data = sample_data()
        data["joints_list"] = []
        data["joint_positions"] = np.empty((3, 0))
        self.assertEqual(motion_data.parse_motion(data).joints, ())

    def test_missing_pickle_dependency_is_actionable(self):
        with patch.object(
            motion_data.np, "load", side_effect=ModuleNotFoundError("numpy._core")
        ):
            with self.assertRaisesRegex(ValueError, "compatible"):
                motion_data.load_motion("motion.npy", trusted=True)


if __name__ == "__main__":
    unittest.main()
