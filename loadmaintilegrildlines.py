import re
import methodifcfindings as ifc_findings
import string
import numpy as np
import math


class loadmainTMP:
    def __init__(
        self,
        all_objs,
        stage2_rows,
        walls,
        wall_bss20,
        wall_bss12,
        origin_x,
        origin_y,
        floor,
        storeys,
        centerpoint_rows,
        opening,
        boxup,
        glass_walls,
    ):
        self.all_objs = all_objs
        self.stage2_rows = stage2_rows
        self.walls = walls
        self.wall_bss20 = wall_bss20
        self.wall_bss20 = self.extract_tile_sizes(self.wall_bss20)
        self.opening = opening
        self.glass_walls = glass_walls
        self.glass_walls = min(self.glass_walls, key=lambda d: d.get("z", float("inf")))
        self.height20 = self.wall_bss20[0]["area"][1]
        first_wall = list(self.walls[0].values())[0]
        self.wallsheight50 = first_wall["area"][1]
        self.thickness = self.height20 + self.wallsheight50
        self.wall_bss12 = wall_bss12
        self.boxup = boxup
        self.alphabet_string = string.ascii_lowercase
        wall12 = self.wall_bss12[0]
        for wall in self.wall_bss20:
            tile_size = self.extract_tile_size(wall["name"])
            if tile_size:
                wall12["tile_size"] = tile_size
                break
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.floor = floor
        self.centerpoint_rows = centerpoint_rows
        x_widths = [
            w["centerpointwidth"]
            for w in self.centerpoint_rows
            if "X" in w["AxisDirection"]
        ]
        y_widths = [
            w["centerpointwidth"]
            for w in self.centerpoint_rows
            if "Y" in w["AxisDirection"]
        ]
        self.x_maxinternalwidth = (max(x_widths) + self.wallsheight50) * 2
        self.y_maxinternalwidth = (max(y_widths)) * 2
        self.storey_min_height = min(
            storeys, key=lambda s: s["elevation"], default={"elevation": 0}
        )["elevation"]
        z_values = [w["z"] for w in self.wall_bss20 if "z" in w]
        self.two_lowest_z = sorted(z_values)[:2]
        self.index = 0
        self.tmptemp = []
        self.addTMP1()

    def extract_wall_id(self, name):
        match = re.search(r":(\d+)$", name)
        return match.group(1) if match else None

    def extract_tile_size(self, name):
        # Accept formats like: (600x600mm), 600x600mm, 600 x 600 mm, 600X600MM
        match = re.search(r"\(?\s*(\d+)\s*[xX]\s*(\d+)\s*mm\)?", name)
        if match:
            width = int(match.group(1))
            height = int(match.group(2))
            return f"({width}x{height}mm)"
        return None

    def extract_tile_sizes(self, walls):
        for wall in walls:
            name = wall.get("name", "")
            match = re.search(r"\(\d+x\d+mm\)", name)
            if match:
                wall["tile_size"] = match.group()  # e.g., (600x600mm)
            else:
                wall["tile_size"] = None
        return walls

    def getlongerwidthsurface(self):
        x_widths, y_widths = [], []
        height = 0
        for wall_dict in self.walls:
            for wall_name, data in wall_dict.items():
                axis = data.get("axis")
                width = data["area"][0]
                height = data["area"][1]
                if axis == "X":
                    x_widths.append((width, wall_name))
                elif axis == "Y":
                    y_widths.append((width, wall_name))
        x_sorted = sorted(x_widths, key=lambda x: x[0], reverse=True)
        y_sorted = sorted(y_widths, key=lambda x: x[0], reverse=True)
        if len(x_sorted) >= 2:
            second_x = int(x_sorted[1][0]) + height
        if len(y_sorted) >= 2:
            second_y = int(y_sorted[1][0]) + height
        return second_x, second_y

    def get_width_heights_intervals(self, next_w):
        tile_size = next_w.get("tile_size", "")
        match = re.search(r"\((\d+)x(\d+)mm\)", tile_size)
        width, height = 0, 0
        if match:
            width = int(match.group(1))
            height = int(match.group(2))
        return width, height

    def get_width_heights_interval(self, next_w):
        match = re.search(r"\((\d+)x(\d+)mm\)", next_w["name"])
        width, height = 0, 0
        if match:
            width = int(match.group(1))  # 600
            height = int(match.group(2))  # 150
        return width, height

    def find_opening_by_name(self, wall_name):
        return next((o for o in self.opening if o["name"] == wall_name), None)

    def addTMP1(self):
        wall_finishes_lowest_height = min(
            self.wall_bss20, key=lambda s: s["z"], default={"z": 0}
        )["z"]
        combined_walls = self.wall_bss20 + self.wall_bss12
        self.shower_walls = [
            wall
            for wall in combined_walls
            if wall.get("z", 0) - wall_finishes_lowest_height == 0
        ]
        for i, wall_dict in enumerate(self.walls):
            if i == self.index:
                wall_obj = list(wall_dict.values())[0]
                opening_match = self.find_opening_by_name(wall_obj["name"])
                first_w, _ = ifc_findings.find_closest_wall(wall_obj, self.wall_bss20)
                second_w, _ = ifc_findings.find_closest_wall(first_w, self.wall_bss20)
                tiles_x, tiles_y, dist_needed = [], [], []
                x_min_limit = 0
                for w in [first_w, second_w]:
                    if opening_match:
                        vertices = opening_match.get("vertices")
                        if vertices is not None and len(vertices) > 0:
                            x_coords = np.array(vertices)[:, 0]  # get all X values
                            x_min_limit = x_coords.min()
                            x_max_limit = x_coords.max()
                    if not w:
                        continue  # Skip if None
                    x_val, y_val = w.get("x", 0), w.get("y", 0)
                    z_val = w.get("z", 0) + self.height20
                    area = w.get("area")
                    width = area[0]
                    axis = w.get("axis")
                    facingaxis = w.get("facingaxis")
                    if axis in "X":
                        end_x = 0
                        if facingaxis == "-X":
                            end_x = x_val - width
                        else:
                            end_x = x_val + width
                        tiles_x.append({"x": x_val, "z": z_val})
                        tiles_x.append({"x": end_x, "z": z_val})
                    else:
                        end_y = 0
                        if facingaxis == "-Y":
                            end_y = y_val - width
                        else:
                            end_y = y_val + width
                        tiles_y.append({"x": y_val, "z": z_val})
                        tiles_y.append({"x": end_y, "z": z_val})
                tiles_x_structured = [t for t in tiles_x if isinstance(t, dict)]
                tiles_y_structured = [t for t in tiles_y if isinstance(t, dict)]
                tiles_x_structured.sort(key=lambda x: x["x"])
                tiles_y_structured.sort(key=lambda y: y["y"])
                axis = list(wall_dict.values())[0]["axis"]
                tile_list = (
                    [t["x"] for t in tiles_x_structured]
                    if axis == "X"
                    else [t["y"] for t in tiles_y_structured]
                )
                tile_list.append(x_min_limit)
                tile_list.append(x_max_limit)
                tile_list.sort()
                x_wallsurface, y_wallsurface = 0, 0
                if axis == "X":
                    dist_needed = 0 - wall_obj["y"]
                    y_wallsurface = wall_obj["y"] + dist_needed
                else:
                    dist_needed = 0 - wall_obj["x"]
                    x_wallsurface = wall_obj["x"] + dist_needed
                alphabet_list = list(self.alphabet_string)
                counter = 0
                z = z_val
                z1 = self.storey_min_height
                for count, pos in enumerate(tile_list):
                    alpha = ""
                    for index, item in enumerate(alphabet_list):
                        if index == (count):
                            alpha = item
                    self.tmptemp.append(
                        {
                            "Wall Number": self.index + 1,
                            "Name": f"TMP{self.index + 1}S2{alpha}1",
                            "Position X": pos if axis == "X" else x_wallsurface,
                            "Position Y": y_wallsurface if axis == "X" else pos,
                            "Position Z": z,
                        }
                    )
                    self.tmptemp.append(
                        {
                            "Wall Number": self.index + 1,
                            "Name": f"TMP{self.index + 1}S2{alpha}2",
                            "Position X": pos if axis == "X" else x_wallsurface,
                            "Position Y": y_wallsurface if axis == "X" else pos,
                            "Position Z": z1,
                        }
                    )
                    counter += 1
        self.index += 1
        self.addTMP2()

    def get_factors(self, n, x_value):
        return [i for i in x_value if i != 0 and n % i == 0 and i % 10 == 0]

    def addTMP2(self):
        for i, wall_dict in enumerate(self.walls):
            if i == self.index:
                wall_obj = list(wall_dict.values())[0]
                next_w, _ = ifc_findings.find_closest_wall_rotation(
                    wall_obj, self.wall_bss20 + self.wall_bss12
                )
                opening_match = self.find_opening_by_name(wall_obj["name"])
                tiles_x, tiles_y= [], []
                w = next_w
                x_val, y_val, area = w.get("x", 0), w.get("y", 0), w.get("area")
                wall_width, z_val = area[0] , 0
                if w in self.shower_walls:
                    z_val = self.two_lowest_z[0] + self.height20
                else:
                    z_val = self.two_lowest_z[1] + self.height20
                facing = w.get("facingaxis")
                end = 0
                if facing in ["+X", "-X"]:
                    current = x_val
                    if facing == "+X":
                        end = current + wall_width
                    elif facing == "-X":
                        end = current - wall_width
                    tiles_x.append({"x": current, "z": z_val})
                    tiles_x.append({"x": end, "z": z_val})
                elif facing in ["+Y", "-Y"]:
                    current = y_val
                    if facing == "+Y":
                        end = y_val + wall_width
                    elif facing == "-Y":
                        end = y_val - wall_width
                    tiles_y.append({"y": current, "z": z_val})
                    tiles_y.append({"y": end, "z": z_val})
                tiles_x_structured = [t for t in tiles_x if isinstance(t, dict)]
                tiles_y_structured = [t for t in tiles_y if isinstance(t, dict)]
                tiles_x_structured.sort(key=lambda x: x["x"])
                tiles_y_structured.sort(key=lambda y: y["y"])
                axis = list(wall_dict.values())[0]["axis"]
                tile_list = (
                    [t["x"] for t in tiles_x_structured]
                    if axis == "X"
                    else [t["y"] for t in tiles_y_structured]
                )
                z_base = (
                    tiles_x_structured[0]["z"]
                    if axis == "X"
                    else tiles_y_structured[0]["z"]
                )
                x_wallsurface, y_wallsurface = 0, 0
                if axis == "X":
                    dist_needed = 0 - wall_obj["y"]
                    y_wallsurface = wall_obj["y"] + dist_needed
                else:
                    dist_needed = 0 - wall_obj["x"]
                    x_wallsurface = wall_obj["x"] + dist_needed
                alphabet_list = list(self.alphabet_string)
                z_min_limit, z_max_limit = 0, 0
                y_min_limit, y_max_limit = 0, 0
                tiles_z = []
                tiles_z.append(z_base)
                tiles_z.append(self.storey_min_height)
                if opening_match:
                    vertices = opening_match.get("vertices")
                    if vertices is not None and len(vertices) > 0:
                        y_coords = np.array(vertices)[:, 1]  # get all Y values
                        z_coords = np.array(vertices)[:, 2]  # get all Z values
                        y_min_limit, y_max_limit = y_coords.min(), y_coords.max()
                        z_min_limit, z_max_limit = z_coords.min(), z_coords.max()
                        if y_val != y_min_limit: 
                            tile_list.append(y_min_limit)
                        tile_list.append(y_max_limit)
                        tiles_z.append(z_min_limit)
                        tiles_z.append(z_max_limit)
                tile_list.sort()
                tiles_z.sort()
                for count, pos in enumerate(tile_list):
                    alpha = ""
                    for index, item in enumerate(alphabet_list):
                        if index == (count):
                            alpha = item
                    for i , zpos in enumerate(tiles_z):
                        self.tmptemp.append(
                            {
                                "Wall Number": self.index + 1,
                                "Name": f"TMP{self.index + 1}S2{alpha}{i+1}",
                                "Position X": pos if axis == "X" else x_wallsurface,
                                "Position Y": y_wallsurface if axis == "X" else pos,
                                "Position Z": zpos,
                            }
                        )
                self.index += 1
        self.getTMPFloor()

    def getTMPFloor(self):
        floor_finishes = sorted(
            [
                obj
                for obj in self.floor
                if "floor finishes" in obj["name"].lower()
                and obj.get("area") != (0, 0, 0)
            ],
            key=lambda obj: obj["x"],
        )
        counters = 0  # global X-letter index
        tmpfloor, distance_needed = [], []
        for floor in floor_finishes:
            distance_needed.append(
                {
                    "name": floor["name"],
                    "remaining_distance": self.boxup[0]["Position X"] - floor["x"],
                }
            )
        min_item = min(distance_needed, key=lambda d: d["remaining_distance"])
        for floor in floor_finishes:
            width, height = self.get_width_heights_interval(floor)
            vertices = floor["vertices"]
            min_x = math.ceil(np.min(vertices[:, 0]) / 10) * 10
            max_x = math.ceil(np.max(vertices[:, 0]) / 10) * 10
            min_y = math.ceil(np.min(vertices[:, 1]) / 10) * 10
            max_y = math.ceil(np.max(vertices[:, 1]) / 10) * 10
            tiles_x, tiles_y = [], []
            # X tiles
            current_x = min_x
            current_y = min_y
            tiles_x.append({"x": current_x, "z": floor["z"]})
            tiles_x.append({"x": max_x, "z": floor["z"]})
            tiles_y.append({"y": current_y, "z": floor["z"]})
            tiles_y.append({"y": max_y, "z": floor["z"]})
            for xpos in tiles_x:
                alpha = (
                    self.alphabet_string[counters]
                    if counters < len(self.alphabet_string)
                    else f"z{counters}"
                )
                for count_y, ypos in enumerate(tiles_y):
                    tmpfloor.append(
                        {
                            "Wall Number": "F",
                            "Name": f"TMP{self.index + 1}S2{alpha}{count_y+1}",
                            "Position X": xpos["x"],
                            "Position Y": ypos["y"],
                            "Position Z": floor["z"],
                        }
                    )
                counters += 1  # ✅ moved here (once per X-column)
        self.tmptemp.extend(tmpfloor)
        self.returnalltmps()

    def returnalltmps(self):
        return self.tmptemp
