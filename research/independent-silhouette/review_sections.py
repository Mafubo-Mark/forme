"""Plot diagnostic cross-sections of the photo-native visual hull."""
from pathlib import Path
import cv2
import numpy as np

OUT = Path('/Volumes/extra/workspace1/projects/test4/independent-silhouette')
npz = np.load(OUT / 'photo_native_hull_volume.npz')
volume = npz['support']
z = npz['z_mm']
levels = [-45, 0, 45, 90, 135, 180, 225, 270, 315]
tiles = []
for height in levels:
    idx = int(np.argmin(np.abs(z - height)))
    section = volume[idx].astype(np.uint8)
    tile = cv2.resize(section * 255, (360, 360), interpolation=cv2.INTER_NEAREST)
    tile = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)
    cv2.line(tile, (180, 0), (180, 359), (50, 100, 50), 1)
    cv2.line(tile, (0, 180), (359, 180), (50, 100, 50), 1)
    cv2.putText(tile, f'z={z[idx]:.0f} mm', (8, 30), cv2.FONT_HERSHEY_SIMPLEX,
                .8, (0, 180, 255), 2, cv2.LINE_AA)
    tiles.append(tile)
grid = np.concatenate([np.concatenate(tiles[i:i+3], axis=1) for i in range(0, 9, 3)], axis=0)
cv2.imwrite(str(OUT / 'sections.jpg'), grid, [cv2.IMWRITE_JPEG_QUALITY, 94])
print(OUT / 'sections.jpg')
