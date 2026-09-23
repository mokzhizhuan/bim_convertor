import re, math, pandas as pd
from pathlib import Path

DXF_PATH = "TERRAHL2-FP-MB-T1am(JMB)-A88.dxf"

# ----------------- basic helpers -----------------


def split_blocks(txt: str):
    parts = re.split(r"(?:\r?\n)\s*0(?:\r?\n)", txt)
    return [p for p in parts[1:] if p.strip()]


def code_vals(block: str, code: str):
    return re.findall(rf"(?:\r?\n)\s*{re.escape(code)}(?:\r?\n)([^\r\n]+)", block)


def code_first(block: str, code: str, last=False):
    vals = code_vals(block, code)
    if not vals:
        return None
    return vals[-1] if last else vals[0]


def fnum(block: str, code: str, default=None, last=False):
    v = code_first(block, code, last=last)
    try:
        return float(v) if v is not None else default
    except:
        return default


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


# ----------------- indexing by BLOCK_RECORD handle -----------------


def index_blocks(blocks, key="BSS_Tile Setting Out Point"):
    """
    Returns:
      - record_to_name: {BLOCK_RECORD handle -> BLOCK name}, filtered to names CONTAINING `key`
      - name_to_record: {BLOCK name -> BLOCK_RECORD handle}, same filter
    We read from BLOCK headers: code 2 = name, code 330 = BLOCK_RECORD handle.
    """
    want = _norm(key)
    record_to_name, name_to_record = {}, {}
    for b in blocks:
        lines = b.strip().splitlines()
        if not lines or lines[0].strip().upper() != "BLOCK":
            continue
        name = (code_first(b, "2") or "").strip()
        if _norm(name).find(want) == -1:
            continue
        rec = (code_first(b, "330") or "").strip()  # BLOCK_RECORD handle
        if not rec:
            continue
        record_to_name[rec] = name
        name_to_record[name] = rec
    return record_to_name, name_to_record


def index_insert_layers_by_record(blocks, name_to_record):
    record_layers = {}
    for b in blocks:
        lines = b.strip().splitlines()
        if not lines or lines[0].strip().upper() != "INSERT":
            continue
        name = (code_first(b, "2") or "").strip()
        rec = name_to_record.get(name)
        if not rec:
            continue
        lay = (code_first(b, "8") or "").strip()
        record_layers.setdefault(rec, set()).add(lay)
    return record_layers


# ----------------- main collector -----------------


def getdata(dxf_file):
    txt = Path(dxf_file).read_text(errors="ignore")
    blocks = split_blocks(txt)

    TARGET_LAYER = "A-_ANOT----_A"
    BSS_KEY = "BSS_Tile Setting Out Point"
    target_r = 50.164994
    rtol = 1e-3

    # Build indices
    record_to_name, name_to_record = index_blocks(blocks, key=BSS_KEY)
    record_layers = index_insert_layers_by_record(blocks, name_to_record)

    circle_rows = []
    for b in blocks:
        lines = b.strip().splitlines()
        if not lines:
            continue
        if lines[0].strip().upper() != "CIRCLE":
            continue

        layer = (code_first(b, "8") or "").strip()
        if layer != TARGET_LAYER:
            continue

        subclasses = code_vals(b, "100")
        has_ent = any((s or "").strip() == "AcDbEntity" for s in subclasses)
        has_circ = any((s or "").strip() == "AcDbCircle" for s in subclasses)

        owner_rec = (
            code_first(b, "330") or ""
        ).strip()  # CIRCLE's owner = BLOCK_RECORD handle
        rad = fnum(b, "40", 0.0) or 0.0
        cx = fnum(b, "10", 0.0) or 0.0
        cy = fnum(b, "20", 0.0) or 0.0
        cz = fnum(b, "30", 0.0) or 0.0

        bss_name = record_to_name.get(owner_rec, "")
        layer_set = record_layers.get(owner_rec, set())

        row = {
            "circle_handle": (code_first(b, "5") or "").strip(),
            "owner_record": owner_rec,
            "layer": layer,
            "center_x_rounded": round(cx),
            "center_y_rounded": round(cy),
            "center_z_rounded": round(cz),
            "radius": rad,
            "radius_rounded": round(rad),
            "has_AcDbEntity": has_ent,
            "has_AcDbCircle": has_circ,
            "is_BSS_signature_radius": abs(rad - target_r) <= rtol,
            # owner-handle link to BSS block via BLOCK_RECORD
            "bss_owner_match": bool(bss_name),
            "bss_block_name": bss_name,
            # confirm where that block is actually INSERTed
            "bss_insert_layers": ";".join(sorted(layer_set)) if layer_set else "",
            "bss_has_insert_on_A-_ANOT----_A": (TARGET_LAYER in layer_set),
        }
        circle_rows.append(row)

    return circle_rows
