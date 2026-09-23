#!/usr/bin/env python3
# pip install ezdxf
import ezdxf
from pathlib import Path

DXF_PATH = r"TERRAHL2-FP-MB-T1am(JMB)-A88dxf.dxf"  # <- change this
HANDLE = "B3BB"  # MTEXT handle from your snippet


def info(ent):
    if ent is None:
        return "<None>"
    # Not all DXF objects have all DXF attributes, so guard with getattr:
    return (
        f"{ent.dxftype()} "
        f"handle={getattr(ent.dxf, 'handle', None)} "
        f"owner={getattr(ent.dxf, 'owner', None)} "
        f"layer={getattr(ent.dxf, 'layer', None)} "
        f"name={getattr(ent.dxf, 'name', None)}"
    )


def main():
    doc = ezdxf.readfile(DXF_PATH)
    db = doc.entitydb

    # 1) Get the entity by handle (B3BB)
    e = db.get(HANDLE)
    if e is None:
        print(f"Handle {HANDLE!r} not found.")
        return
    print("Entity:", info(e))

    # 2) Resolve the owner via group code 330 (owner handle "70" in your case)
    owner_h = getattr(e.dxf, "owner", None)
    owner = db.get(owner_h) if owner_h else None
    print("Owner :", info(owner))

    # 3) If the owner is a BLOCK_RECORD, show its name and try to map it to a Layout
    if owner is not None and owner.dxftype() == "BLOCK_RECORD":
        br_name = getattr(owner.dxf, "name", None)
        print(f"BLOCK_RECORD name: {br_name}")

        # Which layout uses this BLOCK_RECORD?
        layout_for_block = None
        for layout in doc.layouts:
            if getattr(layout.dxf, "block_record_handle", None) == owner_h:
                layout_for_block = layout
                break

        if layout_for_block:
            print(f"Layout: {layout_for_block.dxf.name}")
        else:
            # Could be the model space block record (*Model_Space) or a regular block.
            print(
                "No Layout points to this BLOCK_RECORD (likely *Model_Space or a regular block)."
            )

    # 4) One more level up (owner of owner), just for completeness
    if owner is not None and hasattr(owner.dxf, "owner"):
        oo_h = owner.dxf.owner
        oo = db.get(oo_h)
        print("Owner of owner:", info(oo))


if __name__ == "__main__":
    main()
