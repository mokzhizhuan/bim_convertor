import numpy as np
import pandas as pd

PIPE_GEOM_TYPES = {
    "IfcPipeSegment",
    "IfcFlowSegment",
    "IfcPipeFitting",
    "IfcFlowFitting",
}
MANUAL_OPENING_BY_IFC_ID = {
    1428478: {
        "name": "BSS.GESSI.SM.49079",
        "wall_number": 3,

        "left_extension": 80.0,
        "right_extension": 65.0,

        "top_height": 80.0,

        "stem_width": 80.0,
        "stem_height": 500.0,
    },
}
MANUAL_OPENING_NAME_KEYWORDS = [
    "gessi.sm.49079",
    "sm.49079",
    "29046000",
]
PORT_TYPES = {"IfcDistributionPort"}
TARGET_HOST_IFC_TYPES = {
    "IfcFlowTerminal",
    "IfcSanitaryTerminal",
    "IfcFlowFitting",
    "IfcBuildingElementProxy",
    "IfcFurnishingElement",
}
TARGET_HOST_KEYWORDS = {
    "floor_drain": [
        "floor drain",
        "floor waste",
        "waste drain",
        "floor trap",
        "fd",
    ],
    "concealed_cistern": [
        "concealed cistern",
        "tece.concealed cistern",
        "cister",
        "tece",
    ],
    "toilet_wc_end": [
        "laufen.wc.820714",
        "820959000 white",
        "laufen.wc",
        "wc.820714",
    ],
    "basin_cabinet": [
        "basin cabinet",
    ],
    "bib_tap": [
        "bib tap",
        "monic.bib tap",
        "t-4d-3",
    ],
    "basin_mixer": [
        "gessi,bm.49001",
        "bm.49001",
        "solferino basin mixer",
        "49001",
    ],
    "hand_shower": [
        "hand shower",
        "hand shower set",
        "emporio shower set",
    ],
}

# Only basin cabinet is allowed to show IfcHostFallback.
# Concealed cistern and BM.49001 must use real host geometry / real IFC type.
HOST_FALLBACK_ALLOWED = {"basin_cabinet"}

HOST_GEOMETRY_ALLOWED = {
    "concealed_cistern",
    "basin_mixer",
    "toilet_wc_end",
    "bib_tap",
    "hand_shower",
    "floor_drain",
}

# Project-specific target bands from the elevation drawing logic:
# - WC pipe target should be almost at floor / bottom outlet level.
# - Hand shower should mark the lower holder / hose connection, not the upper shower set body.
WC_FLOOR_TARGET_Z_MM = 31.0
HAND_SHOWER_HOLDER_DROP_MM = 450.0

WANTED_COLS = [
    "Marking Type",
    "Name",
    "GX",
    "GY",
    "GZ",
    "Position X",
    "Position Y",
    "Position Z",
    "Wall Number",
    "Shape Type",
    "Status",
    "Quadrant",
    "Unnamed",
    "Width",
    "Height",
    "Orientation",
    "Diameter",
]

SANITARY_WALL_OVERRIDE_BY_CLASS = {
    # These are physically close to side walls,
    # but in the elevation / marking output they belong to Wall 5.
    "basin_cabinet": 5,
    "bib_tap": 5,
    "toilet_wc_end": 5,
}

# ---------------------------
# Basic helpers
# ---------------------------


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def _get_name(obj):
    return str(obj.get("name", "") or "")


def _get_type(obj):
    for key in ("type", "ifc_type", "Shape Type"):
        if obj.get(key):
            return str(obj.get(key))
    ent = obj.get("entity")
    if ent is not None:
        try:
            return ent.is_a()
        except Exception:
            pass
    return ""


def _normalize_axis(axis):
    s = str(axis or "").strip().upper()
    if s in {"X", "+X", "-X", "Y", "+Y", "-Y", "Z", "+Z", "-Z"}:
        return s
    return ""


def _entity_id(ent):
    try:
        return ent.id()
    except Exception:
        return None


def _entity_name(ent):
    try:
        return str(getattr(ent, "Name", "") or "")
    except Exception:
        return ""


def _entity_type(ent):
    try:
        return ent.is_a()
    except Exception:
        return ""


def collect_direct_target_hosts(ifc_file):
    """
    Collect sanitary fixtures directly from the IFC.

    This catches fixtures such as:
    BSS.HAND SHOWER SET.MASTER BATH

    which may not be present in all_objs.
    """
    collected = []

    for ifc_type in TARGET_HOST_IFC_TYPES:
        try:
            entities = ifc_file.by_type(ifc_type)
        except Exception:
            entities = []

        for ent in entities:
            name = _entity_name(ent)

            if not name:
                continue

            temp_obj = {
                "entity": ent,
                "ifc_id": _entity_id(ent),
                "name": name,
                "type": _entity_type(ent) or ifc_type,
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
                "vertices": np.array([]),
            }

            # Only keep relevant sanitary targets or manual overrides.
            if (
                classify_target_host(temp_obj)
                or get_manual_opening_config(temp_obj) is not None
            ):
                x, y, z = _placement_xyz_from_entity(ent)

                temp_obj["x"] = x
                temp_obj["y"] = y
                temp_obj["z"] = z

                collected.append(temp_obj)

    return _dedupe_objects(collected)


def _is_excluded_host(obj):
    name_l = _get_name(obj).lower()

    # Flush plate is not a pipe marking target. It is only a face plate.
    if "flush plate" in name_l:
        return True

    # Exclude unrelated bracket geometry.
    if "chair bracket" in name_l:
        return True

    # Exclude top / ceiling shower head target.
    if any(
        k in name_l
        for k in ["63352", "ceiling-mounted", "ceiling shower", "showerhead"]
    ):
        return True

    return False


def classify_target_host(obj):
    name_l = _get_name(obj).lower()
    for cls, keywords in TARGET_HOST_KEYWORDS.items():
        if any(k in name_l for k in keywords):
            return cls
    return ""


def _placement_xyz_from_entity(ent):
    x = y = z = 0.0
    try:
        placement = getattr(ent, "ObjectPlacement", None)
        if placement and hasattr(placement, "RelativePlacement"):
            rp = placement.RelativePlacement
            if hasattr(rp, "Location") and rp.Location:
                coords = list(rp.Location.Coordinates)
                if len(coords) >= 3:
                    x = _safe_float(coords[0])
                    y = _safe_float(coords[1])
                    z = _safe_float(coords[2])
    except Exception:
        pass
    return x, y, z


def _global_bbox(obj):
    x = _safe_float(obj.get("x", 0.0))
    y = _safe_float(obj.get("y", 0.0))
    z = _safe_float(obj.get("z", 0.0))

    verts = obj.get("vertices")
    if isinstance(verts, np.ndarray) and verts.size > 0:
        abs_verts = verts.copy().astype(float)
        abs_verts[:, 0] += x
        abs_verts[:, 1] += y
        abs_verts[:, 2] += z
        min_x, min_y, min_z = abs_verts.min(axis=0)
        max_x, max_y, max_z = abs_verts.max(axis=0)
    else:
        min_x = max_x = x
        min_y = max_y = y
        min_z = max_z = z

    return {
        "min_x": float(min_x),
        "max_x": float(max_x),
        "min_y": float(min_y),
        "max_y": float(max_y),
        "min_z": float(min_z),
        "max_z": float(max_z),
        "center_x": float((min_x + max_x) / 2.0),
        "center_y": float((min_y + max_y) / 2.0),
        "center_z": float((min_z + max_z) / 2.0),
        "size_x": float(max_x - min_x),
        "size_y": float(max_y - min_y),
        "size_z": float(max_z - min_z),
    }


def _bbox_is_point(bbox, tol=1e-6):
    return (
        abs(bbox["size_x"]) <= tol
        and abs(bbox["size_y"]) <= tol
        and abs(bbox["size_z"]) <= tol
    )


def _dist3(a, b):
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    dz = a[2] - b[2]
    return dx * dx + dy * dy + dz * dz


def _looks_like_pipe_protrusion(bbox):
    dims = sorted([bbox["size_x"], bbox["size_y"], bbox["size_z"]])
    largest = dims[2]
    mid = dims[1]
    smallest = dims[0]

    if largest > 650.0:
        return False
    if mid > 350.0:
        return False
    if smallest > 250.0:
        return False
    return True


def _dedupe_objects(objs):
    seen = set()
    unique = []
    for obj in objs:
        key = (
            obj.get("ifc_id"),
            _get_name(obj),
            _get_type(obj),
            round(_safe_float(obj.get("x", 0.0)), 3),
            round(_safe_float(obj.get("y", 0.0)), 3),
            round(_safe_float(obj.get("z", 0.0)), 3),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(obj)
    return unique


# ---------------------------
# IFC object collection
# ---------------------------


def _collect_direct_ifc_types(ifc_file, ifc_types):
    collected = []
    for ifc_type in ifc_types:
        try:
            entities = ifc_file.by_type(ifc_type)
        except Exception:
            entities = []

        for ent in entities:
            x, y, z = _placement_xyz_from_entity(ent)
            collected.append(
                {
                    "entity": ent,
                    "ifc_id": _entity_id(ent),
                    "name": _entity_name(ent) or ifc_type,
                    "type": _entity_type(ent) or ifc_type,
                    "x": x,
                    "y": y,
                    "z": z,
                    "vertices": np.array([]),
                }
            )

    return _dedupe_objects(collected)


def _filter_pipe_like_objects(objs):
    return [obj for obj in objs if _get_type(obj) in PIPE_GEOM_TYPES]


def _filter_port_objects(objs):
    return [obj for obj in objs if _get_type(obj) in PORT_TYPES]


def collect_target_hosts(all_objs):
    hosts = []
    for obj in all_objs:
        if _is_excluded_host(obj):
            continue

        host_class = classify_target_host(obj)
        if not host_class:
            continue

        hosts.append(
            {
                "obj": obj,
                "host_class": host_class,
                "bbox": _global_bbox(obj),
            }
        )
    return hosts


# ---------------------------
# Wall assignment: follow fitting method
# ---------------------------


def _axis_base(axis):
    s = str(axis or "").strip().upper()
    s = s.replace("+", "").replace("-", "")
    if s in {"X", "Y", "Z"}:
        return s
    return ""


def apply_sanitary_wall_override(host_class, wall_ctx):
    """Override wall number for sanitary items that should follow service/elevation wall.

    Nearest wall distance can assign:
    - basin cabinet to Wall 6
    - bib tap to Wall 4

    But for marking/elevation output, both should be assigned to Wall 5.
    """
    forced_wall = SANITARY_WALL_OVERRIDE_BY_CLASS.get(host_class)

    if forced_wall is not None:
        wall_ctx = dict(wall_ctx)
        wall_ctx["wall_number"] = forced_wall

    return wall_ctx


def detect_sanitary_service_wall(host_entries, visited):
    """Automatically detect main sanitary service/elevation wall.

    Uses reliable anchor objects that are usually mounted on the main
    service wall/elevation:
    - basin_mixer / BM.49001
    - concealed_cistern

    Returns the dominant wall number, e.g. 5.
    """
    anchor_classes = {
        "basin_mixer",
        "concealed_cistern",
    }

    wall_votes = {}

    for entry in host_entries or []:
        host_class = entry.get("host_class")
        host_obj = entry.get("obj")

        if host_class not in anchor_classes:
            continue

        wall_ctx = assign_wall_like_fitting(host_obj, visited)
        wall_num = wall_ctx.get("wall_number")

        if wall_num in ("", None, "F"):
            continue

        wall_votes[wall_num] = wall_votes.get(wall_num, 0) + 1

    if not wall_votes:
        return None

    # Return wall with most anchor votes
    return max(wall_votes.items(), key=lambda x: x[1])[0]


def apply_auto_sanitary_service_wall(host_class, wall_ctx, service_wall):
    """Automatically assign related sanitary objects to detected service wall.

    No hardcoded Wall 5 here.
    service_wall is calculated from anchor objects.
    """
    service_wall_classes = {
        "basin_cabinet",
        "bib_tap",
        "toilet_wc_end",
    }

    if service_wall is not None and host_class in service_wall_classes:
        wall_ctx = dict(wall_ctx)
        wall_ctx["wall_number"] = service_wall

    return wall_ctx


def assign_wall_like_fitting(obj, visited):
    """Assign nearest wall using same distance idea as assign_nearest_fitting.

    X-axis wall -> compare Y distance.
    Y-axis wall -> compare X distance.

    Supports X, +X, -X, Y, +Y, -Y.
    Uses bbox center instead of raw obj x/y when geometry exists.
    """
    bbox = _global_bbox(obj)

    ox = bbox["center_x"]
    oy = bbox["center_y"]
    oz = bbox["center_z"]

    min_dist = float("inf")
    nearestwallindex = ""
    nearest_wall = None

    for idx, wall_dict in enumerate(visited or [], start=1):
        wall = (
            next(iter(wall_dict.values()))
            if isinstance(wall_dict, dict) and wall_dict
            else None
        )
        if not wall:
            continue

        wx = _safe_float(wall.get("x", 0.0))
        wy = _safe_float(wall.get("y", 0.0))

        axis_raw = wall.get("axis", "")
        axis = _axis_base(axis_raw)

        if axis == "X":
            # Wall runs along X, so wall plane is selected by Y distance.
            dist = abs(oy - wy)
        elif axis == "Y":
            # Wall runs along Y, so wall plane is selected by X distance.
            dist = abs(ox - wx)
        else:
            # Fallback: choose smaller plane distance.
            dist = min(abs(ox - wx), abs(oy - wy))

        if dist < min_dist:
            min_dist = dist
            nearestwallindex = idx
            nearest_wall = wall

    if oz < 0:
        nearestwallindex = "F"
    name_l = _get_name(obj).lower()
    if "floor drain" in name_l or "floor waste" in name_l or "floor trap" in name_l:
        nearestwallindex = "F"
    return {
        "wall_number": nearestwallindex,
        "axis": _normalize_axis(nearest_wall.get("axis", "")) if nearest_wall else "",
    }


# ---------------------------
# IFC relation maps
# ---------------------------


def build_ifc_relation_maps(ifc_file):
    port_to_host_ids = {}
    host_to_port_ids = {}
    port_to_connected_port_ids = {}

    try:
        nests = ifc_file.by_type("IfcRelNests")
    except Exception:
        nests = []

    for rel in nests:
        try:
            host = rel.RelatingObject
            host_id = _entity_id(host)
            for child in rel.RelatedObjects or []:
                if _entity_type(child) == "IfcDistributionPort":
                    pid = _entity_id(child)
                    if pid is None or host_id is None:
                        continue
                    port_to_host_ids[pid] = host_id
                    host_to_port_ids.setdefault(host_id, []).append(pid)
        except Exception:
            pass

    try:
        rels = ifc_file.by_type("IfcRelConnectsPortToElement")
    except Exception:
        rels = []

    for rel in rels:
        try:
            port = rel.RelatingPort
            host = rel.RelatedElement
            pid = _entity_id(port)
            hid = _entity_id(host)
            if pid is None or hid is None:
                continue
            port_to_host_ids[pid] = hid
            host_to_port_ids.setdefault(hid, []).append(pid)
        except Exception:
            pass

    try:
        pp = ifc_file.by_type("IfcRelConnectsPorts")
    except Exception:
        pp = []

    for rel in pp:
        try:
            p1 = rel.RelatingPort
            p2 = rel.RelatedPort
            id1 = _entity_id(p1)
            id2 = _entity_id(p2)
            if id1 is None or id2 is None:
                continue
            port_to_connected_port_ids.setdefault(id1, set()).add(id2)
            port_to_connected_port_ids.setdefault(id2, set()).add(id1)
        except Exception:
            pass

    return port_to_host_ids, host_to_port_ids, port_to_connected_port_ids


def build_entity_lookup(all_objs, ifc_file):
    by_id = {}
    by_name = {}

    for obj in all_objs:
        eid = obj.get("ifc_id")
        if eid is not None:
            by_id[eid] = obj
        name_l = _get_name(obj).lower()
        if name_l:
            by_name.setdefault(name_l, []).append(obj)

    # Add relation-relevant IFC entities that may not appear in process_elements().
    extra_types = list(PIPE_GEOM_TYPES | PORT_TYPES) + [
        "IfcFlowTerminal",
        "IfcSanitaryTerminal",
        "IfcBuildingElementProxy",
        "IfcFurnishingElement",
    ]

    for ifc_type in extra_types:
        try:
            ents = ifc_file.by_type(ifc_type)
        except Exception:
            ents = []

        for ent in ents:
            eid = _entity_id(ent)
            if eid in by_id:
                continue

            x, y, z = _placement_xyz_from_entity(ent)
            name = _entity_name(ent)
            obj = {
                "entity": ent,
                "ifc_id": eid,
                "name": name,
                "type": _entity_type(ent),
                "x": x,
                "y": y,
                "z": z,
                "vertices": np.array([]),
            }
            by_id[eid] = obj

            name_l = name.lower()
            if name_l:
                by_name.setdefault(name_l, []).append(obj)

    return by_id, by_name


def match_host_obj_to_ifc_id(host_obj, ifc_file):
    if host_obj.get("ifc_id") is not None:
        return host_obj["ifc_id"]

    host_name_l = _get_name(host_obj).lower()
    if not host_name_l:
        return None

    candidate_types = [
        "IfcFlowTerminal",
        "IfcSanitaryTerminal",
        "IfcBuildingElementProxy",
        "IfcFurnishingElement",
        "IfcFlowFitting",
    ]

    # Exact name match first.
    for ifc_type in candidate_types:
        try:
            ents = ifc_file.by_type(ifc_type)
        except Exception:
            ents = []
        for ent in ents:
            if _entity_name(ent).lower() == host_name_l:
                return _entity_id(ent)

    # Loose name match second.
    for ifc_type in candidate_types:
        try:
            ents = ifc_file.by_type(ifc_type)
        except Exception:
            ents = []
        for ent in ents:
            nm = _entity_name(ent).lower()
            if host_name_l in nm or nm in host_name_l:
                return _entity_id(ent)

    return None


def resolve_host_ports(host_obj, ifc_file, host_to_port_ids, entity_lookup_by_id):
    host_id = match_host_obj_to_ifc_id(host_obj, ifc_file)
    if host_id is None:
        return []

    port_ids = host_to_port_ids.get(host_id, [])
    return [entity_lookup_by_id[pid] for pid in port_ids if pid in entity_lookup_by_id]


def resolve_connected_pipe_from_port(
    port_obj,
    port_to_connected_port_ids,
    port_to_host_ids,
    entity_lookup_by_id,
):
    pid = port_obj.get("ifc_id")
    if pid is None:
        return None

    connected_pids = list(port_to_connected_port_ids.get(pid, set()))
    candidates = []

    for cpid in connected_pids:
        hid = port_to_host_ids.get(cpid)
        if hid is None:
            continue
        obj = entity_lookup_by_id.get(hid)
        if not obj:
            continue
        if _get_type(obj) in PIPE_GEOM_TYPES:
            candidates.append(obj)

    return candidates[0] if candidates else None


# ---------------------------
# Host-specific selection
# ---------------------------


def _is_port_driven_host(host_class):
    return host_class in {"concealed_cistern", "toilet_wc_end", "hand_shower"}


def _is_geometry_driven_host(host_class):
    return host_class in {"basin_cabinet", "bib_tap", "basin_mixer"}


def find_ports_near_host(host_obj, port_objs, host_class):
    max_dist_mm = 700.0
    if host_class == "toilet_wc_end":
        max_dist_mm = 900.0
    elif host_class in {"hand_shower", "basin_cabinet"}:
        max_dist_mm = 850.0

    hb = _global_bbox(host_obj)
    hc = (hb["center_x"], hb["center_y"], hb["center_z"])
    max_d2 = max_dist_mm * max_dist_mm

    found = []
    for obj in port_objs:
        pb = _global_bbox(obj)
        pc = (pb["center_x"], pb["center_y"], pb["center_z"])
        if _dist3(hc, pc) <= max_d2:
            found.append(obj)
    return found


def select_best_port_for_host(host_obj, ports, host_class):
    if not ports:
        return None

    host_bbox = _global_bbox(host_obj)
    host_cx = host_bbox["center_x"]
    host_cy = host_bbox["center_y"]
    host_cz = host_bbox["center_z"]

    ranked = []
    for port in ports:
        # Skip direct/local port coordinates that are far away from the processed host.
        if not _port_coord_looks_valid_for_host(port, host_obj, host_class):
            continue

        pb = _global_bbox(port)
        px = pb["center_x"]
        py = pb["center_y"]
        pz = pb["center_z"]

        score = _dist3((px, py, pz), (host_cx, host_cy, host_cz))

        if host_class == "toilet_wc_end":
            # Prefer lower WC connection / outlet, but only if it is still near the WC.
            if pz < host_cz:
                score -= 2_000_000.0
            score -= (host_cz - pz) * 10_000.0
            score += abs(px - host_cx) * 20.0
            score += abs(py - host_cy) * 20.0

        elif host_class == "basin_cabinet":
            # Prefer underside connection.
            if pz < host_cz:
                score -= 800_000.0
            score -= (host_cz - pz) * 6_000.0
            score += abs(px - host_cx) * 10.0
            score += abs(py - host_cy) * 10.0

        elif host_class == "basin_mixer":
            # BM.49001 should stay around mixer area.
            # Do not prefer low basin-cabinet underside points.
            score += abs(pz - host_cz) * 5_000.0

        elif host_class == "bib_tap":
            # Bib tap should stay around tap area, not basin-cabinet underside.
            score += abs(pz - host_cz) * 5_000.0

        elif host_class == "hand_shower":
            # Keep hand shower / mixer area, not ceiling head.
            score += abs(pz - host_cz) * 500.0

        ranked.append((score, port))

    if not ranked:
        return None

    ranked.sort(key=lambda x: x[0])
    return ranked[0][1]


def choose_pipe_near_selected_port(
    selected_port, pipe_objs, host_class, max_dist_mm=1200.0
):
    if selected_port is None:
        return None

    pb = _global_bbox(selected_port)
    pc = (pb["center_x"], pb["center_y"], pb["center_z"])
    max_d2 = max_dist_mm * max_dist_mm

    ranked = []
    for obj in pipe_objs:
        bbox = _global_bbox(obj)
        if not _looks_like_pipe_protrusion(bbox):
            continue

        center = (bbox["center_x"], bbox["center_y"], bbox["center_z"])
        d2 = _dist3(center, pc)
        if d2 > max_d2:
            continue

        name_l = _get_name(obj).lower()
        score = d2

        if host_class == "toilet_wc_end":
            if any(
                k in name_l
                for k in ["soil", "waste", "discharge", "outlet", "wc", "toilet"]
            ):
                score -= 1200.0

        elif host_class == "concealed_cistern":
            if any(k in name_l for k in ["cister", "flush", "tece"]):
                score -= 1200.0

        elif host_class == "hand_shower":
            if any(
                k in name_l
                for k in ["63352", "ceiling", "ceiling-mounted", "showerhead"]
            ):
                continue
            if any(
                k in name_l
                for k in ["hand shower", "shower set", "hose", "outlet", "mixer"]
            ):
                score -= 1200.0

        ranked.append((score, obj))

    ranked.sort(key=lambda x: x[0])
    return ranked[0][1] if ranked else None


def choose_pipe_for_geometry_host(host_obj, host_class, pipe_objs, max_dist_mm=1500.0):
    hb = _global_bbox(host_obj)
    hc = (hb["center_x"], hb["center_y"], hb["center_z"])
    max_d2 = max_dist_mm * max_dist_mm

    ranked = []
    for obj in pipe_objs:
        bbox = _global_bbox(obj)
        if not _looks_like_pipe_protrusion(bbox):
            continue

        center = (bbox["center_x"], bbox["center_y"], bbox["center_z"])
        d2 = _dist3(center, hc)
        if d2 > max_d2:
            continue

        name_l = _get_name(obj).lower()
        score = d2

        if host_class == "basin_cabinet":
            if any(
                k in name_l
                for k in ["wc", "toilet", "cister", "flush", "hand shower", "shower"]
            ):
                continue
            if any(k in name_l for k in ["basin", "cabinet", "waste", "drain", "trap"]):
                score -= 1500.0
            # Lower object is better for under-basin pipe.
            score += center[2] * 3.0

        elif host_class == "bib_tap":
            if any(
                k in name_l
                for k in ["wc", "toilet", "cister", "flush", "hand shower", "shower"]
            ):
                continue
            if any(k in name_l for k in ["bib tap", "tap", "monic"]):
                score -= 1500.0

        elif host_class == "basin_mixer":
            if any(
                k in name_l
                for k in ["wc", "toilet", "cister", "flush", "hand shower", "shower"]
            ):
                continue
            if any(k in name_l for k in ["bm.49001", "gessi,bm.49001", "mixer", "tap"]):
                score -= 1500.0

        ranked.append((score, obj))

    ranked.sort(key=lambda x: x[0])
    return ranked[0][1] if ranked else None


# ---------------------------
# Face / shape geometry
# ---------------------------


def get_pipe_major_axis(bbox):
    dims = {
        "X": bbox["size_x"],
        "Y": bbox["size_y"],
        "Z": bbox["size_z"],
    }
    return max(dims, key=dims.get)


def get_connected_end_sign(pipe_bbox, port_bbox):
    axis = get_pipe_major_axis(pipe_bbox)

    px = port_bbox["center_x"]
    py = port_bbox["center_y"]
    pz = port_bbox["center_z"]

    if axis == "X":
        d_min = abs(px - pipe_bbox["min_x"])
        d_max = abs(px - pipe_bbox["max_x"])
    elif axis == "Y":
        d_min = abs(py - pipe_bbox["min_y"])
        d_max = abs(py - pipe_bbox["max_y"])
    else:
        d_min = abs(pz - pipe_bbox["min_z"])
        d_max = abs(pz - pipe_bbox["max_z"])

    return axis, "-" if d_min <= d_max else "+"


def _infer_protrusion_from_wall_axis(bbox, wall_axis):
    cx = bbox["center_x"]
    cy = bbox["center_y"]

    if wall_axis in {"X", "+X", "-X"}:
        return "Y", "+" if cy >= 0 else "-"
    if wall_axis in {"Y", "+Y", "-Y"}:
        return "X", "+" if cx >= 0 else "-"
    if wall_axis in {"Z", "+Z", "-Z"}:
        return "Z", "+"

    sx = bbox["size_x"]
    sy = bbox["size_y"]
    if sx <= sy:
        return "X", "+" if cx >= 0 else "-"
    return "Y", "+" if cy >= 0 else "-"


def compute_mark_shape(bbox, protrude_axis, edge_margin_mm=5.0):
    edge_margin_mm = max(0.0, float(edge_margin_mm))

    if protrude_axis == "X":
        raw_w = bbox["size_y"]
        raw_h = bbox["size_z"]
    elif protrude_axis == "Y":
        raw_w = bbox["size_x"]
        raw_h = bbox["size_z"]
    else:
        raw_w = bbox["size_x"]
        raw_h = bbox["size_y"]

    usable_w = max(0.0, raw_w - 2.0 * edge_margin_mm)
    usable_h = max(0.0, raw_h - 2.0 * edge_margin_mm)
    return {"Mark Width": float(usable_w), "Mark Height": float(usable_h)}


def compute_pipe_diameter(bbox, protrude_axis):
    if protrude_axis == "X":
        d1, d2 = bbox["size_y"], bbox["size_z"]
    elif protrude_axis == "Y":
        d1, d2 = bbox["size_x"], bbox["size_z"]
    else:
        d1, d2 = bbox["size_x"], bbox["size_y"]
    return float((d1 + d2) / 2.0)


def compute_end_face_points(pipe_bbox, axis, sign, inset_mm=15.0, edge_margin_mm=5.0):
    inset_mm = max(0.0, float(inset_mm))
    edge_margin_mm = max(0.0, float(edge_margin_mm))

    min_x = pipe_bbox["min_x"] + edge_margin_mm
    max_x = pipe_bbox["max_x"] - edge_margin_mm
    min_y = pipe_bbox["min_y"] + edge_margin_mm
    max_y = pipe_bbox["max_y"] - edge_margin_mm
    min_z = pipe_bbox["min_z"] + edge_margin_mm
    max_z = pipe_bbox["max_z"] - edge_margin_mm

    if min_x > max_x:
        min_x = max_x = pipe_bbox["center_x"]
    if min_y > max_y:
        min_y = max_y = pipe_bbox["center_y"]
    if min_z > max_z:
        min_z = max_z = pipe_bbox["center_z"]

    if axis == "X":
        face_x = (
            pipe_bbox["min_x"] + inset_mm
            if sign == "-"
            else pipe_bbox["max_x"] - inset_mm
        )
        return [
            (face_x, min_y, min_z),
            (face_x, max_y, min_z),
            (face_x, min_y, max_z),
            (face_x, max_y, max_z),
        ]

    if axis == "Y":
        face_y = (
            pipe_bbox["min_y"] + inset_mm
            if sign == "-"
            else pipe_bbox["max_y"] - inset_mm
        )
        return [
            (min_x, face_y, min_z),
            (max_x, face_y, min_z),
            (min_x, face_y, max_z),
            (max_x, face_y, max_z),
        ]

    face_z = (
        pipe_bbox["min_z"] + inset_mm if sign == "-" else pipe_bbox["max_z"] - inset_mm
    )
    return [
        (min_x, min_y, face_z),
        (max_x, min_y, face_z),
        (min_x, max_y, face_z),
        (max_x, max_y, face_z),
    ]


def _host_geometry_bbox(host_obj, host_class, selected_port=None):
    """Use host geometry without labeling it as IfcHostFallback."""
    hb = _global_bbox(host_obj)

    # If host has real vertices, keep it.
    if not _bbox_is_point(hb):
        return hb

    # If host is point-only but owns a port, use the port center with a small inferred shape.
    if selected_port is not None:
        pb = _global_bbox(selected_port)
        cx, cy, cz = pb["center_x"], pb["center_y"], pb["center_z"]
    else:
        cx, cy, cz = hb["center_x"], hb["center_y"], hb["center_z"]

    # These are inferred marking dimensions, but Shape Type remains the real host IFC type.
    if host_class == "basin_mixer":
        sx, sy, sz = 130.0, 0.0, 62.0
    elif host_class == "concealed_cistern":
        sx, sy, sz = 130.0, 0.0, 62.0
    elif host_class == "toilet_wc_end":
        sx, sy, sz = 130.0, 0.0, 62.0
    elif host_class == "bib_tap":
        sx, sy, sz = 210.0, 0.0, 62.0
    elif host_class == "hand_shower":
        sx, sy, sz = 130.0, 0.0, 62.0
    else:
        sx, sy, sz = 130.0, 0.0, 62.0

    return {
        "min_x": cx - sx / 2.0,
        "max_x": cx + sx / 2.0,
        "min_y": cy - sy / 2.0,
        "max_y": cy + sy / 2.0,
        "min_z": cz - sz / 2.0,
        "max_z": cz + sz / 2.0,
        "center_x": cx,
        "center_y": cy,
        "center_z": cz,
        "size_x": sx,
        "size_y": sy,
        "size_z": sz,
    }


def _host_fallback_bbox(host_obj, host_class, selected_port=None):
    """Only use this for host classes in HOST_FALLBACK_ALLOWED."""
    hb = _global_bbox(host_obj)

    if selected_port is not None:
        pb = _global_bbox(selected_port)
        cx, cy, cz = pb["center_x"], pb["center_y"], pb["center_z"]
    else:
        cx, cy, cz = hb["center_x"], hb["center_y"], hb["center_z"]

    if host_class == "basin_cabinet":
        # Use bottom/underside of basin cabinet as the fuser-like basin pipe area.
        if selected_port is None:
            cz = hb["min_z"] + 30.0
        return {
            "min_x": cx - 60.0,
            "max_x": cx + 60.0,
            "min_y": cy,
            "max_y": cy,
            "min_z": cz - 26.0,
            "max_z": cz + 26.0,
            "center_x": cx,
            "center_y": cy,
            "center_z": cz,
            "size_x": 120.0,
            "size_y": 0.0,
            "size_z": 52.0,
        }

    return hb


def _shape_defaults_for_host(host_class):
    if host_class == "floor_drain":
        return 130.0, 62.0, 106.0
    if host_class == "bib_tap":
        return 210.0, 62.0, 146.0
    if host_class == "basin_cabinet":
        return 120.0, 52.0, 106.0
    if host_class == "basin_mixer":
        return 130.0, 62.0, 106.0
    if host_class == "concealed_cistern":
        return 130.0, 62.0, 106.0
    if host_class == "toilet_wc_end":
        return 130.0, 62.0, 106.0
    if host_class == "hand_shower":
        return 130.0, 62.0, 106.0
    return 130.0, 62.0, 106.0


def _bbox_from_center(cx, cy, cz, sx, sy, sz):
    return {
        "min_x": float(cx - sx / 2.0),
        "max_x": float(cx + sx / 2.0),
        "min_y": float(cy - sy / 2.0),
        "max_y": float(cy + sy / 2.0),
        "min_z": float(cz - sz / 2.0),
        "max_z": float(cz + sz / 2.0),
        "center_x": float(cx),
        "center_y": float(cy),
        "center_z": float(cz),
        "size_x": float(sx),
        "size_y": float(sy),
        "size_z": float(sz),
    }


def _default_dims_for_host(host_class):
    width, height, diameter = _shape_defaults_for_host(host_class)

    # The code normally marks on an X-Z face, with Y as wall depth.
    # Keep size_y very small instead of 0 so compute_end_face_points() can produce stable points.
    sx = float(width)
    sy = max(float(diameter), 10.0)
    sz = float(height)
    return sx, sy, sz


def _port_coord_looks_valid_for_host(selected_port, host_obj, host_class):
    """Reject bad direct-IFC local port coordinates.

    Many direct IfcDistributionPort placements are local to the host, not global.
    If we use those as GX/GY/GZ, WC / cistern / BM can jump to the wrong room area.
    So only trust a port coordinate when it is spatially close to the processed host geometry.
    """
    if selected_port is None:
        return False

    hb = _global_bbox(host_obj)
    pb = _global_bbox(selected_port)

    hc = (hb["center_x"], hb["center_y"], hb["center_z"])
    pc = (pb["center_x"], pb["center_y"], pb["center_z"])

    # Use a bigger tolerance for WC / basin cabinet because their ports can sit lower / behind.
    max_dist = 900.0
    if host_class in {"toilet_wc_end", "basin_cabinet"}:
        max_dist = 1200.0
    elif host_class in {"basin_mixer", "bib_tap"}:
        max_dist = 700.0

    return _dist3(hc, pc) <= max_dist * max_dist


def _name_number_tokens(obj):
    """Extract useful numeric tokens from an object name.

    Used to match objects like WC 1457003 with related ports such as
    OutPort_1457003_1 / InPort_1457003_2.
    """
    import re

    name = _get_name(obj)
    return set(re.findall(r"[0-9]{4,}", name))


def _port_point_bbox_for_host(point_obj, host_class):
    """Create a small stable bbox around a point-like IFC object.

    Point-only DistributionPorts / outlet points have no vertices, so their
    bbox size becomes 0. This function keeps the point as the target location
    but gives it a usable marking box.
    """
    pb = _global_bbox(point_obj)
    cx, cy, cz = pb["center_x"], pb["center_y"], pb["center_z"]
    sx, sy, sz = _default_dims_for_host(host_class)
    return _bbox_from_center(cx, cy, cz, sx, sy, sz)


def _concealed_cistern_low_connection_center(
    host_obj, selected_port=None, related_wc_obj=None
):
    """Return lower concealed-cistern pipe connection target.

    Important rule for this project:
    The concealed cistern object itself is high in the wall, so its bbox center
    can produce GZ around mirror-cabinet height. That is not the pipe marking
    point. For marking, use the lower toilet connection band, below the flush
    plate and close to the WC water connection zone.
    """
    hb = _global_bbox(host_obj)

    cx = hb["center_x"]
    cy = hb["center_y"]

    # Best reference: nearest WC object. Use the WC bottom band as the cistern
    # pipe connection reference, not the cistern body center.
    if related_wc_obj is not None:
        wb = _global_bbox(related_wc_obj)
        cx = wb["center_x"]
        cy = wb["center_y"]

        # Keep the cistern pipe just above the WC floor outlet band.
        # This avoids the old GZ 1600+ result.
        if wb["size_z"] > 0:
            cz = max(0.0, wb["min_z"] + 120.0)
        else:
            cz = max(0.0, wb["center_z"] + 120.0)
        return cx, cy, cz

    # If there is no WC reference, still never use the high cistern center.
    # Put the point in a lower pipe-connection band.
    if hb["size_z"] > 0:
        cz = max(0.0, hb["min_z"] + 120.0)
    else:
        cz = max(0.0, hb["center_z"] - 700.0)

    return cx, cy, cz


def _wc_bottom_flush_center(host_obj, selected_port=None):
    """Return the WC bottom flushing outlet target center.

    The WC marking point should be the bottom outlet / flushing pipe shown near
    the floor line in the elevation drawing, not the WC ceramic body center.
    """
    hb = _global_bbox(host_obj)

    # Use processed WC bbox for XY. Direct IFC ports can be local coordinates and
    # can move the target to the wrong side of the room.
    cx = hb["center_x"]
    cy = hb["center_y"]

    # Force the outlet band near floor datum. The old logic using hb["min_z"]
    # still produced GZ around 562/614 for this IFC, which is too high for the
    # below-WC pipe in the drawing.
    cz = WC_FLOOR_TARGET_Z_MM

    return cx, cy, cz


def _hand_shower_holder_connection_center(host_obj, selected_port=None):
    """Return the hand-shower holder / hose connection target.

    The hand shower set bbox center is too high because it describes the whole
    hand-shower assembly. The drawing target is the lower holder / hose
    connection, so shift down from the host center while keeping host XY.
    """
    hb = _global_bbox(host_obj)

    cx = hb["center_x"]
    cy = hb["center_y"]

    # Prefer a valid port only if it is lower than the host center and close to
    # the hand-shower object. Otherwise derive the holder point from the host.
    if _port_coord_looks_valid_for_host(selected_port, host_obj, "hand_shower"):
        pb = _global_bbox(selected_port)
        if pb["center_z"] < hb["center_z"]:
            return pb["center_x"], pb["center_y"], pb["center_z"]

    # Derived holder / hose-connection band.
    cz = max(0.0, hb["center_z"] - HAND_SHOWER_HOLDER_DROP_MM)

    return cx, cy, cz


def _hand_shower_holder_connection_bbox(host_obj, selected_port=None):
    cx, cy, cz = _hand_shower_holder_connection_center(
        host_obj,
        selected_port=selected_port,
    )
    sx, sy, sz = _default_dims_for_host("hand_shower")
    return _bbox_from_center(cx, cy, cz, sx, sy, sz)


def _port_based_bbox(selected_port, host_obj, host_class, related_wc_obj=None):
    """Build a small bbox around the target point.

    Important:
    - Use selected_port only when its coordinate is valid/global.
    - If the selected port is a local IFC coordinate, use processed host geometry instead.
    - BM.49001 and bib tap should not steal basin cabinet / wrong pipe ports.
    - WC must target the bottom flushing outlet band, not body center.
    - Concealed cistern must target the lower connection band, not the upper cistern body.
    - Hand shower must target the lower holder / hose connection, not the upper assembly center.
    """
    if host_class == "toilet_wc_end":
        cx, cy, cz = _wc_bottom_flush_center(host_obj, selected_port=selected_port)
        sx, sy, sz = _default_dims_for_host(host_class)
        return _bbox_from_center(cx, cy, cz, sx, sy, sz)

    if host_class == "concealed_cistern":
        cx, cy, cz = _concealed_cistern_low_connection_center(
            host_obj,
            selected_port=selected_port,
            related_wc_obj=related_wc_obj,
        )
        sx, sy, sz = _default_dims_for_host(host_class)
        return _bbox_from_center(cx, cy, cz, sx, sy, sz)

    if host_class == "hand_shower":
        return _hand_shower_holder_connection_bbox(
            host_obj,
            selected_port=selected_port,
        )
    if host_class == "floor_drain":
        hb = _global_bbox(host_obj)
        cx = hb["center_x"]
        cy = hb["center_y"]

        # Floor drain should be close to floor level.
        # If IFC has actual Z, keep it; otherwise clamp near 0.
        cz = max(0.0, hb["center_z"])

        sx, sy, sz = _default_dims_for_host(host_class)
        return _bbox_from_center(cx, cy, cz, sx, sy, sz)
    use_port = _port_coord_looks_valid_for_host(selected_port, host_obj, host_class)

    if use_port:
        pb = _global_bbox(selected_port)
        cx, cy, cz = pb["center_x"], pb["center_y"], pb["center_z"]
    else:
        hb = _global_bbox(host_obj)
        cx, cy, cz = hb["center_x"], hb["center_y"], hb["center_z"]

        # Basin cabinet fallback should use lower underside, not the cabinet center.
        if host_class == "basin_cabinet":
            cz = hb["min_z"] + 30.0

        # BM.49001 should stay around the mixer/body point if the port is unreliable.
        # Do not move it down to basin-cabinet underside.
        if host_class == "basin_mixer":
            cz = hb["center_z"]

    sx, sy, sz = _default_dims_for_host(host_class)
    return _bbox_from_center(cx, cy, cz, sx, sy, sz)


def choose_wc_bottom_flush_pipe(host_obj, all_candidate_objs, max_xy_mm=1200.0):
    """Find the actual WC bottom flushing / discharge connection.

    This does NOT use floor_z and does NOT rely only on IfcPipeSegment.
    Some IFC exports store the WC outlet/bottom flushing connection as
    IfcDistributionPort, IfcFlowTerminal, IfcFlowFitting, or point-like objects.

    Strategy:
    1. Search objects near the WC in XY.
    2. Prefer objects sharing the WC numeric identifier, e.g. 1457003 / 820714.
    3. Prefer OutPort / outlet / soil / waste / discharge names.
    4. Prefer the lowest object below the WC body center.
    """
    hb = _global_bbox(host_obj)
    wc_cx = hb["center_x"]
    wc_cy = hb["center_y"]
    wc_center_z = hb["center_z"]
    wc_min_z = hb["min_z"]
    max_xy2 = float(max_xy_mm) * float(max_xy_mm)

    host_tokens = _name_number_tokens(host_obj)
    ranked = []

    for obj in all_candidate_objs:
        if obj is host_obj:
            continue

        obj_type = _get_type(obj)
        name_l = _get_name(obj).lower()

        # Reject unrelated bathroom fixtures so WC does not steal basin/bib/shower geometry.
        if any(
            k in name_l
            for k in [
                "basin cabinet",
                "bm.49001",
                "gessi",
                "bib tap",
                "hand shower",
                "shower set",
                "concealed cistern",
                "tece",
            ]
        ):
            continue

        # Keep pipe/port/fitting/terminal/proxy style candidates only.
        if obj_type not in (
            PIPE_GEOM_TYPES
            | PORT_TYPES
            | {
                "IfcFlowTerminal",
                "IfcSanitaryTerminal",
                "IfcBuildingElementProxy",
                "IfcFurnishingElement",
                "IfcDistributionElement",
                "IfcElementAssembly",
            }
        ):
            # If type is missing but name looks like a connection, still allow it.
            if not any(
                k in name_l
                for k in [
                    "outport",
                    "inport",
                    "port",
                    "soil",
                    "waste",
                    "discharge",
                    "outlet",
                    "drain",
                    "flush",
                    "pipe",
                ]
            ):
                continue

        bbox = _global_bbox(obj)
        cx = bbox["center_x"]
        cy = bbox["center_y"]
        cz = bbox["center_z"]

        dxy2 = (cx - wc_cx) ** 2 + (cy - wc_cy) ** 2
        if dxy2 > max_xy2:
            continue

        # Bottom flushing connection should not be above the WC center.
        if cz > wc_center_z:
            continue

        obj_tokens = _name_number_tokens(obj)
        shared_token = bool(
            host_tokens and obj_tokens and host_tokens.intersection(obj_tokens)
        )

        # Base score: lower and close to WC wins.
        score = dxy2 + abs(cz - wc_min_z) * 4000.0

        # Same WC identifier is the strongest signal.
        if shared_token:
            score -= 5_000_000.0

        # OutPort / discharge side is better than inlet.
        if any(
            k in name_l
            for k in [
                "outport",
                "out_port",
                "outlet",
                "discharge",
                "soil",
                "waste",
                "drain",
            ]
        ):
            score -= 2_000_000.0
        if any(k in name_l for k in ["inport", "in_port"]):
            score -= 300_000.0

        # Prefer real pipe/fitting solids when they exist.
        if obj_type in PIPE_GEOM_TYPES and not _bbox_is_point(bbox):
            score -= 1_000_000.0

        # Prefer compact connection pieces, not large WC body / big furniture geometry.
        dims = sorted([bbox["size_x"], bbox["size_y"], bbox["size_z"]])
        score += dims[2] * 200.0

        ranked.append((score, obj))

    if not ranked:
        return None

    ranked.sort(key=lambda x: x[0])
    return ranked[0][1]


def _find_nearest_host_entry(host_obj, host_entries, wanted_class, max_dist_mm=900.0):
    """Find nearest classified host entry by class."""
    hb = _global_bbox(host_obj)
    hc = (hb["center_x"], hb["center_y"], hb["center_z"])
    max_d2 = float(max_dist_mm) * float(max_dist_mm)

    ranked = []
    for entry in host_entries or []:
        if entry.get("host_class") != wanted_class:
            continue

        other_obj = entry.get("obj")
        if other_obj is host_obj:
            continue

        ob = entry.get("bbox") or _global_bbox(other_obj)
        oc = (ob["center_x"], ob["center_y"], ob["center_z"])
        d2 = _dist3(hc, oc)

        if d2 <= max_d2:
            ranked.append((d2, entry))

    if not ranked:
        return None

    ranked.sort(key=lambda x: x[0])
    return ranked[0][1]


def _basin_cabinet_bottom_pipe_bbox(host_obj, host_entries=None):
    """Stable basin cabinet fallback.

    This restores the earlier correct basin result:
    - basin cabinet remains IfcHostFallback
    - XY anchors to nearest BM.49001 basin mixer
    - Z is placed below the mixer as the basin bottom filter / fuser pipe area
    """
    hb = _global_bbox(host_obj)

    cx = hb["center_x"]
    cy = hb["center_y"]
    cz = hb["min_z"] + 30.0

    nearest_mixer = _find_nearest_host_entry(
        host_obj,
        host_entries,
        "basin_mixer",
        max_dist_mm=1200.0,
    )

    if nearest_mixer is not None:
        mixer_bbox = nearest_mixer["bbox"]
        cx = mixer_bbox["center_x"]
        cy = mixer_bbox["center_y"]

        # Earlier correct basin output was about 170 mm below BM.49001 center.
        cz = mixer_bbox["center_z"] - 170.0

    sx, sy, sz = _default_dims_for_host("basin_cabinet")
    return _bbox_from_center(cx, cy, cz, sx, sy, sz)


def _select_mark_source(
    host_obj,
    host_class,
    selected_port,
    pipe_objs,
    port_objs,
    all_candidate_objs,
    port_to_connected_port_ids,
    port_to_host_ids,
    entity_lookup_by_id,
    related_wc_obj=None,
    host_entries=None,
):
    """Select final marking bbox/source for each sanitary host.

    Final project rules:
    - Basin cabinet: restore previous stable fallback under BM.49001.
    - WC: force near floor-level outlet.
    - Concealed cistern: force below flush plate / near WC connection.
    - Hand shower: force lower holder / hose connection.
    - BM.49001 and bib tap: keep real host type, no IfcHostFallback.
    - Only real pipe geometry with real bbox size may override host/port geometry.
    """

    # 1) Basin cabinet: do this first so it cannot be stolen by random candidate pipe.
    # This restores your earlier good basin data around GX 2325/2435, GY 2210.5,
    # GZ 706.5/748.5 when BM.49001 is the nearest mixer anchor.
    if host_class == "basin_cabinet":
        return (
            host_obj,
            _basin_cabinet_bottom_pipe_bbox(
                host_obj,
                host_entries=host_entries,
            ),
            "IfcHostFallback",
            "basin_stable_fallback",
        )

    # 2) WC: force below-WC pipe / floor outlet area.
    if host_class == "toilet_wc_end":
        host_type = _get_type(host_obj) or "IfcFlowTerminal"
        return (
            host_obj,
            _port_based_bbox(
                selected_port,
                host_obj,
                host_class,
                related_wc_obj=related_wc_obj,
            ),
            host_type,
            "wc_floor_connection",
        )

    # 3) Concealed cistern: target the low connection band, not high cistern body.
    if host_class == "concealed_cistern":
        host_type = _get_type(host_obj) or "IfcFlowTerminal"
        return (
            host_obj,
            _port_based_bbox(
                selected_port,
                host_obj,
                host_class,
                related_wc_obj=related_wc_obj,
            ),
            host_type,
            "cistern_low_connection",
        )

    # 4) Hand shower: holder / hose connection, not upper shower body.
    if host_class == "hand_shower":
        host_type = _get_type(host_obj) or "IfcFlowTerminal"
        return (
            host_obj,
            _port_based_bbox(
                selected_port,
                host_obj,
                host_class,
                related_wc_obj=related_wc_obj,
            ),
            host_type,
            "hand_shower_holder_connection",
        )

    # 5) For remaining hosts, real pipe geometry may be used only if valid.
    connected_pipe = None
    if selected_port is not None:
        connected_pipe = resolve_connected_pipe_from_port(
            selected_port,
            port_to_connected_port_ids,
            port_to_host_ids,
            entity_lookup_by_id,
        )

    selected_pipe = None

    if _is_port_driven_host(host_class):
        if connected_pipe is not None and _get_type(connected_pipe) in PIPE_GEOM_TYPES:
            selected_pipe = connected_pipe
        else:
            selected_pipe = choose_pipe_near_selected_port(
                selected_port,
                pipe_objs,
                host_class,
                max_dist_mm=1200.0,
            )

    elif _is_geometry_driven_host(host_class):
        selected_pipe = choose_pipe_for_geometry_host(
            host_obj,
            host_class,
            pipe_objs,
            max_dist_mm=1500.0,
        )

    if selected_pipe is not None:
        selected_pipe_bbox = _global_bbox(selected_pipe)
        if not _bbox_is_point(selected_pipe_bbox) and _looks_like_pipe_protrusion(
            selected_pipe_bbox
        ):
            return selected_pipe, selected_pipe_bbox, _get_type(selected_pipe), "pipe"

    # 6) BM.49001 / bib tap keep real host type. They must not become fallback.
    if host_class in HOST_GEOMETRY_ALLOWED:
        host_type = _get_type(host_obj) or "IfcHostGeometry"
        return (
            host_obj,
            _port_based_bbox(
                selected_port,
                host_obj,
                host_class,
                related_wc_obj=related_wc_obj,
            ),
            host_type,
            "port_or_host_geometry",
        )

    return None, None, "", "skip"


def _normalise_text_for_match(text):
    import re

    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _get_short_name(obj):
    """Automatically shorten IFC name using IFC fixture keywords.

    Example:
    BSS.TECE.CONCEALED CISTERN.9370224:...
    -> BSS.TECE.CONCEALED CISTERN

    BSS.LAUFEN.WC.820714:...
    -> BSS.LAUFEN.WC

    BSS.MONIC.BIB TAP.T-4L:...
    -> BSS.MONIC.BIB TAP
    """
    name = _get_name(obj)
    if not name:
        return ""

    # Keep first section before ":"
    name = name.split(":")[0].strip()

    parts = [p.strip() for p in name.split(".") if p.strip()]
    if not parts:
        return name

    host_class = classify_target_host(obj)
    keywords = TARGET_HOST_KEYWORDS.get(host_class, [])

    # Use meaningful keywords from IFC matching rules.
    # Skip number/model-code keywords like 49001, 820714, T-4D-3.
    useful_keywords = []
    for keyword in keywords:
        keyword_norm = _normalise_text_for_match(keyword)

        if not keyword_norm:
            continue

        # Skip keywords with digits because those are usually model/code suffixes.
        if any(ch.isdigit() for ch in keyword_norm):
            continue

        # Skip very short single-word brand-only fallback if better keyword exists.
        useful_keywords.append(keyword_norm)

    # Longest keyword first:
    # "tece concealed cistern" or "concealed cistern" should win over "tece".
    useful_keywords = sorted(
        useful_keywords,
        key=lambda k: (len(k.split()), len(k)),
        reverse=True,
    )

    best_stop_index = None

    for keyword_norm in useful_keywords:
        # Avoid stopping at brand-only words when the class has better keywords.
        if len(keyword_norm.split()) == 1 and len(useful_keywords) > 1:
            continue

        for idx in range(len(parts)):
            prefix = ".".join(parts[: idx + 1])
            prefix_norm = _normalise_text_for_match(prefix)

            if keyword_norm in prefix_norm:
                best_stop_index = idx
                break

        if best_stop_index is not None:
            break

    if best_stop_index is not None:
        return ".".join(parts[: best_stop_index + 1])

    # Fallback: keep BSS + next part
    return ".".join(parts[:2]) if len(parts) >= 2 else name


# ---------------------------
# Main builders
# ---------------------------


def build_sanitary_pipe_bbox_rows(
    ifc_file,
    all_objs=None,
    visited=None,
    inset_mm=15.0,
    edge_margin_mm=5.0,
):
    all_objs = all_objs or []
    visited = visited or []

    # =====================================================
    # 1. Collect direct IFC objects first
    # =====================================================
    direct_pipe_objs = _collect_direct_ifc_types(
        ifc_file,
        PIPE_GEOM_TYPES,
    )

    direct_port_objs = _collect_direct_ifc_types(
        ifc_file,
        PORT_TYPES,
    )

    direct_target_hosts = collect_direct_target_hosts(ifc_file)

    # =====================================================
    # 2. Combine processed and directly collected hosts
    # =====================================================
    all_host_objs = _dedupe_objects(all_objs + direct_target_hosts)

    # =====================================================
    # 3. Build pipe and port collections
    # =====================================================
    pipe_objs = _dedupe_objects(_filter_pipe_like_objects(all_objs) + direct_pipe_objs)

    # Do not use direct IFC ports as global coordinate candidates.
    port_objs = _dedupe_objects(_filter_port_objects(all_objs))

    all_candidate_objs = _dedupe_objects(
        all_objs + direct_pipe_objs + direct_port_objs + direct_target_hosts
    )

    # =====================================================
    # 4. Build lookup after direct_target_hosts exists
    # =====================================================
    entity_lookup_by_id, _ = build_entity_lookup(
        all_objs + direct_target_hosts + direct_pipe_objs + direct_port_objs,
        ifc_file,
    )

    (
        port_to_host_ids,
        host_to_port_ids,
        port_to_connected_port_ids,
    ) = build_ifc_relation_maps(ifc_file)

    # =====================================================
    # 5. Classify all hosts
    # Do not overwrite this with collect_target_hosts(all_objs)
    # =====================================================
    host_entries = collect_target_hosts(all_host_objs)

    service_wall = detect_sanitary_service_wall(
        host_entries=host_entries,
        visited=visited,
    )

    rows = []

    toilet_hosts = [
        entry["obj"] for entry in host_entries if entry["host_class"] == "toilet_wc_end"
    ]

    def _nearest_toilet_host(host_obj):
        if not toilet_hosts:
            return None

        host_bbox = _global_bbox(host_obj)
        host_center = (
            host_bbox["center_x"],
            host_bbox["center_y"],
            host_bbox["center_z"],
        )

        ranked = []

        for wc_obj in toilet_hosts:
            wc_bbox = _global_bbox(wc_obj)
            wc_center = (
                wc_bbox["center_x"],
                wc_bbox["center_y"],
                wc_bbox["center_z"],
            )

            ranked.append(
                (
                    _dist3(host_center, wc_center),
                    wc_obj,
                )
            )

        ranked.sort(key=lambda item: item[0])
        return ranked[0][1]

    # =====================================================
    # 6. Generate rows
    # =====================================================
    for entry in host_entries:
        host_obj = entry["obj"]
        host_class = entry["host_class"]

        # -------------------------------------------------
        # Manual T-shaped opening:
        # insert 8 Pipes rows, then skip normal processing.
        # -------------------------------------------------
        if host_class == "manual_opening":
            rows.extend(
                build_manual_t_opening_rows(
                    host_obj=host_obj,
                    manual_config=entry["manual_config"],
                )
            )
            continue

        owned_ports = resolve_host_ports(
            host_obj,
            ifc_file,
            host_to_port_ids,
            entity_lookup_by_id,
        )

        if not owned_ports:
            owned_ports = find_ports_near_host(
                host_obj,
                port_objs,
                host_class,
            )

        selected_port = select_best_port_for_host(
            host_obj,
            owned_ports,
            host_class,
        )

        related_wc_obj = (
            _nearest_toilet_host(host_obj)
            if host_class == "concealed_cistern"
            else None
        )

        (
            mark_source_obj,
            mark_bbox,
            shape_type,
            source_mode,
        ) = _select_mark_source(
            host_obj=host_obj,
            host_class=host_class,
            selected_port=selected_port,
            pipe_objs=pipe_objs,
            port_objs=port_objs,
            all_candidate_objs=all_candidate_objs,
            port_to_connected_port_ids=port_to_connected_port_ids,
            port_to_host_ids=port_to_host_ids,
            entity_lookup_by_id=entity_lookup_by_id,
            related_wc_obj=related_wc_obj,
            host_entries=host_entries,
        )

        if mark_bbox is None:
            continue

        # Use real pipe geometry for wall assignment only when available.
        wall_ref_obj = mark_source_obj if source_mode == "pipe" else host_obj

        wall_ctx = assign_wall_like_fitting(
            wall_ref_obj,
            visited,
        )

        wall_ctx = apply_auto_sanitary_service_wall(
            host_class=host_class,
            wall_ctx=wall_ctx,
            service_wall=service_wall,
        )

        wall_ctx = apply_sanitary_wall_override(
            host_class,
            wall_ctx,
        )

        if selected_port is not None and source_mode == "pipe":
            port_bbox = _global_bbox(selected_port)

            major_axis, end_sign = get_connected_end_sign(
                mark_bbox,
                port_bbox,
            )
        else:
            major_axis, end_sign = _infer_protrusion_from_wall_axis(
                mark_bbox,
                wall_ctx["axis"],
            )

        if source_mode == "pipe":
            mark_shape = compute_mark_shape(
                mark_bbox,
                major_axis,
                edge_margin_mm=edge_margin_mm,
            )

            width = mark_shape["Mark Width"]
            height = mark_shape["Mark Height"]

            diameter = compute_pipe_diameter(
                mark_bbox,
                major_axis,
            )
        else:
            width, height, diameter = _shape_defaults_for_host(host_class)

        bbox_points = compute_end_face_points(
            mark_bbox,
            major_axis,
            end_sign,
            inset_mm=inset_mm,
            edge_margin_mm=edge_margin_mm,
        )

        for index, (gx, gy, gz) in enumerate(
            bbox_points,
            start=1,
        ):
            rows.append(
                {
                    "Marking Type": "Pipes",
                    "Name": f"{_get_short_name(host_obj)}_{index}",
                    "GX": int(round(gx)),
                    "GY": int(round(gy)),
                    "GZ": int(round(gz)),
                    "Position X": "",
                    "Position Y": "",
                    "Position Z": "",
                    "Wall Number": wall_ctx["wall_number"],
                    "Shape Type": 1,
                    "Status": "",
                    "Quadrant": "",
                    "Unnamed": "",
                    "Width": width,
                    "Height": height,
                    "Orientation": "",
                    "Diameter": diameter,
                }
            )

    return rows


def build_sanitary_pipe_bbox_df(
    ifc_file,
    all_objs=None,
    visited=None,
    inset_mm=15.0,
    edge_margin_mm=5.0,
):
    rows = build_sanitary_pipe_bbox_rows(
        ifc_file=ifc_file,
        all_objs=all_objs,
        visited=visited,
        inset_mm=inset_mm,
        edge_margin_mm=edge_margin_mm,
    )

    df = pd.DataFrame(rows)

    for col in WANTED_COLS:
        if col not in df.columns:
            df[col] = ""

    return df[WANTED_COLS]


def get_manual_opening_config(obj):
    ifc_id = obj.get("ifc_id")

    if ifc_id in MANUAL_OPENING_BY_IFC_ID:
        return MANUAL_OPENING_BY_IFC_ID[ifc_id]

    name_l = _get_name(obj).lower()

    if any(keyword in name_l for keyword in MANUAL_OPENING_NAME_KEYWORDS):
        return {
            "manual_type": "T_SHAPE",
            "name": "BSS.GESSI.SM.49079",
            "wall_number": 3,
        }

    return None


def collect_target_hosts(all_objs):
    hosts = []

    for obj in all_objs:
        if _is_excluded_host(obj):
            continue

        manual_config = get_manual_opening_config(obj)

        if manual_config is not None:
            hosts.append(
                {
                    "obj": obj,
                    "host_class": "manual_opening",
                    "manual_config": manual_config,
                    "bbox": _global_bbox(obj),
                }
            )
            continue

        host_class = classify_target_host(obj)

        if not host_class:
            continue

        hosts.append(
            {
                "obj": obj,
                "host_class": host_class,
                "bbox": _global_bbox(obj),
            }
        )

    return hosts


def build_manual_t_opening_rows(host_obj, manual_config):
    """
    Build 6 Excel rows for one T-shaped pipe opening.

    Point order:
    1. Top-left
    2. Top-right
    3. Bottom-right of top bar
    4. Bottom-right of stem
    5. Bottom-left of stem
    6. Bottom-left of top bar
    """

    bbox = _global_bbox(host_obj)

    center_x = bbox["center_x"]
    center_y = bbox["center_y"]
    center_z = bbox["center_z"]

    wall_number = manual_config.get("wall_number", 3)
    base_name = manual_config.get("name", "BSS.GESSI.SM.49079")

    left_extension = float(
        manual_config.get("left_extension", 80.0)
    )

    right_extension = float(
        manual_config.get("right_extension", 65.0)
    )

    top_height = float(
        manual_config.get("top_height", 80.0)
    )

    stem_width = float(
        manual_config.get("stem_width", 80.0)
    )

    stem_height = float(
        manual_config.get("stem_height", 500.0)
    )

    # Stem is centred on the IFC reference X.
    stem_min_x = center_x - stem_width / 2.0
    stem_max_x = center_x + stem_width / 2.0

    # Top bar is asymmetric.
    top_min_x = stem_min_x - left_extension
    top_max_x = stem_max_x + right_extension

    # Treat IFC reference Z as the top edge of the T.
    top_max_z = center_z
    top_min_z = top_max_z - top_height

    # Stem starts directly below the top bar.
    stem_top_z = top_min_z
    stem_bottom_z = stem_top_z - stem_height

    t_points = [
        # 1. Top-left
        (top_min_x, center_y, top_max_z),

        # 2. Top-right
        (top_max_x, center_y, top_max_z),

        # 3. Bottom-right of top bar
        (top_max_x, center_y, top_min_z),

        # 4. Bottom-right of stem
        (stem_max_x, center_y, stem_bottom_z),

        # 5. Bottom-left of stem
        (stem_min_x, center_y, stem_bottom_z),

        # 6. Bottom-left of top bar
        (top_min_x, center_y, top_min_z),
    ]

    rows = []

    for index, (gx, gy, gz) in enumerate(t_points, start=1):
        rows.append(
            {
                "Marking Type": "Pipes",
                "Name": f"{base_name}_T_{index}",
                "GX": int(round(gx)),
                "GY": int(round(gy)),
                "GZ": int(round(gz)),
                "Position X": "",
                "Position Y": "",
                "Position Z": "",
                "Wall Number": wall_number,
                "Shape Type": 1,
                "Status": "",
                "Quadrant": "",
                "Unnamed": "",
                "Width": "",
                "Height": "",
                "Orientation": "",
                "Diameter": "",
            }
        )

    return rows