#!/usr/bin/env python3
"""
IFC -> filtered STL exporter for booth/shell extraction.

Goal:
- Keep booth shell geometry (walls, slabs, optional proxies)
- Keep the extra basin wall (e.g. Wall 5) if it is modeled as a wall
- Exclude sanitary fixtures such as basin/sink/pipe/fittings
- Export one merged STL
- Also write a JSON report listing included/excluded IFC elements

Typical usage:
    python ifc_to_stl_booth_extract.py model.ifc

With custom output:
    python ifc_to_stl_booth_extract.py model.ifc --output-stl booth_shell_only.stl

If your IFC naming is messy, add more exclude keywords:
    python ifc_to_stl_booth_extract.py model.ifc --exclude-keywords basin sink lavatory washbowl pipe trap waste faucet

Optional:
- --include-types lets you override which IFC classes are considered for export
- --exclude-types lets you extend excluded IFC classes
- --include-name-keywords restricts export to names containing one of those words
"""

from __future__ import annotations

import argparse
import json
import sys
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
    "toilet accessory",
    "soap dispenser",
    "grab bar",
]

# Useful when the user wants only a booth area but not the whole building.
# Leave empty by default so walls/slabs are not restricted by name.
DEFAULT_INCLUDE_NAME_KEYWORDS = []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export filtered booth shell geometry from IFC to STL."
    )
    parser.add_argument("ifc_file", help="Path to input IFC file")
    parser.add_argument(
        "--output-stl",
        help="Path to output STL. Default: <ifc_stem>_booth_shell.stl",
        default=None,
    )
    parser.add_argument(
        "--report-json",
        help="Path to JSON report. Default: <ifc_stem>_booth_shell_report.json",
        default=None,
    )
    parser.add_argument(
        "--include-types",
        nargs="*",
        default=DEFAULT_INCLUDE_TYPES,
        help="IFC entity types to consider for export",
    )
    parser.add_argument(
        "--exclude-types",
        nargs="*",
        default=DEFAULT_EXCLUDE_TYPES,
        help="IFC entity types to exclude even if included by other rules",
    )
    parser.add_argument(
        "--exclude-keywords",
        nargs="*",
        default=DEFAULT_EXCLUDE_KEYWORDS,
        help="Name keywords to exclude (case-insensitive)",
    )
    parser.add_argument(
        "--include-name-keywords",
        nargs="*",
        default=DEFAULT_INCLUDE_NAME_KEYWORDS,
        help="If provided, only names containing at least one keyword are kept",
    )
    parser.add_argument(
        "--min-faces",
        type=int,
        default=12,
        help="Skip tiny geometry pieces below this triangle count",
    )
    parser.add_argument(
        "--sew-shells",
        action="store_true",
        help="Attempt trimesh processing/cleanup before export",
    )
    return parser.parse_args()


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

    include_type_set = set(include_types)
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

    # Deduplicate by GlobalId because overlapping include types may return same object
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

    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    return mesh


def main():
    args = parse_args()

    ifc_path = Path(args.ifc_file)
    if not ifc_path.exists():
        raise SystemExit(f"IFC file not found: {ifc_path}")

    output_stl = Path(args.output_stl) if args.output_stl else ifc_path.with_name(f"{ifc_path.stem}_booth_shell.stl")
    report_json = Path(args.report_json) if args.report_json else ifc_path.with_name(f"{ifc_path.stem}_booth_shell_report.json")

    ifc = ifcopenshell.open(str(ifc_path))

    candidates, excluded_pre = collect_candidates(
        ifc=ifc,
        include_types=args.include_types,
        exclude_types=args.exclude_types,
        include_name_keywords=args.include_name_keywords,
        exclude_keywords=args.exclude_keywords,
    )

    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)

    kept_meshes = []
    included_report = []
    excluded_geom = []

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

        if mesh is None or len(mesh.faces) < args.min_faces:
            excluded_geom.append(
                {
                    "global_id": gid,
                    "type": etype,
                    "name": name,
                    "reason": f"too_small_or_empty_faces<{args.min_faces}",
                }
            )
            continue

        if args.sew_shells:
            try:
                mesh.remove_duplicate_faces()
            except Exception:
                pass
            try:
                mesh.remove_unreferenced_vertices()
            except Exception:
                pass
            try:
                mesh.process(validate=True)
            except Exception:
                pass

        kept_meshes.append(mesh)
        bounds = mesh.bounds
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
            "No geometry remained after filtering. Try relaxing the filters:\n"
            "- remove some --exclude-keywords\n"
            "- remove --include-name-keywords\n"
            "- lower --min-faces\n"
            "- inspect the JSON report"
        )

    merged = trimesh.util.concatenate(kept_meshes)
    merged.export(str(output_stl))

    report = {
        "input_ifc": str(ifc_path),
        "output_stl": str(output_stl),
        "include_types": args.include_types,
        "exclude_types": args.exclude_types,
        "exclude_keywords": args.exclude_keywords,
        "include_name_keywords": args.include_name_keywords,
        "min_faces": args.min_faces,
        "included_count": len(included_report),
        "excluded_pre_count": len(excluded_pre),
        "excluded_geometry_count": len(excluded_geom),
        "included": included_report,
        "excluded_pre": excluded_pre,
        "excluded_geometry": excluded_geom,
    }

    report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Saved STL: {output_stl}")
    print(f"Saved report: {report_json}")
    print(f"Included entities: {len(included_report)}")
    print(f"Pre-filter excluded entities: {len(excluded_pre)}")
    print(f"Geometry-excluded entities: {len(excluded_geom)}")
    print()
    print("Note:")
    print("- Walls/slabs are kept by default, so the extra basin wall can remain.")
    print("- Basin/sink/pipe fixtures are excluded mainly by IFC type and name keywords.")
    print("- If the basin fixture is modeled as a wall/proxy with a neutral name, add more --exclude-keywords.")
    print("- If too much is missing, reduce filtering or inspect the JSON report.")


if __name__ == "__main__":
    main()
