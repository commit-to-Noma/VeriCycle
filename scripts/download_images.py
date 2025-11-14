"""
Small helper to download three high-quality recycling images into static/images/
Run from the project root (where app.py lives):

    python .\scripts\download_images.py

This uses only the Python standard library (urllib) so it should work without extra deps.
If your environment blocks external downloads, instead download the files manually and place them in static/images/.
"""
import os
import sys
from urllib.request import urlretrieve

IMAGES = {
    'mpact.jpg': 'https://images.unsplash.com/photo-1579277025211-744383c3c72b?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&q=80',
    'fmsa.jpg': 'https://images.unsplash.com/photo-1557053910-d9dcdf43685e?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&q=80',
    'roodepoort.jpg': 'https://images.unsplash.com/photo-1596726274488-8250005d5193?crop=entropy&cs=tinysrgb&fit=max&fm=jpg&q=80',
}

OUT_DIR = os.path.join('static', 'images')

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, url in IMAGES.items():
        out_path = os.path.join(OUT_DIR, name)
        try:
            print(f'Downloading {name} from {url} ...')
            urlretrieve(url, out_path)
            print('Saved to', out_path)
        except Exception as e:
            print('Failed to download', url)
            print('Error:', e)
            print('You can manually download the image and place it at', out_path)
    print('\nDone. Start the app and visit /network to verify visuals.')

if __name__ == '__main__':
    main()
