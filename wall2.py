import vtkmodules.all as vtk

# === Load STL Mesh ===
reader = vtk.vtkSTLReader()
reader.SetFileName("output.stl")
reader.Update()
mesh = reader.GetOutput()

# === Compute Bounds ===
bounds = mesh.GetBounds()
xmin, xmax, ymin, ymax, zmin, zmax = bounds
print(f"Mesh Bounds:\nX: {xmin} to {xmax}\nY: {ymin} to {ymax}\nZ: {zmin} to {zmax}")

# === Clip along X to isolate Wall 2 ===
clip_x_min = xmin + 0.1  # Small margin from start
clip_x_max = xmin + 0.3  # Thin slice for narrow side

plane_min = vtk.vtkPlane()
plane_min.SetOrigin(clip_x_min, 0, 0)
plane_min.SetNormal(1, 0, 0)

plane_max = vtk.vtkPlane()
plane_max.SetOrigin(clip_x_max, 0, 0)
plane_max.SetNormal(-1, 0, 0)

clipper1 = vtk.vtkClipPolyData()
clipper1.SetInputData(mesh)
clipper1.SetClipFunction(plane_min)
clipper1.InsideOutOn()
clipper1.Update()

clipper2 = vtk.vtkClipPolyData()
clipper2.SetInputData(clipper1.GetOutput())
clipper2.SetClipFunction(plane_max)
clipper2.InsideOutOn()
clipper2.Update()

clipped = clipper2.GetOutput()
print(f"✅ Clipped Wall 2 points: {clipped.GetNumberOfPoints()}")

# === Flatten geometry to YZ plane (drop X) ===
points = clipped.GetPoints()
flat_points = vtk.vtkPoints()

for i in range(points.GetNumberOfPoints()):
    _, y, z = points.GetPoint(i)
    flat_points.InsertNextPoint(0, y, z)  # Set X = 0

flattened = vtk.vtkPolyData()
flattened.SetPoints(flat_points)
flattened.SetPolys(clipped.GetPolys())

# === Visualization ===
mapper = vtk.vtkPolyDataMapper()
mapper.SetInputData(flattened)

actor = vtk.vtkActor()
actor.SetMapper(mapper)
actor.GetProperty().SetColor(0, 0, 1)  # Blue

renderer = vtk.vtkRenderer()
renderer.AddActor(actor)
renderer.SetBackground(1, 1, 1)

render_window = vtk.vtkRenderWindow()
render_window.AddRenderer(renderer)

interactor = vtk.vtkRenderWindowInteractor()
interactor.SetRenderWindow(render_window)
render_window.Render()
interactor.Start()
