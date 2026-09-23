#!/usr/bin/env python3
"""
Clean IFC -> 3 STL exporter for Greyform PBU scan stages.

Outputs:
  01: PBU wall only
  02: PBU wall + BSS floor/head + box-up + pipe/header blocks
  03: PBU wall + BSS floor/head + box-up + pipe/header blocks + OUTER external skin only

Important rules:
  - Exclude ceiling / compound ceiling / ceiling access panel
  - Exclude glass
  - Exclude toilet/WC, hand shower, hose/cord and loose bathroom fittings
  - Do not use IfcBuildingElementProxy by class alone; proxy must also have pipe/header terms in name
  - Stage 3 outer cover is based on PBU wall+box-up core bounds, not floor-expanded bounds
"""

import re
from pathlib import Path

import numpy as np
import meshio

try:
    import ifcopenshell
    import ifcopenshell.geom as geom
except Exception as e:
    raise RuntimeError(f"ifcopenshell import failed: {e}")


# ============================================================
# Text helpers
# ============================================================

def _norm(text) -> str:
    if text is None:
        return ""
    text = str(text).lower()
    text = text.replace("\\", "/")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _product_text(prod) -> str:
    parts = [
        getattr(prod, "Name", "") or "",
        getattr(prod, "ObjectType", "") or "",
        getattr(prod, "Description", "") or "",
        prod.is_a() if hasattr(prod, "is_a") else "",
    ]
    return _norm(" | ".join(parts))


def _stable_key(name: str) -> str:
    n = _norm(name)
    if not n:
        return ""
    return n.split(":")[0].strip()


def _keys_from_names(names) -> set:
    keys = set()
    if not names:
        return keys
    for name in names:
        key = _stable_key(name)
        if key:
            keys.add(key)
    return keys


# ============================================================
# IFC product helpers
# ============================================================

def _all_products(model):
    return list(model.by_type("IfcProduct"))


def _unique_products(products):
    selected = []
    seen = set()
    for p in products:
        gid = getattr(p, "GlobalId", None)
        if gid and gid in seen:
            continue
        if gid:
            seen.add(gid)
        selected.append(p)
    return selected


# ============================================================
# Selection rules
# ============================================================

def _is_ceiling_or_access_panel(prod) -> bool:
    text = _product_text(prod)
    blocked_terms = [
        "ceiling",
        "compound ceiling",
        "access panel",
        "ceiling access panel",
        "bss.ceiling",
        "bss ceiling",
    ]
    return any(t in text for t in blocked_terms)

def _is_ceiling_shell(prod) -> bool:
    """
    Ceiling geometry that should appear in Stage 2 / Stage 3 STL.
    """
    text = _product_text(prod)
    cls = _norm(prod.is_a())

    return (
        "ceiling" in text
        or "compound ceiling" in text
        or "bss.ceiling" in text
        or "bss ceiling" in text
        or "access panel" in text
        or cls in {"ifccovering", "ifcbuildingelementproxy"} and "ceiling" in text
    )


def _is_ceiling_block_excluded(prod) -> bool:
    """
    Ceiling should not become pipe/header/opening/cabinet obstacle block.
    """
    text = _product_text(prod)

    blocked_terms = [
        "ceiling",
        "compound ceiling",
        "access panel",
        "ceiling access panel",
        "bss.ceiling",
        "bss ceiling",
    ]

    return any(t in text for t in blocked_terms)

def _is_opening_cover_target(prod) -> bool:
    if _is_ceiling_or_access_panel(prod):
        return False

    cls = _norm(prod.is_a())
    text = _product_text(prod)

    return (
        cls == "ifcopeningelement"
        or "ifcopeningelement" in text
        or "opening" in text
        or "window" in text
        or "door" in text
    )


def _opening_cover_blocks(opening_products, shell_min, shell_max, clearance=0.02):
    """
    Fill window / door / opening holes as STL block approximations.
    """
    blocks = []

    if shell_min is None or shell_max is None:
        return blocks

    for p in opening_products:
        bmin, bmax = _product_bbox(p)

        if not _bbox_intersects_shell(
            bmin,
            bmax,
            shell_min,
            shell_max,
            tolerance=0.15,
        ):
            continue

        size = bmax - bmin
        center = (bmin + bmax) / 2.0

        sx = float(max(size[0] + clearance * 2.0, 0.08))
        sy = float(max(size[1] + clearance * 2.0, 0.08))
        sz = float(max(size[2] + clearance * 2.0, 0.08))

        vertices, faces = _make_box_vertices_faces(
            cx=float(center[0]),
            cy=float(center[1]),
            cz=float(center[2]),
            sx=sx,
            sy=sy,
            sz=sz,
        )
        blocks.append((vertices, faces))

    print(f"[STL] Opening cover blocks: {len(blocks)}")
    return blocks

def _is_opening_or_void(prod) -> bool:
    cls = _norm(prod.is_a())
    text = _product_text(prod)
    if cls in {"ifcopeningelement", "ifcvoidingfeature", "ifcfeatureelementsubtraction"}:
        return True
    return "ifcopeningelement" in text or "opening" in text or "void" in text


def _is_glass(prod) -> bool:
    return "glass" in _product_text(prod)


def _is_pbu_wall(prod, pbu_wall_keys: set) -> bool:
    cls = _norm(prod.is_a())
    text = _product_text(prod)
    if cls not in {"ifcwall", "ifcwallstandardcase"}:
        return False
    if pbu_wall_keys:
        return any(key in text for key in pbu_wall_keys)
    return "basic wall:bss.50" in text


def _is_bss_floor(prod) -> bool:
    if _is_ceiling_shell(prod):
        return False
    cls = _norm(prod.is_a())
    text = _product_text(prod)
    if cls != "ifcslab":
        return False
    return (
        "bss.floor" in text
        or "bss floor" in text
        or "floor:bss" in text
        or "basic floor" in text
        or "floor" in text
    )


def _is_boxup(prod) -> bool:
    if _is_ceiling_or_access_panel(prod):
        return False
    text = _product_text(prod)
    return (
        "box-up1:box-up" in text
        or "box-up1" in text
        or "box up1" in text
        or "box-up" in text
        or "box up" in text
    )


def _is_stage2_stage3_excluded_fixture(prod) -> bool:
    text = _product_text(prod)
    blocked_terms = [
        "toilet",
        "wc",
        "water closet",
        "hand shower",
        "shower set",
        "shower hose",
        "hose",
        "cord",
        "basin cabinet",
        "mirror cabinet",
        "chair bracket",
        "basin mixer",
        "bib tap",
        "gessi",
        "gomgo",
        "laufen",
        "lauffen",
    ]
    return any(t in text for t in blocked_terms)


def _is_water_header_or_pipe(prod) -> bool:
    """
    Select pipe / water header / pipe connection products.
    IfcBuildingElementProxy is accepted only if the name also contains pipe/header/drain terms.
    """
    if _is_ceiling_block_excluded(prod):
        return False
    if _is_stage2_stage3_excluded_fixture(prod):
        return False

    cls = _norm(prod.is_a())
    text = _product_text(prod)

    pipe_classes = [
        "ifcflowsegment",
        "ifcflowfitting",
        "ifcflowterminal",
        "ifcdistributionport",
        "ifcdistributionflowelement",
        "ifcdistributionelement",
        "ifcpipefitting",
        "ifcpipesegment",
    ]

    name_terms = [
        "water header",
        "header",
        "manifold",
        "water distribution",
        "pipe",
        "pipeconnection",
        "pipe connection",
        "connector",
        "connection",
        "sanitary",
        "drain",
        "floor drain",
        "floor_drain",
        "waste",
        "trap",
        "bottle trap",
        "vp",
        "sp",
    ]

    is_pipe_class = any(t in cls for t in pipe_classes)
    is_named_pipe = any(t in text for t in name_terms)
    is_proxy_named_pipe = "ifcbuildingelementproxy" in cls and is_named_pipe

    return is_pipe_class or is_named_pipe or is_proxy_named_pipe

def _pbu_shell_products(
    model,
    pbu_wall_names=None,
    include_floor=False,
    include_boxup=False,
    include_ceiling=False,
):
    pbu_wall_keys = _keys_from_names(pbu_wall_names)
    selected = []

    for p in _all_products(model):
        if _is_opening_or_void(p):
            continue

        if _is_glass(p):
            continue

        if _is_pbu_wall(p, pbu_wall_keys):
            selected.append(p)
            continue

        if include_floor and _is_bss_floor(p):
            selected.append(p)
            continue

        if include_boxup and _is_boxup(p):
            selected.append(p)
            continue

        if include_ceiling and _is_ceiling_shell(p):
            selected.append(p)
            continue

    return _unique_products(selected)


# ============================================================
# Mesh helpers
# ============================================================

def _make_settings():
    settings = geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    try:
        settings.set(settings.USE_PYTHON_OPENCASCADE, True)
    except Exception:
        pass
    return settings


def _add_ifc_product(settings, prod, all_vertices, all_faces):
    shape = geom.create_shape(settings, prod)
    g = shape.geometry
    verts = np.array(g.verts, dtype=float).reshape(-1, 3)
    faces = np.array(g.faces, dtype=int).reshape(-1, 3)
    if verts.size == 0 or faces.size == 0:
        return False
    base = len(all_vertices)
    all_vertices.extend(verts.tolist())
    all_faces.extend((faces + base).tolist())
    return True


def _product_bbox(prod):
    settings = _make_settings()
    try:
        shape = geom.create_shape(settings, prod)
        verts = np.array(shape.geometry.verts, dtype=float).reshape(-1, 3)
        if verts.size == 0:
            return None, None
        return verts.min(axis=0), verts.max(axis=0)
    except Exception:
        return None, None


def _mesh_bounds_from_products(products):
    settings = _make_settings()
    pts = []
    for p in products:
        try:
            shape = geom.create_shape(settings, p)
            verts = np.array(shape.geometry.verts, dtype=float).reshape(-1, 3)
            if verts.size:
                pts.extend(verts.tolist())
        except Exception:
            continue
    if not pts:
        return None, None, None
    arr = np.array(pts, dtype=float)
    mn = arr.min(axis=0)
    mx = arr.max(axis=0)
    return mn, mx, mx - mn


def _bbox_intersects_shell(bmin, bmax, shell_min, shell_max, tolerance=0.10):
    if bmin is None or bmax is None or shell_min is None or shell_max is None:
        return False
    return not (
        bmax[0] < shell_min[0] - tolerance or bmin[0] > shell_max[0] + tolerance or
        bmax[1] < shell_min[1] - tolerance or bmin[1] > shell_max[1] + tolerance or
        bmax[2] < shell_min[2] - tolerance or bmin[2] > shell_max[2] + tolerance
    )


def _make_box_vertices_faces(cx, cy, cz, sx, sy, sz):
    x0 = cx - sx / 2.0
    x1 = cx + sx / 2.0
    y0 = cy - sy / 2.0
    y1 = cy + sy / 2.0
    z0 = cz - sz / 2.0
    z1 = cz + sz / 2.0

    vertices = np.array([
        [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
        [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1],
    ], dtype=float)

    faces = np.array([
        [0, 1, 2], [0, 2, 3],
        [4, 6, 5], [4, 7, 6],
        [0, 4, 5], [0, 5, 1],
        [1, 5, 6], [1, 6, 2],
        [2, 6, 7], [2, 7, 3],
        [3, 7, 4], [3, 4, 0],
    ], dtype=int)

    return vertices, faces


def _append_mesh(all_vertices, all_faces, vertices, faces):
    base = len(all_vertices)
    all_vertices.extend(vertices.tolist())
    all_faces.extend((faces + base).tolist())


def _blocks_from_products(
    products,
    shell_min,
    shell_max,
    clearance=0.12,
    min_xy=0.20,
    min_z=0.18,
    max_xy=0.50,
    max_z=0.65,
    tolerance=0.10,
    label="blocks",
):
    blocks = []
    if shell_min is None or shell_max is None:
        return blocks

    for p in products:
        bmin, bmax = _product_bbox(p)
        if not _bbox_intersects_shell(bmin, bmax, shell_min, shell_max, tolerance=tolerance):
            continue

        size = bmax - bmin
        center = (bmin + bmax) / 2.0

        # Do not pull external/floating objects into the PBU.
        if not (
            shell_min[0] - tolerance <= center[0] <= shell_max[0] + tolerance and
            shell_min[1] - tolerance <= center[1] <= shell_max[1] + tolerance and
            shell_min[2] - tolerance <= center[2] <= shell_max[2] + tolerance
        ):
            continue

        sx = float(np.clip(size[0] + clearance * 2.0, min_xy, max_xy))
        sy = float(np.clip(size[1] + clearance * 2.0, min_xy, max_xy))
        sz = float(np.clip(size[2] + clearance * 2.0, min_z, max_z))

        vertices, faces = _make_box_vertices_faces(
            cx=float(center[0]),
            cy=float(center[1]),
            cz=float(center[2]),
            sx=sx,
            sy=sy,
            sz=sz,
        )
        blocks.append((vertices, faces))

    print(f"[STL] {label}: {len(blocks)}")
    return blocks


def _outer_external_skin_blocks(shell_min, shell_max, skin_thickness=0.08):
    """
    Stage 3 external cover: covers only the OUTER perimeter of the PBU.
    It does not cover internal room/floor area.
    """
    if shell_min is None or shell_max is None:
        return []

    x0, y0, z0 = shell_min
    x1, y1, z1 = shell_max

    height = max(z1 - z0, 0.10)
    zc = (z0 + z1) / 2.0
    width_x = max(x1 - x0, 0.10)
    width_y = max(y1 - y0, 0.10)

    specs = [
        ((x0 + x1) / 2.0, y0 - skin_thickness / 2.0, zc, width_x, skin_thickness, height),
        ((x0 + x1) / 2.0, y1 + skin_thickness / 2.0, zc, width_x, skin_thickness, height),
        (x0 - skin_thickness / 2.0, (y0 + y1) / 2.0, zc, skin_thickness, width_y, height),
        (x1 + skin_thickness / 2.0, (y0 + y1) / 2.0, zc, skin_thickness, width_y, height),
    ]

    blocks = []
    for cx, cy, cz, sx, sy, sz in specs:
        vertices, faces = _make_box_vertices_faces(
            cx=float(cx), cy=float(cy), cz=float(cz),
            sx=float(sx), sy=float(sy), sz=float(sz),
        )
        blocks.append((vertices, faces))

    print(f"[STL] Stage 3 outer external skin blocks: {len(blocks)}")
    return blocks

def _move_vertices_to_origin(vertices, mode="min"):
    """
    Move STL close to origin without changing IFC rotation.

    mode="min":
        minimum X/Y/Z becomes 0,0,0

    mode="center_xy":
        X/Y centered around 0, minimum Z becomes 0
    """
    V = np.array(vertices, dtype=float)

    if V.size == 0:
        return V, np.array([0.0, 0.0, 0.0], dtype=float)

    mn = V.min(axis=0)
    mx = V.max(axis=0)

    if mode == "center_xy":
        center_xy = (mn[:2] + mx[:2]) / 2.0
        offset = np.array([center_xy[0], center_xy[1], mn[2]], dtype=float)
    else:
        offset = mn.astype(float)

    return V - offset, offset

# ============================================================
# STL transform helpers
# ============================================================

def _find_door_origin_corner(model, core_min=None, core_max=None):
    """
    Find a practical door-corner origin from IFC.

    Priority:
      1. IfcDoor / door opening bbox
      2. Large low IfcOpeningElement bbox
      3. Fallback to core_min

    Returns one XYZ point in IFC world coordinates.
    """
    candidates = []

    for p in _all_products(model):
        cls = _norm(p.is_a())
        text = _product_text(p)

        is_door_like = (
            cls == "ifcdoor"
            or "door" in text
            or "door opening" in text
        )

        is_large_opening = (
            cls == "ifcopeningelement"
            and "window" not in text
            and "ceiling" not in text
        )

        if not (is_door_like or is_large_opening):
            continue

        bmin, bmax = _product_bbox(p)
        if bmin is None or bmax is None:
            continue

        size = bmax - bmin

        # Door/opening should be tall enough and near floor.
        if size[2] < 1.0:
            continue

        candidates.append((p, bmin, bmax, size))

    if not candidates:
        print("[STL] Door origin not found. Using core_min as origin.")
        if core_min is not None:
            return np.array(core_min, dtype=float)
        return np.array([0.0, 0.0, 0.0], dtype=float)

    # Prefer the lowest and largest opening/door.
    candidates.sort(
        key=lambda item: (
            item[1][2],                  # lower Z first
            -item[3][0] * item[3][2],    # larger face next
        )
    )

    _, bmin, bmax, _ = candidates[0]

    # Four bottom corners of door/opening bbox.
    door_corners = np.array([
        [bmin[0], bmin[1], bmin[2]],
        [bmin[0], bmax[1], bmin[2]],
        [bmax[0], bmin[1], bmin[2]],
        [bmax[0], bmax[1], bmin[2]],
    ], dtype=float)

    if core_min is not None:
        # Pick the corner closest to the PBU minimum corner.
        ref = np.array([core_min[0], core_min[1], bmin[2]], dtype=float)
        idx = int(np.argmin(np.linalg.norm(door_corners[:, :2] - ref[:2], axis=1)))
        origin = door_corners[idx]
    else:
        origin = door_corners[0]

    print(f"[STL] Door origin corner selected: {origin}")
    return origin


def _transform_vertices_to_door_origin(
    vertices,
    origin_point,
    mirror=True,
    mirror_axis="X",
):
    """
    Move STL origin to door corner and optionally mirror.

    Important:
      - Keeps IFC rotation.
      - Applies same transform to all stages if same origin_point is passed.
      - Mirror happens around the door origin.
    """
    V = np.array(vertices, dtype=float)

    if V.size == 0:
        return V

    origin = np.array(origin_point, dtype=float)

    # Move door corner to 0,0,0.
    V = V - origin

    if mirror:
        axis = str(mirror_axis).upper().strip()

        if axis == "X":
            V[:, 0] *= -1.0
        elif axis == "Y":
            V[:, 1] *= -1.0
        elif axis == "Z":
            V[:, 2] *= -1.0
        else:
            print(f"[STL] Unknown mirror axis '{mirror_axis}', skip mirror.")

    return V

def _write_stl(
    products,
    output_path,
    extra_meshes=None,
    origin_point=None,
    mirror=True,
    mirror_axis="X",
):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    settings = _make_settings()
    all_vertices = []
    all_faces = []
    processed = 0
    skipped = 0

    for p in products:
        try:
            if _add_ifc_product(settings, p, all_vertices, all_faces):
                processed += 1
            else:
                skipped += 1
        except Exception as e:
            skipped += 1
            print(
                f"[WARN] STL skip {getattr(p, 'GlobalId', '?')} "
                f"{p.is_a()} {getattr(p, 'Name', '')}: {e}"
            )

    if extra_meshes:
        for vertices, faces in extra_meshes:
            _append_mesh(all_vertices, all_faces, vertices, faces)

    if not all_vertices or not all_faces:
        print(f"[WARN] No geometry written: {output_path}")
        return {"path": str(output_path), "written": False}

    V = np.array(all_vertices, dtype=float)
    F = np.array(all_faces, dtype=int)

    if origin_point is not None:
        V = _transform_vertices_to_door_origin(
            V,
            origin_point=origin_point,
            mirror=mirror,
            mirror_axis=mirror_axis,
        )

    mn = V.min(axis=0)
    mx = V.max(axis=0)
    span = mx - mn

    print(f"      mirror    : {mirror}, axis={mirror_axis}")
    print(f"      origin    : {origin_point}")
    print(f"[STL] {output_path.name}")
    print(f"      bounds min: {mn}")
    print(f"      bounds max: {mx}")
    print(f"      span      : {span}")
    print(f"      products={processed}, skipped={skipped}, blocks={len(extra_meshes or [])}")
    print(f"      origin offset used: {origin_offset}")
    mesh = meshio.Mesh(points=V, cells=[("triangle", F)])
    meshio.write(str(output_path), mesh, file_format="stl")

    return {
        "path": str(output_path),
        "written": True,
        "products": processed,
        "skipped": skipped,
        "blocks": len(extra_meshes or []),
        "bounds_min": mn.tolist(),
        "bounds_max": mx.tolist(),
        "bounds_span": span.tolist(),
        "origin_offset": origin_offset.tolist(),
    }

def _pbu_wall_products(model, pbu_wall_names=None):
    pbu_wall_keys = _keys_from_names(pbu_wall_names)
    selected = []

    for p in _all_products(model):
        if _is_opening_or_void(p):
            continue

        if _is_glass(p):
            continue

        if _is_pbu_wall(p, pbu_wall_keys):
            selected.append(p)

    return _unique_products(selected)

def _pbu_wall_cover_blocks(
    wall_products,
    cover_thickness=0.08,
):
    """
    Create solid cover panels from real PBU wall bboxes.

    Purpose:
      - Follow PBU wall shape
      - Cover window/door/opening holes
      - Do NOT use opening objects
      - Do NOT create one large rectangular room box

    This creates one solid panel per PBU wall.
    """
    blocks = []

    for wall in wall_products:
        bmin, bmax = _product_bbox(wall)

        if bmin is None or bmax is None:
            continue

        size = bmax - bmin
        center = (bmin + bmax) / 2.0

        length_x = float(size[0])
        length_y = float(size[1])
        height = float(max(size[2], 0.10))

        # Wall mainly runs along X
        if length_x >= length_y:
            sx = max(length_x, 0.10)
            sy = max(length_y, cover_thickness)
            sz = height

        # Wall mainly runs along Y
        else:
            sx = max(length_x, cover_thickness)
            sy = max(length_y, 0.10)
            sz = height

        vertices, faces = _make_box_vertices_faces(
            cx=float(center[0]),
            cy=float(center[1]),
            cz=float(center[2]),
            sx=float(sx),
            sy=float(sy),
            sz=float(sz),
        )

        blocks.append((vertices, faces))

    print(f"[STL] PBU wall solid cover blocks: {len(blocks)}")
    return blocks

def _outer_skin_from_pbu_walls(
    wall_products,
    skin_thickness=0.08,
):
    """
    Stage 3 outer cover following actual PBU wall shape.

    This creates one outside skin per wall instead of one big bounding box.
    It keeps the STL closer to the real PBU outline.
    """
    blocks = []

    if not wall_products:
        return blocks

    mins = []
    maxs = []

    for wall in wall_products:
        bmin, bmax = _product_bbox(wall)
        if bmin is not None:
            mins.append(bmin)
            maxs.append(bmax)

    if not mins:
        return blocks

    core_min = np.min(np.array(mins), axis=0)
    core_max = np.max(np.array(maxs), axis=0)
    core_center = (core_min + core_max) / 2.0

    for wall in wall_products:
        bmin, bmax = _product_bbox(wall)
        if bmin is None:
            continue

        size = bmax - bmin
        center = (bmin + bmax) / 2.0

        length_x = size[0]
        length_y = size[1]
        height = max(size[2], 0.10)

        # Wall mainly runs along X, so thickness direction is Y.
        if length_x >= length_y:
            sx = max(length_x, 0.10)
            sy = skin_thickness
            sz = height

            cx = center[0]

            # Place cover on outside face, away from PBU center.
            if center[1] < core_center[1]:
                cy = bmin[1] - skin_thickness / 2.0
            else:
                cy = bmax[1] + skin_thickness / 2.0

            cz = center[2]

        # Wall mainly runs along Y, so thickness direction is X.
        else:
            sx = skin_thickness
            sy = max(length_y, 0.10)
            sz = height

            if center[0] < core_center[0]:
                cx = bmin[0] - skin_thickness / 2.0
            else:
                cx = bmax[0] + skin_thickness / 2.0

            cy = center[1]
            cz = center[2]

        vertices, faces = _make_box_vertices_faces(
            cx=float(cx),
            cy=float(cy),
            cz=float(cz),
            sx=float(sx),
            sy=float(sy),
            sz=float(sz),
        )

        blocks.append((vertices, faces))

    print(f"[STL] Stage 3 wall-following outer skin blocks: {len(blocks)}")
    return blocks

def _is_window_or_door_opening(prod) -> bool:
    cls = _norm(prod.is_a())
    text = _product_text(prod)

    return (
        cls == "ifcopeningelement"
        or "window" in text
        or "door" in text
        or "opening" in text
    )


# ============================================================
# Public API
# ============================================================

def export_stage_stls_from_ifc(
    ifc_path,
    output_folder,
    output_name,
    stage1_names=None,
    stage2_names=None,
    stage3_names=None,
    stage1_pipe_block_rows=None,
    stage2_pipe_block_rows=None,
    stage3_pipe_block_rows=None,
    pbu_wall_names=None,
):
    """
    01: PBU wall only
    02: PBU wall + BSS floor/head + box-up + pipe/header blocks
    03: PBU wall + BSS floor/head + box-up + pipe/header blocks + OUTER perimeter skin only

    The stage*_names and stage*_pipe_block_rows parameters are kept for compatibility
    with samplewallaxis.py, but this exporter uses IFC geometry directly.
    """
    model = ifcopenshell.open(str(ifc_path))
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    out_01 = output_folder / f"{output_name}_01_empty_wall_only.stl"
    out_02 = output_folder / f"{output_name}_02_stage1_pipe_boxup.stl"
    out_03 = output_folder / f"{output_name}_03_stage2_stage3_pipe_floor.stl"

    wall_only = _pbu_shell_products(
        model,
        pbu_wall_names=pbu_wall_names,
        include_floor=False,
        include_boxup=False,
    )

    stage2_shell = _pbu_shell_products(
        model,
        pbu_wall_names=pbu_wall_names,
        include_floor=True,
        include_boxup=True,
        include_ceiling=True,
    )

    stage3_shell = _pbu_shell_products(
        model,
        pbu_wall_names=pbu_wall_names,
        include_floor=True,
        include_boxup=True,
        include_ceiling=True,
    )

    # Core bounds prevent BSS floor/head from expanding pipe/block filtering.
    core_shell = _pbu_shell_products(
        model,
        pbu_wall_names=pbu_wall_names,
        include_floor=False,
        include_boxup=True,
        include_ceiling=False,
    )
    door_origin = _find_door_origin_corner(
        model,
        core_min=core_min,
        core_max=core_max,
    )

    mirror_stl = True
    mirror_axis = "X"   # change to "Y" if the mirror direction is wrong
    core_min, core_max, _ = _mesh_bounds_from_products(core_shell)

    all_products = _all_products(model)
    pipe_header_products = [
        p for p in all_products
        if not _is_opening_or_void(p)
        and not _is_glass(p)
        and _is_water_header_or_pipe(p)
    ]    
    pbu_walls = _pbu_wall_products(
        model,
        pbu_wall_names=pbu_wall_names,
    )

    # Stage 2:
    # Pipe/header blocks + solid PBU wall covers.
    # This removes visible window/door/opening holes without using opening objects.
    stage2_blocks = []

    stage2_blocks += _blocks_from_products(
        pipe_header_products,
        core_min,
        core_max,
        clearance=0.12,
        min_xy=0.20,
        min_z=0.18,
        max_xy=0.50,
        max_z=0.65,
        tolerance=0.10,
        label="Stage 2 pipe/header blocks",
    )

    stage2_blocks += _pbu_wall_cover_blocks(
        pbu_walls,
        cover_thickness=0.08,
    )

    # Stage 3:
    # Same PBU-shaped wall cover, plus pipe/header blocks.
    # No opening objects are used.
    stage3_blocks = []

    stage3_blocks += _blocks_from_products(
        pipe_header_products,
        core_min,
        core_max,
        clearance=0.12,
        min_xy=0.20,
        min_z=0.18,
        max_xy=0.50,
        max_z=0.65,
        tolerance=0.10,
        label="Stage 3 pipe/header blocks",
    )

    stage3_blocks += _pbu_wall_cover_blocks(
        pbu_walls,
        cover_thickness=0.08,
    )

    stage3_blocks += _outer_skin_from_pbu_walls(
        pbu_walls,
        skin_thickness=0.08,
    )
    print("[STL] Exporting 01 wall only...")
    r1 = _write_stl(
        wall_only,
        out_01,
        origin_point=door_origin,
        mirror=mirror_stl,
        mirror_axis=mirror_axis,
    )

    print("[STL] Exporting 02 with BSS floor/head + box-up + pipe/header...")
    r2 = _write_stl(
        stage2_shell,
        out_02,
        extra_meshes=stage2_blocks,
        origin_point=door_origin,
        mirror=mirror_stl,
        mirror_axis=mirror_axis,
    )

    print("[STL] Exporting 03 with full outer external skin only...")
    r3 = _write_stl(
        stage3_shell,
        out_03,
        extra_meshes=stage3_blocks,
        origin_point=door_origin,
        mirror=mirror_stl,
        mirror_axis=mirror_axis,
    )

    return {
        "wall_only": r1,
        "stage1_pipe_boxup": r2,
        "stage2_stage3_pipe_floor": r3,
    }
