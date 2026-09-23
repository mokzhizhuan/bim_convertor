class boundingboxpoint:
    def __init__(self, fitting_stage3, all_objs):
        self.fitting_stage3 = fitting_stage3
        self.all_objs = all_objs
        self.setboundingboxpoint()

    def setboundingboxpoint(self):
        self.fitting_bboxes = []
        for t in self.fitting_stage3:
            for obj in self.all_objs:
                if t["Name"] in obj["name"]:
                    min_xyz = obj["vertices"].min(axis=0)
                    max_xyz = obj["vertices"].max(axis=0)
                    bbox = {
                        "Name": obj["name"],
                        "Min": min_xyz,
                        "Max": max_xyz,
                        "Center": (min_xyz + max_xyz) / 2,
                        "Size": max_xyz - min_xyz,
                    }
                    self.fitting_bboxes.append(bbox)
        self.returnallfitting()    
                
    def returnallfitting(self):
        return self.fitting_bboxes        
