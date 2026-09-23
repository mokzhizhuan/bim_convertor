import ifcopenshell

# Load your IFC
ifc = ifcopenshell.open("TERRAHL2-FP-MB-T1am(JMB).ifc")


def cart3(pt):
    coords = list(pt.Coordinates)
    if len(coords) == 2:
        coords.append(0.0)
    return tuple(float(c) for c in coords[:3])


matches = []
for pt in ifc.by_type("IfcCartesianPoint"):
    x, y, z = cart3(pt)
    if abs(x - 515) < 1e-6 or abs(y - 515) < 1e-6:
        matches.append({"id": pt.id(), "coords": (x, y, z)})

print(f"Found {len(matches)} points with X=515 or Y=515")
for m in matches:
    print(f"#{m['id']}  coords={m['coords']}")
