"""Create simple orthographic previews of the diagnostic PLY without Blender."""
from pathlib import Path
import cv2
import numpy as np
import trimesh

OUT = Path('/Volumes/extra/workspace1/projects/test4/independent-silhouette')
mesh = trimesh.load(OUT / 'photo_native_hull_preview.ply', process=False)
verts = np.asarray(mesh.vertices)
faces = np.asarray(mesh.faces)
normals = np.asarray(mesh.face_normals)
height, width = 820, 430
camera_directions = [np.array([1., 0., .10]), np.array([0., 1., .10]),
                     np.array([1., 1., .15])]
labels = ['X view', 'Y view', 'Diagonal view']
tiles = []
for direction, label in zip(camera_directions, labels):
    direction /= np.linalg.norm(direction)
    right = np.cross(np.array([0., 0., 1.]), direction)
    right /= np.linalg.norm(right)
    up = np.cross(direction, right)
    projected = np.column_stack([verts @ right, verts @ up, verts @ direction])
    projected[:, 1] *= -1  # Local +Z points toward the white tube.
    scale = min((width - 50) / np.ptp(projected[:, 0]),
                (height - 75) / np.ptp(projected[:, 1]))
    xy = np.column_stack([(projected[:, 0] - np.mean(projected[:, 0])) * scale + width/2,
                          (projected[:, 1] - np.mean(projected[:, 1])) * scale + height/2])
    image = np.full((height, width, 3), 249, np.uint8)
    depth = projected[faces, 2].mean(axis=1)
    light = np.array([.35, -.25, -.90])
    light /= np.linalg.norm(light)
    brightness = np.clip(.48 + .46 * np.abs(normals @ light), 0, 1)
    for index in np.argsort(depth):
        triangle = np.rint(xy[faces[index]]).astype(np.int32)
        gray = int(85 + 105 * brightness[index])
        cv2.fillConvexPoly(image, triangle, (gray, gray, gray), lineType=cv2.LINE_AA)
    cv2.putText(image, label, (15, 32), cv2.FONT_HERSHEY_SIMPLEX,
                .8, (40, 40, 40), 2, cv2.LINE_AA)
    tiles.append(image)
canvas = np.concatenate(tiles, axis=1)
cv2.imwrite(str(OUT / 'hull-preview.jpg'), canvas, [cv2.IMWRITE_JPEG_QUALITY, 94])
print(OUT / 'hull-preview.jpg')
