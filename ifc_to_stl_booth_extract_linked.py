#!/usr/bin/env python3
"""
Linked IFC -> filtered STL exporter for booth/shell extraction.

This version is intentionally linked to the same input flow used by samplewallaxis.py:
- uses ifc_findings.parse_args() to read args.ifc_file
- opens the same IFC source as samplewallaxis.py
- can be dropped into the same project and run the same way

Goal:
- Keep booth shell geometry (walls, slabs, optional proxies/coverings)
- Keep the extra basin wall (for example Wall 5) if it is modeled as a wall
- Exclude sanitary fixtures such as basin/sink/pipe/fittings
- Export one merged STL
- Also write a JSON report listing included/excluded IFC elements
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

try:
    import trimesh
except Exception as exc:
    raise SystemExit(
        "Missing dependency: trimesh. Install it with: pip install trimesh"
    ) from exc

try:
    import ifcopenshell
    import ifcopenshell.geom
except Exception as exc:
    raise SystemExit(
        "Missing dependency: ifcopenshell with geometry support."
    ) from exc

try:
    import ifc_findings
except Exception as exc:
    raise SystemExit(
        "Could not import ifc_findings. Put this file in the same project as samplewallaxis.py."
    ) from exc


DEFAULT_INCLUDE_TYPES = [
    "IfcWall",
    "IfcWallStandardCase",
    "IfcSlab",
    "IfcCovering",
    "IfcBuildingElementProxy",
]

DEFAULT_EXCLUDE_TYPES = [
    "IfcSanitaryTerminal",
    "IfcFlowTerminal",
    "IfcFlowSegment",
    "IfcPipeSegment",
    "IfcPipeFitting",
    "IfcPipeAccessory",
    "IfcValve",
    "IfcFurnishingElement",
    "IfcFurniture",
    "IfcMechanicalFastener",
    "IfcFlowController",
    "IfcFlowFitting",
    "IfcDistributionFlowElement",
]

DEFAULT_EXCLUDE_KEYWORDS = [
    "basin",
    "sink",
    "lavatory",
    "wash basin",
    "washbasin",
    "washbowl",
    "wc",
    "water closet",
    "urinal",
    "tap",
    "faucet",
    "spout",
    "pipe",
    "waste",
    "trap",
    "drain",
    "sanitary",
    "soap dispenser",
    "grab bar",
]

DEFAULT_INCLUDE_NAME_KEYWORDS = []


def entity_name(entity) -> str:
    name = getattr(entity, "Name", None)
    return str(name) if name else ""


def entity_type(entity) -> str:
    return entity.is_a()


def global_id(entity) -> str:
    gid = getattr(entity, "GlobalId", None)
    return str(gid) if gid else ""


def should_keep_by_name(name: str, include_keywords: list[str], exclude_keywords: list[str]) -> tuple[bool, str]:
    lower = name.lower()

    if include_keywords:
        if not any(k.lower() in lower for k in include_keywords):
            return False, "name_not_in_include_keywords"

    if any(k.lower() in lower for k in exclude_keywords):
        return False, "name_matches_exclude_keyword"

    return True, "name_ok"


def collect_candidates(
    ifc,
    include_types: list[str],
    exclude_types: list[str],
    include_name_keywords: list[str],
    exclude_keywords: list[str],
):
    included = []
    excluded = []

    exclude_type_set = set(exclude_types)

    for type_name in include_types:
        try:
            entities = ifc.by_type(type_name)
        except Exception:
            entities = []

        for ent in entities:
            etype = entity_type(ent)
            name = entity_name(ent)

            if etype in exclude_type_set:
                excluded.append(
                    {
                        "global_id": global_id(ent),
                        "type": etype,
                        "name": name,
                        "reason": "excluded_type",
                    }
                )
                continue

            keep_name, reason = should_keep_by_name(
                name,
                include_keywords=include_name_keywords,
                exclude_keywords=exclude_keywords,
            )
            if not keep_name:
                excluded.append(
                    {
                        "global_id": global_id(ent),
                        "type": etype,
                        "name": name,
                        "reason": reason,
                    }
                )
                continue

            included.append(ent)

    seen = set()
    deduped = []
    for ent in included:
        gid = global_id(ent) or id(ent)
        if gid in seen:
            continue
        seen.add(gid)
        deduped.append(ent)

    return deduped, excluded


def mesh_from_entity(settings, ent):
    shape = ifcopenshell.geom.create_shape(settings, ent)
    geom = shape.geometry

    verts = np.array(geom.verts, dtype=float).reshape((-1, 3))
    faces = np.array(geom.faces, dtype=np.int64).reshape((-1, 3))

    if len(verts) == 0 or len(faces) == 0:
        return None

    return trimesh.Trimesh(vertices=verts, faces=faces, process=False)


def main():
    # Link to the same IFC arg flow used by samplewallaxis.py
    args = ifc_findings.parse_args()
    ifc_path = Path(args.ifc_file)
    if not ifc_path.exists():
        raise SystemExit(f"IFC file not found: {ifc_path}")

    ifc = ifcopenshell.open(str(ifc_path))

    output_stl = ifc_path.with_name(f"{ifc_path.stem}_booth_shell.stl")
    report_json = ifc_path.with_name(f"{ifc_path.stem}_booth_shell_report.json")

    candidates, excluded_pre = collect_candidates(
        ifc=ifc,
        include_types=DEFAULT_INCLUDE_TYPES,
        exclude_types=DEFAULT_EXCLUDE_TYPES,
        include_name_keywords=DEFAULT_INCLUDE_NAME_KEYWORDS,
        exclude_keywords=DEFAULT_EXCLUDE_KEYWORDS,
    )

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    kept_meshes = []
    included_report = []
    excluded_geom = []

    min_faces = 12

    for ent in candidates:
        name = entity_name(ent)
        etype = entity_type(ent)
        gid = global_id(ent)

        try:
            mesh = mesh_from_entity(settings, ent)
        except Exception as exc:
            excluded_geom.append(
                {
                    "global_id": gid,
                    "type": etype,
                    "name": name,
                    "reason": f"geometry_error: {exc}",
                }
            )
            continue

        if mesh is None or len(mesh.faces) < min_faces:
            excluded_geom.append(
                {
                    "global_id": gid,
                    "type": etype,
                    "name": name,
                    "reason": f"too_small_or_empty_faces<{min_faces}",
                }
            )
            continue

        bounds = mesh.bounds
        kept_meshes.append(mesh)
        included_report.append(
            {
                "global_id": gid,
                "type": etype,
                "name": name,
                "faces": int(len(mesh.faces)),
                "bounds_min": bounds[0].tolist(),
                "bounds_max": bounds[1].tolist(),
            }
        )

    if not kept_meshes:
        raise SystemExit(
            "No geometry remained after filtering. "
            "Inspect the JSON report and relax the keyword/type filters if needed."
        )

    merged = trimesh.util.concatenate(kept_meshes)
    merged.export(str(output_stl))

    report = {
        "input_ifc": str(ifc_path),
        "output_stl": str(output_stl),
        "linked_to": "samplewallaxis.py via ifc_findings.parse_args() and same args.ifc_file",
        "include_types": DEFAULT_INCLUDE_TYPES,
        "exclude_types": DEFAULT_EXCLUDE_TYPES,
        "exclude_keywords": DEFAULT_EXCLUDE_KEYWORDS,
        "min_faces": min_faces,
        "included_count": len(included_report),
        "excluded_pre_count": len(excluded_pre),
        "excluded_geometry_count": len(excluded_geom),
        "included": included_report,
        "excluded_pre": excluded_pre,
        "excluded_geometry": excluded_geom,
    }

    report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Linked IFC source: {ifc_path}")
    print(f"Saved STL: {output_stl}")
    print(f"Saved report: {report_json}")
    print(f"Included entities: {len(included_report)}")
    print(f"Pre-filter excluded entities: {len(excluded_pre)}")
    print(f"Geometry-excluded entities: {len(excluded_geom)}")
    print()
    print("This exporter follows the same IFC argument flow as samplewallaxis.py.")
    print("It keeps wall/slab shell geometry, including the extra basin wall if it is a wall,")
    print("while excluding likely basin/sink/pipe fixture objects.")


if __name__ == "__main__":
    main()
