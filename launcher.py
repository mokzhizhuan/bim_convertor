import os
import sys
import traceback
import multiprocessing
from pathlib import Path
import tkinter as tk
from tkinter import messagebox


# ============================================================
# GREYFORM LAUNCHER
#
# This launcher is compiled into:
#
#     Greyform_IFC_Extractor.exe
#
# The EXE directly imports and opens the GUI from:
#
#     samplewallaxis.py
#
# The end user DOES NOT need:
#
#     - Python installed
#     - pip
#     - PowerShell
#     - Command Prompt
#     - requirements.txt installation
#
# They only double-click the EXE.
# ============================================================


# ============================================================
# APPLICATION DIRECTORY
# ============================================================

if getattr(sys, "frozen", False):

    # Folder containing Greyform_IFC_Extractor.exe
    APP_DIR = Path(sys.executable).resolve().parent

else:

    # Running launcher.py directly during development
    APP_DIR = Path(__file__).resolve().parent


# ============================================================
# LOG FILE
# ============================================================

LOG_FILE = APP_DIR / "greyform_startup_error.log"


# ============================================================
# WRITE ERROR LOG
# ============================================================

def write_error_log(error_text: str) -> None:

    try:

        LOG_FILE.write_text(
            error_text,
            encoding="utf-8",
        )

    except Exception:
        pass


# ============================================================
# SHOW STARTUP ERROR
# ============================================================

def show_startup_error(error_text: str) -> None:

    write_error_log(
        error_text
    )

    # --------------------------------------------------------
    # Create temporary Tk root only for the error dialog
    # --------------------------------------------------------

    try:

        root = tk.Tk()

        root.withdraw()

        messagebox.showerror(
            "Greyform IFC Extractor",
            "Greyform could not start.\n\n"
            "A startup error log has been created:\n\n"
            f"{LOG_FILE}\n\n"
            "Error:\n"
            f"{error_text[-1500:]}"
        )

        root.destroy()

    except Exception:

        # If even Tkinter cannot display a dialog,
        # the log file will still contain the error.
        pass


# ============================================================
# START GREYFORM GUI
# ============================================================

def start_greyform() -> None:

    # ========================================================
    # Import the real GUI
    #
    # samplewallaxis.py contains:
    #
    #     class ExecutableLauncher(tk.Tk):
    #
    # PyInstaller bundles this module into the EXE.
    # ========================================================

    from samplewallaxis import ExecutableLauncher


    # ========================================================
    # Create GUI
    # ========================================================

    app = ExecutableLauncher()


    # ========================================================
    # Start Tkinter event loop
    # ========================================================

    app.mainloop()


# ============================================================
# MAIN
# ============================================================

def main() -> None:

    try:

        # ----------------------------------------------------
        # Remove an old error log from a previous failed run
        # ----------------------------------------------------

        if LOG_FILE.exists():

            try:
                LOG_FILE.unlink()

            except Exception:
                pass


        # ----------------------------------------------------
        # Open Greyform
        # ----------------------------------------------------

        start_greyform()


    except Exception:

        # ----------------------------------------------------
        # Capture COMPLETE traceback
        # ----------------------------------------------------

        error_text = traceback.format_exc()


        # ----------------------------------------------------
        # Write log + show user-friendly message
        # ----------------------------------------------------

        show_startup_error(
            error_text
        )


# ============================================================
# PROGRAM ENTRY
# ============================================================

if __name__ == "__main__":

    # Required because samplewallaxis.py uses multiprocessing
    multiprocessing.freeze_support()

    main()