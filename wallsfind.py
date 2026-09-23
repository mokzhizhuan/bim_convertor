import ifcopenshell

# Load IFC
ifc = ifcopenshell.open("TERRAHL2-FP-MB-T1am(JMB).ifc")

# Loop through all IfcWallStandardCase
for wall in ifc.by_type("IfcWallStandardCase"):
    print("\nWall:", wall.GlobalId, wall.Name)

    # Get product definition shape
    shape = wall.Representation
    if not shape:
        continue

    # Loop through all shape representations
    for rep in shape.Representations:
        print("  RepresentationIdentifier:", rep.RepresentationIdentifier)
        print("  RepresentationType:", rep.RepresentationType)

        # Loop through geometry items in each representation
        for item in rep.Items:
            print("    Item:", item.is_a())

            # Example: IfcExtrudedAreaSolid (common for walls)
            if item.is_a("IfcExtrudedAreaSolid"):
                profile = (
                    item.SweptArea
                )  # usually IfcRectangleProfileDef or IfcArbitraryClosedProfileDef
                placement = item.Position  # IfcAxis2Placement3D
                extrusion_dir = item.ExtrudedDirection
                depth = item.Depth

                print("      Profile Type:", profile.is_a())
                print("      Extrusion Depth:", depth)

                # If profile is rectangular
                if profile.is_a("IfcRectangleProfileDef"):
                    print("      Width:", profile.XDim)
                    print("      Height:", profile.YDim)

                # If profile is arbitrary closed polygon
                if profile.is_a("IfcArbitraryClosedProfileDef"):
                    outer_curve = profile.OuterCurve
                    if outer_curve.is_a("IfcPolyline"):
                        points = []
                        for p in outer_curve.Points:
                            coords = p.Coordinates
                            points.append(tuple(coords))
                        print("      Polygon Points:", points)

            # Example: IfcFacetedBrep
            if item.is_a("IfcFacetedBrep"):
                for face in item.Outer.CfsFaces:
                    for loop in face.Bounds:
                        for vert in loop.Bound.Vertices:
                            coords = vert.Coordinates
                            print("      Vertex:", tuple(coords))
