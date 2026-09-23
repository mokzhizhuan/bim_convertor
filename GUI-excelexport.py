import PySimpleGUI as sg # pip install pysimplegui
from pathlib import Path
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as Element
from ifcopenshell.util.placement import get_local_placement
import pandas as pd

# Menu Definition #
menu_def = [["Menu", ["Command 1", "Command 2"]],
            ["Help", ["Settings", "About", "Guide", "Exit"]]]

# Main Window Function #
def main_window():
    
    # Validation Function #
    def is_valid_path(filepath):
        if filepath and Path(filepath).exists():
            return True
        else:
            sg.popup_no_titlebar("Filepath is Incorrect")
            return False

    # Export Excel Function #
    def extract_data(ifc_file_path, output_folder):
        filepath = Path(ifc_file_path)
        file = ifcopenshell.open(filepath)

        def get_objects_data_by_class(file, class_type):
            def add_pset_attributes(psets):
                for pset_name, pset_data in psets.items():
                    for property_name in pset_data.keys():
                        pset_attributes.add(f'{pset_name}.{property_name}')
            
            pset_attributes = set()
            objects_data=[]
            objects = file.by_type(class_type)
            for object in objects:
                psets = Element.get_psets(object, psets_only=True)
                add_pset_attributes(psets)
                qtos = Element.get_psets(object, qtos_only=True)
                add_pset_attributes(qtos)
                placement_matrix = get_local_placement(object.ObjectPlacement)
                # Extract Vertices of Elements
                if object.Representation is not None:
                    settings = ifcopenshell.geom.settings()
                    shape = ifcopenshell.geom.create_shape(settings, object)
                    verts = shape.geometry.verts
                    grouped_verts = [[verts[i], verts[i + 1], verts[i + 2]] for i in range(0, len(verts), 3)]
                objects_data.append({
                "ExpressID" : object.id(),
                "GlobalID" : object.GlobalId,
                "Class" : object.is_a(),
                "PredefinedType" : Element.get_predefined_type(object),
                "Name" : object.Name,
                "Level" : Element.get_container(object).Name if Element.get_container(object) else "",
                "ObjectType" : Element.get_type(object).Name if Element.get_type(object) else "",
                "PlacementMatrix" : placement_matrix,
                "Vertices" : grouped_verts,
                "QuantitySets" : qtos,
                "PropertySets" : psets
            })
            return objects_data, list(pset_attributes)

        def get_attribute_value(object_data, attribute):
            if "." not in attribute:
                return object_data[attribute]
            elif "." in attribute:
                pset_name = attribute.split(".",1)[0]
                prop_name = attribute.split(".",-1)[1]
                if pset_name in object_data["PropertySets"].keys():
                    if prop_name in object_data["PropertySets"][pset_name].keys():
                        return object_data["PropertySets"][pset_name][prop_name]
                    else:
                        return None
                if pset_name in object_data["QuantitySets"].keys():
                    if prop_name in object_data["QuantitySets"][pset_name].keys():
                        return object_data["QuantitySets"][pset_name][prop_name]
                    else:
                        return None
            else:
                return None

        data, pset_attributes = get_objects_data_by_class(file, "IfcElement")
        attributes = ["ExpressID", "GlobalID", "Class", "PredefinedType", "Name", "Level", "ObjectType", "PlacementMatrix","Vertices"] + pset_attributes

        pandas_data = []
        for object_data in data:
            row = []
            for attribute in attributes:
                value = get_attribute_value (object_data, attribute)
                row.append(value)
            pandas_data.append(tuple(row))

        dataframe = pd.DataFrame.from_records(pandas_data, columns=attributes)

        outputpath = Path(output_folder)
        writer = pd.ExcelWriter(outputpath/'exporteddata.xlsx', engine='xlsxwriter')
        
        for object_class in dataframe["Class"].unique():
            df_class = dataframe[dataframe["Class"] == object_class]
            df_class = df_class.dropna(axis=1, how='all')
            df_class.to_excel(writer, sheet_name=object_class)
        writer._save()
        sg.popup_no_titlebar("Completed")

    # GUI Definition #
    layout = [
        [sg.MenubarCustom(menu_def, tearoff=False)],
        [sg.Text("Input File :    "), sg.Input(key="-IN-"), sg.FileBrowse(file_types=(("IFC Files", "*.ifc*"),))],
        [sg.Text("Output File : "), sg.Input(key="-OUT-"), sg.FolderBrowse()],
        [sg.Button("Extract Data", s=16), sg.Button("View Live Feed", s=16), sg.Button("View Overlay", s=16), sg.Exit(s=16)]
    ]

    window_title = settings["GUI"]["title"]
    window = sg.Window(window_title, layout)

    while True:
        event, values = window.read()
        print(event, values)
        if event == "About":
            window.disappear()
            sg.popup(window_title, "Version 1.0")
            window.reappear()

        if event == "Guide":
            window.disappear()
            sg.popup("Greyform BIM Data Interpreter Guide: ", "Click browse under input and select a valid IFC file.", "Cick browse under output and select a valid folder location.", "Click Extract Data. A 'Extraction Completed'popup will appear.", "The extracted data file can be found in the selected folder location.")
            window.reappear()

        if event in (sg.WINDOW_CLOSED, "Exit"):
            break

        if event == "Extract Data":
            if is_valid_path(values["-IN-"] and values["-OUT-"]):
                extract_data(
                    ifc_file_path=values["-IN-"],
                    output_folder=values["-OUT-"]
                )
    window.close()

if __name__ == "__main__":
    SETTINGS_PATH = Path.cwd()
    # create settings object and use ini format
    settings = sg.UserSettings(
        path=SETTINGS_PATH, filename="Config.ini", use_config_file=True, convert_bools_and_none=True
    )
    theme = settings["GUI"]["theme"]
    font_family = settings["GUI"]["font_family"]
    font_size = int(settings["GUI"]["font_size"])
    sg.theme(theme)
    sg.set_options(font=(font_family, font_size))
    main_window()