import ifcopenshell


def step_atom(x):
    """Format a value like STEP: strings quoted, None as $, and refs as #id."""
    if x is None:
        return "$"
    if hasattr(x, "id"):  # entity reference
        return f"#{x.id()}"
    if isinstance(x, (list, tuple)):  # list of refs or values
        return "(" + ",".join(step_atom(v) for v in x) + ")"
    if isinstance(x, str):
        return f"'{x}'"
    return str(x)


def extract_ifcproject(path):
    f = ifcopenshell.open(path)
    proj = f.by_type("IfcProject")[0]  # assume one project
    # Core attributes (IFC2x3/IFC4 order):
    # GlobalId, OwnerHistory, Name, Description, ObjectType, LongName, Phase,
    # RepresentationContexts, UnitsInContext
    attrs = {
        "GlobalId": proj.GlobalId,
        "OwnerHistory": proj.OwnerHistory,  # entity ref
        "Name": proj.Name,
        "Description": getattr(proj, "Description", None),
        "ObjectType": getattr(proj, "ObjectType", None),
        "LongName": getattr(proj, "LongName", None),
        "Phase": getattr(proj, "Phase", None),
        "RepresentationContexts": getattr(proj, "RepresentationContexts", None),
        "UnitsInContext": getattr(proj, "UnitsInContext", None),
    }

    # Friendly display
    if attrs["OwnerHistory"]:
        print("OwnerHistory (#):", f"#{attrs['OwnerHistory'].id()}")
    if attrs["UnitsInContext"]:
        print("UnitsInContext (#):", f"#{attrs['UnitsInContext'].id()}")

    # Build a STEP-like line to mirror the IFC text
    step_values = [
        step_atom(attrs["GlobalId"]),
        step_atom(attrs["OwnerHistory"]),
        step_atom(attrs["Name"]),
        step_atom(attrs["Description"]),
        step_atom(attrs["ObjectType"]),
        step_atom(attrs["LongName"]),
        step_atom(attrs["Phase"]),
        step_atom(attrs["RepresentationContexts"]),
        step_atom(attrs["UnitsInContext"]),
    ]
    return attrs
