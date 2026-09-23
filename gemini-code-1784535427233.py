import math

def compute_face_centers(distances, rotations, start_pos=(0.0, 0.0), start_angle=0.0, use_degrees=True):
    """
    Computes the midpoint of each polygon face given distances and rotations.
    
    Args:
        distances (list): List of edge lengths.
        rotations (list): List of turning angles at the end of each edge.
        start_pos (tuple): Starting (x, y) coordinates.
        start_angle (float): Initial heading angle.
        use_degrees (bool): If True, treats rotations as degrees; otherwise, radians.
        
    Returns:
        list of tuples: The (x, y) coordinates of each face's center.
    """
    if len(distances) != len(rotations):
        raise ValueError("The number of distances must match the number of rotations.")
        
    centers = []
    x, y = start_pos
    current_angle = start_angle

    for d, r in zip(distances, rotations):
        # Convert the current heading to radians for math functions
        rad_angle = math.radians(current_angle) if use_degrees else current_angle

        # 1. Calculate the midpoint of the current face
        mid_x = x + (d / 2.0) * math.cos(rad_angle)
        mid_y = y + (d / 2.0) * math.sin(rad_angle)
        centers.append((mid_x, mid_y))

        # 2. Move the current position to the end of the face (the next vertex)
        x += d * math.cos(rad_angle)
        y += d * math.sin(rad_angle)

        # 3. Apply the rotation to update the heading for the next face
        current_angle += r

    return centers

# ==========================================
# Example Usage: A Simple 2x2 Square
# ==========================================
if __name__ == "__main__":
    # A square has 4 sides of equal length. 
    # At each vertex, we turn 90 degrees left.
    square_distances = [1.832,1.840,0.592,0.960,1.240,2.800]
    square_rotations = [90, 90, 270, 90 , 90 , 90] 

    face_centers = compute_face_centers(square_distances, square_rotations)

    print("Face Centers for a 2x2 Square starting at (0,0):")
    for i, center in enumerate(face_centers):
        # Rounding to 4 decimal places to clean up floating-point inaccuracies (like 1.22e-16)
        print(f"Face {i+1}: ({center[0]:.4f}, {center[1]:.4f})")