import math
import matplotlib.pyplot as plt


def compute_aligned_centers(
    distances, rotations, start_pos=(0.0, 0.0), start_angle=0.0, use_degrees=True
):
    """
    Computes a center for each polygon face based on the furthest projected bounds
    of the entire polygon along the line defined by the face.
    """
    if len(distances) != len(rotations):
        raise ValueError("The number of distances must match the number of rotations.")

    # 1. Calculate all vertex coordinates
    vertices = [start_pos]
    x, y = start_pos
    current_angle = start_angle

    for d, r in zip(distances, rotations):
        rad_angle = math.radians(current_angle) if use_degrees else current_angle
        x += d * math.cos(rad_angle)
        y += d * math.sin(rad_angle)
        vertices.append((x, y))
        current_angle += r

    # The last vertex overlaps the first in a closed polygon.
    # We slice [:-1] to get the unique vertices.
    unique_vertices = vertices[:-1]
    centers = []
    n_faces = len(distances)

    # 2. Compute the aligned center for each face
    for i in range(n_faces):
        v_start = vertices[i]
        v_end = vertices[i + 1]

        # Calculate direction vector of the current face
        dx = v_end[0] - v_start[0]
        dy = v_end[1] - v_start[1]
        length = math.hypot(dx, dy)

        if length == 0:
            # Fallback if distance is 0
            centers.append(v_start)
            continue

        # Unit vector (ux, uy) represents the direction of the face line
        ux = dx / length
        uy = dy / length

        # 3. Project all vertices onto the line of this face
        projections = []
        for v in unique_vertices:
            # Vector from face start to the current vertex
            vx_diff = v[0] - v_start[0]
            vy_diff = v[1] - v_start[1]

            # Dot product gives the projected distance along the line
            proj_dist = (vx_diff * ux) + (vy_diff * uy)
            projections.append(proj_dist)

        # 4. Find extents and the midpoint
        t_min = min(projections)
        t_max = max(projections)
        t_mid = (t_min + t_max) / 2.0

        # Translate the midpoint distance back into an (x, y) coordinate
        center_x = v_start[0] + (t_mid * ux)
        center_y = v_start[1] + (t_mid * uy)
        centers.append((center_x, center_y))

    return centers, vertices


# ==========================================
# Example Usage: An Asymmetrical L-Shape
# ==========================================
if __name__ == "__main__":
    # Consider an inverted L-shape.
    # Vertices (approx): (0,0)->(1,0)->(1,1)->(4,1)->(4,2)->(0,2)
    # The first face goes from (0,0) to (1,0) on the X-axis.
    # The whole shape, however, stretches all the way to x=4.

    l_distances = [1.832, 1.840, 0.592, 0.960, 1.240, 2.800]
    l_rotations = [90, 90, 270, 90, 90, 90]

    aligned_centers, vertices = compute_aligned_centers(l_distances, l_rotations)

    print("Aligned Centers for the Asymmetrical L-Shape:")
    for i, center in enumerate(aligned_centers):
        print(f"Face {i+1}: ({center[0]:.4f}, {center[1]:.4f})")

    fig, ax = plt.subplots(figsize=(10, 8))
    original_x = [p[0] for p in aligned_centers]
    original_y = [p[1] for p in aligned_centers]
    for i, (p0, p1) in enumerate(zip(vertices[:-1], vertices[1:])):
        ax.plot(
            [p0[0], p1[0]],
            [p0[1], p1[1]],
            linestyle="--",
            linewidth=1,
        )
        ax.annotate(
            f"wall {(i+1)%(len(vertices)-1) + 1}",
            (original_x[i], original_y[i]),
            xytext=(6, -18),
            textcoords="offset points",
            fontsize=8,
        )
    ax.scatter(original_x, original_y, s=90, marker="o", label="Original")
    ax.grid(True)
    ax.axis("equal")
    plt.show()
