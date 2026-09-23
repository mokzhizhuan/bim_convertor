from pathlib import Path
import struct
import numpy as np


def read_stl(path):
    """Read binary or ASCII STL and return triangles."""
    path = Path(path)
    data = path.read_bytes()

    # ---------- Binary STL ----------
    if len(data) >= 84:
        triangle_count = struct.unpack_from("<I", data, 80)[0]

        if 84 + triangle_count * 50 == len(data):
            triangles = np.empty(
                (triangle_count, 3, 3),
                dtype=np.float32
            )

            offset = 84

            for i in range(triangle_count):

                # Skip original normal
                offset += 12

                triangles[i] = np.frombuffer(
                    data,
                    dtype="<f4",
                    count=9,
                    offset=offset
                ).reshape(3, 3)

                offset += 36

                # Skip attribute byte count
                offset += 2

            return triangles

    # ---------- ASCII STL ----------
    vertices = []

    text = data.decode("utf-8", errors="ignore")

    for line in text.splitlines():

        parts = line.strip().split()

        if len(parts) == 4 and parts[0].lower() == "vertex":

            vertices.append([
                float(parts[1]),
                float(parts[2]),
                float(parts[3])
            ])

    vertices = np.asarray(vertices, dtype=np.float32)

    return vertices.reshape(-1, 3, 3)


def write_stl(path, triangles):
    """Write triangles as binary STL."""

    path = Path(path)

    with open(path, "wb") as f:

        # 80-byte STL header
        header = b"PBU mirror X + STL-only Z rotation +90deg"
        f.write(header.ljust(80, b" "))

        # Number of triangles
        f.write(
            struct.pack("<I", len(triangles))
        )

        for triangle in triangles:

            v1, v2, v3 = triangle

            # Recalculate face normal
            normal = np.cross(
                v2 - v1,
                v3 - v1
            )

            length = np.linalg.norm(normal)

            if length != 0:
                normal = normal / length

            # Normal
            f.write(
                struct.pack("<3f", *normal)
            )

            # 3 vertices
            f.write(
                struct.pack(
                    "<9f",
                    *triangle.reshape(-1)
                )
            )

            # Attribute byte count
            f.write(
                struct.pack("<H", 0)
            )
def mirror_to_right(input_file):
    """
    Mirror the STL as before, then rotate ONLY the STL by +90 degrees
    around GLOBAL Z while keeping the STL at the same XY centre.

    centers.json is NOT changed.

    Transformation order
    --------------------
    1. Mirror across global X=0:
           X -> -X
           Y ->  Y
           Z ->  Z

    2. Find the mirrored STL's own XY centre.

    3. Rotate the mirrored STL +90 degrees counter-clockwise
       around that centre.

    This keeps the STL centred in the same place instead of rotating
    around world origin and flying away from the existing center.json points.
    """

    input_file = Path(input_file)

    triangles = read_stl(input_file)

    transformed = triangles.copy()

    # =====================================================
    # STEP 1 — SAME MIRROR AS BEFORE
    # =====================================================
    transformed[:, :, 0] *= -1.0

    # Reflection reverses triangle handedness.
    transformed = transformed[:, [0, 2, 1], :]

    # =====================================================
    # STEP 2 — FIND MIRRORED STL XY CENTRE
    # =====================================================
    x_min = float(np.min(transformed[:, :, 0]))
    x_max = float(np.max(transformed[:, :, 0]))

    y_min = float(np.min(transformed[:, :, 1]))
    y_max = float(np.max(transformed[:, :, 1]))

    center_x = (x_min + x_max) / 2.0
    center_y = (y_min + y_max) / 2.0

    # =====================================================
    # STEP 3 — ROTATE +90° ABOUT STL'S OWN CENTRE
    #
    # +90° = 90° counter-clockwise
    #
    # Local-centred coordinates:
    #     xr = x - center_x
    #     yr = y - center_y
    #
    # Rotation:
    #     x_rot = -yr
    #     y_rot =  xr
    #
    # Then translate back to the SAME centre.
    # =====================================================
    old_x = transformed[:, :, 0].copy()
    old_y = transformed[:, :, 1].copy()

    local_x = old_x - center_x
    local_y = old_y - center_y

    transformed[:, :, 0] = -local_y + center_x
    transformed[:, :, 1] = local_x + center_y

    output_file = input_file.with_name(
        input_file.stem + "_MIRRORED_ROT90_STL_ONLY.stl"
    )

    write_stl(
        output_file,
        transformed
    )

    new_x_min = float(np.min(transformed[:, :, 0]))
    new_x_max = float(np.max(transformed[:, :, 0]))

    new_y_min = float(np.min(transformed[:, :, 1]))
    new_y_max = float(np.max(transformed[:, :, 1]))

    print()
    print("Created:", output_file)
    print("centers.json: UNCHANGED")
    print()
    print("Mirrored STL centre used as rotation pivot:")
    print(f"  center_x = {center_x:.3f} mm")
    print(f"  center_y = {center_y:.3f} mm")
    print()
    print("Before +90-degree STL rotation:")
    print(f"  X: {x_min:.3f} .. {x_max:.3f} mm")
    print(f"  Y: {y_min:.3f} .. {y_max:.3f} mm")
    print()
    print("After +90-degree STL rotation:")
    print(f"  X: {new_x_min:.3f} .. {new_x_max:.3f} mm")
    print(f"  Y: {new_y_min:.3f} .. {new_y_max:.3f} mm")

    return output_file


def mirror_across_y_axis(input_file):
    """
    Mirror STL across global Y axis.

    Transformation:
        X -> -X
        Y ->  Y
        Z ->  Z

    This keeps the model upright/oriented
    the same while producing the left/right mirror.
    """

    input_file = Path(input_file)

    triangles = read_stl(input_file)

    mirrored = triangles.copy()

    # -----------------------------------
    # MIRROR ACROSS GLOBAL Y AXIS
    # X -> -X
    # -----------------------------------

    mirrored[:, :, 0] *= -1.0

    # Reflection reverses triangle handedness.
    # Swap vertex 2 and 3 to restore normals.
    mirrored = mirrored[:, [0, 2, 1], :]

    output_file = input_file.with_name(
        input_file.stem +
        "_MIRRORED_ACROSS_Y_AXIS.stl"
    )

    write_stl(
        output_file,
        mirrored
    )

    print("Created:", output_file)

    return output_file


# ==========================================
# YOUR STL FILES
# ==========================================
mirror_to_right("Stage_1.stl")
mirror_to_right("Stage_2.stl")
mirror_to_right("Stage_3.stl")