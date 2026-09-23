import json
import numpy as np
import open3d as o3d
from pathlib import Path
from scipy.spatial.transform import Rotation as R

centers_path = Path("cw_stage_2_centers_fixed.json")
data = json.loads(centers_path.read_text(encoding="utf-8"))

origin_frame = o3d.geometry.TriangleMesh.create_coordinate_frame(size=1000, origin=[0, 0, 0])
R_0 = (0, 0, 0)
R_90_X = (np.pi/2, 0, 0)
R_90_Y = (0, np.pi/2, 0)
R_NEG_90_Z = (0, 0, -np.pi/2)
rotations = [R_NEG_90_Z, R_NEG_90_Z, R_0, R_NEG_90_Z, R_0, R_0, R_0]
geometries = [origin_frame]
# for (stage, center), rot_xyz in zip(data.items(), rotations):
#     print(f"{stage}: {center}")
#     t = (center["x"]*1000, center["y"]*1000, center["z"]*1000)
#     quat = (center["qw"], center["qx"], center["qy"], center["qz"])
#     center_frame = o3d.geometry.TriangleMesh.create_coordinate_frame(size=300, origin=[0, 0, 0])
#     mtx = center_frame.get_rotation_matrix_from_quaternion(quat)
#     rot = center_frame.get_rotation_matrix_from_xyz(rot_xyz)
#     center_frame.rotate(mtx, center=(0, 0, 0))
#     # center_frame.rotate(rot, center=(0, 0, 0))
#     quat_final = R.from_matrix(mtx @ rot).as_quat()
#     # print(quat_final)
#     center_frame.translate(t)
#     geometries.append(center_frame)

# mesh_path = "Stage_1_MIRRORED_RIGHT.stl"
mesh_path = "Stage_2.stl"
mesh = o3d.io.read_triangle_mesh(mesh_path)
T_mirror = np.array([[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
mesh.transform(T_mirror)
triangles = np.asarray(mesh.triangles)
mesh.triangles = o3d.utility.Vector3iVector(triangles[:, ::-1])  # Reverse triangle winding order
R_90_Z = mesh.get_rotation_matrix_from_xyz((0,0,np.pi/2))
mesh.rotate(R_90_Z, center=(0, 0, 0))
mesh.compute_vertex_normals()
o3d.io.write_triangle_mesh("cw_stage_2_mirror_v2.stl", mesh)
geometries.append(mesh)
pcd = mesh.sample_points_uniformly(20000)
pcd.paint_uniform_color([0.7,0.7,0.7])
geometries.append(pcd)
o3d.visualization.draw_geometries(geometries, mesh_show_back_face=True)