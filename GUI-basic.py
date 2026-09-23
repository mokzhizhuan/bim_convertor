import PySimpleGUI as sg # pip install pysimplegui
from pathlib import Path

import pandas as pd

# Function #
def convert_csv(excel_file_path, output_folder, separator, decimal):
   df = pd.read_excel(excel_file_path)
   filename = Path(excel_file_path).stem
   outputfile = Path(output_folder) / f"{filename}.csv"
   df.to_csv(outputfile, sep=separator, decimal=decimal, index=False)
   sg.popup_no_titlebar("Completed")

# GUI Definition #
layout = [
    [sg.Text("Input File"), sg.Input(key="-IN-"), sg.FileBrowse(file_types=(("IFC Files", "*.xlsx*"),))],
    [sg.Text("Output File"), sg.Input(key="-OUT-"), sg.FolderBrowse()],
    [sg.Exit(), sg.Button("Extract Data")]
]

window = sg.Window("Greyform BIM Data Interpreter", layout)

while True:
    event, values = window.read()
    print(event, values)
    if event in (sg.WINDOW_CLOSED, "Exit"):
        break
    if event == "Extract Data":
        convert_csv(
            excel_file_path=values["-IN-"],
            output_folder=values["-OUT-"],
            separator="|",
            decimal="."
        )
window.close()