"""
Generate Stage 1, Stage 2 and Stage 3 centers.json files.

Correct coordinate rule
-----------------------
- The IFC is used for wall IDs, wall lengths and Stage 3 reductions.
- The original centers.json is used as the calibrated ROBOT coordinate frame.
- Final generated poses are expressed in the non-mirrored Stage_1/Stage_2/Stage_3 STL frame.
- The STL and robot poses share the same global (0,0,0) origin and axis directions.
- Stage 1 and Stage 2 use the measured non-mirrored STL wall locations.
- Stage 3 moves a center only when start/end reductions are unequal.

Requested IFC mapping
---------------------
Starting from output.xlsx:
    wall_2 <-> wall_6
    wall_3 <-> wall_5

Final mapping:
    wall_1 -> IFC 1428191
    wall_2 -> IFC 1428186
    wall_3 -> IFC 1428187
    wall_4 -> IFC 1428188
    wall_5 -> IFC 1428189
    wall_6 -> IFC 1428190
"""

from __future__ import annotations

import argparse
import json
import math
import re
import matplotlib.pyplot as plt
from copy import deepcopy
from pathlib import Path
from typing import Any
import numpy as np
from matplotlib.animation import FuncAnimation
from mpl_toolkits.mplot3d import Axes3D


DEFAULT_IFC = "TERRAHL2-FP-MB-T1am(JMB)27-8-2025.ifc"
DEFAULT_REFERENCE_CENTERS = "centers.json"
ROOM_HEIGHT_M = 2.8
ROBOT_MARKER_HEIGHT_M = 0.15
WALL_REFERENCE_HEIGHT_ABOVE_FLOOR_M = 1.000
# TerraHill IFC Z coordinates use a 100000 mm project datum.
# Remove this base before converting the floor elevation to robot metres.
IFC_Z_BASE_MM = 100000.0

# Only finished-floor regions inside the PBU are used for Z reference.
# These IFC slabs are identified by their floor-finish naming/geometry,
# not by a hard-coded finished-floor Z value.
PBU_FLOOR_FINISH_NAME = "20mm Floor Finishes"

# Layout rule used only to decide which ONE robot wall point belongs
# to the lower shower floor:
#   door left  -> shower is on the right-most side
#   door right -> shower is on the left-most side
DOOR_SIDE = "left"
PBU_BBOX_TOLERANCE_M = 0.35

WALL_MAPPING = {
    "wall_1": "1428191",
    "wall_2": "1428186",
    "wall_3": "1428187",
    "wall_4": "1428188",
    "wall_5": "1428189",
    "wall_6": "1428190",
}
ROBOT_ROOM_VERTICES = [
    (0.0, 0.0),
    (-1.82, 0.0),
    (-1.82, 1.81),
    (-1.24, 1.81),
    (-1.24, 2.81),
    (0.0, 2.81),
    (0.0, 0.0),
]
# ==========================================================
# Required local +Y direction for each wall.
#
# The GREEN Y arrow must point toward the room interior.
#
# Values are GLOBAL robot XY directions.
# ==========================================================
WALL_INWARD_Y_DIRECTIONS = {
    # bottom wall -> inside is toward negative global X in the original STL frame
    "wall_1": (-1.0,  0.0),

    # left wall -> inside is toward positive global Y
    "wall_2": ( 0.0,  1.0),

    # lower horizontal / shallow wall -> inside toward +X
    "wall_3": ( 1.0,  0.0),

    # vertical step -> inside toward +Y
    "wall_4": ( 0.0,  1.0),

    # upper horizontal wall -> inside toward +X
    "wall_5": ( 1.0,  0.0),

    # right wall -> inside toward negative global Y
    "wall_6": ( 0.0, -1.0),
}
# Stage 3 trimming in millimetres:
# IFC tag: (trim_from_start, trim_from_end)
#
# Equal trimming does not move the midpoint.
STAGE3_TRIMS_MM = {
    "1428191": (0.0, 0.0),
    "1428186": (50.0, 50.0),
    "1428187": (25.0, 25.0),
    "1428188": (0.0, 0.0),
    "1428189": (0.0, 0.0),
    "1428190": (25.0, 25.0),
}
# Stage 3 inward offset in metres.
# 0.040 m = 40 mm.
STAGE3_INWARD_OFFSET_M = 0.040

# Explicit inward directions in the calibrated robot XY frame.
# This is safer than guessing the inward side only from quaternion yaw.
STAGE3_INWARD_DIRECTIONS = {
    "wall_1": (-1.0,  0.0),
    "wall_2": ( 0.0,  1.0),
    "wall_3": ( 1.0,  0.0),
    "wall_4": ( 0.0, -1.0),
    "wall_5": ( 1.0,  0.0),
    "wall_6": ( 0.0, -1.0),
}
REQUIRED_FIELDS = {"x", "y", "z", "qx", "qy", "qz", "qw"}
# Manual robot-frame position refinements.
#
# Only x, y or z values listed here are changed.
# Quaternion orientation remains unchanged.
POSITION_OVERRIDES = {
    "wall_3": {
        # Keep it on the left wall and raise it to the
        # same horizontal level as wall_1 and wall_5.
        "x": -1.82,
        "y": 1.405,
    },

   "wall_5": {
        # Move slightly left so it aligns with the
        # inner vertical wall at x ≈ -1.24.
        "x": -1.24,
        "y": 1.405,
    },
}
#POSITION_OVERRIDES = {
#    "wall_2": {
#        "y": 2.810,
#    },

#    "wall_5": {
#        "x": -1.240,
#    },

#    "wall_4": {
#        "y": 1.900,
 #   },
#}

# ==========================================================
# Right-hand / door-on-right bathroom
# ==========================================================

USE_RIGHT_HAND_LAYOUT = False

# Bathroom overall width in the calibrated robot Y direction.
# Existing calibrated model = approximately 2.81 m.
ROOM_WIDTH_Y_M = 2.81

RIGHT_LAYOUT_PIVOT_X = -1.53
RIGHT_LAYOUT_PIVOT_Y = 1.405
REQUIRED_FIELDS = {"x", "y", "z", "qx", "qy", "qz", "qw"}

# ==========================================================
# Right-hand / door-on-right bathroom
# ==========================================================

USE_RIGHT_HAND_LAYOUT = False
ROOM_WIDTH_M = 2.81
# Bathroom overall width in the calibrated robot Y direction.
# Existing calibrated model = approximately 2.81 m.
ROOM_WIDTH_Y_M = 2.81
ROBOT_ROOM_VERTICES = [
    ( 0.000, 0.000),     # STL origin / inside wall corner
    (-1.832, 0.000),     # deep wall inner face
    (-1.832, 1.840),     # deep-wall / step corner
    (-1.240, 1.840),     # step / shallow-wall corner
    (-1.240, 2.800),     # shallow-wall / top corner
    ( 0.000, 2.800),     # top / origin-side wall corner
    ( 0.000, 0.000),     # close
]
def mirror_xy_right_hand(
    x: float,
    y: float,
) -> tuple[float, float]:
    """
    Mirror the bathroom left/right.

    Robot frame:
        X stays unchanged.
        Y is mirrored across the bathroom width.
    """
    new_x = float(x)
    new_y = ROOM_WIDTH_M - float(y)

    return (
        round(new_x, 6),
        round(new_y, 6),
    )
def get_right_hand_room_vertices() -> list[tuple[float, float]]:
    """
    Mirror the complete room outline using the same
    transformation used for the robot centers.
    """
    mirrored_vertices = []

    for x, y in ROBOT_ROOM_VERTICES:

        new_x, new_y = mirror_xy_right_hand(
            x,
            y,
        )

        mirrored_vertices.append(
            (new_x, new_y)
        )

    return mirrored_vertices
ACTIVE_ROOM_VERTICES = (
    get_right_hand_room_vertices()
    if USE_RIGHT_HAND_LAYOUT
    else ROBOT_ROOM_VERTICES
)
def quaternion_for_inward_y(
    inward_x: float,
    inward_y: float,
) -> tuple[float, float, float, float]:
    """
    Create a yaw-only quaternion such that the robot's
    LOCAL +Y axis points in the requested GLOBAL XY direction.

    For a Z-axis yaw:

        local +X -> ( cos(yaw), sin(yaw) )
        local +Y -> (-sin(yaw), cos(yaw) )

    Therefore, for desired local +Y direction (ix, iy):

        yaw = atan2(-ix, iy)
    """

    length = math.hypot(
        inward_x,
        inward_y,
    )

    if length <= 1e-12:
        raise ValueError(
            "Inward Y direction cannot be zero."
        )

    inward_x /= length
    inward_y /= length

    yaw = math.atan2(
        -inward_x,
        inward_y,
    )

    half_yaw = yaw / 2.0

    qx = 0.0
    qy = 0.0
    qz = math.sin(half_yaw)
    qw = math.cos(half_yaw)

    return qx, qy, qz, qw
def orient_wall_y_axes_inward(
    poses: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """
    Correct every wall quaternion so that its local +Y axis
    points toward the bathroom interior.
    """

    result = deepcopy(poses)

    for wall_name, pose in result.items():

        if wall_name not in WALL_INWARD_Y_DIRECTIONS:
            raise ValueError(
                f"Missing inward Y direction for {wall_name}."
            )

        inward_x, inward_y = (
            WALL_INWARD_Y_DIRECTIONS[wall_name]
        )

        qx, qy, qz, qw = quaternion_for_inward_y(
            inward_x=inward_x,
            inward_y=inward_y,
        )

        pose["qx"] = round(qx, 9)
        pose["qy"] = round(qy, 9)
        pose["qz"] = round(qz, 9)
        pose["qw"] = round(qw, 9)

    return result
def mirror_pose_right_hand(
    pose: dict[str, float],
    room_width_y: float = ROOM_WIDTH_Y_M,
) -> dict[str, float]:
    """
    Mirror a pose horizontally for the right-hand bathroom.

    Robot coordinate convention:
        X = bathroom depth
        Y = bathroom width
        Z = up

    Right-hand mirror:
        y_new = room_width - y_old

    X and Z remain unchanged.

    Quaternion is mirrored separately so that the displayed
    robot axes remain consistent with the mirrored layout.
    """

    result = deepcopy(pose)

    # ------------------------------------------------------
    # Position
    # ------------------------------------------------------
    result["y"] = round(
        float(room_width_y) - float(pose["y"]),
        6,
    )

    return result

def make_right_hand_layout(
    poses: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """
    Mirror all robot centres into the right-hand bathroom.
    """
    result = {}

    for wall_name, pose in poses.items():
        result[wall_name] = mirror_pose_right_hand(
            pose=pose,
            room_width_y=ROOM_WIDTH_Y_M,
        )

    return result
def draw_robot_room_outline(ax: Any) -> None:
    """
    Draw the master-bathroom wall outline in the calibrated robot frame.
    """
    outline_x = [
        point[0]
        for point in ACTIVE_ROOM_VERTICES
    ]

    outline_y = [
        point[1]
        for point in ACTIVE_ROOM_VERTICES
    ]

    ax.plot(
        outline_x,
        outline_y,
        linestyle="--",
        linewidth=1.5,
        label="Room wall outline",
    )
def draw_robot_room_3d(
    ax: Any,
    room_height_m: float = ROOM_HEIGHT_M,
    floor_z_m: float = 0.0,
) -> None:
    """
    Draw the bathroom outline as a simple 3D wall wireframe.

    The lower outline is drawn at the actual main/toilet floor Z read
    from the generated centers JSON. This makes small negative floor
    offsets visible instead of always drawing the room from Z=0.
    """
    vertices = ROBOT_ROOM_VERTICES[:-1]

    floor_z_m = float(floor_z_m)
    ceiling_z_m = floor_z_m + float(room_height_m)

    for z in (floor_z_m, ceiling_z_m):
        xs = [point[0] for point in ROBOT_ROOM_VERTICES]
        ys = [point[1] for point in ROBOT_ROOM_VERTICES]
        zs = [z] * len(ROBOT_ROOM_VERTICES)
        ax.plot(xs, ys, zs, linestyle="--", linewidth=1.5)

    for x, y in vertices:
        ax.plot(
            [x, x],
            [y, y],
            [floor_z_m, ceiling_z_m],
            linewidth=1.0,
        )

def get_pose_x_axis_3d(
    pose: dict[str, float],
    length: float = 0.30,
) -> tuple[float, float, float]:
    """
    Rotate the robot's local positive X-axis by the full quaternion.

    Local robot axis:
        X = forward
        Y = left/right
        Z = up

    Returns the robot X-axis direction in the global XYZ frame.
    """
    qx = float(pose["qx"])
    qy = float(pose["qy"])
    qz = float(pose["qz"])
    qw = float(pose["qw"])

    magnitude = math.sqrt(
        qx * qx
        + qy * qy
        + qz * qz
        + qw * qw
    )

    if magnitude <= 1e-12:
        raise ValueError(
            "Quaternion magnitude cannot be zero."
        )

    qx /= magnitude
    qy /= magnitude
    qz /= magnitude
    qw /= magnitude

    # First column of the quaternion rotation matrix.
    # This is the transformed local positive X-axis.
    direction_x = (
        1.0
        - 2.0 * (
            qy * qy
            + qz * qz
        )
    )

    direction_y = (
        2.0
        * (
            qx * qy
            + qw * qz
        )
    )

    direction_z = (
        2.0
        * (
            qx * qz
            - qw * qy
        )
    )

    return (
        length * direction_x,
        length * direction_y,
        length * direction_z,
    )
def plot_stage_poses_3d(
    poses: dict[str, dict[str, float]],
    output_path: Path,
    title: str,
) -> None:
    """
    Draw the generated centers JSON in 3D and show it interactively.

    The main floor, normal 1 m wall points and the one lower shower
    point are labelled explicitly so a 20-50 mm Z difference is visible.
    """
    fig = plt.figure(figsize=(11, 9))
    ax = fig.add_subplot(111, projection="3d")

    floor_z = float(poses.get("floor", {}).get("z", 0.0))
    draw_robot_room_3d(ax, floor_z_m=floor_z)

    all_x = [point[0] for point in ROBOT_ROOM_VERTICES]
    all_y = [point[1] for point in ROBOT_ROOM_VERTICES]
    all_z = [floor_z, floor_z + ROOM_HEIGHT_M]

    wall_z_values = [
        float(poses[name]["z"])
        for name in WALL_MAPPING
        if name in poses
    ]
    normal_wall_z = max(wall_z_values) if wall_z_values else floor_z + 1.0
    shower_wall_z = min(wall_z_values) if wall_z_values else normal_wall_z

    for pose_name, pose in poses.items():
        x = float(pose["x"])
        y = float(pose["y"])
        z = float(pose["z"])

        all_x.append(x)
        all_y.append(y)
        all_z.append(z)

        is_floor = pose_name == "floor"
        is_shower = (
            pose_name in WALL_MAPPING
            and normal_wall_z - z > 1e-6
            and abs(z - shower_wall_z) <= 1e-6
        )

        ax.scatter([x], [y], [z], s=120 if (is_floor or is_shower) else 90, marker="o", zorder=5)

        axes = get_pose_axes_3d(pose=pose, length=0.30)
        x_axis = axes["x"]
        y_axis = axes["y"]
        z_axis = axes["z"]

        ax.quiver(x, y, z, *x_axis, normalize=False, arrow_length_ratio=0.20, linewidth=3.0, color="red")
        ax.quiver(x, y, z, *y_axis, normalize=False, arrow_length_ratio=0.20, linewidth=2.5, color="green")
        ax.quiver(x, y, z, *z_axis, normalize=False, arrow_length_ratio=0.20, linewidth=2.5, color="blue")

        ax.text(x + x_axis[0], y + x_axis[1], z + x_axis[2], "X", fontsize=9, color="red")
        ax.text(x + y_axis[0], y + y_axis[1], z + y_axis[2], "Y", fontsize=9, color="green")
        ax.text(x + z_axis[0], y + z_axis[1], z + z_axis[2], "Z", fontsize=9, color="blue")

        ax.plot([x, x], [y, y], [floor_z, z], linestyle=":", linewidth=1.0)

        suffix = ""
        if is_floor:
            suffix = "  MAIN FLOOR"
        elif is_shower:
            suffix = "  SHOWER POINT"

        ax.text(
            x, y, z + 0.055,
            f"{pose_name}{suffix}\n({x:.3f}, {y:.3f}, {z:.3f})",
            fontsize=8,
        )

    margin = 0.35
    ax.set_xlim(min(all_x) - margin, max(all_x) + margin)
    ax.set_ylim(min(all_y) - margin, max(all_y) + margin)

    # Include negative floor levels and add enough vertical margin to see them.
    z_min = min(all_z) - 0.12
    z_max = max(max(all_z) + 0.20, floor_z + ROOM_HEIGHT_M + 0.10)
    ax.set_zlim(z_min, z_max)

    ax.set_xlabel("Global X (m)")
    ax.set_ylabel("Global Y (m)")
    ax.set_zlabel("Global Z - Up (m)")
    ax.set_title(
        f"{title}\n"
        f"main floor={floor_z:.3f} m | normal wall={normal_wall_z:.3f} m | "
        f"shower wall={shower_wall_z:.3f} m"
    )

    ax.set_box_aspect((
        max(all_x) - min(all_x),
        max(all_y) - min(all_y),
        ROOM_HEIGHT_M,
    ))
    ax.view_init(elev=28, azim=-60)

    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.show(block=True)
    plt.close(fig)

def get_pose_axes_3d(
    pose: dict[str, float],
    length: float = 0.30,
) -> dict[str, tuple[float, float, float]]:
    """
    Return the rotated local X, Y and Z axes from the pose quaternion.

    Quaternion fields:
        qx, qy, qz, qw

    Output:
        {
            "x": (dx, dy, dz),
            "y": (dx, dy, dz),
            "z": (dx, dy, dz),
        }
    """
    qx = float(pose["qx"])
    qy = float(pose["qy"])
    qz = float(pose["qz"])
    qw = float(pose["qw"])

    magnitude = math.sqrt(
        qx * qx +
        qy * qy +
        qz * qz +
        qw * qw
    )

    if magnitude <= 1e-12:
        raise ValueError("Quaternion magnitude cannot be zero.")

    qx /= magnitude
    qy /= magnitude
    qz /= magnitude
    qw /= magnitude

    # Rotation matrix from quaternion
    r00 = 1.0 - 2.0 * (qy * qy + qz * qz)
    r01 = 2.0 * (qx * qy - qw * qz)
    r02 = 2.0 * (qx * qz + qw * qy)

    r10 = 2.0 * (qx * qy + qw * qz)
    r11 = 1.0 - 2.0 * (qx * qx + qz * qz)
    r12 = 2.0 * (qy * qz - qw * qx)

    r20 = 2.0 * (qx * qz - qw * qy)
    r21 = 2.0 * (qy * qz + qw * qx)
    r22 = 1.0 - 2.0 * (qx * qx + qy * qy)

    return {
        # Columns of the rotation matrix
        "x": (
            length * r00,
            length * r10,
            length * r20,
        ),
        "y": (
            length * r01,
            length * r11,
            length * r21,
        ),
        "z": (
            length * r02,
            length * r12,
            length * r22,
        ),
    }
def apply_position_overrides(
    poses: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """
    Apply calibrated robot-position corrections.

    The quaternion fields are preserved unless an override
    explicitly contains quaternion values.
    """
    corrected = deepcopy(poses)

    for wall_name, override_values in POSITION_OVERRIDES.items():
        if wall_name not in corrected:
            raise ValueError(
                f"Position override refers to unknown wall: {wall_name}"
            )

        for field_name, field_value in override_values.items():
            if field_name not in REQUIRED_FIELDS:
                raise ValueError(
                    f"Invalid override field "
                    f"{field_name!r} for {wall_name}."
                )

            corrected[wall_name][field_name] = float(field_value)

    return corrected

def move_pose_inward(
    wall_name: str,
    base_pose: dict[str, float],
    offset_m: float,
) -> dict[str, float]:
    """
    Move a pose toward the room interior in the calibrated robot XY frame.

    Only x and y change. The complete quaternion is preserved.
    """
    if wall_name not in STAGE3_INWARD_DIRECTIONS:
        raise ValueError(
            f"Missing Stage 3 inward direction for {wall_name}."
        )

    direction_x, direction_y = STAGE3_INWARD_DIRECTIONS[wall_name]
    direction_length = math.hypot(direction_x, direction_y)

    if direction_length <= 1e-12:
        raise ValueError(
            f"Stage 3 inward direction for {wall_name} cannot be zero."
        )

    direction_x /= direction_length
    direction_y /= direction_length

    result = deepcopy(base_pose)
    result["x"] = round(
        float(base_pose["x"]) + float(offset_m) * direction_x,
        6,
    )
    result["y"] = round(
        float(base_pose["y"]) + float(offset_m) * direction_y,
        6,
    )

    return result

def polygon_centroid_xy(
    vertices: list[tuple[float, float]],
) -> tuple[float, float]:
    """Return the area centroid of the room floor polygon."""
    points = list(vertices)
    if len(points) >= 2 and points[0] == points[-1]:
        points = points[:-1]

    if len(points) < 3:
        raise ValueError("Floor polygon requires at least 3 vertices.")

    twice_area = 0.0
    cx_sum = 0.0
    cy_sum = 0.0

    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        cross = x0 * y1 - x1 * y0
        twice_area += cross
        cx_sum += (x0 + x1) * cross
        cy_sum += (y0 + y1) * cross

    if abs(twice_area) <= 1e-12:
        raise ValueError("Floor polygon area is zero.")

    cx = cx_sum / (3.0 * twice_area)
    cy = cy_sum / (3.0 * twice_area)
    return round(cx, 6), round(cy, 6)


def _ifc_world_vertices(entity: Any, geom_settings: Any, ifc_geom: Any) -> list[tuple[float, float, float]]:
    """Return world-space IFC geometry vertices in metres."""
    shape = ifc_geom.create_shape(geom_settings, entity)
    raw = shape.geometry.verts
    return [
        (float(raw[i]), float(raw[i + 1]), float(raw[i + 2]))
        for i in range(0, len(raw), 3)
    ]


def _matches_floor_filter(
    slab: Any,
    floor_guid: str | None,
    floor_name: str | None,
) -> bool:
    if floor_guid:
        return str(getattr(slab, "GlobalId", "")) == floor_guid

    if floor_name:
        needle = floor_name.casefold()
        fields = [
            str(getattr(slab, "Name", "") or ""),
            str(getattr(slab, "LongName", "") or ""),
            str(getattr(slab, "Tag", "") or ""),
        ]
        return any(needle in field.casefold() for field in fields)

    predefined = str(getattr(slab, "PredefinedType", "") or "").upper()
    name = str(getattr(slab, "Name", "") or "").casefold()
    return predefined in {"FLOOR", "BASESLAB", "NOTDEFINED", "USERDEFINED"} or "floor" in name


def _ifc_world_vertices(
    entity: Any,
    ifc_geom: Any,
) -> list[tuple[float, float, float]]:
    """Return IFC geometry vertices in accumulated/world coordinates."""
    settings = ifc_geom.settings()
    try:
        settings.set(settings.USE_WORLD_COORDS, True)
    except Exception:
        try:
            settings.set("use-world-coords", True)
        except Exception:
            pass

    shape = ifc_geom.create_shape(settings, entity)
    raw = shape.geometry.verts
    return [
        (float(raw[i]), float(raw[i + 1]), float(raw[i + 2]))
        for i in range(0, len(raw), 3)
    ]


def _bbox_xy(vertices: list[tuple[float, float, float]]) -> tuple[float, float, float, float]:
    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    return min(xs), max(xs), min(ys), max(ys)


def _bbox_overlap_area(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    ax0, ax1, ay0, ay1 = a
    bx0, bx1, by0, by1 = b
    dx = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    dy = max(0.0, min(ay1, by1) - max(ay0, by0))
    return dx * dy


def _find_mapped_pbu_world_bbox(
    model: Any,
    ifc_geom: Any,
) -> tuple[float, float, float, float]:
    """
    Build a coarse world-XY PBU envelope from the six mapped IFC walls.

    This is used only to reject floor finishes that belong to another room,
    corridor, external slab, or upper/lower unrelated PBU.
    """
    mapped_tags = set(WALL_MAPPING.values())
    wall_vertices: list[tuple[float, float, float]] = []

    for wall in model.by_type("IfcWall"):
        fields = " ".join(
            str(getattr(wall, attr, "") or "")
            for attr in ("Name", "LongName", "Tag")
        )
        if not any(tag in fields for tag in mapped_tags):
            continue

        try:
            wall_vertices.extend(_ifc_world_vertices(wall, ifc_geom))
        except Exception as exc:
            print(
                f"Warning: unable to read mapped IFC wall geometry "
                f"{getattr(wall, 'GlobalId', '?')}: {exc}"
            )

    if not wall_vertices:
        raise ValueError(
            "Unable to build PBU XY bounds from the six mapped IFC walls."
        )

    x0, x1, y0, y1 = _bbox_xy(wall_vertices)
    t = PBU_BBOX_TOLERANCE_M
    return x0 - t, x1 + t, y0 - t, y1 + t


def get_ifc_floor_heights_m(
    ifc_path: Path,
    floor_guid: str | None = None,
    floor_name: str | None = None,
) -> tuple[float, float, dict[str, Any]]:
    """
    Read the finished-floor regions INSIDE the mapped PBU.

    Selection rule
    --------------
    1. Resolve IFC geometry in world coordinates.
    2. Remove the TerraHill 100000 mm Z datum once.
    3. Prefer slabs named "20mm Floor Finishes".
    4. Keep only floor-finish geometry that overlaps the mapped PBU XY envelope.
    5. Main/toilet floor = MAX(top Z) among valid inside-PBU finishes.
    6. Shower floor     = MIN(top Z) among valid inside-PBU finishes.

    No floor Z is hard-coded.
    """
    try:
        import ifcopenshell
        import ifcopenshell.geom as ifc_geom
    except ImportError as exc:
        raise RuntimeError(
            "IfcOpenShell is required to read the IFC floor geometry. "
            "Install it with: pip install ifcopenshell"
        ) from exc

    model = ifcopenshell.open(str(ifc_path))
    pbu_bbox = _find_mapped_pbu_world_bbox(model, ifc_geom)

    slabs = list(model.by_type("IfcSlab"))
    if floor_guid or floor_name:
        slabs = [
            slab for slab in slabs
            if _matches_floor_filter(slab, floor_guid, floor_name)
        ]
    else:
        # Default automatic mode: finished floor evidence only.
        slabs = [
            slab for slab in slabs
            if PBU_FLOOR_FINISH_NAME.casefold()
            in str(getattr(slab, "Name", "") or "").casefold()
        ]

    if not slabs:
        raise ValueError(
            "No IFC finished-floor slabs matched the requested filter. "
            f"Expected names containing {PBU_FLOOR_FINISH_NAME!r}."
        )

    datum_m = IFC_Z_BASE_MM / 1000.0
    candidates: list[dict[str, Any]] = []

    for slab in slabs:
        try:
            vertices = _ifc_world_vertices(slab, ifc_geom)
        except Exception as exc:
            print(
                f"Warning: unable to read world geometry for IFC slab "
                f"{getattr(slab, 'GlobalId', '?')}: {exc}"
            )
            continue

        if not vertices:
            continue

        bbox = _bbox_xy(vertices)
        overlap_area = _bbox_overlap_area(bbox, pbu_bbox)

        sx0, sx1, sy0, sy1 = bbox
        slab_bbox_area = max(sx1 - sx0, 0.0) * max(sy1 - sy0, 0.0)
        overlap_ratio = (
            overlap_area / slab_bbox_area
            if slab_bbox_area > 1e-12
            else 0.0
        )

        # Must physically overlap the mapped PBU region.
        if overlap_area <= 1e-6:
            continue

        zs = [v[2] for v in vertices]
        world_top_z_m = max(zs)
        world_bottom_z_m = min(zs)
        top_z_m = world_top_z_m - datum_m
        bottom_z_m = world_bottom_z_m - datum_m

        cx = (sx0 + sx1) / 2.0
        cy = (sy0 + sy1) / 2.0

        candidates.append(
            {
                "entity": slab,
                "bbox": bbox,
                "center_x": cx,
                "center_y": cy,
                "overlap_area": overlap_area,
                "overlap_ratio": overlap_ratio,
                "world_top_z_m": world_top_z_m,
                "world_bottom_z_m": world_bottom_z_m,
                "top_z_m": top_z_m,
                "bottom_z_m": bottom_z_m,
            }
        )

    if not candidates:
        raise ValueError(
            "Floor-finish slabs were found, but none overlap the mapped PBU."
        )

    main_candidate = max(
        candidates,
        key=lambda item: (
            float(item["top_z_m"]),
            float(item["overlap_ratio"]),
            float(item["overlap_area"]),
        ),
    )
    shower_candidate = min(
        candidates,
        key=lambda item: (
            float(item["top_z_m"]),
            -float(item["overlap_ratio"]),
            -float(item["overlap_area"]),
        ),
    )

    main_floor_z = round(float(main_candidate["top_z_m"]), 6)
    shower_floor_z = round(float(shower_candidate["top_z_m"]), 6)

    if abs(main_floor_z) > 10.0 or abs(shower_floor_z) > 10.0:
        raise ValueError(
            "Corrected IFC finished-floor Z is unexpectedly large. "
            f"main={main_floor_z:.6f} m, shower={shower_floor_z:.6f} m."
        )

    print()
    print("Mapped PBU world XY bounds:")
    print(
        f"  X: {pbu_bbox[0]:.3f} .. {pbu_bbox[1]:.3f} m | "
        f"Y: {pbu_bbox[2]:.3f} .. {pbu_bbox[3]:.3f} m"
    )
    print()
    print("Inside-PBU finished-floor candidates:")
    for candidate in sorted(candidates, key=lambda item: float(item["top_z_m"])):
        slab = candidate["entity"]
        print(
            "  "
            f"{getattr(slab, 'GlobalId', '?')} | "
            f"{getattr(slab, 'Name', '')} | "
            f"bottom={candidate['bottom_z_m']:.6f} m | "
            f"top={candidate['top_z_m']:.6f} m | "
            f"overlap={candidate['overlap_ratio'] * 100.0:.1f}% | "
            f"center=({candidate['center_x']:.3f}, {candidate['center_y']:.3f})"
        )

    main_slab = main_candidate["entity"]
    shower_slab = shower_candidate["entity"]
    floor_drop_m = round(main_floor_z - shower_floor_z, 6)

    print()
    print("Selected PBU floor levels:")
    print(
        f"  MAIN/TOILET = MAX inside-PBU finish top "
        f"= {main_floor_z:.6f} m | "
        f"{getattr(main_slab, 'Name', '')}"
    )
    print(
        f"  SHOWER      = MIN inside-PBU finish top "
        f"= {shower_floor_z:.6f} m | "
        f"{getattr(shower_slab, 'Name', '')}"
    )
    print(f"  Shower drop = {floor_drop_m * 1000.0:.1f} mm")

    info = {
        "main_global_id": str(getattr(main_slab, "GlobalId", "") or ""),
        "main_name": str(getattr(main_slab, "Name", "") or ""),
        "shower_global_id": str(getattr(shower_slab, "GlobalId", "") or ""),
        "shower_name": str(getattr(shower_slab, "Name", "") or ""),
        "main_floor_z": main_floor_z,
        "shower_floor_z": shower_floor_z,
        "floor_drop_m": floor_drop_m,
        "ifc_z_base_mm": IFC_Z_BASE_MM,
        "datum_m": round(datum_m, 6),
        "pbu_bbox": tuple(round(float(v), 6) for v in pbu_bbox),
    }

    return main_floor_z, shower_floor_z, info


def set_wall_reference_height(

    poses: dict[str, dict[str, float]],
    floor_z_m: float,
    height_above_floor_m: float = WALL_REFERENCE_HEIGHT_ABOVE_FLOOR_M,
) -> dict[str, dict[str, float]]:
    """Set wall_1..wall_6 Z to IFC finished floor height + manual 1 m."""
    result = deepcopy(poses)
    wall_z = round(float(floor_z_m) + float(height_above_floor_m), 6)
    for wall_name in WALL_MAPPING:
        if wall_name not in result:
            raise ValueError(f"Missing wall pose: {wall_name}")
        result[wall_name]["z"] = wall_z
    return result


def apply_shower_wall_height(
    poses: dict[str, dict[str, float]],
    shower_floor_z_m: float,
    height_above_floor_m: float = WALL_REFERENCE_HEIGHT_ABOVE_FLOOR_M,
) -> tuple[dict[str, dict[str, float]], str]:
    """
    Apply the lower shower-floor height to ONE wall point only.

    Layout rule:
        door left  -> shower is on the right-most robot-Y side
        door right -> shower is on the left-most robot-Y side

    All other wall points remain at main/toilet floor + 1 m.
    """
    result = deepcopy(poses)

    if DOOR_SIDE == "left":
        shower_wall_name = max(
            WALL_MAPPING,
            key=lambda name: float(result[name]["y"]),
        )
    elif DOOR_SIDE == "right":
        shower_wall_name = min(
            WALL_MAPPING,
            key=lambda name: float(result[name]["y"]),
        )
    else:
        raise ValueError(f"Unsupported DOOR_SIDE: {DOOR_SIDE!r}")

    result[shower_wall_name]["z"] = round(
        float(shower_floor_z_m) + float(height_above_floor_m),
        6,
    )

    return result, shower_wall_name


def build_floor_pose(floor_z_m: float) -> dict[str, float]:
    """
    Build the new top-level 'floor' pose.

    X/Y are the centroid of the room footprint shown by ROBOT_ROOM_VERTICES.
    Z is the finished/top floor elevation read from the IFC.
    """
    floor_x, floor_y = polygon_centroid_xy(ROBOT_ROOM_VERTICES)
    return {
        "x": floor_x,
        "y": floor_y,
        "z": round(float(floor_z_m), 6),
        "qx": 0.0,
        "qy": 0.0,
        "qz": 0.0,
        "qw": 1.0,
    }


def read_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Unable to read {path}")


def validate_ifc_wall_tags(ifc_path: Path) -> None:
    """Confirm that every mapped structural wall exists in the IFC."""
    text = read_text(ifc_path)

    found_tags = set(
        re.findall(
            r"IFCWALLSTANDARDCASE\([^;]*?'Basic Wall:BSS\.50:(\d+)'",
            text,
            flags=re.IGNORECASE,
        )
    )

    required_tags = set(WALL_MAPPING.values())
    missing = required_tags - found_tags

    if missing:
        raise ValueError(
            f"Missing mapped IFC wall tags: {sorted(missing)}"
        )


def load_reference_centers(path: Path) -> dict[str, dict[str, float]]:
    data: Any = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise ValueError("Reference centers must be a JSON object.")

    for wall_name in WALL_MAPPING:
        if wall_name not in data:
            raise ValueError(
                f"Reference centers is missing {wall_name}."
            )

        pose = data[wall_name]
        missing = REQUIRED_FIELDS - set(pose)

        if missing:
            raise ValueError(
                f"{wall_name} is missing fields: {sorted(missing)}"
            )

    return data


def quaternion_to_yaw(pose: dict[str, float]) -> float:
    qx = float(pose["qx"])
    qy = float(pose["qy"])
    qz = float(pose["qz"])
    qw = float(pose["qw"])

    magnitude = math.sqrt(
        qx * qx + qy * qy + qz * qz + qw * qw
    )

    if magnitude <= 1e-12:
        raise ValueError("Quaternion magnitude cannot be zero.")

    qx /= magnitude
    qy /= magnitude
    qz /= magnitude
    qw /= magnitude

    return math.atan2(
        2.0 * (qw * qz + qx * qy),
        1.0 - 2.0 * (qy * qy + qz * qz),
    )


def make_stage3_pose(
    base_pose: dict[str, float],
    trim_start_mm: float,
    trim_end_mm: float,
) -> dict[str, float]:
    """
    Recalculate the robot midpoint after trimming the wall ends.

    Original midpoint:
        L / 2

    New midpoint measured from original start:
        trim_start + (L - trim_start - trim_end) / 2

    Midpoint shift:
        (trim_start - trim_end) / 2

    The shift is along the wall tangent represented by the quaternion.
    """
    shift_m = (
        float(trim_start_mm) - float(trim_end_mm)
    ) / 2000.0

    yaw = quaternion_to_yaw(base_pose)

    result = deepcopy(base_pose)
    result["x"] = round(
        float(base_pose["x"]) + shift_m * math.cos(yaw),
        6,
    )
    result["y"] = round(
        float(base_pose["y"]) + shift_m * math.sin(yaw),
        6,
    )

    return result


def write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, indent=4) + "\n",
        encoding="utf-8",
    )


def read_generated_centers_json(path: Path) -> dict[str, dict[str, float]]:
    """Read back exactly what was written before generating visuals."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Generated centers JSON is not an object: {path}")
    for name in [*WALL_MAPPING.keys(), "floor"]:
        if name not in data:
            raise ValueError(f"Generated centers JSON is missing {name}: {path}")
    return data

def animate_stage2_to_stage3(
    stage_2: dict[str, dict[str, float]],
    stage_3: dict[str, dict[str, float]],
    output_path: Path,
    frame_count: int = 60,
) -> None:
    """
    Animate all wall poses moving from Stage 2 to Stage 3.
    """
    fig = plt.figure(figsize=(11, 9))
    ax = fig.add_subplot(111, projection="3d")

    wall_names = list(WALL_MAPPING)

    room_x = [point[0] for point in ROBOT_ROOM_VERTICES]
    room_y = [point[1] for point in ROBOT_ROOM_VERTICES]

    def update(frame_index: int) -> None:
        ax.clear()
        draw_robot_room_3d(ax)

        progress = frame_index / max(frame_count - 1, 1)

        for wall_name in wall_names:
            pose_2 = stage_2[wall_name]
            pose_3 = stage_3[wall_name]

            x = (
                float(pose_2["x"])
                + progress
                * (
                    float(pose_3["x"])
                    - float(pose_2["x"])
                )
            )

            y = (
                float(pose_2["y"])
                + progress
                * (
                    float(pose_3["y"])
                    - float(pose_2["y"])
                )
            )

            z = (
                float(pose_2["z"])
                + progress
                * (
                    float(pose_3["z"])
                    - float(pose_2["z"])
                )
            )

            dx, dy, dz = get_pose_x_axis_3d(
                pose_3,
                length=0.30,
            )

            ax.scatter(
                [x],
                [y],
                [z],
                s=90,
                marker="o",
            )

            ax.quiver(
                x,
                y,
                z,
                dx,
                dy,
                dz,
                normalize=False,
                arrow_length_ratio=0.25,
            )

            ax.text(
                x,
                y,
                z + 0.07,
                wall_name,
                fontsize=8,
            )

        ax.set_xlim(
            min(room_x) - 0.4,
            max(room_x) + 0.4,
        )
        ax.set_ylim(
            min(room_y) - 0.4,
            max(room_y) + 0.4,
        )
        ax.set_zlim(
            0.0,
            ROOM_HEIGHT_M,
        )

        ax.set_xlabel("Robot X (m)")
        ax.set_ylabel("Robot Y (m)")
        ax.set_zlabel("Robot Z (m)")

        ax.set_title(
            "Stage 2 → Stage 3\n"
            f"Progress: {progress * 100:.0f}%"
        )

        ax.set_box_aspect((
            max(room_x) - min(room_x),
            max(room_y) - min(room_y),
            ROOM_HEIGHT_M,
        ))

        # Slowly rotate the camera
        ax.view_init(
            elev=25,
            azim=-60 + frame_index * 0.35,
        )

    animation = FuncAnimation(
        fig,
        update,
        frames=frame_count,
        interval=50,
        repeat=True,
    )

    animation.save(
        output_path,
        writer="pillow",
        fps=20,
    )

    plt.close(fig)
def transform_to_left_stl_layout(
    poses: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """
    Place the robot wall centres directly in the measured, NON-MIRRORED
    Stage_1 / Stage_2 / Stage_3 STL coordinate frame.

    Coordinate convention:
        origin = (0, 0, 0)
        X      = original STL X direction (room lies mainly at negative X)
        Y      = original STL Y direction (0.000 to 2.800 m internally)
        Z      = up

    Measured inner/reference wall coordinates taken from the uploaded STL:
        origin-side wall X =  0.000 m
        centre line X      = -0.916 m
        shallow wall X     = -1.240 m
        deep wall X        = -1.832 m
        bottom Y           =  0.000 m
        room centre Y      =  1.400 m
        step Y             =  1.840 m
        top Y              =  2.800 m

    No left/right mirroring and no wall-number swapping is done here.
    """
    result = deepcopy(poses)

    measured_xy = {
        "wall_1": ( 0.000, 1.400),
        "wall_2": (-0.916, 0.000),
        "wall_3": (-1.832, 1.400),
        "wall_4": (-0.916, 1.840),
        "wall_5": (-1.240, 1.400),
        "wall_6": (-0.916, 2.800),
    }

    for wall_name, (new_x, new_y) in measured_xy.items():
        if wall_name not in result:
            raise ValueError(f"Missing wall pose: {wall_name}")
        result[wall_name]["x"] = new_x
        result[wall_name]["y"] = new_y

    return result


def swap_wall_3_and_wall_5_positions(
    poses: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """
    Restore the correct physical wall positions:

        wall_3 = front / shallow wall
        wall_5 = behind / deep wall

    Only XYZ positions are swapped.

    Quaternion orientation is NOT swapped because each wall
    will be re-oriented afterward so local +Y points inside
    the bathroom.
    """

    result = deepcopy(poses)

    # Save wall_3 position
    wall_3_position = {
        "x": float(result["wall_3"]["x"]),
        "y": float(result["wall_3"]["y"]),
        "z": float(result["wall_3"]["z"]),
    }

    # Save wall_5 position
    wall_5_position = {
        "x": float(result["wall_5"]["x"]),
        "y": float(result["wall_5"]["y"]),
        "z": float(result["wall_5"]["z"]),
    }

    # ======================================================
    # wall_3 takes wall_5's current position
    # ======================================================
    result["wall_3"]["x"] = wall_5_position["x"]
    result["wall_3"]["y"] = wall_5_position["y"]
    result["wall_3"]["z"] = wall_5_position["z"]

    # ======================================================
    # wall_5 takes wall_3's current position
    # ======================================================
    result["wall_5"]["x"] = wall_3_position["x"]
    result["wall_5"]["y"] = wall_3_position["y"]
    result["wall_5"]["z"] = wall_3_position["z"]

    return result
def swap_wall_2_and_wall_6_positions(
    poses: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """
    After mirroring, restore the clockwise naming convention:

        wall_2 = leftmost wall
        wall_6 = rightmost wall

    Only the XYZ positions are swapped here.
    Orientation is recalculated separately.
    """

    result = deepcopy(poses)

    wall_2_position = {
        "x": float(result["wall_2"]["x"]),
        "y": float(result["wall_2"]["y"]),
        "z": float(result["wall_2"]["z"]),
    }

    wall_6_position = {
        "x": float(result["wall_6"]["x"]),
        "y": float(result["wall_6"]["y"]),
        "z": float(result["wall_6"]["z"]),
    }

    # wall_2 takes wall_6's mirrored position
    result["wall_2"]["x"] = wall_6_position["x"]
    result["wall_2"]["y"] = wall_6_position["y"]
    result["wall_2"]["z"] = wall_6_position["z"]

    # wall_6 takes wall_2's mirrored position
    result["wall_6"]["x"] = wall_2_position["x"]
    result["wall_6"]["y"] = wall_2_position["y"]
    result["wall_6"]["z"] = wall_2_position["z"]

    return result
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ifc",
        type=Path,
        default=Path(DEFAULT_IFC),
    )
    parser.add_argument(
        "--reference-centers",
        type=Path,
        default=Path(DEFAULT_REFERENCE_CENTERS),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("generated_centers_left"),
    )
    parser.add_argument(
        "--floor-guid",
        type=str,
        default=None,
        help="Optional IFC GlobalId for the floor slab.",
    )
    parser.add_argument(
        "--floor-name",
        type=str,
        default=None,
        help="Optional name substring used to select the IFC floor slab.",
    )
    parser.add_argument(
        "--wall-height-above-floor",
        type=float,
        default=WALL_REFERENCE_HEIGHT_ABOVE_FLOOR_M,
        help="Manual wall reference height above IFC finished floor (default: 1.0 m).",
    )
    args = parser.parse_args()

    if not args.ifc.is_file():
        raise FileNotFoundError(f"IFC not found: {args.ifc}")

    if not args.reference_centers.is_file():
        raise FileNotFoundError(
            f"Reference centers not found: "
            f"{args.reference_centers}"
        )

    validate_ifc_wall_tags(args.ifc)

    # ======================================================
    # IFC finished floor elevation
    # ======================================================
    main_floor_z_m, shower_floor_z_m, floor_info = get_ifc_floor_heights_m(
        ifc_path=args.ifc,
        floor_guid=args.floor_guid,
        floor_name=args.floor_name,
    )

    print()
    print("Selected IFC PBU finished floors:")
    print(f"  Main/toilet floor Z: {main_floor_z_m:.6f} m")
    print(f"  Shower floor Z:      {shower_floor_z_m:.6f} m")
    print(f"  Shower drop:         {floor_info['floor_drop_m'] * 1000.0:.1f} mm")
    print(f"  IFC Z datum removed: {floor_info['datum_m']:.6f} m")
    print(
        f"  Normal wall Z:       "
        f"{main_floor_z_m + args.wall_height_above_floor:.6f} m"
    )
    print(
        f"  Shower wall Z:       "
        f"{shower_floor_z_m + args.wall_height_above_floor:.6f} m"
    )

    # ======================================================
    # 1. Original centers.json reference
    # ======================================================
    reference = load_reference_centers(
        args.reference_centers
    )

    calibrated_reference = apply_position_overrides(
        reference
    )

    # ======================================================
    # 2. Place directly in the measured NON-MIRRORED STL frame
    #
    # No Y mirror and no wall_2/wall_6 or wall_3/wall_5 swaps.
    # The STL and generated poses use the same (0,0,0) origin.
    # ======================================================
    left_reference = transform_to_left_stl_layout(
        calibrated_reference
    )

    # ======================================================
    # 3. Recalculate orientation for the original STL layout
    # ======================================================
    left_reference = orient_wall_y_axes_inward(
        left_reference
    )


    # ======================================================
    # Z reference rule
    # 5 normal wall points = main/toilet IFC finished floor + manual 1.0 m
    # 1 shower wall point  = lower shower IFC finished floor + manual 1.0 m
    # floor                = main/toilet IFC finished floor
    # ======================================================
    left_reference = set_wall_reference_height(
        poses=left_reference,
        floor_z_m=main_floor_z_m,
        height_above_floor_m=args.wall_height_above_floor,
    )

    left_reference, shower_wall_name = apply_shower_wall_height(
        poses=left_reference,
        shower_floor_z_m=shower_floor_z_m,
        height_above_floor_m=args.wall_height_above_floor,
    )

    floor_pose = build_floor_pose(main_floor_z_m)

    # ======================================================
    # Stage 1 / Stage 2
    # ======================================================
    stage_1 = deepcopy(
        left_reference
    )

    stage_2 = deepcopy(
        left_reference
    )


    # Keep floor as the final top-level key after wall_6.
    stage_1["floor"] = deepcopy(floor_pose)
    stage_2["floor"] = deepcopy(floor_pose)

    # ======================================================
    # Stage 3 starts from Stage 2:
    # 1. Apply unequal start/end trimming along wall tangent.
    # 2. Move the result inward toward the room interior.
    # ======================================================
    stage_3: dict[str, dict[str, float]] = {}

    for wall_name, ifc_tag in WALL_MAPPING.items():
        trim_start_mm, trim_end_mm = STAGE3_TRIMS_MM.get(
            ifc_tag,
            (0.0, 0.0),
        )

        trimmed_pose = make_stage3_pose(
            stage_2[wall_name],
            trim_start_mm,
            trim_end_mm,
        )

        stage_3[wall_name] = move_pose_inward(
            wall_name=wall_name,
            base_pose=trimmed_pose,
            offset_m=STAGE3_INWARD_OFFSET_M,
        )

    # Floor does not receive Stage 3 wall trimming/inward offsets.
    # Assignment occurs after wall_6 so JSON ordering remains wall_1..wall_6,floor.
    stage_3["floor"] = deepcopy(floor_pose)

    print()
    print("Stage 2 -> Stage 3 inward movement:")
    for wall_name in WALL_MAPPING:
        x2 = float(stage_2[wall_name]["x"])
        y2 = float(stage_2[wall_name]["y"])
        x3 = float(stage_3[wall_name]["x"])
        y3 = float(stage_3[wall_name]["y"])

        print(
            f"  {wall_name}: "
            f"({x2:.3f}, {y2:.3f}) -> "
            f"({x3:.3f}, {y3:.3f}), "
            f"delta=({x3 - x2:+.3f}, {y3 - y2:+.3f})"
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # ======================================================
    # Write JSON first
    # ======================================================
    stage_1_json = args.output_dir / "stage_1_centers.json"
    stage_2_json = args.output_dir / "stage_2_centers.json"
    stage_3_json = args.output_dir / "stage_3_centers.json"

    write_json(stage_1_json, stage_1)
    write_json(stage_2_json, stage_2)
    write_json(stage_3_json, stage_3)

    # IMPORTANT: read the files back from disk. All images below are generated
    # from the JSON that was actually written, not from an earlier dictionary.
    stage_1_saved = read_generated_centers_json(stage_1_json)
    stage_2_saved = read_generated_centers_json(stage_2_json)
    stage_3_saved = read_generated_centers_json(stage_3_json)

    print()
    print("Generated JSON verification:")
    for stage_name, saved in (
        ("Stage 1", stage_1_saved),
        ("Stage 2", stage_2_saved),
        ("Stage 3", stage_3_saved),
    ):
        wall_values = {name: float(saved[name]["z"]) for name in WALL_MAPPING}
        shower_name = min(wall_values, key=wall_values.get)
        print(
            f"  {stage_name}: floor.z={saved['floor']['z']:.6f}, "
            f"shower={shower_name} z={wall_values[shower_name]:.6f}, "
            f"normal max z={max(wall_values.values()):.6f}"
        )

    # ======================================================
    # Generate images FROM THE SAVED JSON
    # ======================================================
    plot_stage_poses(
        poses=stage_1_saved,
        output_path=args.output_dir / "stage_1_positions.png",
        title="Stage 1 Robot Positions",
    )
    plot_stage_poses(
        poses=stage_2_saved,
        output_path=args.output_dir / "stage_2_positions.png",
        title="Stage 2 Robot Positions",
    )
    plot_stage_poses(
        poses=stage_3_saved,
        output_path=args.output_dir / "stage_3_positions.png",
        title="Stage 3 Robot Positions",
    )

    plot_stage_poses_3d(
        poses=stage_1_saved,
        output_path=args.output_dir / "stage_1_positions_3d.png",
        title="Stage 1 Robot Positions — 3D",
    )
    plot_stage_poses_3d(
        poses=stage_2_saved,
        output_path=args.output_dir / "stage_2_positions_3d.png",
        title="Stage 2 Robot Positions — 3D",
    )
    plot_stage_poses_3d(
        poses=stage_3_saved,
        output_path=args.output_dir / "stage_3_positions_3d.png",
        title="Stage 3 Robot Positions — 3D",
    )

    plot_stage_comparison(
        stage_1=stage_1_saved,
        stage_2=stage_2_saved,
        stage_3=stage_3_saved,
        output_path=args.output_dir / "stage_comparison.png",
    )
    animate_stage2_to_stage3(
        stage_2=stage_2_saved,
        stage_3=stage_3_saved,
        output_path=args.output_dir / "stage_2_to_stage_3.gif",
    )

    print("Final wall mapping:")
    for wall_name, ifc_tag in WALL_MAPPING.items():
        pose = stage_1[wall_name]
        print(
            f"  {wall_name} -> IFC {ifc_tag}: "
            f"x={pose['x']}, y={pose['y']}"
        )

    print(
        f"  floor -> MAIN IFC finish {floor_info['main_global_id']}: "
        f"x={floor_pose['x']}, y={floor_pose['y']}, z={floor_pose['z']}"
    )
    print(
        f"  shower point -> {shower_wall_name} | "
        f"IFC finish {floor_info['shower_global_id']} | "
        f"z={stage_1[shower_wall_name]['z']}"
    )

    print()
    print("Created/overwritten in this run:")
    for filename in (
        "stage_1_centers.json",
        "stage_2_centers.json",
        "stage_3_centers.json",
        "stage_1_positions.png",
        "stage_2_positions.png",
        "stage_3_positions.png",
        "stage_1_positions_3d.png",
        "stage_2_positions_3d.png",
        "stage_3_positions_3d.png",
        "stage_comparison.png",
        "stage_2_to_stage_3.gif",
    ):
        print(f"  {args.output_dir / filename}")

def plot_stage_poses(
    poses: dict[str, dict[str, float]],
    output_path: Path,
    title: str,
    orientation_length: float = 0.32,
) -> None:
    """
    Draw robot XY positions together with the room outline.

    The orientation line represents the quaternion yaw axis.
    It is not an arrow pointing from the robot toward the wall.
    """
    fig, ax = plt.subplots(figsize=(10, 8))

    draw_robot_room_outline(ax)

    all_x: list[float] = [
        point[0]
        for point in ROBOT_ROOM_VERTICES
    ]

    all_y: list[float] = [
        point[1]
        for point in ROBOT_ROOM_VERTICES
    ]

    for wall_name, pose in poses.items():
        x = float(pose["x"])
        y = float(pose["y"])
        yaw = quaternion_to_yaw(pose)

        all_x.append(x)
        all_y.append(y)

        # ----------------------------------------------
        # Robot position
        # ----------------------------------------------
        ax.scatter(
            x,
            y,
            s=90,
            marker="o",
            zorder=4,
        )

        # ----------------------------------------------
        # Wall/quaternion orientation
        #
        # Draw a centred line rather than an arrow.
        # This avoids making it look as if the quaternion
        # must point directly toward the physical wall.
        # ----------------------------------------------
        half_length = orientation_length / 2.0

        dx = half_length * math.cos(yaw)
        dy = half_length * math.sin(yaw)

        ax.plot(
            [x - dx, x + dx],
            [y - dy, y + dy],
            linewidth=2.5,
            zorder=3,
        )

        # Small marker on the positive yaw side
        ax.scatter(
            x + dx,
            y + dy,
            s=35,
            marker=">",
            zorder=5,
        )

        ax.annotate(
            (
                f"{wall_name}\n"
                f"x={x:.3f}, y={y:.3f}\n"
                f"yaw={math.degrees(yaw):.0f}°"
            ),
            xy=(x, y),
            xytext=(8, 8),
            textcoords="offset points",
            fontsize=8,
        )

    margin = 0.35

    ax.set_xlim(
        min(all_x) - margin,
        max(all_x) + margin,
    )

    ax.set_ylim(
        min(all_y) - margin,
        max(all_y) + margin,
    )

    ax.axhline(
        0.0,
        linewidth=1,
    )

    ax.axvline(
        0.0,
        linewidth=1,
    )

    ax.set_title(title)
    ax.set_xlabel("Robot X position (m)")
    ax.set_ylabel("Robot Y position (m)")
    ax.grid(True)
    ax.axis("equal")
    ax.legend(loc="best")

    fig.tight_layout()

    fig.savefig(
        output_path,
        dpi=200,
        bbox_inches="tight",
    )

    plt.close(fig)


def plot_stage_comparison(
    stage_1: dict[str, dict[str, float]],
    stage_2: dict[str, dict[str, float]],
    stage_3: dict[str, dict[str, float]],
    output_path: Path,
) -> None:
    """
    Overlay Stage 1, Stage 2 and Stage 3 positions.

    This makes it easy to see whether Stage 3 moved any wall pose.
    """
    fig, ax = plt.subplots(figsize=(10, 8))

    stages = [
        ("Stage 1", stage_1, "o"),
        ("Stage 2", stage_2, "s"),
        ("Stage 3", stage_3, "^"),
    ]

    all_x: list[float] = []
    all_y: list[float] = []

    for stage_name, poses, marker in stages:
        stage_x: list[float] = []
        stage_y: list[float] = []

        for wall_name, pose in poses.items():
            x = float(pose["x"])
            y = float(pose["y"])

            stage_x.append(x)
            stage_y.append(y)

            all_x.append(x)
            all_y.append(y)

            ax.annotate(
                wall_name,
                xy=(x, y),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=7,
            )

        ax.scatter(
            stage_x,
            stage_y,
            s=80,
            marker=marker,
            label=stage_name,
        )

    # Show Stage 1 -> Stage 3 movement
    for wall_name in WALL_MAPPING:
        x1 = float(stage_1[wall_name]["x"])
        y1 = float(stage_1[wall_name]["y"])

        x3 = float(stage_3[wall_name]["x"])
        y3 = float(stage_3[wall_name]["y"])

        movement = math.hypot(
            x3 - x1,
            y3 - y1,
        )

        if movement > 1e-9:
            ax.arrow(
                x1,
                y1,
                x3 - x1,
                y3 - y1,
                width=0.004,
                head_width=0.05,
                head_length=0.06,
                length_includes_head=True,
            )

    if all_x and all_y:
        margin = 0.5

        ax.set_xlim(
            min(all_x) - margin,
            max(all_x) + margin,
        )
        ax.set_ylim(
            min(all_y) - margin,
            max(all_y) + margin,
        )

    ax.axhline(
        0.0,
        linewidth=1,
    )
    ax.axvline(
        0.0,
        linewidth=1,
    )

    ax.set_title("Stage 1, Stage 2 and Stage 3 Robot Positions")
    ax.set_xlabel("Robot X position (m)")
    ax.set_ylabel("Robot Y position (m)")
    ax.grid(True)
    ax.axis("equal")
    ax.legend()

    fig.tight_layout()
    fig.savefig(
        output_path,
        dpi=200,
        bbox_inches="tight",
    )

    plt.close(fig)

if __name__ == "__main__":
    main()