from typing import List, Dict
import json

def build_width_bins(internalmax: List[Dict]) -> tuple[list[float], list[float]]:
    """
    internalmax: [
      {'Wall Number': 1, 'Internal Max Width': 2760.0, 'Axis': 'X'},
      {'Wall Number': 2, 'Internal Max Width': 1200,  'Axis': 'Y'},
      ...
    ]
    Returns (X, Y) where each index e corresponds to a pair of walls:
      pair 0 -> walls 1 (X) & 2 (Y)
      pair 1 -> walls 3 (X) & 4 (Y)
      pair 2 -> walls 5 (X) & 6 (Y) ...
    """
    items = sorted(internalmax, key=lambda d: int(d['Wall Number']))
    bins = (len(items) + 1) // 2
    X = [0.0] * bins
    Y = [0.0] * bins

    for it in items:
        wn = int(it['Wall Number'])
        w  = float(it['Internal Max Width'])
        ax = str(it['Axis']).upper()
        e  = (wn - 1) // 2  # bin index

        if ax == 'X':
            X[e] = w
        elif ax == 'Y':
            Y[e] = w
        else:
            raise ValueError(f"Unknown Axis '{ax}' for wall {wn}")

    # Optional safety: ensure we filled both sides when expected
    # (leave as-is if some projects truly have missing sides)
    return X, Y


def compute_wall_centerpoints_from_axis(internalmax: List[Dict], visited, posz_cp: float):
    """
    Uses the exact stride-2 recipe you confirmed:
      e = i//2, k = i%2
      e==0:
        k==0 (W1): GX=X[0]/2, GY=0
        k==1 (W2): GX=X[0],   GY=Y[0]/2
      e==1:
        k==0 (W3): GX=X[1]/2,                GY=Y[0]
        k==1 (W4): GX=X[1],                  GY=Y[0] + Y[1]/2
      e>=2:
        k==0 (W5 @ e=2): GX=X[e-1] + X[e]/2, GY=Y[e]
        k==1:            GX=X[e],            GY=Y[e-1] + Y[e]/2
    """
    X, Y = build_width_bins(internalmax)
    internalmax_axis = [d.get("Facing_Axis") for d in internalmax]

    def safe(arr, idx):
        if not arr: return 0.0
        idx = max(0, min(idx, len(arr)-1))
        return arr[idx]

    points = []
    n_vis = len(visited)
    for i, _ in enumerate(visited):
        e = i // 2
        k = i % 2

        if e == 0:
            if k == 0:  # Wall 1
                GX = safe(X, 0) / 2.0
                GY = 0.0
            else:       # Wall 2
                GX = 0.0
                GY = safe(Y, 0) / 2.0

        elif e == 1:
            if k == 0:  # Wall 3 (your refined rule)
                GX = safe(X, 1) / 2.0
                GY = safe(Y, 0)
            else:       # Wall 4
                GX = safe(X, 1)
                GY = safe(Y, 0) + safe(Y, 1) / 2.0

        else:  # e >= 2
            if k == 0:  # Wall 5 (first in bin e)
                GX = safe(X, e-1) + safe(X, e) / 2.0
                GY = safe(Y, e)
            else:       # second in bin e
                GX = safe(X, 0)
                GY = safe(Y, e) / 2.0
        points.append({"GX": GX, "GY": GY, "GZ": posz_cp, "Facing_Axis": internalmax_axis[i]})

    return points

def write_json(centers: Dict[str, Dict[str, float]], fp: str) -> None:
    with open(fp, "w") as f:
        json.dump(centers, f, indent=2)
