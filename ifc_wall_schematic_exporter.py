import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
import numpy as np
import math
import os
from pathlib import Path
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union, linemerge
from shapely import affinity
import sys

# ============================================================
# CONFIG
# ============================================================
WALL_COLOR = "#6b4f2a" 
FLOOR_COLOR = "#b08a4f"
LABEL_COLOR = "black"
LINE_W = 10
ARROW_LEN = 150
LABEL_OFFSET = 220
DOOR_LABEL_OFFSET = 220
SNAP_TOL = 80  # mm

DIR_ARROW = {
    "+X": ("red", 1, 0),
    "-X": ("red", -1, 0),
    "+Y": ("blue", 0, 1),
    "-Y": ("blue", 0, -1),
}

# ------------------------------------------------------------
# Mirrored display label map
# internal wall -> display wall
# ------------------------------------------------------------
MIRRORED_WALL_LABEL_MAP = {1: 1, 2: 6, 3: 5, 4: 4, 5: 3, 6: 2}

# ------------------------------------------------------------
# Robot-centered marking gauge config
# ------------------------------------------------------------
MARKING_GAUGE_ENABLED = True
DRAW_ARROW_TEXT_LABEL = False
# Slide reference:
# Max. Marking Zone: 2200 x 2200
# Min. Marking Zone: 1950 x 1950
MAX_MARKING_SIZE_MM = 2200.0
MIN_MARKING_SIZE_MM = 1950.0

MARKING_GAUGE_STYLE = {
    "max_color":"#ff6666",
    "min_color": "#7fbf7f",
    "max_alpha": 0.50,
    "min_alpha": 0.50,
    "edge_width": 2,
    "label_color": "white",
    "label_size": 12,
}

# Whether to clip the centered robot square to the IFC room polygon.
# True matches "must link to the ifcwall".
CLIP_MARKING_ZONE_TO_ROOM = True

# ------------------------------------------------------------
# Position-to-wall arrow config
# ------------------------------------------------------------
POSITION_WALL_ARROW_ENABLED = True

POSITION_WALL_ARROW_STYLE = {
    "color": "#FFD700",          # yellow / gold
    "line_width": 3.0,
    "head_scale": 18,
    "arrow_shrink_start": 80,    # keep arrow away from robot icon
    "arrow_shrink_end": 12,      # small shrink so arrow head lands near wall
}


def get_resource_path(filename):
    """
    Return the correct path both:
    - when running normal Python
    - when running as PyInstaller EXE
    """

    if getattr(sys, "frozen", False):
        base_dir = Path(sys._MEIPASS)
    else:
        base_dir = Path(__file__).resolve().parent

    return base_dir / filename


ROBOT_ICON_CANDIDATES = [
    get_resource_path("robotarm.png"),
    get_resource_path("robotarm.jpg"),
]

def closest_point_on_segment(pt, a, b):
    """
    Returns the closest point on line segment AB to point PT.
    This lets the arrow hit the wall drawing itself.
    """
    px, py = pt
    ax, ay = a
    bx, by = b

    vx = bx - ax
    vy = by - ay
    seg_len2 = vx * vx + vy * vy

    if seg_len2 <= 1e-9:
        return a

    t = ((px - ax) * vx + (py - ay) * vy) / seg_len2
    t = max(0.0, min(1.0, t))

    return (ax + t * vx, ay + t * vy)

def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])

def derive_marking_sizes_from_wall_lengths(chained_edges):
    wall_lengths = []

    for wnum, a, b in chained_edges:
        L = dist(a, b)
        wall_lengths.append((wnum, float(L)))

    wall_lengths.sort(key=lambda x: x[1], reverse=True)

    if not wall_lengths:
        return None, None, []

    max_gauge = wall_lengths[0][1]
    min_gauge = wall_lengths[1][1] if len(wall_lengths) > 1 else wall_lengths[0][1]

    return max_gauge, min_gauge, wall_lengths


def label_normal(dx, dy, idx):
    nx, ny = -dy, dx
    if idx % 2 == 0:
        nx, ny = -nx, -ny
    n = math.hypot(nx, ny)
    return (nx / n, ny / n) if n else (0.0, 0.0)


def find_robot_icon_path():

    for p in ROBOT_ICON_CANDIDATES:

        if Path(p).exists():

            print(
                "[ROBOT ICON] Found:",
                p
            )

            return str(p)

    print(
        "[ROBOT ICON] NOT FOUND"
    )

    for p in ROBOT_ICON_CANDIDATES:

        print(
            "[ROBOT ICON] Checked:",
            p
        )

    return None


def mirror_point_lr(pt, floor_poly):
    if pt is None:
        return None
    minx, miny, maxx, maxy = floor_poly.bounds
    x, y = pt
    return (minx + maxx - x, y)


def transform_point(pt, floor_poly, mirror_layout=False):
    if pt is None:
        return None
    return mirror_point_lr(pt, floor_poly) if mirror_layout else pt


def draw_robot_at_position(ax, pos, icon, zoom):
    ab = AnnotationBbox(OffsetImage(icon, zoom=zoom), pos, frameon=False, zorder=20)
    ax.add_artist(ab)


def local_to_global_xy(obj):
    verts = obj["vertices"]
    tx = float(obj.get("x", 0.0))
    ty = float(obj.get("y", 0.0))
    facing = obj.get("facingaxis", "+X")
    out = []
    for v in verts:
        vx, vy = float(v[0]), float(v[1])
        if facing == "+X":
            gx, gy = vx, vy
        elif facing == "-X":
            gx, gy = -vx, -vy
        elif facing == "+Y":
            gx, gy = -vy, vx
        elif facing == "-Y":
            gx, gy = vy, -vx
        else:
            gx, gy = vx, vy
        out.append((gx + tx, gy + ty))
    return np.array(out, dtype=float)


def wall_endpoints_2d(wall):
    xy = local_to_global_xy(wall)
    if len(xy) < 2:
        p = (float(wall.get("x", 0.0)), float(wall.get("y", 0.0)))
        return p, p
    best_i, best_j, best_d = 0, 1, -1.0
    for i in range(len(xy)):
        for j in range(i + 1, len(xy)):
            d = (xy[i, 0] - xy[j, 0]) ** 2 + (xy[i, 1] - xy[j, 1]) ** 2
            if d > best_d:
                best_d = d
                best_i, best_j = i, j
    return (
        (float(xy[best_i, 0]), float(xy[best_i, 1])),
        (float(xy[best_j, 0]), float(xy[best_j, 1])),
    )


def opening_t_range_on_wall_local(opening, wall):
    if "vertices" not in opening or "vertices" not in wall:
        return None
    wvx = wall["vertices"][:, 0].astype(float)
    ovx = opening["vertices"][:, 0].astype(float)
    wmin, wmax = float(wvx.min()), float(wvx.max())
    dmin, dmax = float(ovx.min()), float(ovx.max())
    L = wmax - wmin
    if L <= 1e-9:
        return None
    t1 = (dmin - wmin) / L
    t2 = (dmax - wmin) / L
    t1 = max(0.0, min(1.0, t1))
    t2 = max(0.0, min(1.0, t2))
    if t2 <= t1:
        return None
    return (t1, t2)


def is_likely_door(opening):
    if "vertices" not in opening:
        return False
    z0 = float(opening.get("z", 0.0))
    z_vals = opening["vertices"][:, 2].astype(float) + z0
    zmin = float(z_vals.min())
    zmax = float(z_vals.max())
    height = zmax - zmin
    touches_floor = zmin <= 250
    tall_enough = height >= 1800
    return touches_floor and tall_enough


def straighten_by_ifc_axis(a, b, wall):
    ax, ay = a
    bx, by = b
    axis = wall.get("axis") or wall.get("facingaxis") or ""
    axis = axis.upper()
    if "X" in axis:
        y = (ay + by) * 0.5
        return (ax, y), (bx, y)
    if "Y" in axis:
        x = (ax + bx) * 0.5
        return (x, ay), (x, by)
    return a, b


def snap_points_to_nodes(segments, tol=80.0):
    nodes = []

    def get_node(p):
        px, py = p
        for nx, ny in nodes:
            if dist((px, py), (nx, ny)) <= tol:
                return (nx, ny)
        nodes.append((px, py))
        return (px, py)

    out = []
    for a, b in segments:
        a2 = get_node(a)
        b2 = get_node(b)
        if dist(a2, b2) > 1e-6:
            out.append((a2, b2))
    return out


def snap_loop_to_grid(chained_edges):
    snapped = []
    xs = {}
    ys = {}
    for wnum, a, b in chained_edges:
        if abs(a[0] - b[0]) < abs(a[1] - b[1]):
            xs[wnum] = (a[0] + b[0]) * 0.5
        else:
            ys[wnum] = (a[1] + b[1]) * 0.5
    prev_end = None
    for wnum, a, b in chained_edges:
        if prev_end is not None:
            a = prev_end
        if wnum in xs:
            x = xs[wnum]
            a2 = (x, a[1])
            b2 = (x, b[1])
        elif wnum in ys:
            y = ys[wnum]
            a2 = (a[0], y)
            b2 = (b[0], y)
        else:
            a2, b2 = a, b
        snapped.append((wnum, a2, b2))
        prev_end = b2
    return snapped


def get_robot_position_1(chained_edges, floor_poly):
    seg_map = {wnum: (a, b) for (wnum, a, b) in chained_edges}
    if 5 not in seg_map or 6 not in seg_map:
        return None
    a5, b5 = seg_map[5]
    a6, b6 = seg_map[6]
    x = (a5[0] + b5[0]) * 0.5
    y = (a6[1] + b6[1]) * 0.5
    return (x, y)


def get_robot_position_2(chained_edges, floor_poly):
    seg_map = {wnum: (a, b) for (wnum, a, b) in chained_edges}
    if 1 not in seg_map or 3 not in seg_map or 4 not in seg_map:
        return None

    a3, b3 = seg_map[3]
    a4, b4 = seg_map[4]
    a1, b1 = seg_map[1]

    corner3 = b3 if min(dist(b3, a4), dist(b3, b4)) <= min(dist(a3, a4), dist(a3, b4)) else a3

    vx1, vy1 = b1[0] - a1[0], b1[1] - a1[1]
    seg1_len2 = vx1 * vx1 + vy1 * vy1
    if seg1_len2 <= 1e-9:
        near1 = a1
    else:
        wx1, wy1 = corner3[0] - a1[0], corner3[1] - a1[1]
        t = max(0.0, min(1.0, (wx1 * vx1 + wy1 * vy1) / seg1_len2))
        near1 = (a1[0] + t * vx1, a1[1] + t * vy1)

    POS2_SHIFT_RIGHT_MM = 400.0

    x = (
        (corner3[0] + near1[0]) * 0.5
    )

    y = (
        (corner3[1] + near1[1]) * 0.5
    )

    x += POS2_SHIFT_RIGHT_MM

    return (
        x,
        y,
)
    # return ((corner3[0] + near1[0]) * 0.5, (corner3[1] + near1[1]) * 0.5)


def is_layout_mirrored_by_shape(floor_poly):
    minx, miny, maxx, maxy = floor_poly.bounds
    cx = (minx + maxx) * 0.5
    coords = list(floor_poly.exterior.coords)
    notch = None
    for x, y in coords:
        if minx < x < maxx and miny < y < maxy:
            notch = (x, y)
            break
    if notch is None:
        return False
    notch_x, _ = notch
    return notch_x < cx


def get_display_wall_label(internal_wall, mirror_layout=False):
    return MIRRORED_WALL_LABEL_MAP.get(internal_wall, internal_wall) if mirror_layout else internal_wall


# ============================================================
# MARKING ZONE HELPERS - ROBOT CENTERED, IFC WALL LINKED
# ============================================================
def build_centered_box(center, width, height=None):
    if center is None:
        return Polygon()
    if height is None:
        height = width
    cx, cy = center
    hw = float(width) * 0.5
    hh = float(height) * 0.5
    return Polygon([
        (cx - hw, cy - hh),
        (cx + hw, cy - hh),
        (cx + hw, cy + hh),
        (cx - hw, cy + hh),
    ])


def polygon_to_xy_list(poly):
    if poly.is_empty:
        return []
    if poly.geom_type == "Polygon":
        coords = list(poly.exterior.coords)[:-1]
        return [(float(x), float(y)) for x, y in coords]
    return []


def point_to_segment_distance(pt, a, b):
    px, py = pt
    ax, ay = a
    bx, by = b
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    seg_len2 = vx * vx + vy * vy
    if seg_len2 <= 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / seg_len2))
    qx = ax + t * vx
    qy = ay + t * vy
    return math.hypot(px - qx, py - qy)


def nearest_internal_wall_for_point(pt, chained_edges):
    best_wall = None
    best_dist = float("inf")
    for wnum, a, b in chained_edges:
        d = point_to_segment_distance(pt, a, b)
        if d < best_dist:
            best_dist = d
            best_wall = wnum
    return best_wall


def tag_polygon_edges_to_walls(poly, chained_edges, mirror_layout=False):
    if poly.is_empty or poly.geom_type != "Polygon":
        return []

    coords = list(poly.exterior.coords)
    out = []

    for i in range(len(coords) - 1):
        p0 = coords[i]
        p1 = coords[i + 1]
        mx = (p0[0] + p1[0]) * 0.5
        my = (p0[1] + p1[1]) * 0.5
        internal_wall = nearest_internal_wall_for_point((mx, my), chained_edges)
        out.append({
            "edge_start": (float(p0[0]), float(p0[1])),
            "edge_end": (float(p1[0]), float(p1[1])),
            "internal_wall": internal_wall,
            "display_wall": get_display_wall_label(internal_wall, mirror_layout=mirror_layout),
        })

    return out


def build_robot_marking_zone_polygons(
    robot_pos,
    floor_poly,
    chained_edges,
    mirror_layout=False,
    max_size=MAX_MARKING_SIZE_MM,
    min_size=MIN_MARKING_SIZE_MM,
):
    max_box = build_centered_box(robot_pos, max_size, max_size)
    min_box = build_centered_box(robot_pos, min_size, min_size)

    if CLIP_MARKING_ZONE_TO_ROOM:
        max_poly = max_box.intersection(floor_poly)
        min_poly = min_box.intersection(floor_poly)
    else:
        max_poly = max_box
        min_poly = min_box

    return {
        "robot_pos": robot_pos,
        "max_box_raw": max_box,
        "min_box_raw": min_box,
        "max_poly": max_poly,
        "min_poly": min_poly,
        "max_edges_to_walls": tag_polygon_edges_to_walls(max_poly, chained_edges, mirror_layout=mirror_layout),
        "min_edges_to_walls": tag_polygon_edges_to_walls(min_poly, chained_edges, mirror_layout=mirror_layout),
    }


def draw_zone_polygon(ax, poly, floor_poly, color, alpha, edge_width, mirror_layout=False, zorder_fill=2, zorder_edge=3):
    pts = polygon_to_xy_list(poly)
    if not pts:
        return

    pts = [transform_point(p, floor_poly, mirror_layout) for p in pts]
    if len(pts) < 3:
        return

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]

    # full translucent fill
    ax.fill(xs, ys, facecolor=color, edgecolor="none", alpha=alpha, zorder=zorder_fill)

    # border on top
    xs2 = xs + [xs[0]]
    ys2 = ys + [ys[0]]
    ax.plot(xs2, ys2, color=color, linewidth=edge_width, zorder=zorder_edge)


def polygon_center(poly):
    pts = polygon_to_xy_list(poly)
    if not pts:
        return None
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return (cx, cy)


def draw_robot_marking_zone(ax, zone_data, floor_poly, mirror_layout=False):
    if not zone_data:
        return

    style = MARKING_GAUGE_STYLE

    max_poly = zone_data.get("max_poly")
    min_poly = zone_data.get("min_poly")

    if max_poly is None or max_poly.is_empty:
        return

    if min_poly is None or min_poly.is_empty:
        draw_zone_geom(
            ax=ax,
            geom=max_poly,
            floor_poly=floor_poly,
            color=style["max_color"],
            alpha=style["max_alpha"],
            edge_width=style["edge_width"],
            mirror_layout=mirror_layout,
            zorder_fill=1,
            zorder_edge=2,
        )
        return

    outer_green = max_poly.difference(min_poly)
    inner_red = min_poly

    draw_zone_geom(
        ax=ax,
        geom=outer_green,
        floor_poly=floor_poly,
        color=style["max_color"],
        alpha=style["max_alpha"],
        edge_width=style["edge_width"],
        mirror_layout=mirror_layout,
        zorder_fill=1,
        zorder_edge=2,
    )

    draw_zone_geom(
        ax=ax,
        geom=inner_red,
        floor_poly=floor_poly,
        color=style["min_color"],
        alpha=style["min_alpha"],
        edge_width=style["edge_width"],
        mirror_layout=mirror_layout,
        zorder_fill=3,
        zorder_edge=4,
    )
def shorten_line(p0, p1, shrink_start=0.0, shrink_end=0.0):
    x0, y0 = p0
    x1, y1 = p1
    vx = x1 - x0
    vy = y1 - y0
    L = math.hypot(vx, vy)

    if L <= 1e-9:
        return p0, p1

    ux = vx / L
    uy = vy / L

    new_start = (x0 + ux * shrink_start, y0 + uy * shrink_start)
    new_end = (x1 - ux * shrink_end, y1 - uy * shrink_end)

    return new_start, new_end


def get_wall_text_position(
    wnum,
    a,
    b,
    wall,
    floor_poly,
    mirror_layout=False,
):
    a_draw = transform_point(a, floor_poly, mirror_layout)
    b_draw = transform_point(b, floor_poly, mirror_layout)

    arrow_color, dx, dy = DIR_ARROW.get(wall.get("facingaxis", ""), ("black", 0, 0))
    nx, ny = label_normal(dx, dy, wnum)

    if mirror_layout:
        nx = -nx
        dx = -dx

    cx = (a_draw[0] + b_draw[0]) * 0.5
    cy = (a_draw[1] + b_draw[1]) * 0.5

    return (
        cx + nx * LABEL_OFFSET,
        cy + ny * LABEL_OFFSET,
    )

def draw_position_wall_arrows(
    ax,
    position_name,
    robot_pos,
    target_internal_walls,
    chained_edges,
    wall_seg,
    floor_poly,
    mirror_layout=False,
):
    if not POSITION_WALL_ARROW_ENABLED:
        return

    if robot_pos is None:
        return

    style = POSITION_WALL_ARROW_STYLE

    robot_pos_draw = transform_point(robot_pos, floor_poly, mirror_layout)
    edge_map = {wnum: (a, b) for wnum, a, b in chained_edges}

    for internal_wall in target_internal_walls:
        if internal_wall not in edge_map:
            continue

        a, b = edge_map[internal_wall]

        # ----------------------------------------------------
        # Aim at the actual wall segment, not the wall text
        # ----------------------------------------------------
        wall_hit_pt = closest_point_on_segment(robot_pos, a, b)
        wall_hit_pt_draw = transform_point(wall_hit_pt, floor_poly, mirror_layout)

        arrow_start, arrow_end = shorten_line(
            robot_pos_draw,
            wall_hit_pt_draw,
            shrink_start=style["arrow_shrink_start"],
            shrink_end=style["arrow_shrink_end"],
        )

        ax.annotate(
            "",
            xy=arrow_end,
            xytext=arrow_start,
            arrowprops=dict(
                arrowstyle="->",
                color=style["color"],
                linewidth=style["line_width"],
                shrinkA=0,
                shrinkB=0,
            ),
            zorder=18,
        )

        if DRAW_ARROW_TEXT_LABEL:
            display_wall = get_display_wall_label(
                internal_wall,
                mirror_layout=mirror_layout,
            )

            lx = arrow_start[0] + (arrow_end[0] - arrow_start[0]) * 0.55
            ly = arrow_start[1] + (arrow_end[1] - arrow_start[1]) * 0.55

            ax.text(
                lx,
                ly,
                f"{position_name}_wall{display_wall}",
                fontsize=style["label_size"],
                weight="bold",
                color=style["label_color"],
                ha="center",
                va="center",
                bbox=dict(
                    facecolor=style["label_box_face"],
                    alpha=style["label_box_alpha"],
                    edgecolor="none",
                    boxstyle="round,pad=0.25",
                ),
                zorder=19,
            )

# ============================================================
# RENDER
# ============================================================
def render_and_save_schematic(
    chained_edges,
    wall_seg,
    reversed_wall,
    doors_by_wall,
    floor_poly,
    output_path,
    robot_pos=None,
    icon_path=None,
    mirror_layout=False,
    marking_zone_data=None,
    robot_position_name=None,
    arrow_target_walls=None,
):
    floor_poly_draw = (
        affinity.scale(floor_poly, xfact=-1, yfact=1, origin="center")
        if mirror_layout
        else floor_poly
    )

    xs, ys = floor_poly_draw.exterior.xy

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.fill(xs, ys, color=FLOOR_COLOR, zorder=0)

    # ========================================================
    # 1. Draw marking gauge first
    # ========================================================
    if marking_zone_data and MARKING_GAUGE_ENABLED:
        draw_robot_marking_zone(
            ax,
            marking_zone_data,
            floor_poly,
            mirror_layout=mirror_layout,
        )

    # ========================================================
    # 2. Draw walls, wall labels, direction arrows
    # ========================================================
    for wnum, a_raw, b_raw in chained_edges:
        a = transform_point(a_raw, floor_poly, mirror_layout)
        b = transform_point(b_raw, floor_poly, mirror_layout)

        wall = wall_seg[wnum]["wall"]

        arrow_color, dx, dy = DIR_ARROW.get(
            wall.get("facingaxis", ""),
            ("black", 0, 0),
        )

        nx, ny = label_normal(dx, dy, wnum)

        if mirror_layout:
            nx = -nx
            dx = -dx

        display_wnum = get_display_wall_label(
            wnum,
            mirror_layout=mirror_layout,
        )

        # -----------------------------
        # Door break
        # -----------------------------
        if wnum in doors_by_wall and len(doors_by_wall[wnum]) > 0:
            t1, t2 = doors_by_wall[wnum][0]

            g1 = (
                a[0] + (b[0] - a[0]) * t1,
                a[1] + (b[1] - a[1]) * t1,
            )

            g2 = (
                a[0] + (b[0] - a[0]) * t2,
                a[1] + (b[1] - a[1]) * t2,
            )

            ax.plot(
                [a[0], g1[0]],
                [a[1], g1[1]],
                WALL_COLOR,
                linewidth=LINE_W,
                zorder=10,
            )

            ax.plot(
                [g2[0], b[0]],
                [g2[1], b[1]],
                WALL_COLOR,
                linewidth=LINE_W,
                zorder=10,
            )

            ax.text(
                (g1[0] + g2[0]) / 2 + nx * DOOR_LABEL_OFFSET,
                (g1[1] + g2[1]) / 2 + ny * DOOR_LABEL_OFFSET,
                "Door",
                fontsize=12,
                weight="bold",
                ha="center",
                va="center",
                color=LABEL_COLOR,
                zorder=11,
            )

        else:
            ax.plot(
                [a[0], b[0]],
                [a[1], b[1]],
                WALL_COLOR,
                linewidth=LINE_W,
                zorder=10,
            )

        # -----------------------------
        # Wall text
        # -----------------------------
        cx = (a[0] + b[0]) / 2
        cy = (a[1] + b[1]) / 2

        ax.text(
            cx + nx * LABEL_OFFSET,
            cy + ny * LABEL_OFFSET,
            f"Wall {display_wnum}",
            fontsize=14,
            weight="bold",
            ha="center",
            va="center",
            color=LABEL_COLOR,
            zorder=11,
        )

        # -----------------------------
        # Red / blue direction arrows
        # -----------------------------
        if dx != 0 or dy != 0:
            ax.arrow(
                cx,
                cy,
                dx * ARROW_LEN,
                dy * ARROW_LEN,
                head_width=40,
                head_length=40,
                fc=arrow_color,
                ec=arrow_color,
                length_includes_head=True,
                zorder=11,
            )

    # ========================================================
    # 3. Draw one black position arrow only after all walls
    #    This must NOT be inside the wall loop.
    # ========================================================
    if (
        robot_position_name
        and robot_pos is not None
        and arrow_target_walls
        and POSITION_WALL_ARROW_ENABLED
    ):
        draw_position_wall_arrows(
            ax=ax,
            position_name=robot_position_name,
            robot_pos=robot_pos,
            target_internal_walls=arrow_target_walls,
            chained_edges=chained_edges,
            wall_seg=wall_seg,
            floor_poly=floor_poly,
            mirror_layout=mirror_layout,
        )

    # ========================================================
    # 4. Draw robot icon last
    # ========================================================
    if robot_pos is not None and icon_path:
        try:
            icon = mpimg.imread(icon_path)
            robot_pos_draw = transform_point(robot_pos, floor_poly, mirror_layout)

            minx, miny, maxx, maxy = floor_poly_draw.bounds
            span = max(maxx - minx, maxy - miny)
            zoom = max(0.12, min(0.28, span / 18000.0))

            draw_robot_at_position(
                ax,
                robot_pos_draw,
                icon,
                zoom,
            )

        except Exception as e:
            print("robot icon load failed:", e)

    # ========================================================
    # 5. Save image
    # ========================================================
    minx, miny, maxx, maxy = floor_poly_draw.bounds
    pad_x = (maxx - minx) * 0.08
    pad_y = (maxy - miny) * 0.08

    ax.set_xlim(minx - pad_x, maxx + pad_x)
    ax.set_ylim(miny - pad_y, maxy + pad_y)
    ax.set_aspect("equal")
    ax.axis("off")

    plt.savefig(output_path, dpi=200)
    plt.close(fig)

def next_walls_after_anchor(anchor_wall, wall_numbers, count=3):
    """
    Example:
    wall_numbers = [1, 2, 3, 4, 5, 6]

    anchor 1 -> [2, 3, 4]
    anchor 4 -> [5, 6, 1]
    """
    if anchor_wall not in wall_numbers:
        return []

    idx = wall_numbers.index(anchor_wall)
    out = []

    for i in range(1, count + 1):
        next_idx = (idx + i) % len(wall_numbers)
        out.append(wall_numbers[next_idx])

    return out

def build_display_to_internal_wall_map(chained_edges, mirror_layout=False):
    """
    Converts displayed Wall number back to internal wall number.

    Example when mirrored:
        internal 6 may display as Wall 2.
        So display_to_internal[2] = 6.
    """
    display_to_internal = {}

    for internal_wall, _, _ in chained_edges:
        display_wall = get_display_wall_label(
            internal_wall,
            mirror_layout=mirror_layout,
        )
        display_to_internal[display_wall] = internal_wall

    return display_to_internal


def rotate_sequence_after_anchor(sequence, anchor_value, count):
    """
    Example:
        sequence = [1, 2, 3, 4, 5, 6]
        anchor_value = 1
        count = 3

    Result:
        [2, 3, 4]
    """
    if not sequence:
        return []

    if anchor_value not in sequence:
        anchor_value = sequence[0]

    start_idx = sequence.index(anchor_value)
    out = []

    for i in range(1, count + 1):
        idx = (start_idx + i) % len(sequence)
        out.append(sequence[idx])

    return out


# def auto_assign_target_walls_by_display_sequence(
#     chained_edges,
#     mirror_layout=False,
#     walls_per_position=3,
# ):
#     """
#     Correct arrow image assignment.

#     This uses displayed wall labels, not nearest distance.

#     For 6 walls:
#         pos1 = Wall 2, Wall 3, Wall 4
#         pos2 = Wall 5, Wall 6, Wall 1

#     Then it converts those display wall labels back into internal wall IDs
#     for drawing.
#     """

#     display_to_internal = build_display_to_internal_wall_map(
#         chained_edges=chained_edges,
#         mirror_layout=mirror_layout,
#     )

#     display_wall_numbers = sorted(display_to_internal.keys())

#     if not display_wall_numbers:
#         return {
#             "pos1": [],
#             "pos2": [],
#             "pos1_display": [],
#             "pos2_display": [],
#         }

#     # Anchor is display Wall 1.
#     # Position 1 covers the next 3 walls after Wall 1.
#     pos1_display_targets = rotate_sequence_after_anchor(
#         sequence=display_wall_numbers,
#         anchor_value=1,
#         count=walls_per_position,
#     )

#     # Position 2 continues after the last pos1 wall.
#     if pos1_display_targets:
#         pos2_anchor_display = pos1_display_targets[-1]
#     else:
#         pos2_anchor_display = 1

#     pos2_display_targets = rotate_sequence_after_anchor(
#         sequence=display_wall_numbers,
#         anchor_value=pos2_anchor_display,
#         count=walls_per_position,
#     )

#     pos1_internal_targets = [
#         display_to_internal[d]
#         for d in pos1_display_targets
#         if d in display_to_internal
#     ]

#     pos2_internal_targets = [
#         display_to_internal[d]
#         for d in pos2_display_targets
#         if d in display_to_internal
#     ]

#     print("pos1 display target walls =", pos1_display_targets)
#     print("pos1 internal target walls =", pos1_internal_targets)

#     print("pos2 display target walls =", pos2_display_targets)
#     print("pos2 internal target walls =", pos2_internal_targets)

#     return {
#         "pos1": pos1_internal_targets,
#         "pos2": pos2_internal_targets,
#         "pos1_display": pos1_display_targets,
#         "pos2_display": pos2_display_targets,
#     }

def auto_assign_target_walls_by_display_sequence(
    chained_edges,
    mirror_layout=False,
    walls_per_position=3,
):
    """
    Fixed robot position assignment by DISPLAY wall number.

    Position 1:
        Wall 4
        Wall 5
        Wall 6

    Position 2:
        Wall 1
        Wall 2
        Wall 3

    Display wall numbers are converted back to internal wall
    numbers so this also works when the layout is mirrored.
    """

    display_to_internal = build_display_to_internal_wall_map(
        chained_edges=chained_edges,
        mirror_layout=mirror_layout,
    )

    # ========================================================
    # Fixed machine position grouping
    # ========================================================
    pos1_display_targets = [
        4,
        5,
        6,
    ]

    pos2_display_targets = [
        1,
        2,
        3,
    ]

    # ========================================================
    # Display wall -> internal wall
    # ========================================================
    pos1_internal_targets = [
        display_to_internal[d]
        for d in pos1_display_targets
        if d in display_to_internal
    ]

    pos2_internal_targets = [
        display_to_internal[d]
        for d in pos2_display_targets
        if d in display_to_internal
    ]

    print(
        "pos1 display target walls =",
        pos1_display_targets,
    )

    print(
        "pos1 internal target walls =",
        pos1_internal_targets,
    )

    print(
        "pos2 display target walls =",
        pos2_display_targets,
    )

    print(
        "pos2 internal target walls =",
        pos2_internal_targets,
    )

    return {
        "pos1": pos1_internal_targets,
        "pos2": pos2_internal_targets,

        "pos1_display": pos1_display_targets,
        "pos2_display": pos2_display_targets,
    }


def make_position_wall_output_path(base_output_path, position_name, display_wall):
    base = Path(base_output_path)
    folder = base.parent
    suffix = base.suffix if base.suffix else ".png"
    return str(folder / f"{position_name}_wall{display_wall}{suffix}")

def build_position_wall_arrow_rows(
    pos1,
    pos2,
    chained_edges,
    floor_poly,
    layout_mirrored=False,
    walls_per_position=3,
):
    """
    Build position-wall arrow data as a variable array/list.
    This does NOT generate images.

    Used later for Stage Excel generation.

    Output:
        [
            {
                "Position": "pos1",
                "Display Wall": 2,
                "Internal Wall": 2,
                "Arrow Start X": ...,
                "Arrow Start Y": ...,
                "Arrow End X": ...,
                "Arrow End Y": ...,
                "Image Name": "pos1_wall2.png",
            },
            ...
        ]
    """

    auto_target_walls = auto_assign_target_walls_by_display_sequence(
        chained_edges=chained_edges,
        mirror_layout=layout_mirrored,
        walls_per_position=walls_per_position,
    )

    edge_map = {
        wnum: (a, b)
        for wnum, a, b in chained_edges
    }

    rows = []

    position_data = [
        ("pos1", pos1, auto_target_walls["pos1"]),
        ("pos2", pos2, auto_target_walls["pos2"]),
    ]

    for position_name, robot_pos, target_walls in position_data:
        if robot_pos is None:
            continue

        robot_pos_draw = transform_point(
            robot_pos,
            floor_poly,
            layout_mirrored,
        )

        for internal_wall in target_walls:
            if internal_wall not in edge_map:
                continue

            a, b = edge_map[internal_wall]

            # Aim arrow at actual wall segment, not wall text
            wall_hit_pt = closest_point_on_segment(
                robot_pos,
                a,
                b,
            )

            wall_hit_pt_draw = transform_point(
                wall_hit_pt,
                floor_poly,
                layout_mirrored,
            )

            arrow_start, arrow_end = shorten_line(
                robot_pos_draw,
                wall_hit_pt_draw,
                shrink_start=POSITION_WALL_ARROW_STYLE["arrow_shrink_start"],
                shrink_end=POSITION_WALL_ARROW_STYLE["arrow_shrink_end"],
            )

            display_wall = get_display_wall_label(
                internal_wall,
                mirror_layout=layout_mirrored,
            )

            image_name = f"{position_name}_wall{display_wall}.png"

            rows.append({
                "Position": position_name,
                "Display Wall": display_wall,
                "Internal Wall": internal_wall,

                "Robot X": float(robot_pos[0]),
                "Robot Y": float(robot_pos[1]),

                "Wall Hit X": float(wall_hit_pt[0]),
                "Wall Hit Y": float(wall_hit_pt[1]),

                "Arrow Start X": float(arrow_start[0]),
                "Arrow Start Y": float(arrow_start[1]),
                "Arrow End X": float(arrow_end[0]),
                "Arrow End Y": float(arrow_end[1]),

                "Image Name": image_name,
                "Arrow Color": POSITION_WALL_ARROW_STYLE["color"],
                "Arrow Line Width": POSITION_WALL_ARROW_STYLE["line_width"],
            })

    return rows

def draw_layout_on_ax(
    ax,
    visited,
    opening_dicts,
    position_key,
    floor_poly=None,
    chained_edges=None,
    layout_mirrored=False,
    position_data=None,
):
    # Example structure only:
    # 1. draw floor polygon
    # 2. draw walls
    # 3. draw openings
    # 4. draw wall labels
    # 5. draw robot position marker if needed
    #
    # MOVE YOUR EXISTING export_wall_schematic_2d() geometry drawing here

    if floor_poly is not None:
        try:
            x, y = floor_poly.exterior.xy
            ax.plot(x, y, color="black", linewidth=2)
        except Exception:
            pass

    if chained_edges:
        for wnum, a_raw, b_raw in chained_edges:
            try:
                a = transform_point(a_raw, floor_poly, layout_mirrored)
                b = transform_point(b_raw, floor_poly, layout_mirrored)

                ax.plot(
                    [a[0], b[0]],
                    [a[1], b[1]],
                    color=WALL_COLOR,
                    linewidth=LINE_W,
                    zorder=10,
                )

                cx = (a[0] + b[0]) / 2
                cy = (a[1] + b[1]) / 2

                display_wnum = get_display_wall_label(
                    wnum,
                    mirror_layout=layout_mirrored,
                )

                ax.text(
                    cx,
                    cy,
                    f"Wall {display_wnum}",
                    fontsize=12,
                    weight="bold",
                    ha="center",
                    va="center",
                    color=LABEL_COLOR,
                    zorder=11,
                )

            except Exception as e:
                print("[STAGE IMAGE] failed to draw wall:", wnum, e)
                continue

    # Also draw your wall labels / wall blocks / opening marks here
    # based on visited + position_data

def export_stage_wall_arrow_images(
    visited,
    opening_dicts,
    output_folder,
    position_wall_arrow_rows,
    layout_data,
    force_mirror_layout=False,
):
    os.makedirs(output_folder, exist_ok=True)

    chained_edges = layout_data["chained_edges"]
    wall_seg = layout_data["wall_seg"]
    reversed_wall = layout_data["reversed_wall"]
    doors_by_wall = layout_data["doors_by_wall"]
    floor_poly = layout_data["floor_poly"]
    layout_mirrored = layout_data.get("layout_mirrored", False)

    pos1 = layout_data.get("pos1")
    pos2 = layout_data.get("pos2")
    marking_zone_pos1 = layout_data.get("position_1")
    marking_zone_pos2 = layout_data.get("position_2")
    icon_path = layout_data.get("icon_path")

    for row in position_wall_arrow_rows:
        display_wall = int(row["Display Wall"])
        internal_wall = int(row["Internal Wall"])
        position_name = row.get("Position", "pos1")

        image_name = row.get("Stage Image Name", f"wall{display_wall}.png")
        output_path = os.path.join(output_folder, image_name)

        if position_name == "pos1":
            robot_pos = pos1
            zone_data = marking_zone_pos1
        else:
            robot_pos = pos2
            zone_data = marking_zone_pos2

        render_and_save_schematic(
            chained_edges=chained_edges,
            wall_seg=wall_seg,
            reversed_wall=reversed_wall,
            doors_by_wall=doors_by_wall,
            floor_poly=floor_poly,
            output_path=output_path,
            robot_pos=robot_pos,
            icon_path=icon_path,
            mirror_layout=layout_mirrored,
            marking_zone_data=zone_data,
            robot_position_name=position_name,
            arrow_target_walls=[internal_wall],
        )

        print(
            f"[IMAGE] Saved stage image: {output_path} "
            f"Display Wall={display_wall}, Internal Wall={internal_wall}, Position={position_name}"
        )

def draw_base_wall_layout(
    ax,
    visited,
    opening_dicts,
    force_mirror_layout=False,
    highlight_internal_wall=None,
    highlight_display_wall=None,
):
    """
    Draw the base layout onto ax.
    Reuse your existing plotting logic here.
    """

    # -------------------------------------------------------
    # MOVE YOUR EXISTING drawing code here
    # -------------------------------------------------------
    # Example:
    # - draw all walls
    # - draw openings
    # - draw labels
    # - optionally highlight one wall
    # -------------------------------------------------------

    for idx, wall_dict in enumerate(visited, start=1):
        wall = next(iter(wall_dict.values())) if isinstance(wall_dict, dict) and wall_dict else None
        if wall is None:
            continue

        # Your existing wall plotting logic goes here
        # Example:
        # x = ...
        # y = ...
        # ax.plot(...)

        # Highlight target internal wall
        if highlight_internal_wall is not None and idx == int(highlight_internal_wall):
            # use your highlight logic here
            pass

# ============================================================
# EXPORT
# ============================================================
def export_wall_schematic_2d(
    visited,
    opening_dicts=None,
    output_path="wall_schematic_2d.png",
    output_path_2="wall_schematic_2d_2.png",
    force_mirror_layout=False,
    max_marking_size_mm=None,
    min_marking_size_mm=None,
    return_marking_zone_data=False,
):
    if opening_dicts is None:
        opening_dicts = []

    wall_seg = {}
    for i, wdict in enumerate(visited):
        wnum = i + 1
        wall = list(wdict.values())[0]
        p0, p1 = wall_endpoints_2d(wall)
        wall_seg[wnum] = {"p0": p0, "p1": p1, "wall": wall}

    chained_edges = []
    reversed_wall = {}

    w1 = wall_seg[1]
    w2 = wall_seg[2]
    if min(dist(w1["p0"], w2["p0"]), dist(w1["p0"], w2["p1"])) <= min(
        dist(w1["p1"], w2["p0"]), dist(w1["p1"], w2["p1"])
    ):
        cur = w1["p0"]
        start, end = w1["p0"], w1["p1"]
        reversed_wall[1] = False
    else:
        cur = w1["p1"]
        start, end = w1["p1"], w1["p0"]
        reversed_wall[1] = True

    wall = wall_seg[1]["wall"]
    start, end = straighten_by_ifc_axis(start, end, wall)
    chained_edges.append((1, start, end))
    cur = end

    for wnum in range(2, len(wall_seg) + 1):
        seg = wall_seg[wnum]
        p0, p1 = seg["p0"], seg["p1"]
        if dist(cur, p0) <= dist(cur, p1):
            start, end = p0, p1
            reversed_wall[wnum] = False
        else:
            start, end = p1, p0
            reversed_wall[wnum] = True
        if dist(cur, start) <= SNAP_TOL:
            start = cur
        wall = wall_seg[wnum]["wall"]
        start, end = straighten_by_ifc_axis(start, end, wall)
        chained_edges.append((wnum, start, end))
        cur = end

    chained_edges = snap_loop_to_grid(chained_edges)
    wn_last, a_last, b_last = chained_edges[-1]
    first_start = chained_edges[0][1]

    if dist(b_last, first_start) <= SNAP_TOL:
        chained_edges[-1] = (wn_last, a_last, first_start)

    derived_max_gauge, derived_min_gauge, wall_lengths_ranked = derive_marking_sizes_from_wall_lengths(chained_edges)

    if max_marking_size_mm is None:
        max_marking_size_mm = derived_max_gauge

    if min_marking_size_mm is None:
        min_marking_size_mm = derived_min_gauge

    print("wall_lengths_ranked =", wall_lengths_ranked)
    print("derived max_marking_size_mm =", max_marking_size_mm)
    print("derived min_marking_size_mm =", min_marking_size_mm)

    segs = [(a, b) for (_, a, b) in chained_edges]
    first = segs[0][0]
    last = segs[-1][1]
    if dist(last, first) > SNAP_TOL:
        segs.append((last, first))

    segs = snap_points_to_nodes(segs, tol=SNAP_TOL)
    lines = [LineString([a, b]) for (a, b) in segs]
    merged = linemerge(unary_union(lines))
    polygons = list(polygonize(merged))
    if not polygons:
        raise RuntimeError("Failed to build floor polygon")
    floor_poly = max(polygons, key=lambda p: p.area)

    doors_by_wall = {}
    door_ops = [op for op in opening_dicts if is_likely_door(op)]
    seg_ab = {wnum: (a, b) for (wnum, a, b) in chained_edges}
    for op in door_ops:
        wnum = 1
        if wnum not in seg_ab:
            continue
        wall = wall_seg[wnum]["wall"]
        t_range = opening_t_range_on_wall_local(op, wall)
        if not t_range:
            continue
        t1, t2 = t_range
        if reversed_wall.get(wnum, False):
            t1, t2 = 1 - t2, 1 - t1
        doors_by_wall.setdefault(wnum, []).append((t1, t2))

    if 1 in doors_by_wall and len(doors_by_wall[1]) > 1:
        doors_by_wall[1].sort(key=lambda tt: (tt[0] + tt[1]) / 2.0, reverse=True)
        doors_by_wall[1] = [doors_by_wall[1][0]]
    for wnum in list(doors_by_wall.keys()):
        if wnum == 1:
            continue
        doors_by_wall[wnum].sort(key=lambda tt: (tt[1] - tt[0]), reverse=True)
        doors_by_wall[wnum] = [doors_by_wall[wnum][0]]

    pos1 = get_robot_position_1(chained_edges, floor_poly)
    pos2 = get_robot_position_2(chained_edges, floor_poly)

    auto_layout_mirrored = is_layout_mirrored_by_shape(floor_poly)
    #layout_mirrored = auto_layout_mirrored or 
    layout_mirrored = bool(force_mirror_layout)
    print("auto_layout_mirrored =", auto_layout_mirrored)
    print("force_mirror_layout =", force_mirror_layout)
    print("final_layout_mirrored =", layout_mirrored)

    marking_zone_pos1 = None
    marking_zone_pos2 = None

    if MARKING_GAUGE_ENABLED:
        marking_zone_pos1 = build_robot_marking_zone_polygons(
            robot_pos=pos1,
            floor_poly=floor_poly,
            chained_edges=chained_edges,
            mirror_layout=layout_mirrored,
            max_size=max_marking_size_mm,
            min_size=min_marking_size_mm,
        )

        marking_zone_pos2 = build_robot_marking_zone_polygons(
            robot_pos=pos2,
            floor_poly=floor_poly,
            chained_edges=chained_edges,
            mirror_layout=layout_mirrored,
            max_size=max_marking_size_mm,
            min_size=min_marking_size_mm,
        )

    icon_path = find_robot_icon_path()

    render_and_save_schematic(
        chained_edges=chained_edges,
        wall_seg=wall_seg,
        reversed_wall=reversed_wall,
        doors_by_wall=doors_by_wall,
        floor_poly=floor_poly,
        output_path=output_path,
        robot_pos=pos1,
        icon_path=icon_path,
        mirror_layout=layout_mirrored,
        marking_zone_data=marking_zone_pos1,
        robot_position_name="pos1",
        arrow_target_walls=None,
    )

    if output_path_2:
        render_and_save_schematic(
            chained_edges=chained_edges,
            wall_seg=wall_seg,
            reversed_wall=reversed_wall,
            doors_by_wall=doors_by_wall,
            floor_poly=floor_poly,
            output_path=output_path_2,
            robot_pos=pos2,
            icon_path=icon_path,
            mirror_layout=layout_mirrored,
            marking_zone_data=marking_zone_pos2,
            robot_position_name="pos2",
            arrow_target_walls=None,
        )
    # ========================================================
    # Separate arrow images by filename
    # Main images stay clean. Each output contains only one wall arrow.
    # ========================================================
    auto_target_walls = auto_assign_target_walls_by_display_sequence(
        chained_edges=chained_edges,
        mirror_layout=layout_mirrored,
        walls_per_position=3,
    )

    # separate_arrow_exports = [
    #     ("pos1", pos1, output_path, auto_target_walls["pos1"], marking_zone_pos1),
    #     ("pos2", pos2, output_path_2, auto_target_walls["pos2"], marking_zone_pos2),
    # ]

    # for position_name, robot_position, base_path, target_walls, zone_data in separate_arrow_exports:
    #     if not base_path:
    #         continue

    #     for internal_wall in target_walls:
    #         display_wall = get_display_wall_label(
    #             internal_wall,
    #             mirror_layout=layout_mirrored,
    #         )

    #         arrow_output_path = make_position_wall_output_path(
    #             base_output_path=base_path,
    #             position_name=position_name,
    #             display_wall=display_wall,
    #         )

    #         render_and_save_schematic(
    #             chained_edges=chained_edges,
    #             wall_seg=wall_seg,
    #             reversed_wall=reversed_wall,
    #             doors_by_wall=doors_by_wall,
    #             floor_poly=floor_poly,
    #             output_path=arrow_output_path,
    #             robot_pos=robot_position,
    #             icon_path=icon_path,
    #             mirror_layout=layout_mirrored,
    #             marking_zone_data=zone_data,
    #             robot_position_name=position_name,
    #             arrow_target_walls=[internal_wall],
    #         )

    #         print("saved arrow image:", arrow_output_path)
    position_wall_arrow_rows = build_position_wall_arrow_rows(
        pos1=pos1,
        pos2=pos2,
        chained_edges=chained_edges,
        floor_poly=floor_poly,
        layout_mirrored=layout_mirrored,
        walls_per_position=3,
    )

    print("position_wall_arrow_rows =", position_wall_arrow_rows)
    return {
        "floor_poly": floor_poly,
        "chained_edges": chained_edges,
        "wall_seg": wall_seg,
        "reversed_wall": reversed_wall,
        "doors_by_wall": doors_by_wall,
        "layout_mirrored": layout_mirrored,
        "position_1": marking_zone_pos1,
        "position_2": marking_zone_pos2,
        "pos1": pos1,
        "pos2": pos2,
        "icon_path": icon_path,
        "position_wall_arrow_rows": position_wall_arrow_rows,
    }

def draw_zone_geom(ax, geom, floor_poly, color, alpha, edge_width, mirror_layout=False, zorder_fill=2, zorder_edge=3):
    if geom is None or geom.is_empty:
        return

    geoms = []
    if geom.geom_type == "Polygon":
        geoms = [geom]
    elif geom.geom_type == "MultiPolygon":
        geoms = list(geom.geoms)
    else:
        return

    for poly in geoms:
        pts = polygon_to_xy_list(poly)
        if not pts:
            continue

        pts = [transform_point(p, floor_poly, mirror_layout) for p in pts]
        if len(pts) < 3:
            continue

        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]

        ax.fill(xs, ys, facecolor=color, edgecolor="none", alpha=alpha, zorder=zorder_fill)

        xs2 = xs + [xs[0]]
        ys2 = ys + [ys[0]]
        ax.plot(xs2, ys2, color=color, linewidth=edge_width, zorder=zorder_edge)