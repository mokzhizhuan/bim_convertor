from pyproj import Transformer

# EPSG:4326 = WGS84 (lat/lon), EPSG:3414 = SVY21 (Singapore grid in meters)
transformer = Transformer.from_crs("EPSG:4326", "EPSG:3414", always_xy=True)

# Your Autodesk Viewer coordinates (WGS84)
lon = 103.8198394775
lat = 1.3520829675000003

# Transform to Easting/Northing in meters
easting, northing = transformer.transform(lon, lat)

# Convert to mm
x_mm = easting * 1000
y_mm = northing * 1000

print(f"X: {x_mm:.2f} mm, Y: {y_mm:.2f} mm")
