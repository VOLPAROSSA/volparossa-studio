"""Refresh responsive local pictures from the art masters (Pillow)."""
import json
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'assets/studio'
SPECS = {
    'wall': [768, 1440, 2060],
    'wall-mobile': [390, 740],
    'workshop': [240, 480, 900],
    'maker': [240, 480], 'reviewer': [240, 480],
    'fox': [100, 210],
}


def export():
    inventory = {}
    for name, widths in SPECS.items():
        master = ROOT / 'masters' / (name.split('-')[0] + '.webp')
        with Image.open(master) as source:
            if name == 'wall-mobile':
                source = ImageOps.fit(source, (563, 763), centering=(.17, .5))
            frames = []
            for width in widths:
                width = min(width, source.width)
                height = round(width * source.height / source.width)
                frame = source.resize((width, height), Image.Resampling.LANCZOS)
                frame.save(OUT / f'{name}-{width}.webp', quality=84, method=6)
                frames.append([width, height])
            fallback = frames[len(frames) // 2]
            fallback_image = source.resize(tuple(fallback), Image.Resampling.LANCZOS)
            ext = 'png' if name == 'fox' else 'jpg'
            fallback_image.save(OUT / f'{name}.{ext}', optimize=True, quality=84)
            inventory[name] = dict(frames=frames, fallback=fallback, ext=ext)
    (ROOT / 'src/art.json').write_text(json.dumps(inventory, indent=2) + '\n')


if __name__ == '__main__':
    export()
