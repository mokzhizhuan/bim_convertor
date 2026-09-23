import math
from collections import defaultdict
import ifcopenshell

IFC_PATH = "TERRAHL2-FP-MB-T1am(JMB).ifc"  # your uploaded file
TARGET_SPACING = 600.0  # model units (mm if your model is mm)
ANG_TOL = 1e-3  # ~0.057° in radians
DIST_TOL = 2.0  # mm tolerance for 600 spacing; raise if needed
MIN_RUN = 3  # at least 3 parallel lines in a run

ifc = ifcopenshell.open(IFC_PATH)


def vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vadd(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vdot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vcross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def vlen(a):
    return math.sqrt(vdot(a, a))


def vunit(a):
    L = vlen(a)
    return (a[0] / L, a[1] / L, a[2] / L) if L > 0 else (0.0, 0.0, 0.0)


def almost_zero(x, tol=1e-9):
    return abs(x) <= tol


def cart3(pt):
    cs = list(pt.Coordinates)
    if len(cs) == 2:
        cs.append(0.0)
    return (float(cs[0]), float(cs[1]), float(cs[2]))


def parallel(u, v, ang_tol=ANG_TOL):
    # parallel if angle ~ 0 or pi  → |cross| small relative to product of lengths
    cu = vcross(u, v)
    denom = vlen(u) * vlen(v)
    return (denom > 0) and (vlen(cu) / denom <= math.sin(ang_tol))


def canonical_dir(d):
    # make direction sign-invariant: flip so first nonzero component >=0
    x, y, z = d
    key = (round(x, 6), round(y, 6), round(z, 6))
    if (
        x < -1e-9
        or (almost_zero(x) and (y < -1e-9))
        or (almost_zero(x) and almost_zero(y) and (z < -1e-9))
    ):
        return (-x, -y, -z)
    return (x, y, z)


def find_face_normal(pts):
    # pts: list of >=3 non-collinear points
    # Robustly find a normal by scanning triplets
    o = pts[0]
    for i in range(1, len(pts) - 1):
        a = vsub(pts[i], o)
        b = vsub(pts[i + 1], o)
        n = vcross(a, b)
        if vlen(n) > 1e-9:
            return vunit(n), o
    return None, o


def local_basis_on_plane(n, hint_dir):
    # Build (u,v) orthonormal basis in the plane with normal n.
    # Try to align u with the hint_dir projected into plane.
    # If hint_dir is degenerate, pick any stable axis.
    if vlen(hint_dir) < 1e-9:
        # choose something not parallel to n
        t = (1, 0, 0) if abs(n[0]) < 0.9 else (0, 1, 0)
    else:
        t = hint_dir
    u = vsub(t, tuple(nc * vdot(t, n) for nc in n))  # project t into plane
    if vlen(u) < 1e-9:
        # fallback orthogonal vector
        t = (1, 0, 0) if abs(n[0]) < 0.9 else (0, 1, 0)
        u = vsub(t, tuple(nc * vdot(t, n) for nc in n))
        if vlen(u) < 1e-9:
            t = (0, 0, 1)
            u = vsub(t, tuple(nc * vdot(t, n) for nc in n))
    u = vunit(u)
    v = vcross(n, u)
    return u, v


def signed_offset_along(perp, origin, p):
    # offset = dot((p - origin), perp)
    return vdot(vsub(p, origin), perp)


def is_regularly_spaced(offsets, target=TARGET_SPACING, tol=DIST_TOL, min_run=MIN_RUN):
    """
    Given sorted offsets (floats), check if there exists a consecutive run
    where every step ~ target within tol. Returns the longest such run indices.
    """
    if len(offsets) < min_run:
        return None
    run_start = 0
    best = None
    # We check differences between neighbors ~ target
    for i in range(1, len(offsets)):
        diff = offsets[i] - offsets[i - 1]
        if abs(diff - target) <= tol:
            # continue run
            pass
        else:
            # close run at i-1
            if i - run_start >= min_run:
                best = (run_start, i - 1)
                # keep searching for longer runs
            run_start = i
    # tail
    if len(offsets) - run_start >= min_run:
        cand = (run_start, len(offsets) - 1)
        # prefer longer
        if best is None or (cand[1] - cand[0]) > (best[1] - best[0]):
            best = cand
    return best


detections = []

for pl in ifc.by_type("IfcPolyLoop"):
    pts = [cart3(p) for p in pl.Polygon]
    if len(pts) < 3:
        continue

    n, origin = find_face_normal(pts)
    if n is None:
        continue  # degenerate

    # Build all edge segments for this loop
    segments = []
    for i in range(len(pts)):
        a = pts[i]
        b = pts[(i + 1) % len(pts)]
        d = vsub(b, a)
        L = vlen(d)
        if L < 1e-6:
            continue
        du = vunit(d)
        du = canonical_dir(du)
        segments.append((a, b, du))

    if not segments:
        continue

    # Group by direction (parallel families inside this loop)
    dir_groups = defaultdict(list)
    dirs = []
    for a, b, du in segments:
        assigned = False
        for key in dirs:
            if parallel(du, key, ANG_TOL):
                dir_groups[key].append((a, b, du))
                assigned = True
                break
        if not assigned:
            dirs.append(du)
            dir_groups[du].append((a, b, du))

    # For each parallel group, compute offsets along a perpendicular axis in-plane
    for key_dir, segs in dir_groups.items():
        if len(segs) < MIN_RUN:
            continue

        # Build local (u,v) basis so that u ~ key_dir (projected), v = n x u
        u_hint = key_dir
        u, v = local_basis_on_plane(n, u_hint)
        # We want the axis perpendicular to the lines: that is v if u ~ line direction
        perp = v

        # For each segment, compute the line's signed offset via any point on it
        offsets = []
        for a, b, du in segs:
            off = signed_offset_along(perp, origin, a)
            offsets.append(off)

        # Normalize and sort offsets (collapse near-duplicates from collinear edges)
        offsets.sort()
        # Merge close offsets (many short edges lie on the same infinite line)
        merged = []
        for off in offsets:
            if not merged or abs(off - merged[-1]) > DIST_TOL:
                merged.append(off)

        if len(merged) < MIN_RUN:
            continue

        run = is_regularly_spaced(merged, TARGET_SPACING, DIST_TOL, MIN_RUN)
        if run:
            s, e = run
            family_offsets = merged[s : e + 1]

            # Collect the actual segments that lie on those offsets
            chosen = []
            for a, b, du in segs:
                off = signed_offset_along(perp, origin, a)
                if any(abs(off - m) <= DIST_TOL for m in family_offsets):
                    chosen.append((a, b))

            # Identify owners up the graph for context
            owner = None
            try:
                for inv in ifc.get_inverse(pl):
                    if inv.is_a("IfcFaceBound"):
                        owner = inv
                        break
            except:
                pass

            detections.append(
                {
                    "polyloop_id": pl.id(),
                    "owner_type": owner.is_a() if owner else None,
                    "owner_id": owner.id() if owner else None,
                    "normal": n,
                    "direction": key_dir,  # lines’ direction on the face
                    "perp_offsets": family_offsets,
                    "segments": chosen,  # list of ((x,y,z),(x,y,z))
                }
            )

# --- Report ---
print(
    f"Detected {len(detections)} parallel-line families spaced at ~{TARGET_SPACING} mm"
)
for k, d in enumerate(detections, 1):
    print("\n============================================================")
    print(
        f"[{k}] IfcPolyLoop #{d['polyloop_id']}  owner: {d['owner_type']} #{d['owner_id']}"
    )
    print(f"    direction ~ {d['direction']}")
    print(f"    offsets ({len(d['perp_offsets'])} lines):")
    for off in d["perp_offsets"]:
        print(f"      {off:.3f} mm")
    print(f"    sample segments (up to 5 shown):")
    for a, b in d["segments"][:5]:
        print(f"      A{a} -> B{b}")
