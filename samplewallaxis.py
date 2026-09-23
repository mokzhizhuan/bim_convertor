import pandas as pd
import ifcopenshell
from pyparsing import Dict, Optional
import methodifcfindings as ifc_findings
import loadtmp6sides as tmps6sidesPBU
import fitting_width as fitting
import gettmps as tmps
import getstagesvar as stage_val
import fitting_pointbox as pointbox
import getmodelname as modelnames
from ifcopenshell.util.placement import get_local_placement
import compute_wall_center as wc
import robot_pos as setuprobot
import annotation as modellines
import material as mats
import ifcopenshell
import re
import heapq
import ifc_wall_schematic_exporter as exporter
import sanitary_pipe_bbox_method as sanitary_pipe
import numpy as np
import math
import multiprocessing
import queue
import os
import traceback
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import ifc_to_3_stl_exporter as stl_exporter




def validate_file(path, ext):
    if not path:
        raise ValueError(f"No file selected for {ext}")
    if not os.path.isfile(path):
        raise ValueError(f"File does not exist: {path}")
    if not path.lower().endswith(ext.lower()):
        raise ValueError(f"Expected {ext} file, got: {path}")
    return path


class InputArgs:
    def __init__(self, ifc_file, excel_checklist,output_name, output_folder):
        self.ifc_file = ifc_file
        self.excel_checklist = excel_checklist
        self.output_name = output_name
        self.output_folder = output_folder

def extraction_process_worker(args, result_queue):
    try:
        perform_extraction(args)
        result_queue.put({
            "status": "success",
            "output_folder": args.output_folder,
            "output_name": args.output_name
        })
    except Exception as e:
        result_queue.put({
            "status": "error",
            "error": str(e),
            "trace": traceback.format_exc()
        })

class ExecutableLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Greyform IFC Extractor")
        self.geometry("980x620")
        self.minsize(980, 620)
        self.resizable(True, True)

        self.ifc_var = tk.StringVar()
        self.excel_var = tk.StringVar()
        self.output_name_var = tk.StringVar(value="output")
        self.output_folder_var = tk.StringVar(value=os.getcwd())
        self.status_var = tk.StringVar(value="Ready")

        self.progress_window = None
        self.progress_bar = None
        self.worker_process = None
        self.result_queue = multiprocessing.Queue()

        self._build_ui()

    def _build_ui(self):
        container = ttk.Frame(self, padding=16)
        container.pack(fill="both", expand=True)

        title = ttk.Label(
            container, text="Greyform IFC Extractor", font=("Segoe UI", 16, "bold")
        )
        title.pack(anchor="w", pady=(0, 6))

        subtitle = ttk.Label(
            container,
            text="Select the IFC file and Excel checklist, then type the output name and click Run.",
        )
        subtitle.pack(anchor="w", pady=(0, 14))

        form = ttk.Frame(container)
        form.pack(fill="x")

        self._file_row(form, 0, "IFC File", self.ifc_var, self.pick_ifc)
        self._file_row(form, 1, "Excel Checklist", self.excel_var, self.pick_excel)

        self._file_row(
            form,
            2,
            "Output Folder",
            self.output_folder_var,
            self.pick_output_folder,
            is_file=False,
        )

        ttk.Label(form, text="Output Name").grid(row=4, column=0, sticky="w", pady=8)

        self.output_name_entry = ttk.Entry(
            form,
            textvariable=self.output_name_var,
            width=70,
        )
        self.output_name_entry.grid(row=4, column=1, sticky="we", padx=(8, 8), pady=8)

        form.columnconfigure(1, weight=1)

        help_box = ttk.LabelFrame(container, text="What this program saves", padding=12)
        help_box.pack(fill="x", pady=(16, 12))
        ttk.Label(help_box, text="• <output_name>.xlsx").pack(anchor="w")
        ttk.Label(help_box, text="• <output_name>_pos1.png").pack(anchor="w")
        ttk.Label(help_box, text="• <output_name>_pos2.png").pack(anchor="w")
        ttk.Label(help_box, text="• <output_name>_01_empty_wall_slab.stl").pack(anchor="w")
        ttk.Label(help_box, text="• <output_name>_02_pipe_boxup.stl").pack(anchor="w")
        ttk.Label(help_box, text="• <output_name>_03_everything_except_stage3.stl").pack(anchor="w")

        action_row = ttk.Frame(container)
        action_row.pack(fill="x", pady=(8, 10))
        self.run_button = ttk.Button(
            action_row, text="Run Extraction", command=self.start_extraction, width=18
        )
        self.run_button.pack(side="left")
        self.close_button = ttk.Button(
            action_row, text="Close", command=self.destroy, width=12
        )
        self.close_button.pack(side="left", padx=(8, 0))

        status_frame = ttk.LabelFrame(container, text="Status", padding=12)
        status_frame.pack(fill="both", expand=True)
        ttk.Label(
            status_frame, textvariable=self.status_var, wraplength=700, justify="left"
        ).pack(anchor="w")
    def _file_row(self, parent, row, label, var, command, is_file=True):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=8)
        entry = ttk.Entry(parent, textvariable=var, width=70)
        entry.grid(row=row, column=1, sticky="we", padx=(8, 8), pady=8)
        button = ttk.Button(parent, text="Browse", command=command, width=12)
        button.grid(row=row, column=2, pady=8)

        if row == 0:
            self.ifc_entry = entry
            self.ifc_button = button
        elif row == 1:
            self.excel_entry = entry
            self.excel_button = button
        elif row == 2:
            self.output_folder_entry = entry
            self.output_folder_button = button

        if is_file:
            ttk.Label(parent, text="").grid(row=row, column=3)

    def pick_ifc(self):
        path = filedialog.askopenfilename(
            title="Select IFC file",
            filetypes=[("IFC files", "*.ifc"), ("All files", "*.*")],
        )
        if path:
            self.ifc_var.set(path)

    def pick_excel(self):
        path = filedialog.askopenfilename(
            title="Select Excel checklist",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
        )
        if path:
            self.excel_var.set(path)

    def pick_output_folder(self):
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.output_folder_var.set(path)

    def _set_controls_state(self, state):
        controls = [
            self.ifc_entry,
            self.ifc_button,
            self.excel_entry,
            self.excel_button,
            self.output_folder_entry,
            self.output_folder_button,
            self.output_name_entry,
            self.run_button,
            self.close_button,
        ]

        for widget in controls:
            widget.configure(state=state)

    def _check_extraction_result(self):
        try:
            result = self.result_queue.get_nowait()
        except queue.Empty:
            # Keep checking every 300ms while process is running
            if self.worker_process is not None and self.worker_process.is_alive():
                self.after(300, self._check_extraction_result)
                return

            # Process ended but no result returned
            self._close_progress_window()
            self._set_controls_state("normal")
            self.status_var.set("Extraction stopped unexpectedly.")
            messagebox.showerror("Extraction Error", "Extraction stopped unexpectedly.")
            return

        if result["status"] == "success":
            self._close_progress_window()
            self._set_controls_state("normal")
            self.status_var.set("Extraction of IFC is completed.")

            nl = chr(10)
            message = nl.join([
                "Extraction of IFC is completed.",
                "",
                f"Saved files in: {result['output_folder']}",
                f"- {result['output_name']}.xlsx",
                f"- {result['output_name']}_pos1.png",
                f"- {result['output_name']}_pos2.png",
                f"- {result['output_name']}_01_empty_wall_slab.stl",
                f"- {result['output_name']}_02_pipe_boxup.stl",
                f"- {result['output_name']}_03_everything_except_stage3.stl",
            ])
            messagebox.showinfo("Completed", message)

        else:
            self._close_progress_window()
            self._set_controls_state("normal")
            self.status_var.set(f"Error: {result['error']}")

            error_message = result["error"] + chr(10) + chr(10) + result["trace"]
            messagebox.showerror("Extraction Error", error_message)

    def _validate_inputs(self):
        ifc_file = validate_file(self.ifc_var.get().strip(), ".ifc")
        excel_checklist = validate_file(self.excel_var.get().strip(), ".xlsx")
        output_folder = self.output_folder_var.get().strip() or os.getcwd()
        if not os.path.isdir(output_folder):
            raise ValueError(f"Output folder does not exist: {output_folder}")

        output_name = self.output_name_var.get().strip()
        if not output_name:
            raise ValueError("Output name cannot be empty.")

        invalid = '<>:"/\\|?*'
        if any(ch in output_name for ch in invalid):
            raise ValueError('Output name contains invalid characters: <>:"/\\|?*')

        return InputArgs(
            ifc_file=ifc_file,
            excel_checklist=excel_checklist,
            output_name=output_name,
            output_folder=output_folder,
        )

    def _show_progress_window(self):
        self.progress_window = tk.Toplevel(self)
        self.progress_window.title("Please wait")
        self.progress_window.geometry("400x150")
        self.progress_window.resizable(False, False)
        self.progress_window.transient(self)
        self.progress_window.grab_set()

        frame = ttk.Frame(self.progress_window, padding=18)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="Please wait, IFC extraction in progress...",
            font=("Segoe UI", 11, "bold"),
        ).pack(pady=(8, 12))

        self.progress_bar = ttk.Progressbar(frame, mode="indeterminate", length=320)
        self.progress_bar.pack(pady=8)
        self.progress_bar.start(10)

        ttk.Label(frame, text="This may take a few moments.").pack(pady=(8, 0))

        self.progress_window.protocol("WM_DELETE_WINDOW", lambda: None)

    def _close_progress_window(self):
        if self.progress_window is not None and self.progress_window.winfo_exists():
            self.progress_bar.stop()
            self.progress_window.grab_release()
            self.progress_window.destroy()
        self.progress_window = None
        self.progress_bar = None

    def start_extraction(self):
        try:
            args = self._validate_inputs()
        except Exception as e:
            messagebox.showerror("Input Error", str(e))
            self.status_var.set(str(e))
            return

        self.status_var.set("Please wait, IFC extraction in progress...")
        self._set_controls_state("disabled")
        self._show_progress_window()

        self.worker_process = multiprocessing.Process(
            target=extraction_process_worker,
            args=(args, self.result_queue),
            daemon=True
        )
        self.worker_process.start()

        # Start checking result without freezing Tkinter
        self.after(300, self._check_extraction_result)


    def _on_extraction_complete(self, args):
        self._close_progress_window()
        self._set_controls_state("normal")
        self.status_var.set("Extraction of IFC is completed.")
        nl = chr(10)
        message = nl.join(
            [
                "Extraction of IFC is completed.",
                "",
                f"Saved files in: {args.output_folder}",
                f"- {args.output_name}.xlsx",
                f"- {args.output_name}_pos1.png",
                f"- {args.output_name}_pos2.png",
            ]
        )
        messagebox.showinfo("Completed", message)

    def _on_extraction_error(self, error, trace_text):
        self._close_progress_window()
        self._set_controls_state("normal")
        self.status_var.set(f"Error: {error}")
        error_message = str(error) + chr(10) + chr(10) + trace_text
        messagebox.showerror("Extraction Error", error_message)

def convert_mm_columns_to_m(df):
    """
    Convert selected geometry/output columns from millimetres to metres.
    """
    if df is None or df.empty:
        return df

    columns_to_convert = [
        "GX",
        "GY",
        "GZ",
        "Position X",
        "Position Y",
        "Position Z",
        "Width",
        "Height",
    ]

    df = df.copy()

    for col in columns_to_convert:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            ) / 1000.0

    return df

def _center_xy(obj):
    # Prefer vertices center if available; fallback to x,y
    if isinstance(obj.get("vertices"), np.ndarray) and obj["vertices"].size > 0:
        v = obj["vertices"]
        cx = float(v[:, 0].mean()) + float(obj.get("x", 0.0))
        cy = float(v[:, 1].mean()) + float(obj.get("y", 0.0))
        return (cx, cy)
    return (float(obj.get("x", 0.0)), float(obj.get("y", 0.0)))


def _dist2(a, b):
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return dx * dx + dy * dy


def get_opening_projected_range(opening_obj, wall_axis):
    x = float(opening_obj.get("x", 0.0))
    y = float(opening_obj.get("y", 0.0))
    z = float(opening_obj.get("z", 0.0))

    verts = opening_obj.get("vertices")
    if not isinstance(verts, np.ndarray) or verts.size == 0:
        return {
            "Opening Start": "",
            "Opening End": "",
            "Opening Bottom": "",
            "Opening Top": "",
            "Depth Min": "",
            "Depth Max": "",
        }

    abs_verts = verts.copy().astype(float)
    abs_verts[:, 0] += x
    abs_verts[:, 1] += y
    abs_verts[:, 2] += z

    xs = abs_verts[:, 0]
    ys = abs_verts[:, 1]
    zs = abs_verts[:, 2]

    if str(wall_axis).upper() in ["X", "+X", "-X"]:
        start = float(xs.min())
        end = float(xs.max())
        depth_min = float(ys.min())
        depth_max = float(ys.max())
    elif str(wall_axis).upper() in ["Y", "+Y", "-Y"]:
        start = float(ys.min())
        end = float(ys.max())
        depth_min = float(xs.min())
        depth_max = float(xs.max())
    else:
        start = end = depth_min = depth_max = ""

    bottom = float(zs.min())
    top = float(zs.max())

    return {
        "Opening Start": start,
        "Opening End": end,
        "Opening Bottom": bottom,
        "Opening Top": top,
        "Depth Min": depth_min,
        "Depth Max": depth_max,
    }


def build_opening_stage2_rows(openings, visited):
    rows = []

    def find_nearest_wall(opening_obj, visited_walls):
        ox = float(opening_obj.get("x", 0.0))
        oy = float(opening_obj.get("y", 0.0))

        best_wall = None
        best_wall_num = ""
        best_dist2 = float("inf")

        for idx, wall_dict in enumerate(visited_walls, start=1):
            wall = (
                next(iter(wall_dict.values()))
                if isinstance(wall_dict, dict) and wall_dict
                else None
            )
            if not wall:
                continue

            wx = float(wall.get("x", 0.0))
            wy = float(wall.get("y", 0.0))

            d2 = (ox - wx) ** 2 + (oy - wy) ** 2
            if d2 < best_dist2:
                best_dist2 = d2
                best_wall = wall
                best_wall_num = idx

        return best_wall, best_wall_num

    for i, op in enumerate(openings, start=1):
        name = str(op.get("name", f"IfcOpeningElement_{i}"))

        x = float(op.get("x", 0.0))  # GX
        y = float(op.get("y", 0.0))  # GY
        z = float(op.get("z", 0.0))  # GZ

        wall, wall_number = find_nearest_wall(op, visited)
        wall_axis = wall.get("axis", "") if wall else ""
        axis_norm = str(wall_axis).upper().strip()

        opening_start = opening_end = None
        opening_bottom = opening_top = None
        depth_min = depth_max = None
        width = None
        height = None

        start_x = start_y = start_z = None
        end_x = end_y = end_z = None

        face_coord = None

        # 4 points on one wall-face
        start_p1_x = start_p1_y = start_p1_z = None
        start_p2_x = start_p2_y = start_p2_z = None
        end_p1_x = end_p1_y = end_p1_z = None
        end_p2_x = end_p2_y = end_p2_z = None

        verts = op.get("vertices")
        if isinstance(verts, np.ndarray) and verts.size > 0:
            abs_verts = verts.copy().astype(float)
            abs_verts[:, 0] += x
            abs_verts[:, 1] += y
            abs_verts[:, 2] += z

            xs = abs_verts[:, 0]
            ys = abs_verts[:, 1]
            zs = abs_verts[:, 2]

            # raw full bbox first
            raw_start_x = float(xs.min())
            raw_end_x = float(xs.max())
            raw_start_y = float(ys.min())
            raw_end_y = float(ys.max())
            raw_start_z = float(zs.min())
            raw_end_z = float(zs.max())

            opening_bottom = raw_start_z
            opening_top = raw_end_z
            height = opening_top - opening_bottom

            if axis_norm in ["X", "+X", "-X"]:
                # opening spans along X, face is fixed at GY
                opening_start = raw_start_x
                opening_end = raw_end_x
                depth_min = raw_start_y
                depth_max = raw_end_y
                width = opening_end - opening_start

                face_coord = y  # use GY as default fixed face

                # 4 wall-face points
                start_p1_x = opening_start
                start_p1_y = face_coord
                start_p1_z = opening_bottom

                start_p2_x = opening_start
                start_p2_y = face_coord
                start_p2_z = opening_top

                end_p1_x = opening_end
                end_p1_y = face_coord
                end_p1_z = opening_bottom

                end_p2_x = opening_end
                end_p2_y = face_coord
                end_p2_z = opening_top

                # keep raw X/Z extents, but force Y output to default face
                start_x = raw_start_x
                end_x = raw_end_x
                start_y = face_coord
                end_y = face_coord
                start_z = raw_start_z
                end_z = raw_end_z

            elif axis_norm in ["Y", "+Y", "-Y"]:
                # opening spans along Y, face is fixed at GX
                opening_start = raw_start_y
                opening_end = raw_end_y
                depth_min = raw_start_x
                depth_max = raw_end_x
                width = opening_end - opening_start

                face_coord = x  # use GX as default fixed face

                # 4 wall-face points
                start_p1_x = face_coord
                start_p1_y = opening_start
                start_p1_z = opening_bottom

                start_p2_x = face_coord
                start_p2_y = opening_start
                start_p2_z = opening_top

                end_p1_x = face_coord
                end_p1_y = opening_end
                end_p1_z = opening_bottom

                end_p2_x = face_coord
                end_p2_y = opening_end
                end_p2_z = opening_top

                # keep raw Y/Z extents, but force X output to default face
                start_x = face_coord
                end_x = face_coord
                start_y = raw_start_y
                end_y = raw_end_y
                start_z = raw_start_z
                end_z = raw_end_z

            else:
                # fallback: treat like X-wall style using GY
                opening_start = raw_start_x
                opening_end = raw_end_x
                depth_min = raw_start_y
                depth_max = raw_end_y
                width = opening_end - opening_start

                face_coord = y

                start_p1_x = opening_start
                start_p1_y = face_coord
                start_p1_z = opening_bottom

                start_p2_x = opening_start
                start_p2_y = face_coord
                start_p2_z = opening_top

                end_p1_x = opening_end
                end_p1_y = face_coord
                end_p1_z = opening_bottom

                end_p2_x = opening_end
                end_p2_y = face_coord
                end_p2_z = opening_top

                start_x = raw_start_x
                end_x = raw_end_x
                start_y = face_coord
                end_y = face_coord
                start_z = raw_start_z
                end_z = raw_end_z

        rows.append(
            {
                "Marking Type": "Opening",
                "Name": name,
                "GX": x,
                "GY": y,
                "GZ": z,
                "Position X": x,
                "Position Y": y,
                "Position Z": z,
                "Wall Number": wall_number,
                "Shape Type": "IfcOpeningElement",
                "Status": "",
                "Quadrant": "",
                "Unnamed": "",
                "Width": width if width is not None else "",
                "Height": height if height is not None else "",
                "Orientation": "",
                "Axis": wall_axis,
                "Opening Start": opening_start if opening_start is not None else "",
                "Opening End": opening_end if opening_end is not None else "",
                "Opening Bottom": opening_bottom if opening_bottom is not None else "",
                "Opening Top": opening_top if opening_top is not None else "",
                "Depth Min": depth_min if depth_min is not None else "",
                "Depth Max": depth_max if depth_max is not None else "",
                "Face Coord": face_coord if face_coord is not None else "",
                "Start P1 X": start_p1_x if start_p1_x is not None else "",
                "Start P1 Y": start_p1_y if start_p1_y is not None else "",
                "Start P1 Z": start_p1_z if start_p1_z is not None else "",
                "Start P2 X": start_p2_x if start_p2_x is not None else "",
                "Start P2 Y": start_p2_y if start_p2_y is not None else "",
                "Start P2 Z": start_p2_z if start_p2_z is not None else "",
                "End P1 X": end_p1_x if end_p1_x is not None else "",
                "End P1 Y": end_p1_y if end_p1_y is not None else "",
                "End P1 Z": end_p1_z if end_p1_z is not None else "",
                "End P2 X": end_p2_x if end_p2_x is not None else "",
                "End P2 Y": end_p2_y if end_p2_y is not None else "",
                "End P2 Z": end_p2_z if end_p2_z is not None else "",
                "Start X": start_x if start_x is not None else "",
                "Start Y": start_y if start_y is not None else "",
                "Start Z": start_z if start_z is not None else "",
                "End X": end_x if end_x is not None else "",
                "End Y": end_y if end_y is not None else "",
                "End Z": end_z if end_z is not None else "",
            }
        )

    return rows


def pick_openings_for_doors_from_ifc(ifc_file):
    chosen = []

    for door in ifc_file.by_type("IfcDoor"):
        fills_voids = getattr(door, "FillsVoids", None)
        if not fills_voids:
            continue

        for rel_fill in fills_voids:
            opening = getattr(rel_fill, "RelatingOpeningElement", None)
            if opening:
                chosen.append(opening)

    return chosen


def pick_openings_for_doors(door_dicts, opening_dicts, max_match_dist_mm=1200):
    """
    Returns a filtered list of openings: one best opening per IfcDoor (by XY proximity).
    This removes extra openings (window voids, frames, etc.) and keeps the 'real' door void.
    """
    # keep only openings with vertices
    openings = [o for o in opening_dicts if isinstance(o.get("vertices"), np.ndarray)]
    if not openings or not door_dicts:
        return []

    used = set()
    chosen = []

    for d in door_dicts:
        dc = _center_xy(d)

        best = None
        best_d2 = float("inf")
        for i, o in enumerate(openings):
            if i in used:
                continue
            oc = _center_xy(o)
            d2 = _dist2(dc, oc)
            if d2 < best_d2:
                best_d2 = d2
                best = i

        if best is None:
            continue

        if math.sqrt(best_d2) <= max_match_dist_mm:
            used.add(best)
            chosen.append(openings[best])

    return chosen

def get_stage_wall_numbers(df):
    """
    Return sorted unique valid wall numbers.

    Supports:
        1
        1.0
        "1"
        "wall_1"
        "wall_2"
        ...
    """

    if (
        df is None
        or df.empty
        or "Wall Number" not in df.columns
    ):
        return []

    wall_numbers = []

    for value in df["Wall Number"]:

        if pd.isna(value):
            continue

        text = str(value).strip().lower()

        # ----------------------------------------
        # wall_1 -> 1
        # wall_2 -> 2
        # ----------------------------------------
        if text.startswith("wall_"):
            try:
                wall_num = int(
                    text.split("_", 1)[1]
                )

                if wall_num > 0:
                    wall_numbers.append(
                        wall_num
                    )

            except (ValueError, IndexError):
                pass

            continue

        # ----------------------------------------
        # 1 / 1.0 / "1"
        # ----------------------------------------
        try:
            wall_num = int(
                float(text)
            )

            if wall_num > 0:
                wall_numbers.append(
                    wall_num
                )

        except (ValueError, TypeError):
            continue

    return sorted(
        set(wall_numbers)
    )


def build_stage_position_rows(stage_name, df_stage, position_wall_arrow_rows):
    """
    Filter master position_wall_arrow_rows using the stage dataframe wall numbers.
    Match by Display Wall.
    """
    stage_wall_numbers = set(get_stage_wall_numbers(df_stage))
    if not stage_wall_numbers:
        return []

    matched_rows = []

    for row in position_wall_arrow_rows:
        try:
            display_wall = int(row.get("Display Wall"))
        except Exception:
            continue

        if display_wall in stage_wall_numbers:
            new_row = dict(row)
            new_row["Stage Name"] = stage_name
            new_row["Stage Wall Number"] = display_wall
            new_row["Stage Image Name"] = f"{stage_name}_wall{display_wall}.png"
            matched_rows.append(new_row)

    matched_rows.sort(key=lambda r: int(r["Stage Wall Number"]))
    return matched_rows
def convert_wall_number_to_name(df):
    """
    Convert Wall Number values:
        1 -> wall_1
        2 -> wall_2
        ...
        6 -> wall_6
        F -> floor
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    if "Wall Number" not in df.columns:
        return df

    def convert_value(value):
        if pd.isna(value):
            return value

        text = str(value).strip()

        # Floor
        if text.upper() == "F":
            return "floor"

        # Wall number
        try:
            wall_num = int(float(text))

            if wall_num > 0:
                return f"wall_{wall_num}"

        except (ValueError, TypeError):
            pass

        return value

    df["Wall Number"] = df["Wall Number"].apply(convert_value)

    return df
def perform_extraction(args):
    ifc_file = ifcopenshell.open(args.ifc_file)
    modelattr = modelnames.extract_ifcproject(args.ifc_file)
    modelname = modelattr.get("LongName")
    safe_modelname = (
        args.output_name.strip()
        if getattr(args, "output_name", "").strip()
        else (modelname or "output")
    )
    output_folder = getattr(args, "output_folder", os.getcwd())
    excel_output_path = os.path.join(output_folder, f"{safe_modelname}.xlsx")
    pos1_output_path = os.path.join(output_folder, f"{safe_modelname}_pos1.png")
    pos2_output_path = os.path.join(output_folder, f"{safe_modelname}_pos2.png")
    # get the data  wall , opening , floor
    all_walls = ifc_findings.process_elements(
        ifc_file.by_type("IfcWall"), "basic wall:bss"
    )
    site = ifc_file.by_type("IfcSite")[0]  # Usually only one site
    placement = site.ObjectPlacement
    while hasattr(placement, "PlacementRelTo") and placement.PlacementRelTo:
        placement = placement.PlacementRelTo
    loc = placement.RelativePlacement.Location
    origin_x, origin_y, ____ = loc.Coordinates
    origin_x, origin_y = round(origin_x), round(origin_y)
    box_up = ifc_findings.process_elements(ifc_file.by_type("IfcWall"), "box")
    walls_bss50 = [w for w in all_walls if "basic wall:bss.50" in w["name"].lower()]
    tile_pattern = re.compile(r"no pattern", re.IGNORECASE)
    tile_pattern30 = re.compile(r"600x600", re.IGNORECASE)
    walls_bss20, walls_bss_no_tile = [], []
    for w in all_walls:
        name = w["name"].lower()
        if "glass" in name or "basic wall:bss.50" in name:
            continue
        if tile_pattern.search(name) or tile_pattern30.search(name):
            walls_bss20.append(w)
        else:
            walls_bss_no_tile.append(w)
    openings = ifc_findings.process_elements(
        ifc_file.by_type("IfcOpeningElement"), "basic wall:bss.50"
    )
    door = ifc_findings.process_elements(ifc_file.by_type("IfcDoor"), "opening")
    floors = ifc_findings.process_elements(ifc_file.by_type("IfcSlab"), "floor")
    seen, same, fallback = set(), {}, []
    floors = [f for f in floors if not (f["name"] in seen or seen.add(f["name"]))]
    other_floor = [f for f in floors if "floor:bss.60" not in f["name"].lower()]
    all_objs = ifc_findings.process_elements(ifc_file.by_type("IfcElement"), "")
    storeys = ifc_findings.extract_storeys(ifc_file)
    materials = mats.getmaterial(ifc_file, names_only=True, first_only=True)
    modelline = modellines.getannotation(args.ifc_file)
    if door:
        for doors in door:
            closest_wall, distance = ifc_findings.find_closest_wall(doors, walls_bss50)
            if closest_wall:
                same[closest_wall["name"]] = closest_wall
    else:
        fallback = [
            o for o in openings if any(o["name"] in w["name"] for w in walls_bss50)
        ]
        if fallback:
            max_opening = max(
                fallback, key=lambda o: ifc_findings.compute_area(o["area"])
            )
            same[max_opening["name"]] = max_opening
    start = list(same.values())
    if isinstance(start, list) and len(start) == 1:
        start = start[0]
    start = [w for w in walls_bss50 if w["name"] == start["name"]]
    visited, tmptemp, unvisited = [], [], walls_bss50.copy()
    floor_offset, offset = 0, 0
    internalx_width, internaly_width = 0, 0
    internalxmax_width, internalymax_width = 0, 0
    internal_x_width, internal_y_width = [], []
    if start:
        if isinstance(start, list):
            if len(start) == 1:
                start = start[0]
        unvisited = [w for w in unvisited if w["name"] != start["name"]]
        start_wall = next((w for w in walls_bss50 if w["name"] == start["name"]), start)
        visited = [{start["name"]: start_wall}]
        (
            internalx_width,
            internaly_width,
            internalxmax_width,
            internalymax_width,
            internal_x_width,
            internal_y_width,
            externalxmax_width,
            externalymax_width,
            xmaxwidths,
            ymaxwidths,
        ) = fitting.get_internal_width(
            walls_bss50, start_wall, walls_bss20, walls_bss_no_tile
        )
        floor_offset = abs(max((f.get("z", 0) for f in floors), default=0))
        offset, curr = abs(start["z"]), start
        while unvisited:
            next_w, _ = ifc_findings.find_closest_wall(curr, unvisited)
            if not next_w:
                break
            visited.append({next_w["name"]: next_w})
            unvisited = [w for w in unvisited if w["name"] != next_w["name"]]
            curr = next_w
    if len(visited) == 6:
        top_twofloor_z = heapq.nlargest(2, (f["z"] for f in other_floor if f["z"] < 0))
    walls_facing_plus_y = [
        list(w.values())[0]
        for w in visited
        if list(w.values())[0]["facingaxis"] == "+Y"
    ]
    walls_facing_minus_y = [
        list(w.values())[0]
        for w in visited
        if list(w.values())[0]["facingaxis"] == "-Y"
    ]
    count_plus_y, count_minus_y = len(walls_facing_plus_y), len(walls_facing_minus_y)
    if count_minus_y == 2:
        ifc_findings.swap_last_two(internal_x_width)
        internal_y_width.sort()
        ymaxwidths.sort()
        ifc_findings.swap_first_two(ymaxwidths)
        ifc_findings.swap_last_two(xmaxwidths)
    if count_minus_y == 2 or count_plus_y == 2:
        internal_y_width = fitting.compare_width_y(
            walls_facing_minus_y, internal_y_width, count_plus_y, count_minus_y
        )
    thickness = walls_bss50[0]["area"][1] + walls_bss20[1]["area"][1]
    stage2_rows, centerpoint_rows, stage3_objects, df_checklist = (
        stage_val.getstage2andstage3(
            all_objs,
            args,
            visited,
            origin_x,
            origin_y,
            internalx_width,
            internalxmax_width,
            internalymax_width,
            offset,
            internaly_width,
            other_floor,
            top_twofloor_z,
            floor_offset,
            thickness,
        )
    )
    sanitary_pipe_rows = sanitary_pipe.build_sanitary_pipe_bbox_rows(
        ifc_file=ifc_file,
        all_objs=all_objs,
        visited=visited,
        inset_mm=15.0,
        edge_margin_mm=5.0,
    )
    df_sanitary_pipe = pd.DataFrame(sanitary_pipe_rows)
    sanitary_cols = [
        "Marking Type",
        "Name",
        "GX",
        "GY",
        "GZ",
        "Position X",
        "Position Y",
        "Position Z",
        "Wall Number",
        "Shape Type",
        "Status",
        "Quadrant",
        "Unnamed",
        "Width",
        "Height",
        "Orientation",
        "Diameter",
    ]
    for col in sanitary_cols:
        if col not in df_sanitary_pipe.columns:
            df_sanitary_pipe[col] = ""
    df_sanitary_pipe = df_sanitary_pipe[sanitary_cols]
    glass_walls = [
        obj
        for obj in all_objs
        if "glass" in obj["name"].lower()
        and not (obj.get("x", 0) == 0 and obj.get("y", 0) == 0 and obj.get("z", 0) == 0)
    ]
    df_checklist.columns = df_checklist.iloc[0]
    axes_by_wallnum: Dict[int, Optional[str]] = {}
    for i, wall_dict in enumerate(visited):
        w = (
            next(iter(wall_dict.values()))
            if isinstance(wall_dict, dict) and wall_dict
            else {}
        )
        axis = w.get("axis")  # <-- only axis
        axes_by_wallnum[i + 1] = axis
    wall_info = [
        {
            "Wall Number": int(row["Wall Number"]),
            "Width": row.get("Width"),
            "Height": row.get("Height"),
            "Axis": axes_by_wallnum.get(int(row["Wall Number"]), None),
        }
        for row in stage2_rows
        if isinstance(row.get("Wall Number"), int)
        and str(row.get("Marking Type", "")).strip().lower() == "wall"
    ]
    fitting_stage3 = fitting.assign_nearest_fitting(
        visited,
        stage3_objects,
        storeys,
        other_floor,
        wall_info,
        glass_walls,
        count_minus_y,
        count_plus_y,
        centerpoint_rows,
        walls_bss20,
        walls_bss_no_tile,
    )
    boxup = fitting.assign_nearest_fitting_rotation(
        visited,
        box_up,
        other_floor,
        wall_info,
        glass_walls,
        count_minus_y,
        count_plus_y,
        centerpoint_rows,
    )
    walls_bss20_wall_num = fitting.assign_nearest_fitting_rotation(
        visited,
        walls_bss20 + walls_bss_no_tile,
        other_floor,
        wall_info,
        glass_walls,
        count_minus_y,
        count_plus_y,
        centerpoint_rows,
    )
    model_lines_walls = fitting.assign_nearest_line(
        visited,
        modelline,
        storeys,
        other_floor,
        wall_info,
        glass_walls,
        count_minus_y,
        count_plus_y,
        centerpoint_rows,
        walls_bss20,
        walls_bss_no_tile,
    )
    model_lines_walls.sort(
        key=lambda x: (
            int(x["Wall Number"]) if str(x["Wall Number"]).isdigit() else float("inf")
        )
    )
    fitting_stage3.sort(
        key=lambda x: (
            int(x["Wall Number"]) if str(x["Wall Number"]).isdigit() else float("inf")
        )
    )
    if len(visited) == 4:
        Tmpholder = tmps.getTMP(
            all_objs,
            visited,
            walls_bss20,
            origin_x,
            origin_y,
            other_floor,
            centerpoint_rows,
            storeys,
            externalxmax_width,
            externalymax_width,
            door,
        )
        tmptemp = Tmpholder.returntmp()
    else:
        Tmpholder = tmps6sidesPBU.loadTMP6sides(
            all_objs,
            stage2_rows,
            visited,
            walls_bss20,
            walls_bss_no_tile,
            materials,
            model_lines_walls,
            other_floor,
            storeys,
            fallback,
            boxup,
            walls_bss20_wall_num,
            externalxmax_width,
            externalymax_width,
            origin_x,
            origin_y,
        )
        tmptemp, thickness, internalmax_width = Tmpholder.returnalltmps()
    pts = wc.compute_wall_centerpoints_from_axis(
        internalmax_width, visited, posz_cp=1000
    )
    centerrows = []
    for i, wall_dict in enumerate(visited):
        raw_name = str(wall_dict.get("name", ""))  # or wall_dict.get("Name", "")
        include_name = "basic wall:bss.50" in raw_name.lower()  # case-insensitive
        name_field = f"WallCP{i + 1}({raw_name})" if include_name else f"WallCP{i + 1}"
        centerrows.append(
            {
                "Marking Type": "CenterWallPoint",
                "Name": name_field,
                "X": pts[i]["GX"] / 1000.0,
                "Y": pts[i]["GY"] / 1000.0,
                "Z": pts[i]["GZ"] / 1000.0,
                "Wall Number": i + 1,
                "Shape Type": "",
                "Width": internalmax_width[i]["Internal Max Width"],
                "Height": w["area"][2],
                "Rotation_Axis": pts[i].get("Facing_Axis"),
            }
        )
    wc.write_json(centerrows, "wall_centerpoints.json")
    df_tmptemp = pd.DataFrame(tmptemp)
    df_visited = pd.DataFrame(stage2_rows)
    df_fitting = pd.DataFrame(fitting_stage3)
    # filtered_openings = openings
    # opening_stage2_rows = build_opening_stage2_rows(filtered_openings, visited)
    # df_openings = pd.DataFrame(opening_stage2_rows)
    df_combined = pd.concat([df_tmptemp, df_visited], ignore_index=True)
    df_combined["Wall Number Sort"] = pd.to_numeric(
        df_combined["Wall Number"], errors="coerce"
    )
    df_combined = df_combined.sort_values(by=["Wall Number Sort", "Name"]).drop(
        columns="Wall Number Sort"
    )
    df_combined[["Width", "Height"]] = df_combined.apply(
        lambda row: fitting.applyexternal(row, internalmax_width, visited),
        axis=1,
    )
    df_sanitary_pipe[["Width", "Height"]] = df_sanitary_pipe.apply(
        lambda row: fitting.applyexternal(row, internalmax_width, visited),
        axis=1,
    )
    fittingbox = pointbox.boundingboxpoint(fitting_stage3, all_objs)
    fittingboundingbox = fittingbox.returnallfitting()
    df_fitting[["GX", "GY", "GZ"]] = df_fitting.apply(
        lambda row: setuprobot.setupfittingrequirement(
            row, all_objs, fittingboundingbox, df_checklist
        ),
        axis=1,
    )
    df_fitting[["Width", "Height"]] = df_fitting.apply(
        lambda row: fitting.applyexternal(row, internalmax_width, visited),
        axis=1,
    )
    df_sanitary_pipe = setuprobot.insert_L_cols_between_GZ_and_width(df_sanitary_pipe)
    df_combined = setuprobot.insert_L_cols_between_GZ_and_width(df_combined)
    df_fitting = setuprobot.insert_L_cols_between_GZ_and_width(df_fitting)
    df_combined[["Position X", "Position Y", "Position Z"]] = df_combined.apply(
        lambda row: setuprobot.setuprobotposition(
            row,
            stage2_rows,
            visited,
            internalxmax_width,
            internalymax_width,
            thickness,
            origin_x,
            origin_y,
        ),
        axis=1,
    )
    df_fitting[["Position X", "Position Y", "Position Z"]] = df_fitting.apply(
        lambda row: setuprobot.setuprobotposition_fitting(
            row,
            stage2_rows,
            visited,
            internalxmax_width,
            internalymax_width,
            thickness,
            origin_x,
            origin_y,
        ),
        axis=1,
    )
    df_sanitary_pipe[["Position X", "Position Y", "Position Z"]] = df_sanitary_pipe.apply(
        lambda row: setuprobot.setuprobotposition(
            row,
            stage2_rows,
            visited,
            internalxmax_width,
            internalymax_width,
            thickness,
            origin_x,
            origin_y,
        ),
        axis=1
    )
    df_combined = df_combined.dropna(subset=["Position X", "Position Y", "Position Z"])
    df_fitting = df_fitting.dropna(subset=["Position X", "Position Y", "Position Z"])
    # ============================================================
    # Convert final coordinate outputs from mm -> m
    # ============================================================
    df_sanitary_pipe = convert_mm_columns_to_m(
        df_sanitary_pipe
    )

    df_combined = convert_mm_columns_to_m(
        df_combined
    )

    df_fitting = convert_mm_columns_to_m(
        df_fitting
    )
    # ============================================================
    # Convert wall numbers to readable names
    # ============================================================
    df_sanitary_pipe = convert_wall_number_to_name(
        df_sanitary_pipe
    )

    df_combined = convert_wall_number_to_name(
        df_combined
    )

    df_fitting = convert_wall_number_to_name(
        df_fitting
    )
    for col in ["Orientation", "Diameter"]:
        if col not in df_combined.columns:
            df_combined[col] = ""
        else:
            df_combined[col] = df_combined[col].fillna("").astype(str)
    max_wall = len(visited)
    df_maxwall = pd.DataFrame([{"maxWall": max_wall}])
    df_wallinfo = df_combined.copy()
    # Keep only 'Wall' rows
    df_wallinfo = df_wallinfo[
        df_wallinfo["Marking Type"].astype(str).str.lower() == "wall"
    ]
    # Keep only Basic Wall:BSS.50 objects
    df_wallinfo = df_wallinfo[
        df_wallinfo["Name"].astype(str).str.contains("Basic Wall:BSS.50", case=False)
    ]
    # Make Wall Number numeric and drop rows without it
    df_wallinfo["Wall Number"] = pd.to_numeric(
        df_wallinfo["Wall Number"], errors="coerce"
    )
    df_wallinfo = df_wallinfo.dropna(subset=["Wall Number"])
    # Sort by wall number
    df_wallinfo = df_wallinfo.sort_values(by="Wall Number")
    # ---------------- Axis from axes_by_wallnum (ONLY in df_wallinfo) -------------
    def lookup_axis(wn):
        try:
            wn_int = int(wn)
        except (ValueError, TypeError):
            return ""
        return axes_by_wallnum.get(wn_int, "")

    # Create / overwrite Axis column in df_wallinfo
    df_wallinfo["Axis"] = df_wallinfo["Wall Number"].apply(lookup_axis)
    # If you want to normalize to +X/+Y/-X/-Y, you can optionally do:
    df_wallinfo["Axis"] = df_wallinfo["Axis"].replace(
        {
            "X": "+X",
            "Y": "+Y",
            "-X": "-X",
            "-Y": "-Y",
        }
    )
    # Exact column order from your screenshot
    wallinfo_cols = [
        "Marking Type",
        "Name",
        "GX",
        "GY",
        "GZ",
        "Position X",
        "Position Y",
        "Position Z",
        "Wall Number",
        "Shape Type",
        "Status",
        "Quadrant",
        "Unnamed",
        "Width",
        "Height",
        "Orientation",
        "Axis",
    ]
    result = exporter.export_wall_schematic_2d(
        visited=visited,
        opening_dicts=(openings or []) + (door or []),
        output_path=pos1_output_path,
        output_path_2=pos2_output_path,
        force_mirror_layout=False,
    )

    if not isinstance(result, dict):
        print("[IMAGE] export_wall_schematic_2d did not return layout data. Skipping stage images.")
        position_wall_arrow_rows = []
        layout_data = None
    else:
        position_wall_arrow_rows = result.get("position_wall_arrow_rows", [])
        layout_data = {
            "floor_poly": result["floor_poly"],
            "chained_edges": result["chained_edges"],
            "wall_seg": result["wall_seg"],
            "reversed_wall": result["reversed_wall"],
            "doors_by_wall": result["doors_by_wall"],
            "layout_mirrored": result["layout_mirrored"],
            "position_1": result["position_1"],
            "position_2": result["position_2"],
            "pos1": result["pos1"],
            "pos2": result["pos2"],
            "icon_path": result["icon_path"],
        }
    print("position_wall_arrow_rows:", position_wall_arrow_rows)
    layout_data = {
        "floor_poly": result["floor_poly"],
        "chained_edges": result["chained_edges"],
        "wall_seg": result["wall_seg"],
        "reversed_wall": result["reversed_wall"],
        "doors_by_wall": result["doors_by_wall"],
        "layout_mirrored": result["layout_mirrored"],
        "position_1": result["position_1"],
        "position_2": result["position_2"],
        "pos1": result["pos1"],
        "pos2": result["pos2"],
        "icon_path": result["icon_path"],
    }
    print("layout_data:", layout_data)
    if layout_data is not None and position_wall_arrow_rows:
        stage1_rows_for_images = build_stage_position_rows(
            "stage1",
            df_sanitary_pipe,
            position_wall_arrow_rows,
        )

        stage2_rows_for_images = build_stage_position_rows(
            "stage2",
            df_combined,
            position_wall_arrow_rows,
        )

        stage3_rows_for_images = build_stage_position_rows(
            "stage3",
            df_fitting,
            position_wall_arrow_rows,
        )

        all_stage_image_rows = (
            stage1_rows_for_images
            + stage2_rows_for_images
            + stage3_rows_for_images
        )

        exporter.export_stage_wall_arrow_images(
            visited=visited,
            opening_dicts=(openings or []) + (door or []),
            output_folder=output_folder,
            position_wall_arrow_rows=all_stage_image_rows,
            layout_data=layout_data,
            force_mirror_layout=False,
        )
    else:
        print("[IMAGE] No layout data or no arrow rows. Stage images skipped.")
    print("position_wall_arrow_rows:", position_wall_arrow_rows)
    pbu_wall_names_for_stl = []

    for wall_dict in visited:
        if isinstance(wall_dict, dict) and wall_dict:
            wall_obj = next(iter(wall_dict.values()))
            wall_name = wall_obj.get("name", "")
            if wall_name:
                pbu_wall_names_for_stl.append(str(wall_name))
    stage1_pipe_block_rows = []
    if df_sanitary_pipe is not None and not df_sanitary_pipe.empty:
        stage1_pipe_block_rows = df_sanitary_pipe.to_dict("records")

    stage2_pipe_block_rows = []
    if df_combined is not None and not df_combined.empty:
        stage2_pipe_block_rows = df_combined.to_dict("records")

    stage3_pipe_block_rows = []
    if df_fitting is not None and not df_fitting.empty:
        stage3_pipe_block_rows = df_fitting.to_dict("records")
    # # ============================================================
    # # STL EXPORTS
    # # ============================================================

    # stage1_names_for_stl = []
    # if (
    #     df_sanitary_pipe is not None
    #     and not df_sanitary_pipe.empty
    #     and "Name" in df_sanitary_pipe.columns
    # ):
    #     stage1_names_for_stl = (
    #         df_sanitary_pipe["Name"]
    #         .dropna()
    #         .astype(str)
    #         .tolist()
    #     )

    # stage2_names_for_stl = []
    # if (
    #     df_combined is not None
    #     and not df_combined.empty
    #     and "Name" in df_combined.columns
    # ):
    #     stage2_names_for_stl = (
    #         df_combined["Name"]
    #         .dropna()
    #         .astype(str)
    #         .tolist()
    #     )

    # stage3_names_for_stl = []
    # if (
    #     df_fitting is not None
    #     and not df_fitting.empty
    #     and "Name" in df_fitting.columns
    # ):
    #     stage3_names_for_stl = (
    #         df_fitting["Name"]
    #         .dropna()
    #         .astype(str)
    #         .tolist()
    #     )

    # stl_results = stl_exporter.export_stage_stls_from_ifc(
    #     ifc_path=args.ifc_file,
    #     output_folder=output_folder,
    #     output_name=safe_modelname,
    #     stage1_names=stage1_names_for_stl,
    #     stage2_names=stage2_names_for_stl,
    #     stage3_names=stage3_names_for_stl,
    #     stage1_pipe_block_rows=stage1_pipe_block_rows,
    #     stage2_pipe_block_rows=stage2_pipe_block_rows,
    #     stage3_pipe_block_rows=stage3_pipe_block_rows,
    #     pbu_wall_names=pbu_wall_names_for_stl,
    # )

    # print("[STL] Export results:", stl_results)
    # if not args.ifc_file:
    #     raise ValueError("IFC file path is empty.")
    # if not os.path.exists(args.ifc_file):
    #     raise FileNotFoundError(f"IFC file not found: {args.ifc_file}")

    if not args.excel_checklist:
        raise ValueError("Excel checklist path is empty.")
    if not os.path.exists(args.excel_checklist):
        raise FileNotFoundError(f"Excel checklist not found: {args.excel_checklist}")

    try:
        ifc_file = ifcopenshell.open(args.ifc_file)
    except Exception as e:
        raise RuntimeError(f"Failed to open IFC file: {e}")

    try:
        modelattr = modelnames.extract_ifcproject(args.ifc_file)
    except Exception as e:
        raise RuntimeError(f"Failed to extract IFC project info: {e}")
    stage1_rows_for_images = build_stage_position_rows(
        "stage1",
        df_sanitary_pipe,
        position_wall_arrow_rows,
    )

    stage2_rows_for_images = build_stage_position_rows(
        "stage2",
        df_combined,
        position_wall_arrow_rows,
    )

    stage3_rows_for_images = build_stage_position_rows(
        "stage3",
        df_fitting,
        position_wall_arrow_rows,
    )

    all_stage_image_rows = (
        stage1_rows_for_images
        + stage2_rows_for_images
        + stage3_rows_for_images
    )

    exporter.export_stage_wall_arrow_images(
        visited=visited,
        opening_dicts=(openings or []) + (door or []),
        output_folder=output_folder,
        position_wall_arrow_rows=all_stage_image_rows,
        layout_data=layout_data,
        force_mirror_layout=False,
    )
    with pd.ExcelWriter(excel_output_path, engine="openpyxl") as writer:
        for df, sheet in [
            (df_sanitary_pipe, "Stage 1"),
            (df_combined, "Stage 2"),
            (df_fitting, "Stage 3"),
        ]:
            df.reset_index(drop=True, inplace=True)
            df.index += 1
            df.to_excel(writer, index=True, sheet_name=sheet)
        df_maxwall.to_excel(writer, index=False, sheet_name="maxwall")
        df_wallinfo.to_excel(writer, index=False, sheet_name="wallinfo")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    app = ExecutableLauncher()
    app.mainloop()
