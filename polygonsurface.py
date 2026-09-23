# --- polygon_from_step.py ---
# Build the polyline, print details, and plot (optional)

import math

# Your 2D vertices (from #28868..#28873, close back to #28868)
pts = [
    (-619.99944233338681,-687.49976084423031),
    (620.00055766655782,-687.49976084423031),
    (620.00055766655782,222.49928253267606),
    (329.99944233341324,222.49928253267606),
    (329.99944233341319,242.50119577888114),
    (-330.00055766658431,242.50119577887571),
    (-330.00055766658414,222.49928253267578),
    (-619.99944233338681,222.49928253267578),
]
# Ensure closed
if pts[0] != pts[-1]:
    pts.append(pts[0])


def perimeter(poly):
    d = 0.0
    for a, b in zip(poly, poly[1:]):
        d += math.hypot(b[0] - a[0], b[1] - a[1])
    return d


def area_shoelace(poly):
    # poly is closed (first == last)
    s = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:]):
        s += x1 * y2 - x2 * y1
    return abs(s) * 0.5


# Print a “shape in print version”
print("Vertices (in order):")
for i, p in enumerate(pts):
    print(f"  {i:02d}: ({p[0]:.3f}, {p[1]:.3f})")

print("\nEdges:")
for i, (a, b) in enumerate(zip(pts, pts[1:]), start=1):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    print(f"  e{i:02d}: {a} -> {b}  Δ=({dx:.3f},{dy:.3f})  |e|={L:.3f}")

bbox_x = (min(p[0] for p in pts), max(p[0] for p in pts))
bbox_y = (min(p[1] for p in pts), max(p[1] for p in pts))
print(f"\nBounding box: x∈[{bbox_x[0]}, {bbox_x[1]}], y∈[{bbox_y[0]}, {bbox_y[1]}]")
print(f"Perimeter: {perimeter(pts):.3f}")
print(f"Area:      {area_shoelace(pts):.3f} (2D profile area)")

# OPTIONAL: quick plot (comment this block out if you don't need visuals)
try:
    import matplotlib.pyplot as plt

    xs, ys = zip(*pts)
    plt.figure()
    plt.plot(xs, ys, marker="o")  # outline
    plt.axis("equal")
    plt.title("Polyline / Profile")
    plt.xlabel("X")
    plt.ylabel("Y")
    plt.grid(True)
    plt.show()
except Exception as e:
    print(f"(Plot skipped: {e})")
