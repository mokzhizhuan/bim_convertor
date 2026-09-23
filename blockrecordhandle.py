#!/usr/bin/env python3
# pip install ezdxf
import ezdxf
from pathlib import Path

DXF_PATH = r"TERRAHL2-FP-MB-T1am(JMB)-A88dxf.dxf"  # <-- change this
HANDLE = "BBC8"  # the BLOCK_RECORD handle you asked about


def safe_attr(obj, name, default=None):
    return getattr(obj.dxf, name, default) if obj is not None else default


def describe(obj, label="Object"):
    if obj is None:
        return f"{label}: <None>"
    return (
        f"{label}: type={obj.dxftype()} "
        f"handle={safe_attr(obj, 'handle')} "
        f"owner={safe_attr(obj, 'owner')} "
        f"name={safe_attr(obj, 'name')}"
    )


def main():
    # 1) Open DXF
    doc = ezdxf.readfile(DXF_PATH)
    db = doc.entitydb

    # 2) Get BLOCK_RECORD by handle
    br = db.get(HANDLE)
    print(describe(br, "BLOCK_RECORD"))
    if br is None:
        return

    # 3) Print its block name (group code 2)
    print("Block name:", safe_attr(br, "name"))

    # 4) Resolve and print owner (group code 330) – usually the Block Table (handle '1')
    owner_handle = safe_attr(br, "owner")
    owner = db.get(owner_handle) if owner_handle else None
    print(describe(owner, "Owner"))

    # 5) If this BLOCK_RECORD backs a Layout, find and print that Layout
    layout_for_block = None
    for layout in doc.layouts:
        if (
            safe_attr(layout, "block_record_handle") == owner_handle
            or safe_attr(layout, "block_record_handle") == HANDLE
        ):
            layout_for_block = layout
            break

    if layout_for_block:
        print(f"Layout using this BLOCK_RECORD: {layout_for_block.dxf.name}")
    else:
        print(
            "No Layout links directly to this BLOCK_RECORD (it may be a normal user block)."
        )


if __name__ == "__main__":
    main()
