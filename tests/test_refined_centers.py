"""Offline, no-robot regression tests for refined IFC wall-center generation.

Run from the repository root:
    python -m unittest discover -s tests -p 'test_refined_centers.py' -v

These tests never import ROS or issue robot motion commands.
"""
import math
import unittest
from pathlib import Path

import refined_ifc_to_robot_with_inward_stage3 as generator


REPO_ROOT = Path(__file__).resolve().parents[1]


class RefinedCenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ifc_path = REPO_ROOT / generator.DEFAULT_IFC_FILE
        cls.centers_path = REPO_ROOT / generator.DEFAULT_REFERENCE_CENTERS
        if not cls.ifc_path.exists():
            raise unittest.SkipTest(f"IFC fixture is unavailable: {cls.ifc_path}")
        if not cls.centers_path.exists():
            raise unittest.SkipTest(f"Calibration centers are unavailable: {cls.centers_path}")

        cls.model = generator.IfcStepModel(cls.ifc_path)
        cls.walls = cls.model.extract_walls("Basic Wall:BSS.50:")
        cls.references = generator.load_reference_centers(cls.centers_path)

    def test_six_ifc_walls_exist_and_mappings_are_unique(self):
        self.assertEqual(len(generator.WALL_TAG_ORDER), 6)
        self.assertEqual(len(set(generator.WALL_TAG_ORDER)), 6)
        self.assertEqual(
            set(generator.WALL_TAG_ORDER),
            set(generator.WALL_MAPPING.values()),
        )
        for tag in generator.WALL_TAG_ORDER:
            self.assertIn(tag, self.walls)

    def test_stage_generation_and_quaternion_norms(self):
        stage1, stage2, stage3, report = generator.generate_stages(
            self.walls, self.references
        )
        expected = {f"wall_{n}" for n in range(1, 7)}
        self.assertEqual(set(stage1), expected)
        self.assertEqual(set(stage2), expected)
        self.assertEqual(set(stage3), expected)
        self.assertEqual(stage1, stage2)
        for stage in (stage1, stage2, stage3):
            for wall, pose in stage.items():
                self.assertAlmostEqual(
                    pose["z"], generator.DEFAULT_ROBOT_Z_M, places=9
                )
                self.assertAlmostEqual(
                    sum(pose[q] ** 2 for q in ("qx", "qy", "qz", "qw")),
                    1.0, places=7,
                    msg=f"Quaternion is not normalized for {wall}",
                )
                for key in ("x", "y", "z", "qx", "qy", "qz", "qw"):
                    self.assertTrue(math.isfinite(pose[key]), (wall, key))
        wall_reports = [item for item in report if "wall" in item]
        self.assertEqual(len(wall_reports), 6)
        for item in wall_reports:
            for key in (
                "ifc_length_mm",
                "stage_3_center_shift_mm",
                "stage_3_trim_start_mm",
                "stage_3_trim_end_mm",
                "stage_3_usable_length_mm",
            ):
                self.assertIn(key, item)
            self.assertAlmostEqual(
                item["stage_3_center_shift_mm"],
                (item["stage_3_trim_start_mm"] - item["stage_3_trim_end_mm"]) / 2,
            )

    def test_trimmed_wall_midpoint_and_invalid_trim(self):
        wall = next(iter(self.walls.values()))
        trim = min(wall.length_mm / 10, 20)
        _, _, midpoint, length = generator.trimmed_wall_geometry(
            wall, trim_start_mm=trim, trim_end_mm=trim
        )
        self.assertAlmostEqual(length, wall.length_mm - 2 * trim)
        self.assertAlmostEqual(midpoint[0], wall.midpoint_mm[0], places=6)
        self.assertAlmostEqual(midpoint[1], wall.midpoint_mm[1], places=6)
        with self.assertRaises(ValueError):
            generator.trimmed_wall_geometry(
                wall, trim_start_mm=wall.length_mm, trim_end_mm=0
            )


if __name__ == "__main__":
    unittest.main()
