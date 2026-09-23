#!/usr/bin/env python3
"""
Refined IFC -> Stage 1 / Stage 2 / Stage 3 centers.json generator.

What this version fixes
-----------------------
1. Reads the six BSS.50 walls directly from the IFC.
2. Calculates each center as:
       start + 0.5 * wall_length * wall_direction
3. Keeps Stage 1 and Stage 2 identical.
4. Stage 3 reduces the usable wall length along the wall direction.
   It does NOT blindly shift every wall sideways by 20 mm.
5. Allows different start/end trims for each wall.
6. Applies one configurable IFC-to-robot rigid transformation.
7. Generates x, y, z, qx, qy, qz, qw for every wall.

Important Stage 3 rule
----------------------
If equal finish thickness is removed from both ends:

    trim_start = trim_end

the midpoint does not move.

If only one end is reduced, the midpoint moves by half of the difference:

    center_shift = (trim_start - trim_end) / 2

along the wall direction.

The IFC used by default:
    TERRAHL2-FP-MB-T1am(JMB)27-8-2025.ifc
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ============================================================
# Project configuration
# ============================================================

DEFAULT_IFC_FILE = "TERRAHL2-FP-MB-T1am(JMB)27-8-2025.ifc"
DEFAULT_REFERENCE_CENTERS = "centers.json"

# The six structural walls in the required robot wall order.
# Final wall numbering based on output.xlsx, with the requested swaps:
#
#   wall_2 <-> wall_6
#   wall_3 <-> wall_5
#
# centers.json wall number -> IFC BSS.50 tag:
#   wall_1 -> 1428191   (unchanged)
#   wall_2 -> 1428186   (was wall_6)
#   wall_3 -> 1428187   (was wall_5)
#   wall_4 -> 1428188   (unchanged)
#   wall_5 -> 1428189   (was wall_3)
#   wall_6 -> 1428190   (was wall_2)
WALL_TAG_ORDER = [
    "1428191",
    "1428186",
    "1428187",
    "1428188",
    "1428189",
    "1428190",
]
WALL_MAPPING = {
    "wall_1": "1428191",
    "wall_2": "1428186",
    "wall_3": "1428187",
    "wall_4": "1428188",
    "wall_5": "1428189",
    "wall_6": "1428190",
}
# Stage 3 end reductions in millimetres.
#
# These values are deliberately explicit because the IFC contains:
# - six structural BSS.50 walls;
# - five main finish runs plus one split finish run;
# - openings and irregular finish extents.
#
# Do not assume every wall loses 20 mm at both ends.
#
# Format:
#     wall tag: (trim_from_start_mm, trim_from_end_mm)
#
# Equal values keep the midpoint unchanged.
# Unequal values move the midpoint along the wall tangent.
STAGE3_TRIMS_MM: dict[str, tuple[float, float]] = {
    "1428191": (0.0, 0.0),    # centers.json wall_1, 2800 mm
    "1428186": (50.0, 50.0),  # centers.json wall_2, 1932 -> 1832 mm
    "1428187": (25.0, 25.0),  # centers.json wall_3, 1890 -> 1840 mm
    "1428188": (0.0, 0.0),    # centers.json wall_4, 592 mm
    "1428189": (0.0, 0.0),    # centers.json wall_5, 960 mm
    "1428190": (25.0, 25.0),  # centers.json wall_6, 1290 -> 1240 mm
}

# Robot coordinate calibration.
#
# IFC coordinates are millimetres. Output coordinates are metres.
#
# robot_xy = rotate(ifc_xy - IFC_ORIGIN_MM, ROBOT_FRAME_YAW_DEG)
#            + ROBOT_ORIGIN_M
#
# Set these values using the robot's known reference point.
# The robot transform is calibrated from centers.json.
# We keep the known axis relationship:
#
#   robot_x = -ifc_y + tx
#   robot_y = -ifc_x + ty
#
# tx and ty are solved from selected matching IFC/robot wall centres.
CALIBRATION_WALLS = ("wall_1", "wall_2", "wall_3")

# Stage 3 moves toward the room interior by this distance.
STAGE3_INWARD_OFFSET_M = 0.020

# Robot wall orientation adjustment.
#
# 0 degrees:
#     quaternion follows the IFC wall tangent.
#
# 90 or -90 degrees:
#     use when the robot tool should face the wall normal instead.
ROBOT_TOOL_YAW_OFFSET_DEG = 0.0

# Output working height.
#
# The IFC wall geometry starts below level in this model, while the prior
# centers.json used a fixed robot working height of 1.0 m.
DEFAULT_ROBOT_Z_M = 1.0


# ============================================================
# Data classes
# ============================================================

@dataclass(frozen=True)
class Transform2D:
    """2D rigid transform represented by rotation and translation."""

    r00: float
    r01: float
    r10: float
    r11: float
    tx: float
    ty: float

    @staticmethod
    def identity() -> "Transform2D":
        return Transform2D(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    @staticmethod
    def from_origin_and_x_axis(
        origin: tuple[float, float],
        x_axis: tuple[float, float],
    ) -> "Transform2D":
        dx, dy = x_axis
        magnitude = math.hypot(dx, dy)
        if magnitude <= 1e-12:
            raise ValueError("Placement X-axis has zero magnitude.")

        dx /= magnitude
        dy /= magnitude

        # Local Y is perpendicular to local X.
        return Transform2D(
            r00=dx,
            r01=-dy,
            r10=dy,
            r11=dx,
            tx=origin[0],
            ty=origin[1],
        )

    def apply(self, point: tuple[float, float]) -> tuple[float, float]:
        x, y = point
        return (
            self.r00 * x + self.r01 * y + self.tx,
            self.r10 * x + self.r11 * y + self.ty,
        )

    def rotate_vector(
        self,
        vector: tuple[float, float],
    ) -> tuple[float, float]:
        x, y = vector
        return (
            self.r00 * x + self.r01 * y,
            self.r10 * x + self.r11 * y,
        )

    def compose(self, child: "Transform2D") -> "Transform2D":
        """Return self ∘ child."""
        return Transform2D(
            r00=self.r00 * child.r00 + self.r01 * child.r10,
            r01=self.r00 * child.r01 + self.r01 * child.r11,
            r10=self.r10 * child.r00 + self.r11 * child.r10,
            r11=self.r10 * child.r01 + self.r11 * child.r11,
            tx=self.r00 * child.tx + self.r01 * child.ty + self.tx,
            ty=self.r10 * child.tx + self.r11 * child.ty + self.ty,
        )


@dataclass(frozen=True)
class IfcWall:
    entity_id: int
    tag: str
    name: str

    start_mm: tuple[float, float]
    end_mm: tuple[float, float]

    direction: tuple[float, float]
    length_mm: float
    yaw_rad: float

    @property
    def midpoint_mm(self) -> tuple[float, float]:
        return point_along_wall(
            self.start_mm,
            self.direction,
            self.length_mm / 2.0,
        )


# ============================================================
# IFC STEP parser
# ============================================================

class IfcStepModel:
    """
    Minimal IFC2X3 STEP parser for the geometry used by this file.

    This intentionally avoids a dependency on IfcOpenShell.
    It supports:
      - IFCCARTESIANPOINT
      - IFCDIRECTION
      - IFCAXIS2PLACEMENT3D
      - IFCLOCALPLACEMENT
      - IFCPOLYLINE
      - IFCSHAPEREPRESENTATION
      - IFCPRODUCTDEFINITIONSHAPE
      - IFCWALL / IFCWALLSTANDARDCASE
    """

    ENTITY_PATTERN = re.compile(
        r"#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*?)\)\s*;",
        flags=re.IGNORECASE | re.DOTALL,
    )

    def __init__(self, path: Path) -> None:
        self.path = path
        self.text = self._read_text(path)
        self.entities: dict[int, tuple[str, str]] = {}

        for match in self.ENTITY_PATTERN.finditer(self.text):
            entity_id = int(match.group(1))
            entity_type = match.group(2).upper()
            arguments = match.group(3)
            self.entities[entity_id] = (entity_type, arguments)

        if not self.entities:
            raise ValueError(f"No IFC STEP entities found in: {path}")

        self._placement_cache: dict[int, Transform2D] = {}

    @staticmethod
    def _read_text(path: Path) -> str:
        for encoding in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue

        raise ValueError(f"Unable to decode IFC file: {path}")

    @staticmethod
    def split_top_level(arguments: str) -> list[str]:
        values: list[str] = []
        current: list[str] = []
        depth = 0
        in_string = False
        index = 0

        while index < len(arguments):
            character = arguments[index]

            if character == "'":
                current.append(character)

                # STEP escapes an apostrophe as two apostrophes.
                if in_string and index + 1 < len(arguments):
                    if arguments[index + 1] == "'":
                        current.append(arguments[index + 1])
                        index += 2
                        continue

                in_string = not in_string

            elif not in_string and character == "(":
                depth += 1
                current.append(character)

            elif not in_string and character == ")":
                depth -= 1
                current.append(character)

            elif not in_string and depth == 0 and character == ",":
                values.append("".join(current).strip())
                current = []

            else:
                current.append(character)

            index += 1

        values.append("".join(current).strip())
        return values

    @staticmethod
    def parse_reference(value: str) -> int | None:
        match = re.fullmatch(r"#(\d+)", value.strip())
        return int(match.group(1)) if match else None

    @staticmethod
    def parse_references(value: str) -> list[int]:
        return [int(item) for item in re.findall(r"#(\d+)", value)]

    @staticmethod
    def parse_numbers(value: str) -> list[float]:
        pattern = r"[-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?"
        return [float(number) for number in re.findall(pattern, value)]

    @staticmethod
    def parse_step_string(value: str) -> str:
        value = value.strip()
        if value == "$":
            return ""
        if value.startswith("'") and value.endswith("'"):
            return value[1:-1].replace("''", "'")
        return value

    def entity(self, entity_id: int) -> tuple[str, str]:
        try:
            return self.entities[entity_id]
        except KeyError as error:
            raise KeyError(f"IFC entity #{entity_id} does not exist.") from error

    def cartesian_point(self, entity_id: int) -> tuple[float, float]:
        entity_type, arguments = self.entity(entity_id)
        if entity_type != "IFCCARTESIANPOINT":
            raise TypeError(
                f"Expected IFCCARTESIANPOINT at #{entity_id}, "
                f"found {entity_type}."
            )

        coordinates = self.parse_numbers(arguments)
        if len(coordinates) < 2:
            raise ValueError(
                f"IFCCARTESIANPOINT #{entity_id} has fewer than 2 coordinates."
            )

        return coordinates[0], coordinates[1]

    def direction(self, entity_id: int) -> tuple[float, float]:
        entity_type, arguments = self.entity(entity_id)
        if entity_type != "IFCDIRECTION":
            raise TypeError(
                f"Expected IFCDIRECTION at #{entity_id}, found {entity_type}."
            )

        values = self.parse_numbers(arguments)
        if len(values) < 2:
            raise ValueError(
                f"IFCDIRECTION #{entity_id} has fewer than 2 values."
            )

        magnitude = math.hypot(values[0], values[1])
        if magnitude <= 1e-12:
            raise ValueError(f"IFCDIRECTION #{entity_id} has zero magnitude.")

        return values[0] / magnitude, values[1] / magnitude

    def axis_placement_3d(self, entity_id: int) -> Transform2D:
        entity_type, arguments = self.entity(entity_id)
        if entity_type != "IFCAXIS2PLACEMENT3D":
            raise TypeError(
                f"Expected IFCAXIS2PLACEMENT3D at #{entity_id}, "
                f"found {entity_type}."
            )

        values = self.split_top_level(arguments)

        location_ref = self.parse_reference(values[0])
        if location_ref is None:
            raise ValueError(
                f"IFCAXIS2PLACEMENT3D #{entity_id} has no location."
            )

        origin = self.cartesian_point(location_ref)

        # Argument 2 is the Z axis. Argument 3 is the local X direction.
        ref_direction_ref = (
            self.parse_reference(values[2])
            if len(values) >= 3
            else None
        )

        x_axis = (
            self.direction(ref_direction_ref)
            if ref_direction_ref is not None
            else (1.0, 0.0)
        )

        return Transform2D.from_origin_and_x_axis(origin, x_axis)

    def local_placement(self, entity_id: int) -> Transform2D:
        if entity_id in self._placement_cache:
            return self._placement_cache[entity_id]

        entity_type, arguments = self.entity(entity_id)
        if entity_type != "IFCLOCALPLACEMENT":
            raise TypeError(
                f"Expected IFCLOCALPLACEMENT at #{entity_id}, "
                f"found {entity_type}."
            )

        values = self.split_top_level(arguments)

        parent_ref = self.parse_reference(values[0])
        relative_ref = self.parse_reference(values[1])

        if relative_ref is None:
            raise ValueError(
                f"IFCLOCALPLACEMENT #{entity_id} has no relative placement."
            )

        relative_transform = self.axis_placement_3d(relative_ref)

        if parent_ref is None:
            result = relative_transform
        else:
            parent_transform = self.local_placement(parent_ref)
            result = parent_transform.compose(relative_transform)

        self._placement_cache[entity_id] = result
        return result

    def axis_endpoints_local(
        self,
        product_shape_id: int,
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        entity_type, arguments = self.entity(product_shape_id)
        if entity_type != "IFCPRODUCTDEFINITIONSHAPE":
            raise TypeError(
                f"Expected IFCPRODUCTDEFINITIONSHAPE at #{product_shape_id}, "
                f"found {entity_type}."
            )

        values = self.split_top_level(arguments)
        representation_refs = self.parse_references(values[2])

        for representation_ref in representation_refs:
            rep_type, rep_arguments = self.entity(representation_ref)
            if rep_type != "IFCSHAPEREPRESENTATION":
                continue

            rep_values = self.split_top_level(rep_arguments)
            representation_identifier = self.parse_step_string(rep_values[1])

            if representation_identifier.lower() != "axis":
                continue

            item_refs = self.parse_references(rep_values[3])
            for item_ref in item_refs:
                item_type, item_arguments = self.entity(item_ref)
                if item_type != "IFCPOLYLINE":
                    continue

                point_refs = self.parse_references(item_arguments)
                if len(point_refs) < 2:
                    continue

                start = self.cartesian_point(point_refs[0])
                end = self.cartesian_point(point_refs[-1])
                return start, end

        raise ValueError(
            f"No Axis/Polyline representation found for "
            f"IFCPRODUCTDEFINITIONSHAPE #{product_shape_id}."
        )

    def extract_walls(
        self,
        name_fragment: str,
    ) -> dict[str, IfcWall]:
        result: dict[str, IfcWall] = {}

        for entity_id, (entity_type, arguments) in self.entities.items():
            if entity_type not in {"IFCWALL", "IFCWALLSTANDARDCASE"}:
                continue

            values = self.split_top_level(arguments)
            if len(values) < 8:
                continue

            name = self.parse_step_string(values[2])
            if name_fragment.lower() not in name.lower():
                continue

            placement_ref = self.parse_reference(values[5])
            shape_ref = self.parse_reference(values[6])
            tag = self.parse_step_string(values[7])

            if placement_ref is None or shape_ref is None or not tag:
                continue

            placement = self.local_placement(placement_ref)
            local_start, local_end = self.axis_endpoints_local(shape_ref)

            start = placement.apply(local_start)
            end = placement.apply(local_end)

            delta_x = end[0] - start[0]
            delta_y = end[1] - start[1]
            length = math.hypot(delta_x, delta_y)

            if length <= 1e-9:
                raise ValueError(f"Wall {tag} has zero axis length.")

            direction = delta_x / length, delta_y / length
            yaw = math.atan2(direction[1], direction[0])

            result[tag] = IfcWall(
                entity_id=entity_id,
                tag=tag,
                name=name,
                start_mm=start,
                end_mm=end,
                direction=direction,
                length_mm=length,
                yaw_rad=yaw,
            )

        return result


# ============================================================
# Geometry and robot conversion
# ============================================================

def point_along_wall(
    start: tuple[float, float],
    direction: tuple[float, float],
    distance: float,
) -> tuple[float, float]:
    return (
        start[0] + distance * direction[0],
        start[1] + distance * direction[1],
    )


def trimmed_wall_geometry(
    wall: IfcWall,
    trim_start_mm: float,
    trim_end_mm: float,
) -> tuple[
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
    float,
]:
    """
    Return trimmed start, trimmed end, midpoint and usable length.

    The midpoint is calculated using half of the usable wall length:

        trimmed_midpoint =
            trimmed_start + 0.5 * usable_length * direction
    """
    if trim_start_mm < 0 or trim_end_mm < 0:
        raise ValueError(f"Negative trim is not allowed for wall {wall.tag}.")

    usable_length = wall.length_mm - trim_start_mm - trim_end_mm
    if usable_length <= 0:
        raise ValueError(
            f"Stage 3 trims remove the whole wall {wall.tag}: "
            f"{wall.length_mm:.3f} - {trim_start_mm:.3f} "
            f"- {trim_end_mm:.3f} mm"
        )

    trimmed_start = point_along_wall(
        wall.start_mm,
        wall.direction,
        trim_start_mm,
    )

    trimmed_end = point_along_wall(
        wall.end_mm,
        wall.direction,
        -trim_end_mm,
    )

    midpoint = point_along_wall(
        trimmed_start,
        wall.direction,
        usable_length / 2.0,
    )

    return trimmed_start, trimmed_end, midpoint, usable_length


def load_reference_centers(path: Path) -> dict[str, dict[str, float]]:
    data = json.loads(path.read_text(encoding="utf-8"))

    for wall_name in WALL_MAPPING:
        if wall_name not in data:
            raise ValueError(f"Reference centers is missing {wall_name}.")

    return data


def solve_robot_translation(
    ifc_midpoints_m: dict[str, tuple[float, float]],
    reference_centers: dict[str, dict[str, float]],
) -> tuple[float, float]:
    """
    Solve the translation for the known IFC-to-robot axis conversion:

        robot_x = -ifc_y + tx
        robot_y = -ifc_x + ty

    centers.json is used only as calibration data. The generated positions
    still come from IFC wall midpoints.
    """
    tx_samples: list[float] = []
    ty_samples: list[float] = []

    for wall_name in CALIBRATION_WALLS:
        ifc_x, ifc_y = ifc_midpoints_m[wall_name]
        target = reference_centers[wall_name]

        tx_samples.append(float(target["x"]) + ifc_y)
        ty_samples.append(float(target["y"]) + ifc_x)

    return (
        sum(tx_samples) / len(tx_samples),
        sum(ty_samples) / len(ty_samples),
    )


def ifc_point_to_robot(
    point_mm: tuple[float, float],
    tx: float,
    ty: float,
) -> tuple[float, float]:
    ifc_x = point_mm[0] / 1000.0
    ifc_y = point_mm[1] / 1000.0

    return (
        -ifc_y + tx,
        -ifc_x + ty,
    )


def ifc_yaw_to_robot_yaw(ifc_yaw_rad: float) -> float:
    """
    Vector transformation for:

        robot_x = -ifc_y
        robot_y = -ifc_x

    IFC direction (dx, dy) becomes robot direction (-dy, -dx).
    """
    dx = math.cos(ifc_yaw_rad)
    dy = math.sin(ifc_yaw_rad)

    robot_dx = -dy
    robot_dy = -dx

    return math.atan2(robot_dy, robot_dx)


def yaw_to_quaternion(yaw_rad: float) -> tuple[float, float, float, float]:
    return (
        0.0,
        0.0,
        math.sin(yaw_rad / 2.0),
        math.cos(yaw_rad / 2.0),
    )


def room_centroid(
    points: list[tuple[float, float]],
) -> tuple[float, float]:
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def inward_normal(
    wall_point: tuple[float, float],
    wall_yaw: float,
    centroid: tuple[float, float],
) -> tuple[float, float]:
    """
    Choose the wall normal that points toward the room centroid.
    """
    left = (-math.sin(wall_yaw), math.cos(wall_yaw))
    right = (math.sin(wall_yaw), -math.cos(wall_yaw))

    to_center = (
        centroid[0] - wall_point[0],
        centroid[1] - wall_point[1],
    )

    left_score = left[0] * to_center[0] + left[1] * to_center[1]
    right_score = right[0] * to_center[0] + right[1] * to_center[1]

    return left if left_score >= right_score else right


def make_pose(
    midpoint_mm: tuple[float, float],
    wall_yaw_rad: float,
    tx: float,
    ty: float,
    inward_offset_m: float = 0.0,
    centroid: tuple[float, float] | None = None,
) -> dict[str, float]:
    robot_x, robot_y = ifc_point_to_robot(midpoint_mm, tx, ty)
    robot_yaw = ifc_yaw_to_robot_yaw(wall_yaw_rad)

    if inward_offset_m != 0.0:
        if centroid is None:
            raise ValueError("Centroid is required for inward offset.")

        nx, ny = inward_normal(
            (robot_x, robot_y),
            robot_yaw,
            centroid,
        )

        robot_x += inward_offset_m * nx
        robot_y += inward_offset_m * ny

    qx, qy, qz, qw = yaw_to_quaternion(robot_yaw)

    return {
        "x": clean_number(robot_x),
        "y": clean_number(robot_y),
        "z": clean_number(DEFAULT_ROBOT_Z_M),
        "qx": clean_number(qx),
        "qy": clean_number(qy),
        "qz": clean_number(qz),
        "qw": clean_number(qw),
    }

def clean_number(value: float, digits: int = 9) -> float:
    rounded = round(float(value), digits)
    return 0.0 if abs(rounded) < 10 ** (-digits) else rounded


def make_pose(
    midpoint_mm: tuple[float, float],
    wall_yaw_rad: float,
) -> dict[str, float]:
    robot_x, robot_y = ifc_point_to_robot(midpoint_mm)
    robot_yaw = ifc_yaw_to_robot_yaw(wall_yaw_rad)
    qx, qy, qz, qw = yaw_to_quaternion(robot_yaw)

    return {
        "x": clean_number(robot_x),
        "y": clean_number(robot_y),
        "z": clean_number(DEFAULT_ROBOT_Z_M),
        "qx": clean_number(qx),
        "qy": clean_number(qy),
        "qz": clean_number(qz),
        "qw": clean_number(qw),
    }


# ============================================================
# Stage generation
# ============================================================

def generate_stages(
    structural_walls: dict[str, IfcWall],
    reference_centers: dict[str, dict[str, float]],
) -> tuple[
    dict[str, dict[str, float]],
    dict[str, dict[str, float]],
    dict[str, dict[str, float]],
    list[dict[str, Any]],
]:
    wall_objects: dict[str, IfcWall] = {}

    for wall_number, wall_tag in enumerate(WALL_TAG_ORDER, start=1):
        wall_name = f"wall_{wall_number}"

        if wall_tag not in structural_walls:
            raise ValueError(
                f"Required structural wall tag {wall_tag} was not found."
            )

        wall_objects[wall_name] = structural_walls[wall_tag]

    # IFC midpoints are authoritative.
    ifc_midpoints_m = {
        wall_name: (
            wall.midpoint_mm[0] / 1000.0,
            wall.midpoint_mm[1] / 1000.0,
        )
        for wall_name, wall in wall_objects.items()
    }

    # centers.json is used only to calibrate tx and ty.
    tx, ty = solve_robot_translation(
        ifc_midpoints_m,
        reference_centers,
    )

    stage_1: dict[str, dict[str, float]] = {}
    stage_2: dict[str, dict[str, float]] = {}
    stage_3: dict[str, dict[str, float]] = {}
    report: list[dict[str, Any]] = []

    # First calculate Stage 1 robot positions.
    for wall_name, wall in wall_objects.items():
        pose = make_pose(
            wall.midpoint_mm,
            wall.yaw_rad,
            tx,
            ty,
        )

        stage_1[wall_name] = dict(pose)
        stage_2[wall_name] = dict(pose)

    centroid = room_centroid(
        [
            (pose["x"], pose["y"])
            for pose in stage_1.values()
        ]
    )

    # Stage 3 applies along-wall trims, then a 20 mm inward normal offset.
    for wall_name, wall in wall_objects.items():
        trim_start, trim_end = STAGE3_TRIMS_MM.get(
            wall.tag,
            (0.0, 0.0),
        )

        (
            stage3_start,
            stage3_end,
            stage3_midpoint,
            stage3_length,
        ) = trimmed_wall_geometry(
            wall,
            trim_start_mm=trim_start,
            trim_end_mm=trim_end,
        )

        stage_3[wall_name] = make_pose(
            stage3_midpoint,
            wall.yaw_rad,
            tx,
            ty,
            inward_offset_m=STAGE3_INWARD_OFFSET_M,
            centroid=centroid,
        )

        report.append(
            {
                "wall": wall_name,
                "ifc_tag": wall.tag,
                "ifc_entity": f"#{wall.entity_id}",
                "ifc_midpoint_mm": [
                    clean_number(wall.midpoint_mm[0], 6),
                    clean_number(wall.midpoint_mm[1], 6),
                ],
                "stage_1_robot": stage_1[wall_name],
                "stage_3_trim_start_mm": trim_start,
                "stage_3_trim_end_mm": trim_end,
                "stage_3_usable_length_mm": clean_number(
                    stage3_length,
                    6,
                ),
                "stage_3_robot": stage_3[wall_name],
            }
        )

    report.insert(
        0,
        {
            "calibration": {
                "formula": {
                    "robot_x": "-ifc_y + tx",
                    "robot_y": "-ifc_x + ty",
                },
                "walls": list(CALIBRATION_WALLS),
                "tx": clean_number(tx),
                "ty": clean_number(ty),
                "stage_3_inward_offset_m": STAGE3_INWARD_OFFSET_M,
            }
        },
    )

    return stage_1, stage_2, stage_3, report

def write_json(path: Path, content: Any) -> None:
    path.write_text(
        json.dumps(content, indent=4) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate Stage 1, Stage 2 and Stage 3 centers.json "
            "directly from the six BSS.50 IFC walls."
        )
    )
    parser.add_argument(
        "--ifc",
        type=Path,
        default=Path(DEFAULT_IFC_FILE),
        help=f"IFC input file. Default: {DEFAULT_IFC_FILE}",
    )
    parser.add_argument(
        "--reference-centers",
        type=Path,
        default=Path(DEFAULT_REFERENCE_CENTERS),
        help="centers.json used only to calibrate the robot transform.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("generated_centers"),
        help="Directory for generated JSON files.",
    )
    args = parser.parse_args()

    if not args.ifc.is_file():
        raise FileNotFoundError(f"IFC file not found: {args.ifc}")

    if not args.reference_centers.is_file():
        raise FileNotFoundError(
            f"Reference centers not found: {args.reference_centers}"
        )

    model = IfcStepModel(args.ifc)
    structural_walls = model.extract_walls("Basic Wall:BSS.50:")
    reference_centers = load_reference_centers(
        args.reference_centers
    )

    missing_tags = [
        tag for tag in WALL_TAG_ORDER
        if tag not in structural_walls
    ]
    if missing_tags:
        raise ValueError(
            f"Missing required IFC wall tags: {missing_tags}"
        )

    stage_1, stage_2, stage_3, report = generate_stages(
        structural_walls,
        reference_centers,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    stage_1_path = args.output_dir / "stage_1_centers.json"
    stage_2_path = args.output_dir / "stage_2_centers.json"
    stage_3_path = args.output_dir / "stage_3_centers.json"
    report_path = args.output_dir / "wall_center_report.json"

    write_json(stage_1_path, stage_1)
    write_json(stage_2_path, stage_2)
    write_json(stage_3_path, stage_3)
    write_json(report_path, report)

    print(f"IFC file: {args.ifc.resolve()}")
    print()
    print("Generated:")
    print(f"  {stage_1_path.resolve()}")
    print(f"  {stage_2_path.resolve()}")
    print(f"  {stage_3_path.resolve()}")
    print(f"  {report_path.resolve()}")
    print()
    print("Wall summary:")

    for row in report:
        print(
            f"  {row['wall']} / IFC {row['ifc_tag']}: "
            f"length={row['ifc_length_mm']:.3f} mm, "
            f"trim=({row['stage_3_trim_start_mm']:.3f}, "
            f"{row['stage_3_trim_end_mm']:.3f}) mm, "
            f"usable={row['stage_3_usable_length_mm']:.3f} mm, "
            f"center shift={row['stage_3_center_shift_mm']} mm"
        )


if __name__ == "__main__":
    main()