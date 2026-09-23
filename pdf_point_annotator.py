import os
import fitz  # PyMuPDF
import pandas as pd


# ============================================================
# WALL → PDF VIEW MAPPING
# ============================================================
WALL_TO_PDF_VIEW = {
    1: "Elevation A",
    2: "Elevation B",
    3: "Elevation C",
    4: "Elevation B",
    5: "Elevation C",
    6: "Elevation D",
}


# ============================================================
# REAL PDF VIEW BOXES FOR YOUR A88 PDF PAGE
#
# Page size expected around:
# width  = 2383.92
# height = 1684.32
#
# These boxes are much larger than your old boxes.
# They target the actual elevation drawing area near the top of the PDF.
#
# Format:
# box = (x0, y0, x1, y1)
# x0,y0 = top-left of elevation drawing area
# x1,y1 = bottom-right of elevation drawing area
# ============================================================
PDF_VIEW_BOXES = {
    "Elevation A": {
        "box": (80, 120, 680, 990),
        "width_mm": 2900,
        "height_mm": 2655,
    },
    "Elevation B": {
        "box": (700, 120, 1130, 990),
        "width_mm": 1932,
        "height_mm": 2655,
    },
    "Elevation C": {
        "box": (1160, 120, 1640, 990),
        "width_mm": 2900,
        "height_mm": 2655,
    },
    "Elevation D": {
        "box": (1710, 120, 2260, 990),
        "width_mm": 1932,
        "height_mm": 2655,
    },
    "Shower Area": {
        "box": (1700, 560, 2260, 950),
        "width_mm": 1340,
        "height_mm": 2450,
    },
}


# ============================================================
# SETTINGS
# ============================================================
DRAW_DEBUG_BOXES = True        # Keep True first. Set False after confirmed.
DRAW_LABELS = True             # Set False if too many words overlap.
MAX_LABEL_LEN = 22
POINT_RADIUS = 3.0
LABEL_FONT_SIZE = 4.5


def _safe_float(value, default=None):
    try:
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value, default=None):
    try:
        if pd.isna(value):
            return default
        return int(float(value))
    except Exception:
        return default


def _clean_df(df):
    return df.loc[:, ~df.columns.astype(str).str.contains("^Unnamed")].copy()


def _normalize_axis(axis):
    axis = str(axis or "").upper().strip()
    if axis == "X":
        return "+X"
    if axis == "Y":
        return "+Y"
    return axis


def get_wall_axis_map(excel_input_path):
    """
    Read wallinfo sheet to know whether each wall is X/Y/+X/-X/+Y/-Y.
    """
    axis_map = {}

    try:
        df_wallinfo = pd.read_excel(excel_input_path, sheet_name="wallinfo")
        df_wallinfo = _clean_df(df_wallinfo)
    except Exception as e:
        print(f"[PDF] Cannot read wallinfo axis map: {e}")
        return axis_map

    if "Wall Number" not in df_wallinfo.columns:
        return axis_map

    for _, row in df_wallinfo.iterrows():
        wall_no = _safe_int(row.get("Wall Number"), None)
        if wall_no is None:
            continue

        axis_map[wall_no] = _normalize_axis(row.get("Axis", ""))

    return axis_map


def get_wall_width_map(excel_input_path):
    """
    Read wallinfo sheet to get actual wall width.
    """
    width_map = {}

    try:
        df_wallinfo = pd.read_excel(excel_input_path, sheet_name="wallinfo")
        df_wallinfo = _clean_df(df_wallinfo)
    except Exception as e:
        print(f"[PDF] Cannot read wallinfo width map: {e}")
        return width_map

    if "Wall Number" not in df_wallinfo.columns:
        return width_map

    for _, row in df_wallinfo.iterrows():
        wall_no = _safe_int(row.get("Wall Number"), None)
        width = _safe_float(row.get("Width"), None)

        if wall_no in [1, 2, 3, 4, 5, 6] and width and width > 0:
            width_map[wall_no] = width

    return width_map


def export_pdf_coordinate_grid(pdf_input_path, pdf_output_path):
    """
    Optional calibration PDF.
    Creates grid lines every 100 PDF units.
    """
    doc = fitz.open(pdf_input_path)
    page = doc[0]

    width = page.rect.width
    height = page.rect.height

    x = 0
    while x <= width:
        page.draw_line(
            fitz.Point(x, 0),
            fitz.Point(x, height),
            color=(0, 0, 1),
            width=0.3,
        )
        page.insert_text(
            fitz.Point(x + 2, 15),
            str(int(x)),
            fontsize=6,
            color=(0, 0, 1),
        )
        x += 100

    y = 0
    while y <= height:
        page.draw_line(
            fitz.Point(0, y),
            fitz.Point(width, y),
            color=(1, 0, 0),
            width=0.3,
        )
        page.insert_text(
            fitz.Point(5, y + 8),
            str(int(y)),
            fontsize=6,
            color=(1, 0, 0),
        )
        y += 100

    page.insert_text(
        fitz.Point(40, 40),
        f"PDF page size: width={width:.1f}, height={height:.1f}",
        fontsize=12,
        color=(1, 0, 0),
    )

    doc.save(pdf_output_path)
    doc.close()

    print(f"[PDF GRID] Created: {pdf_output_path}")


def prepare_stage_dataframe(excel_input_path, sheet_name):
    """
    Read one stage sheet and keep only numeric wall rows 1-6.
    This removes Floor/F rows so PDF elevation logic will not crash.
    """
    df = pd.read_excel(excel_input_path, sheet_name=sheet_name)
    df = _clean_df(df)

    if "Wall Number" not in df.columns:
        raise ValueError(f"{sheet_name} does not have 'Wall Number' column.")

    df["_WallNoNum"] = pd.to_numeric(df["Wall Number"], errors="coerce")
    df = df.dropna(subset=["_WallNoNum"]).copy()
    df["_WallNoNum"] = df["_WallNoNum"].astype(int)

    df = df[df["_WallNoNum"].isin([1, 2, 3, 4, 5, 6])].copy()

    return df


def prepare_wall_local_ranges(df, axis_map):
    """
    For each wall, find min/max coordinate from the stage points.
    This converts global robot position to local wall distance.
    """
    ranges = {}

    if df.empty:
        return ranges

    for wall_no in sorted(df["_WallNoNum"].unique()):
        wall_df = df[df["_WallNoNum"] == wall_no].copy()
        axis = axis_map.get(wall_no, "")

        if axis in ["+Y", "-Y", "Y"]:
            coord_col = "Position Y"
        else:
            coord_col = "Position X"

        if coord_col not in wall_df.columns:
            coord_col = "GY" if axis in ["+Y", "-Y", "Y"] else "GX"

        if coord_col not in wall_df.columns:
            continue

        vals = pd.to_numeric(wall_df[coord_col], errors="coerce").dropna()
        if vals.empty:
            continue

        min_v = float(vals.min())
        max_v = float(vals.max())

        ranges[wall_no] = {
            "coord_col": coord_col,
            "min": min_v,
            "max": max_v,
            "span": max_v - min_v,
        }

    return ranges


def infer_along_and_z(row, wall_ranges, wall_width_map, axis_map):
    """
    Convert Excel point row to:
    - along_mm = local distance from left side of elevation
    - z_mm = height from FFL
    """
    wall_no = _safe_int(row.get("_WallNoNum"), None)
    if wall_no is None:
        return None, None

    # -----------------------------
    # Z coordinate
    # -----------------------------
    z_mm = _safe_float(row.get("Position Z"), None)

    if z_mm is None:
        z_mm = _safe_float(row.get("GZ"), 0)

    if z_mm is None:
        z_mm = 0

    # Keep within elevation height
    z_mm = max(0, min(2655, z_mm))

    # -----------------------------
    # Along coordinate
    # -----------------------------
    r = wall_ranges.get(wall_no)
    if not r:
        return 0, z_mm

    coord_col = r["coord_col"]
    coord = _safe_float(row.get(coord_col), None)

    if coord is None:
        return 0, z_mm

    min_v = r["min"]
    max_v = r["max"]
    span = r["span"]

    if span == 0:
        local_ratio = 0.0
    else:
        axis = axis_map.get(wall_no, "")

        if axis in ["-X", "-Y"]:
            local_ratio = (max_v - coord) / span
        else:
            local_ratio = (coord - min_v) / span

        local_ratio = max(0.0, min(1.0, local_ratio))

    width_mm = wall_width_map.get(wall_no, None)

    if width_mm and width_mm > 0:
        along_mm = local_ratio * width_mm
    else:
        along_mm = local_ratio * span

    return along_mm, z_mm


def excel_point_to_pdf_xy(along_mm, z_mm, view_info):
    """
    Convert wall-local elevation coordinate to PDF coordinate.
    """
    x0, y0, x1, y1 = view_info["box"]

    width_mm = float(view_info["width_mm"])
    height_mm = float(view_info["height_mm"])

    scale_x = (x1 - x0) / width_mm
    scale_y = (y1 - y0) / height_mm

    pdf_x = x0 + along_mm * scale_x

    # PDF Y increases downward.
    # Z increases upward.
    pdf_y = y1 - z_mm * scale_y

    # Clamp inside target elevation box
    pdf_x = max(x0, min(x1, pdf_x))
    pdf_y = max(y0, min(y1, pdf_y))

    return pdf_x, pdf_y


def draw_debug_boxes(page):
    """
    Blue boxes show where points are allowed to appear.
    If the box covers elevation, points will be on elevation.
    """
    for view_name, info in PDF_VIEW_BOXES.items():
        x0, y0, x1, y1 = info["box"]
        rect = fitz.Rect(x0, y0, x1, y1)

        page.draw_rect(
            rect,
            color=(0, 0, 1),
            width=1.0,
        )

        page.insert_text(
            fitz.Point(x0 + 6, y0 + 14),
            view_name,
            fontsize=8,
            color=(0, 0, 1),
        )


def shorten_label(label):
    label = str(label or "Point")

    # remove noisy IFC prefix
    label = label.replace("Basic Wall:", "")
    label = label.replace("BSS.", "")

    if len(label) > MAX_LABEL_LEN:
        label = label[:MAX_LABEL_LEN] + "..."

    return label


def annotate_single_stage_pdf(
    pdf_input_path,
    excel_input_path,
    pdf_output_path,
    sheet_name,
    label_column="Name",
    debug_boxes=DRAW_DEBUG_BOXES,
):
    """
    Create one annotated PDF for one stage.
    """
    df = prepare_stage_dataframe(excel_input_path, sheet_name)

    axis_map = get_wall_axis_map(excel_input_path)
    wall_width_map = get_wall_width_map(excel_input_path)
    wall_ranges = prepare_wall_local_ranges(df, axis_map)

    doc = fitz.open(pdf_input_path)
    page = doc[0]

    print(f"[PDF] Page size: {page.rect.width:.2f} x {page.rect.height:.2f}")
    print(f"[PDF] Annotating {sheet_name}")
    print(f"[PDF] Axis map: {axis_map}")
    print(f"[PDF] Width map: {wall_width_map}")
    print(f"[PDF] Wall local ranges: {wall_ranges}")

    # stage title at bottom-left, away from elevation drawings
    page.insert_text(
        fitz.Point(40, page.rect.height - 35),
        f"{sheet_name} Annotated Points",
        fontsize=12,
        color=(1, 0, 0),
    )

    if debug_boxes:
        draw_debug_boxes(page)

    point_count = 0

    for _, row in df.iterrows():
        wall_no = _safe_int(row.get("_WallNoNum"), None)
        if wall_no is None:
            continue

        pdf_view = WALL_TO_PDF_VIEW.get(wall_no)
        if not pdf_view:
            continue

        view_info = PDF_VIEW_BOXES.get(pdf_view)
        if not view_info:
            continue

        along_mm, z_mm = infer_along_and_z(
            row=row,
            wall_ranges=wall_ranges,
            wall_width_map=wall_width_map,
            axis_map=axis_map,
        )

        if along_mm is None or z_mm is None:
            continue

        pdf_x, pdf_y = excel_point_to_pdf_xy(along_mm, z_mm, view_info)

        label = shorten_label(row.get(label_column, "Point"))

        page.draw_circle(
            fitz.Point(pdf_x, pdf_y),
            POINT_RADIUS,
            color=(1, 0, 0),
            fill=(1, 1, 0),
            width=0.8,
        )

        if DRAW_LABELS:
            page.insert_text(
                fitz.Point(pdf_x + 4, pdf_y - 4),
                f"W{wall_no}:{label}",
                fontsize=LABEL_FONT_SIZE,
                color=(1, 0, 0),
            )

        point_count += 1

    doc.save(pdf_output_path)
    doc.close()

    print(f"[PDF] {sheet_name}: drew {point_count} points")
    print(f"[PDF] Created: {pdf_output_path}")

    return pdf_output_path


def export_stage_pdfs_from_excel(
    pdf_input_path,
    excel_input_path,
    output_folder,
    output_name,
):
    """
    Generate:
    - Stage 1 PDF
    - Stage 2 PDF
    - Stage 3 PDF
    """
    print("[PDF ANNOTATOR] Using rewritten elevation annotator")
    print("[PDF ANNOTATOR] PDF_VIEW_BOXES =", PDF_VIEW_BOXES)

    stage_pdf_outputs = {}

    stage_map = {
        "Stage 1": f"{output_name}_stage1_points.pdf",
        "Stage 2": f"{output_name}_stage2_points.pdf",
        "Stage 3": f"{output_name}_stage3_points.pdf",
    }

    xls = pd.ExcelFile(excel_input_path)

    for sheet_name, filename in stage_map.items():
        if sheet_name not in xls.sheet_names:
            print(f"[PDF] Skip {sheet_name}, sheet not found.")
            continue

        output_path = os.path.join(output_folder, filename)

        annotate_single_stage_pdf(
            pdf_input_path=pdf_input_path,
            excel_input_path=excel_input_path,
            pdf_output_path=output_path,
            sheet_name=sheet_name,
            debug_boxes=DRAW_DEBUG_BOXES,
        )

        stage_pdf_outputs[sheet_name] = output_path

    return stage_pdf_outputs