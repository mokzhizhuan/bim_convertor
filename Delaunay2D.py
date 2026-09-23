import vtk

# Load the STL model
reader = vtk.vtkSTLReader()
reader.SetFileName("output.stl")
reader.Update()
mesh = reader.GetOutput()

# Clip back half of the mesh to keep front-facing geometry
clip_plane = vtk.vtkPlane()
clip_plane.SetOrigin(0, 0.15, 0)  # Adjust Y value for depth slicing
clip_plane.SetNormal(0, 1, 0)

clipper = vtk.vtkClipPolyData()
clipper.SetInputData(mesh)
clipper.SetClipFunction(clip_plane)
clipper.InsideOutOn()
clipper.Update()

# Flatten projection along the Y axis (turn 3D → 2D on XZ)
flatten = vtk.vtkTransform()
flatten.Scale(1, 0, 1)  # squash Y

projector = vtk.vtkTransformPolyDataFilter()
projector.SetInputConnection(clipper.GetOutputPort())
projector.SetTransform(flatten)
projector.Update()

# Visualize
mapper = vtk.vtkPolyDataMapper()
mapper.SetInputConnection(projector.GetOutputPort())

actor = vtk.vtkActor()
actor.SetMapper(mapper)
actor.GetProperty().SetColor(0.0, 0.0, 1.0)  # Blue
actor.GetProperty().SetOpacity(1.0)

renderer = vtk.vtkRenderer()
renderer.AddActor(actor)
renderer.SetBackground(1, 1, 1)  # White

window = vtk.vtkRenderWindow()
window.AddRenderer(renderer)
window.SetSize(1000, 700)

interactor = vtk.vtkRenderWindowInteractor()
interactor.SetRenderWindow(window)

window.Render()
interactor.Start()
    