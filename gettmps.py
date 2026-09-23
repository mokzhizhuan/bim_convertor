import re
import methodifcfindings as ifc_findings
import string
import math


class getTMP(object):
    def __init__(
        self,
        all_objs,
        walls,
        wall_bss20,
        origin_x,
        origin_y,
        floor,
        centerpoint_rows,
        storeys,
        externalxmax_width,
        externalymax_width,
        door,
    ):
        self.all_objs = all_objs
        self.walls = walls
        self.centerpoint_rows = centerpoint_rows
        self.wall_bss20 = wall_bss20
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.floor = floor
        min_thickness = min(
            wall_data["area"][1]
            for wall_dict in self.walls
            for wall_data in wall_dict.values()
        )
        self.min_thickness20 = min(wall["area"][1] for wall in self.wall_bss20)
        self.thickness = min_thickness + self.min_thickness20
        self.externalxmax_width = externalxmax_width
        self.externalymax_width = externalymax_width
        self.door = door
        self.index = 0
        self.storeys = storeys
        self.storey_min_height = min(
            storeys, key=lambda s: s["elevation"], default={"elevation": 0}
        )["elevation"]
        z_values = [w["z"] for w in self.wall_bss20 if "z" in w]
        self.getlowestground = min(z_values)
        self.alphabet_list = list(string.ascii_lowercase)
        self.tmptemp = []
        self.dist_neededarray = []
        self.maxwidths = []
        self.getTMP1()

    def returnalpha(self, count):
        for index, item in enumerate(self.alphabet_list):
            if index == (count):
                return item

    def getTMP1(self):
        for i, wall_dict in enumerate(self.walls):
            if i == self.index:
                maxheight, maxwidth = 0, 0
                ceilingzstart = self.storey_min_height
                w, _ = ifc_findings.find_closest_wall_rotation(
                    list(wall_dict.values())[0], self.wall_bss20
                )
                width, height = self.get_width_heights_intervals(w)
                tiles_x, tiles_y, end = [], [], 0
                x_val, y_val = w.get("x", 0), w.get("y", 0)
                facing, area, axis = w.get("facingaxis"), w.get("area"), w.get("axis")
                wall_width, z_val = area[0], w.get("z", 0) + self.min_thickness20
                if axis == "X":
                    if facing in ["+X", "-X"]:
                        current = x_val
                        if facing == "+X":
                            end = current + wall_width
                        elif facing == "-X":
                            end = current - wall_width
                        tiles_x.append({"x": current, "z": z_val})
                        tiles_x.append({"x": end, "z": z_val})
                else:
                    if facing in ["+Y", "-Y"]:
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
                repeatcount = int((ceilingzstart - width) / width) + 1
                door = self.door[0]
                x_origin = door["x"]
                vertices = door["vertices"]
                door_minx = x_origin + vertices[:, 0].min()
                door_maxx = x_origin + vertices[:, 0].max()
                for count, xpos in enumerate(tile_list):
                    alpha = self.returnalpha(count)
                    if door_minx <= xpos <= door_maxx:
                        continue
                    for i in range(repeatcount):
                        z = width + width * i
                        self.tmptemp.append(
                            {
                                "Wall Number": self.index + 1,
                                "Point Name": f"TMP{self.index + 1}S2{alpha}{i + 1}",
                                "GX": int(xpos),
                                "GY": w.get("y", 0),
                                "GZ": z,
                                "Width": maxwidth,
                                "Height": maxheight,
                            }
                        )
                self.index += 1
        self.getTMPFloor()

    def getTMPFloor(self):
        maxheight, maxwidth = 0, 0
        for wallsmax in self.stage2_rows:
            if wallsmax["Wall Number"] == "F":
                maxwidth = wallsmax["Width"]
                maxheight = wallsmax["Height"]
        floorbss20 = [
            obj for obj in self.floor if "floor:bss.80" not in obj["name"].lower()
        ]
        width, height = self.get_width_heights_intervals(floorbss20[0])
        x_val = self.externalxmax_width - height + self.thickness
        tiles_x, tiles_y , self.floor_tmps = [], [] , []
        tiles_x.append(x_val)
        while x_val - height > 0:
            x_val -= height
            if x_val > self.thickness:
                tiles_x.append(x_val)
        vertices = self.boxup[0]["vertices"]
        y_values = vertices[:, 1]
        unique_y = sorted(set(y for y in y_values if y != 0))
        y_val = 0
        if len(unique_y) >= 2:
            y_val = (int(unique_y[1]) // 10) * 10 + self.thickness
            while y_val - width > 0:
                y_val -= width
            while y_val < maxheight:
                if y_val > self.thickness:
                    tiles_y.append(y_val)
                y_val += width
        tiles_x.sort()
        tiles_y.sort()
        count = 0
        for xpos in tiles_x:
            alpha = self.returnalpha(count)
            counter = 0
            for ypos in tiles_y:
                self.floor_tmps.append(
                    {
                        "Wall Number": "F",
                        "Point Name": f"TMP{self.index + 1}S2{alpha}{counter+1}",
                        "Position X": int(xpos),
                        "Position Y": int(ypos),
                        "Position Z": floorbss20[0]["z"],
                        "Width": maxwidth,
                        "Height": maxheight,
                    }
                )
                counter += 1
            if self.floor_tmps:
                count += 1
        self.returntmp()

    def returntmp(self):
        return self.tmptemp + self.floor_tmps

    def get_width_heights_intervals(self, next_w):
        name = next_w["name"]
        match = re.search(r"(\d+)\s*[xX]\s*(\d+)\s*MM", name, re.IGNORECASE)
        if match:
            width, height = int(match.group(1)), int(match.group(2))
            return width, height
