
import PySimpleGUI as sg # pip install pysimplegui
from pathlib import Path
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as Element
from ifcopenshell.util.placement import get_local_placement
import pandas as pd
import cv2
import os

# Global variable
substringTMP1_1 = ['a2', 'a3', 'a4', 'a5']

# Menu Definition #
menu_def = [["Menu", ["Command 1", "Command 2"]],
            ["Help", ["Settings", "About", "Guide"]]]

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

              
                revert_origin = object.Name if object.Name == 'CP1:CP1:1433163' else ""

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
                "RevertOrigin" : revert_origin,
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
            

        def get_next_file_number(output_folder):
            existing_files = os.listdir(output_folder)
            if 'exporteddata.xlsx' not in existing_files:
                return ''
            
            max_number = 0
            for file_name in existing_files:
                if file_name.startswith('exporteddata_') and file_name.endswith('.xlsx'):
                    parts = file_name.split('_')
                    if len(parts) > 1:
                        try:
                            number = int(parts[1].split('.')[0])
                            max_number = max(max_number, number)
                        except ValueError:
                            continue
            return f'_{max_number + 1}'
            
        def format_matrix(matrix):
            return [[f"{element:.2f}" for element in row] for row in matrix]


        def add_markers(row):
            if row['Name'] and row['Name'].startswith('TMP'):
                if any(char in row['Name'] for char in ['a', 'b', 'c']) and row['Name'][8] == 's':
                    return 'T'
                else:
                    return '+'
            return ''
            
        def apply_rotation_to_markers(workbook, worksheet, df_class):
            marker_col_index = df_class.columns.get_loc('Markers')
            format_rotated_n90 = workbook.add_format({'rotation': -90})  
            format_rotated_90 = workbook.add_format({'rotation': 90}) 
            for row_idx, (name, marker) in enumerate(zip(df_class['Name'], df_class['Markers']), start=1):
                if name and name.startswith('TMP') and name[8] == 's' and name[3] == "7":
                    print(f"Rotating marker for row {row_idx}: {marker}")
                    if 'b' in name:
                        worksheet.write(row_idx, marker_col_index+1, marker, format_rotated_90)
                    else:
                        worksheet.write(row_idx, marker_col_index+1, marker, format_rotated_n90)
        
        data, pset_attributes = get_objects_data_by_class(file, "IfcElement")
        attributes = ["ExpressID", "GlobalID", "Class", "PredefinedType", "Name", "Level", "ObjectType", "PlacementMatrix", "RevertOrigin", "Vertices"] + pset_attributes

        pandas_data = []
        for object_data in data:
            row = []
            for attribute in attributes:
                value = get_attribute_value (object_data, attribute)
                row.append(value)
            pandas_data.append(tuple(row))

        dataframe = pd.DataFrame.from_records(pandas_data, columns=attributes)

        dataframe['Markers'] = dataframe.apply(add_markers, axis=1)

        outputpath = Path(output_folder)
        file_suffix = get_next_file_number(output_folder)
        file_name = f'exporteddata{file_suffix}.xlsx'
        with pd.ExcelWriter(outputpath/file_name, engine='xlsxwriter') as writer:
            workbook = writer.book
            # format_rotated = workbook.add_format({'text_wrap': True, 'valign': 'top', 'rotation': 90})
        
            for object_class in dataframe["Class"].unique():
                df_class = dataframe[dataframe["Class"] == object_class]
                df_class = df_class.drop(['Class', 'PredefinedType', 'RevertOrigin', 'Vertices', 'Pset_ProvisionForVoid.Width', 
                                      'Pset_ProvisionForVoid.Depth', 'Pset_QuantityTakeOff.Reference', 'Pset_ProvisionForVoid.id', 
                                      'Pset_ProductRequirements.id', 'Pset_BuildingElementProxyCommon.Reference', 'Pset_QuantityTakeOff.id',
                                      'Pset_BuildingElementProxyCommon.id', 'Pset_ProvisionForVoid.Height', 'Pset_ProductRequirements.Category'], axis=1)
                df_class = df_class.dropna(axis=1, how='all')
                df_class.to_excel(writer, sheet_name=object_class)
                #Rotated cell
                worksheet = writer.sheets[object_class]
                apply_rotation_to_markers(workbook, worksheet, df_class)
        
        # Apply this custom formatting function to the 'PlacementMatrix' column
        dataframe['PlacementMatrix'] = dataframe['PlacementMatrix'].apply(format_matrix)
        
        # writer._save()
        sg.popup_no_titlebar("Completed")  

    # Camera Live Feed For Automated Marking#
    def automated_marking():
        layout = [
            [sg.Image(key = '-IMAGE-')], [sg.Button("Begin Marking", s=16), sg.Exit(s=16)]]

        window = sg.Window(title=None, no_titlebar=True, layout=layout, finalize=True, element_justification="center")
        window.Maximize()

        # Camera Feed #
        camera_Width  = 1600 #320 # 480 # 640 # 1024 # 1280
        camera_Heigth = 1020 #240 # 320 # 480 # 780  # 960
        frameSize = (camera_Width, camera_Heigth)
        video = cv2.VideoCapture(0)
        face_cascade = cv2.CascadeClassifier('haarcascade_frontalface_default.xml')

        while True:
            event, values = window.read(timeout = 0)
            if event in (sg.WINDOW_CLOSED, "Exit"):
                window.disappear()
                break

            _, frame = video.read()
            frame = cv2.resize(frame, frameSize)
            gray = cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(
                gray,
                scaleFactor = 1.1, 
                minNeighbors = 5,
                minSize =(20,20))

            # Rectangle #
            for (x, y, w, h) in faces:
                cv2.rectangle(frame,(x,y),(x + w, y + h),(0,255,0),2)

            # Image Updates #
            imgbytes = cv2.imencode('.png',frame)[1].tobytes()
            window['-IMAGE-'].update(data = imgbytes)

            if event == "Begin Marking":
                sg.popup("Under Construction")

    def object_tracking():        
        layout = [[sg.Image(key = '-IMAGE-')], [sg.Button("Begin Marking", s=16), sg.Exit(s=16)]]

        window = sg.Window(title=None, no_titlebar=True, layout=layout, finalize=True, element_justification="center")
        window.Maximize()

        # Camera Feed #
        camera_Width  = 1600 #320 # 480 # 640 # 1024 # 1280
        camera_Heigth = 1020 #240 # 320 # 480 # 780  # 960
        frameSize = (camera_Width, camera_Heigth)
        video = cv2.VideoCapture(0)

        # Tracking Object with Bounding #
        # tracker = cv2.legacy.TrackerMOSSE_create()
        # tracker = cv2.legacy.TrackerCSRT_create()
        tracker = cv2.legacy.TrackerMedianFlow_create()
        # tracker = cv2.legacy.TrackerKCF_create()	#High Speed. Lose Object, Lose Track#
        # tracker = cv2.TrackerGOTURN_create()	#Deep Learning Tracker#

        _, frame = video.read()
        frame = cv2.resize(frame, frameSize)
        bbox = cv2.selectROI(frame,False)
        tracker.init(frame, bbox)

        def drawBox(frame, bbox):
            x, y, w, h = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
            cv2.rectangle(frame, (x,y), ((x+w), (y+h)), (255,0,255),3,1)
            cv2.putText(frame,"Tracking",(75,75),cv2.QT_FONT_NORMAL,0.7,(0,255,0),2)

        while True:
            timer = cv2.getTickCount()
            event, values = window.read(timeout = 0)
            if event in (sg.WINDOW_CLOSED, "Exit"):
                window.disappear()
                break

            _, frame = video.read()
            frame = cv2.resize(frame, frameSize)

            success, bbox = tracker.update(frame)
            print(bbox)

            if success:
                drawBox(frame, bbox)
            else:
                cv2.putText(frame,"Tracker Lost",(75,75),cv2.QT_FONT_NORMAL,0.7,(0,0,255),2)

            fps = cv2.getTickFrequency()/(cv2.getTickCount()-timer)
            cv2.putText(frame,str(int(fps)),(75,50),cv2.QT_FONT_NORMAL,0.7,(0,255,0),2)

            if event == sg.WIN_CLOSED:
                break

            # Image Updates #
            imgbytes = cv2.imencode('.png',frame)[1].tobytes()
            window['-IMAGE-'].update(data = imgbytes)

            if event == "Begin Marking":
                sg.popup("Under Construction")

    # GUI Definition #
    layout = [
        [sg.MenubarCustom(menu_def, tearoff=False)],
        [sg.Text("Input File :    "), sg.Input(key="-IN-", expand_x=True), sg.FileBrowse(file_types=(("IFC Files", "*.ifc*"),))],
        [sg.Text("Output File : "), sg.Input(key="-OUT-", expand_x=True), sg.FolderBrowse()],
        [sg.Button("Extract Data", s=16), sg.Button("Automated Marking", s=16), sg.Button("Object Tracking", s=16)],
        [sg.Column([[]], expand_y=True)],
        [sg.Push(), sg.Exit(s=16)]
    ]

    window_title = settings["GUI"]["title"]
    window = sg.Window(title=None, no_titlebar=True, layout=layout, finalize=True, disable_close=True, disable_minimize=True, resizable=False)
    window.Maximize()

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

        if event == "Extract Data":
            if is_valid_path(values["-IN-"] and values["-OUT-"]):
                extract_data(
                    ifc_file_path=values["-IN-"],
                    output_folder=values["-OUT-"]
                )

        if event == "Automated Marking":
            automated_marking()

        if event == "Object Tracking":
            object_tracking()

        if event == "Exit":
            break
        
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