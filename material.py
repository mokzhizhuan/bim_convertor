import os
from pathlib import Path
import ifcopenshell

def _normalize(s): return (s or "").strip().lower()

def _iter_materials_from_definition(defn):
    if not defn: return
    t = defn.is_a()
    if t == "IfcMaterial":
        yield defn
    elif t == "IfcMaterialLayerSetUsage":
        for lay in (defn.ForLayerSet.MaterialLayers or []):
            if lay.Material: yield lay.Material
    elif t == "IfcMaterialLayerSet":
        for lay in (defn.MaterialLayers or []):
            if lay.Material: yield lay.Material
    elif t == "IfcMaterialProfileSetUsage":
        for p in (defn.ForProfileSet.MaterialProfiles or []):
            if p.Material: yield p.Material
    elif t == "IfcMaterialProfileSet":
        for p in (defn.MaterialProfiles or []):
            if p.Material: yield p.Material
    elif t == "IfcMaterialConstituentSet":
        for c in (defn.MaterialConstituents or []):
            if c.Material: yield c.Material
    elif t == "IfcMaterialList":
        for m in (defn.Materials or []):
            yield m

def _coerce_ifc(ifc_or_path):
    if hasattr(ifc_or_path, "by_type"):  # already an IfcFile
        return ifc_or_path
    if isinstance(ifc_or_path, (str, os.PathLike, Path)):
        return ifcopenshell.open(str(ifc_or_path))
    name = getattr(ifc_or_path, "name", None)
    if isinstance(name, str) and os.path.exists(name):
        return ifcopenshell.open(name)
    if hasattr(ifc_or_path, "read"):
        data = ifc_or_path.read()
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="ignore")
        return ifcopenshell.file.from_string(data)
    raise TypeError("expected IfcFile, path string, or file-like")

def getmaterial(
    ifc_or_path,
    target_name="BSS.20mm Floor Finishes (600x600mm)",
    *,
    names_only=False,
    first_only=False
):
    ifc = _coerce_ifc(ifc_or_path)
    target_norm = _normalize(target_name)

    # 1) direct IfcMaterial by name
    found = [m for m in ifc.by_type("IfcMaterial") if _normalize(m.Name) == target_norm]

    # 2) via associations
    if not found:
        for rel in ifc.by_type("IfcRelAssociatesMaterial"):
            for m in _iter_materials_from_definition(rel.RelatingMaterial):
                if _normalize(m.Name) == target_norm:
                    found.append(m)

    if names_only:
        names = sorted({(m.Name or "").strip() for m in found})
        return (names[0] if names else None) if first_only else names

    # return entities (dedup) for legacy callers
    ents = list({m.id(): m for m in found}.values())
    return (ents[0] if ents else None) if first_only else ents
