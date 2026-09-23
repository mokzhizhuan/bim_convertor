import ifcopenshell
import numpy as np
import sys
from pathlib import Path


# ---------- matrix helpers ----------
def _axis2placement_to_matrix(a2p):
    """Build a 4x4 transform from IfcAxis2Placement2D/3D."""
    if a2p.is_a("IfcAxis2Placement3D"):
        loc = np.array(a2p.Location.Coordinates, dtype=float)
        z = (
            np.array(a2p.Axis.DirectionRatios, dtype=float)
            if a2p.Axis
            else np.array([0.0, 0.0, 1.0])
        )
        x = (
            np.array(a2p.RefDirection.DirectionRatios, dtype=float)
            if a2p.RefDirection
            else np.array([1.0, 0.0, 0.0])
        )
        z /= np.linalg.norm(z)
        x /= np.linalg.norm(x)
        y = np.cross(z, x)
        y /= np.linalg.norm(y)
        x = np.cross(y, z)
        x /= np.linalg.norm(x)
    elif a2p.is_a("IfcAxis2Placement2D"):
        xy = np.array(a2p.Location.Coordinates, dtype=float)
        loc = np.array([xy[0], xy[1], 0.0])
        x2d = (
            np.array(a2p.RefDirection.DirectionRatios, dtype=float)
            if a2p.RefDirection
            else np.array([1.0, 0.0])
        )
        x = np.array([x2d[0], x2d[1], 0.0])
        x /= np.linalg.norm(x)
        z = np.array([0.0, 0.0, 1.0])
        y = np.cross(z, x)
        y /= np.linalg.norm(y)
    else:
        raise TypeError(f"Unsupported placement type: {a2p.is_a()}")

    M = np.eye(4)
    M[:3, 0] = x
    M[:3, 1] = y
    M[:3, 2] = z
    M[:3, 3] = loc
    return M


def _localplacement_to_matrix(lp):
    return _axis2placement_to_matrix(lp.RelativePlacement)


def world_matrix_from_local_placement(lp):
    """Compose transforms up the PlacementRelTo chain → world 4x4."""
    M = _localplacement_to_matrix(lp)
    parent = lp.PlacementRelTo
    while parent:
        M = _localplacement_to_matrix(parent) @ M
        parent = parent.PlacementRelTo
    return M


def trace_element_placement(elem):
    """Print the chain and return the world 4x4 matrix for elem.ObjectPlacement."""
    lp = elem.ObjectPlacement
    if not lp or not lp.is_a("IfcLocalPlacement"):
        raise ValueError("Element has no IfcLocalPlacement")
    steps = []
    cur = lp
    while cur:
        steps.append(
            {
                "lp_id": cur.id(),
                "relto": cur.PlacementRelTo.id() if cur.PlacementRelTo else None,
                "relpl": cur.RelativePlacement.id() if cur.RelativePlacement else None,
            }
        )
        cur = cur.PlacementRelTo

    print("Placement chain (child → root):")
    for i, s in enumerate(steps):
        print(
            f"  Step {i}: IfcLocalPlacement #{s['lp_id']} "
            f"RelTo=#{s['relto'] if s['relto'] else '$'} "
            f"RelativePlacement=#{s['relpl']}"
        )

    M = world_matrix_from_local_placement(lp)
    with np.printoptions(precision=6, suppress=True):
        print("\nWorld transform (4x4):\n", M)
    origin_world = (M @ np.array([0, 0, 0, 1.0]))[:3]
    print("Element local origin in world XYZ:", origin_world)
    return M


# ---------- main ----------
def main():
    # ---- adjust these ----
    ifc_path = Path("TERRAHL2-FP-MB-T1am(JMB).ifc")  # <- put your .ifc path here
    step_id = 28818  # <- e.g. your wall #28818

    if not ifc_path.exists():
        print(f"IFC not found: {ifc_path.resolve()}")
        sys.exit(1)

    ifc = ifcopenshell.open(str(ifc_path))

    # Option A: pick by STEP id
    elem = ifc.by_id(step_id)
    if elem is None:
        print(f"No element with STEP id #{step_id}")
        # Option B: fallback to first wall
        walls = ifc.by_type("IfcWall")
        if not walls:
            print("No IfcWall found in file.")
            sys.exit(1)
        elem = walls[0]
        print(f"Falling back to first wall: #{elem.id()} {elem.Name}")

    print(f"Element: #{elem.id()} {elem.is_a()} Name={getattr(elem,'Name',None)}")
    M_world = trace_element_placement(elem)


if __name__ == "__main__":
    main()
