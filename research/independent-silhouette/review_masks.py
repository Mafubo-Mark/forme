"""Review masks inferred directly from test4 photos, without 3D point input."""
from pathlib import Path
import cv2
import numpy as np

ROOT = Path('/Volumes/extra/workspace1/projects/test4')
OUT = ROOT / 'independent-silhouette'
images = sorted((ROOT / 'reconstruction/dense/images').glob('frame_*.jpg'))
chosen = [images[int(i)] for i in np.linspace(0, len(images)-1, 12)]
tiles = []
for image_path in chosen:
    rgb = cv2.imread(str(image_path))
    mask = cv2.imread(str(OUT / 'masks' / (image_path.stem + '.png')), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise FileNotFoundError(image_path.stem)
    boundary = cv2.morphologyEx((mask >= 127).astype(np.uint8), cv2.MORPH_GRADIENT,
                                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    rgb[boundary > 0] = (0, 0, 255)
    tile = cv2.resize(rgb, (270, 480), interpolation=cv2.INTER_AREA)
    cv2.putText(tile, image_path.stem, (8, 24), cv2.FONT_HERSHEY_SIMPLEX,
                .7, (0, 255, 255), 2, cv2.LINE_AA)
    tiles.append(tile)
montage = np.concatenate([np.concatenate(tiles[i:i+4], axis=1) for i in range(0, 12, 4)], axis=0)
cv2.imwrite(str(OUT / 'mask-montage.jpg'), montage, [cv2.IMWRITE_JPEG_QUALITY, 91])
print(OUT / 'mask-montage.jpg')
