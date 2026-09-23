import ifcopenshell
import ifcopenshell.geom
import numpy as np
import vtk
from ifcopenshell.util.placement import get_local_placement

# Setup renderer and window
renderer = vtk.vtkRenderer()
render_window = vtk.vtkRenderWindow()
render_window.AddRenderer(renderer)
interactor = vtk.vtkRenderWindowInteractor()
interactor.SetRenderWindow(render_window)

# IFC settings
settings = ifcopenshell.geom.settings()
settings.set(settings.USE_WORLD_COORDS, False)
ifc = ifcopenshell.open("CANBERA2_PBUWC1.ifc")
walls = ifc.by_type("IfcWallStandardCase")
print(f"Found {len(walls)} walls.")


# Assign different colors to each wall
def get_distinct_color(index):
    color_map = [
        (0.8, 0.8, 0.8), (0.9, 0.3, 0.3), (0.3, 0.9, 0.3), (0.3, 0.3, 0.9),
        (0.9, 0.9, 0.3), (0.9, 0.5, 0.9), (0.2, 0.7, 0.9), (0.6, 0.4, 0.3)
    ]
    return color_map[index % len(color_map)]

for idx, wall in enumerate(walls):
    try:
        shape = ifcopenshell.geom.create_shape(settings, wall)
        verts = np.array(shape.geometry.verts).reshape(-1, 3)
        faces = np.array(shape.geometry.faces).reshape(-1, 4)

        if verts.size == 0 or faces.size == 0:
            continue

        # Transform vertices to world coordinates
        transform = get_local_placement(wall.ObjectPlacement)
        verts_world = (transform[:3, :3] @ verts.T).T + transform[:3, 3]

        # Build VTK points
        points = vtk.vtkPoints()
        for pt in verts_world:
            points.InsertNextPoint(*pt)

        # Build faces
        polys = vtk.vtkCellArray()
        for face in faces:
            if face[0] != 3:
                continue
            ids = vtk.vtkIdList()
            for i in face[1:]:
                ids.InsertNextId(int(i))
            polys.InsertNextCell(ids)

        # Create wall mesh
        wall_poly = vtk.vtkPolyData()
        wall_poly.SetPoints(points)
        wall_poly.SetPolys(polys)

        wall_mapper = vtk.vtkPolyDataMapper()
        wall_mapper.SetInputData(wall_poly)

        wall_actor = vtk.vtkActor()
        wall_actor.SetMapper(wall_mapper)
        wall_actor.GetProperty().SetColor(*get_distinct_color(idx))
        renderer.AddActor(wall_actor)

        # Origin sphere
        min_z = np.min(verts_world[:, 2])
        base_pts = verts_world[np.isclose(verts_world[:, 2], min_z)]
        min_x, min_y = np.min(base_pts[:, 0]), np.min(base_pts[:, 1])
        origin = [min_x, min_y, min_z]

        sphere = vtk.vtkSphereSource()
        sphere.SetCenter(*origin)
        sphere.SetRadius(50)

        sphere_mapper = vtk.vtkPolyDataMapper()
        sphere_mapper.SetInputConnection(sphere.GetOutputPort())

        sphere_actor = vtk.vtkActor()
        sphere_actor.SetMapper(sphere_mapper)
        sphere_actor.GetProperty().SetColor(1, 0, 0)
        renderer.AddActor(sphere_actor)

    except Exception as e:
        print(f"Error on wall {wall.Name or wall.GlobalId}: {e}")

# Add coordinate axes (XYZ)
axes_actor = vtk.vtkAxesActor()
axes_actor.SetTotalLength(200, 200, 200)  # scale of XYZ arrows
axes_actor.AxisLabelsOn()  # shows X Y Z letters

# Setup orientation marker widget
orientation_widget = vtk.vtkOrientationMarkerWidget()
orientation_widget.SetOrientationMarker(axes_actor)
orientation_widget.SetInteractor(interactor)
orientation_widget.SetViewport(0.0, 0.0, 0.2, 0.2)  # lower-left corner
orientation_widget.SetEnabled(True)
orientation_widget.InteractiveOff()
renderer.AddActor(axes_actor)

# After adding all geometry, before interactor.Start():
render_window.Render()
renderer.ResetCamera()

cube_axes = vtk.vtkCubeAxesActor()
cube_axes.SetCamera(renderer.GetActiveCamera())
cube_axes.SetBounds(renderer.ComputeVisiblePropBounds())
cube_axes.SetFlyModeToOuterEdges()

# Axis titles
cube_axes.SetXTitle("X (mm)")
cube_axes.SetYTitle("Y (mm)")
cube_axes.SetZTitle("Z (mm)")

# Tick label formats with units
cube_axes.SetXLabelFormat("%.0f mm")
cube_axes.SetYLabelFormat("%.0f mm")
cube_axes.SetZLabelFormat("%.0f mm")

# Colors and size for better visibility
for i in range(3):
    cube_axes.GetTitleTextProperty(i).SetColor(1, 1, 1)
    cube_axes.GetLabelTextProperty(i).SetColor(1, 1, 1)
    cube_axes.GetTitleTextProperty(i).SetFontSize(24)
    cube_axes.GetLabelTextProperty(i).SetFontSize(20)

renderer.AddActor(cube_axes)
interactor.Start()
