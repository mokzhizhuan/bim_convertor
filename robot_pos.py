import pandas as pd
import numpy as np


def setuprobotposition(
    row,
    stage2_rows,
    walls,
    externalxmax_width,
    externalymax_width,
    thickness,
    origin_x,
    origin_y,
):
    pos_x, pos_y, pos_z = row["GX"], row["GY"], row["GZ"]
    if (pos_x == 0 and pos_y == 0) or (
        pos_x == externalxmax_width or pos_y == externalymax_width
    ):
        return pd.Series([None, None, None])
    wall_number, name = row["Wall Number"], row["Name"]
    if (
        "basic wall" not in name.lower()
        and "floor" not in name.lower()
        and "box-up" not in name.lower()
    ):
        matched_wall = None
        if str(wall_number).upper() == "F":
            if wall_number == "F" and "CP" not in name:
                for cp_row in stage2_rows:
                    if "CP" in cp_row["Name"] and cp_row["Wall Number"] == "F":
                        return pd.Series(
                            [
                                pos_x - cp_row["GX"] + origin_x,
                                pos_y - cp_row["GY"] + origin_y,
                                pos_z + cp_row["GZ"],
                            ]
                        )
            elif wall_number == "F" and "CP" in name:
                for cp_row in stage2_rows:
                    if "CP" in cp_row["Name"] and cp_row["Wall Number"] == "F":
                        return pd.Series(
                            [
                                pos_x - cp_row["GX"],
                                pos_y - cp_row["GY"],
                                pos_z - cp_row["GZ"],
                            ]
                        )
        elif isinstance(wall_number, int) and 1 <= wall_number <= len(walls):
            matched_wall = walls[wall_number - 1]
        else:
            matched_wall = None
        if matched_wall is None:
            return pd.Series([pos_x, pos_y, pos_z])
        wall_info = list(matched_wall.values())[0]
        facing = wall_info.get("facingaxis", "")
        if "CP" not in name:
            for cp_row in stage2_rows:
                if "CP" in cp_row["Name"] and cp_row["Wall Number"] == wall_number:
                    cp_x, cp_y, cp_z = cp_row["GX"], cp_row["GY"], cp_row["GZ"]
                    dz = pos_z - cp_z
                    if dz < -1000:
                        return pd.Series([None, None, None])
                    if facing in ["+X", "-X"]:
                        dx = pos_x - cp_x + origin_x
                        dy = pos_y - cp_y - thickness + origin_y
                        protrusion_y = dy - externalymax_width
                        if not (0 > protrusion_y > -abs(externalymax_width)):
                            dy = 0
                        else:
                            dy = protrusion_y
                        if facing == "-X":
                            dx = -abs(dx) if dx > 0 else abs(dx)
                        return pd.Series([dx, dy, dz])
                    elif facing in ["+Y", "-Y"]:
                        dx = pos_x - cp_x - thickness + origin_x
                        dy = pos_y - cp_y + origin_y
                        protrusion_x = dx - externalxmax_width
                        if not (0 > protrusion_x > -abs(externalxmax_width)):
                            dx = 0
                        else:
                            dx = protrusion_x
                        if facing == "-Y":
                            protrusion_xs = externalxmax_width + dx
                            if not (0 < protrusion_xs < externalxmax_width):
                                dx = 0
                            else:
                                dx = -abs(protrusion_xs)
                            dy = -abs(dy) if dy > 0 else abs(dy)
                        return pd.Series([dy, dx, dz])
        elif "CP" in name:
            for cp_row in stage2_rows:
                if "CP" in cp_row["Name"] and cp_row["Wall Number"] == wall_number:
                    cp_x, cp_y, cp_z = cp_row["GX"], cp_row["GY"], cp_row["GZ"]
                    dx = pos_x - cp_x 
                    dy = pos_y - cp_y 
                    dz = pos_z - cp_z
                    return pd.Series([dx, dy, dz])
    return pd.Series([pos_x, pos_y, pos_z])


def setuprobotposition_fitting(
    row,
    stage2_rows,
    walls,
    externalxmax_width,
    externalymax_width,
    thickness,
    origin_x,
    origin_y,
):
    pos_x, pos_y, pos_z = row["GX"], row["GY"], row["GZ"]
    if (pos_x == 0 and pos_y == 0) or (
        pos_x == externalxmax_width or pos_y == externalymax_width
    ):
        return pd.Series([None, None, None])
    wall_number, name, matched_wall = row["Wall Number"], row["Name"], None
    if str(wall_number).upper() == "F":
        if wall_number == "F" and "CP" not in name:
            for cp_row in stage2_rows:
                if "CP" in cp_row["Name"] and cp_row["Wall Number"] == "F":
                    return pd.Series(
                        [
                            pos_x - cp_row["GX"] + origin_x,
                            pos_y - cp_row["GY"] + origin_y,
                            pos_z + cp_row["GZ"],
                        ]
                    )
    elif isinstance(wall_number, int) and 1 <= wall_number <= len(walls):
        matched_wall = walls[wall_number - 1]
    else:
        matched_wall = None
    if matched_wall is None:
        return pd.Series([pos_x, pos_y, pos_z])
    wall_info = list(matched_wall.values())[0]
    facing = wall_info.get("facingaxis", "")
    if "CP" not in name:
        for cp_row in stage2_rows:
            if "CP" in cp_row["Name"] and cp_row["Wall Number"] == wall_number:
                cp_x, cp_y, cp_z = cp_row["GX"], cp_row["GY"], cp_row["GZ"]
                dz = pos_z - cp_z
                if facing in ["+X", "-X"]:
                    dx = pos_x - cp_x + origin_x
                    dy = pos_y - cp_y - thickness + origin_y
                    protrusion_y = dy - externalymax_width
                    if not (0 > protrusion_y > -abs(externalymax_width)):
                        dy = 0
                    else:
                        dy = protrusion_y
                    if facing == "-X":
                        dx = -abs(dx) if dx > 0 else abs(dx)
                    return pd.Series([dx, dy, dz])
                elif facing in ["+Y", "-Y"]:
                    dx = pos_x - cp_x - thickness + origin_x
                    dy = pos_y - cp_y + origin_y
                    protrusion_x = dx - externalxmax_width
                    if not (0 > protrusion_x > -abs(externalxmax_width)):
                        dx = 0
                    else:
                        dx = protrusion_x
                    if facing == "-Y":
                        dy = -abs(dy) if dy > 0 else abs(dy)
                    return pd.Series([dy, dx, dz])
    return pd.Series([pos_x, pos_y, pos_z])

def setupfittingrequirement(row, all_objs, fitting_boundingbox, checklist):
        pos_x, pos_y, pos_z = row["GX"], row["GY"], row["GZ"]
        for f in fitting_boundingbox:
            for obj in all_objs:
                if f["Name"] in obj["name"]:
                    if obj["type"] in ["IfcFlowTerminal", "IfcBuildingElementProxy"]:
                        if row["Name"] in f["Name"]:
                            row_name = str(row["Name"])
                            matched = checklist[
                                checklist["Name"]
                                .astype(str)
                                .apply(lambda x: x.lower() in row_name.lower())
                            ]
                            if not matched.empty:
                                remarks = matched["Remarks"].astype(str).values[0]
                                if "center point" in remarks.lower():
                                    pos_z = pos_z + f["Size"][2] / 2
                                    vertices = obj.get("vertices")
                                    x_coords = vertices[:, 0]
                                    min_x, max_x = np.min(x_coords), np.max(x_coords)
                                    if min_x + max_x > 0:
                                        pos_x = pos_x + f["Size"][0] / 2
        return pd.Series([round(pos_x), round(pos_y), round(pos_z)])


def insert_L_cols_between_GZ_and_width(df, fill_value=np.nan):
    cols = list(df.columns)
    i_gz, i_width = cols.index("GZ"), cols.index("Width")
    if i_gz is not None and i_width is not None and i_gz < i_width:
        insert_at = i_gz + 1
    else:
        insert_at = len(cols)
    for j, c in enumerate(("Position X", "Position Y", "Position Z")):
        if c not in df.columns:
            df.insert(insert_at + j, c, fill_value)
    return df
