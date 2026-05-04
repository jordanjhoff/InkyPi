"""
Run from the custom_calendar directory:
  python debug_cat.py

Outputs two images to assets/:
  debug_positions.png  — room with numbered dots at each floor position
  debug_sprites.png    — sprite sheet with row numbers labeled
"""

import os
import random
from PIL import Image, ImageDraw, ImageFont, ImageOps

ASSET_DIR = os.path.join(os.path.dirname(__file__), "assets")
ROOM_PATH = os.path.join(ASSET_DIR, "cat_room.png")
SPRITE_SHEET = "cat_grey.png"  # change to whichever sheet you want to inspect

FLOOR_POSITIONS = [
    (250, 215),  # 0 in the bed
    (75,  215),  # 1 on top of shelf
    (410, 225),  # 2 on top of cat tree
    (210, 260),  # 3 left-center floor
    (270, 275),  # 4 center floor
    (195, 310),  # 5 lower left floor
    (250, 328),  # 6 lower center floor
    (315, 300),  # 7 lower right floor
    (150, 345),  # 8 far left floor
    (345, 352),  # 9 far right floor
]

DOT_RADIUS = 10
DOT_COLOR  = (220, 50, 50, 220)
TEXT_COLOR = (255, 255, 255, 255)


def remove_background(img, tolerance=40):
    bg = img.getpixel((0, 0))[:3]
    data = list(img.getdata())
    img.putdata([
        (r, g, b, 0)
        if abs(r-bg[0]) <= tolerance and abs(g-bg[1]) <= tolerance and abs(b-bg[2]) <= tolerance
        else (r, g, b, a)
        for r, g, b, a in data
    ])
    return img


def get_sprites():
    """Return one sprite per position, cycling through valid rows."""
    sheet_path = os.path.join(ASSET_DIR, SPRITE_SHEET)
    if not os.path.exists(sheet_path):
        return [None] * len(FLOOR_POSITIONS)
    sheet = Image.open(sheet_path).convert("RGBA")
    cols = sheet.width // 32
    rows = sheet.height // 32
    valid_by_row = {}
    for row in range(rows):
        for col in range(cols):
            tile = sheet.crop((col*32, row*32, col*32+32, row*32+32))
            non_white = sum(1 for r,g,b,a in tile.getdata() if a > 30 and (r<230 or g<230 or b<230))
            if non_white > 30:
                valid_by_row.setdefault(row, []).append(col)
    sleep_rows = [r for r in (2, 6) if r in valid_by_row]
    if not sleep_rows:
        sleep_rows = list(valid_by_row.keys())
    sprites = []
    for i in range(len(FLOOR_POSITIONS)):
        row = sleep_rows[i % len(sleep_rows)]
        col = valid_by_row[row][0]
        sprite = sheet.crop((col*32, row*32, col*32+32, row*32+32))
        if random.random() < 0.5:
            sprite = ImageOps.mirror(sprite)
        sprites.append(sprite.resize((48, 48), Image.NEAREST))
    return sprites


def debug_positions():
    if not os.path.exists(ROOM_PATH):
        print(f"Room image not found: {ROOM_PATH}")
        return

    room = Image.open(ROOM_PATH).convert("RGBA")
    room = remove_background(room)

    bg = Image.new("RGBA", room.size, (255, 255, 255, 255))
    bg.paste(room, mask=room)
    canvas = bg.convert("RGBA")

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    except Exception:
        font = ImageFont.load_default()

    sprites = get_sprites()

    for i, (x, y) in enumerate(FLOOR_POSITIONS):
        cat_size = 48
        sprite = sprites[i]
        if sprite:
            canvas.paste(sprite, (x - cat_size // 2, y - cat_size), sprite)

        # Label number in red circle on top
        draw = ImageDraw.Draw(canvas)
        draw.ellipse((x - DOT_RADIUS, y - cat_size - DOT_RADIUS,
                       x + DOT_RADIUS, y - cat_size + DOT_RADIUS),
                     fill=(220, 50, 50), outline=(255,255,255), width=2)
        draw.text((x - 4, y - cat_size - 8), str(i), fill=(255,255,255), font=font)

    out = os.path.join(ASSET_DIR, "debug_positions.png")
    canvas.convert("RGB").save(out)
    print(f"Saved: {out}  (room size: {room.width}x{room.height})")


def debug_sprites():
    sheet_path = os.path.join(ASSET_DIR, SPRITE_SHEET)
    if not os.path.exists(sheet_path):
        print(f"Sprite sheet not found: {sheet_path}")
        return

    sheet = Image.open(sheet_path).convert("RGBA")
    cols = sheet.width // 32
    rows = sheet.height // 32

    SCALE = 3
    LABEL_W = 40
    cell = 32 * SCALE

    canvas_w = LABEL_W + cols * cell
    canvas_h = rows * cell
    canvas = Image.new("RGB", (canvas_w, canvas_h), (240, 240, 240))
    draw = ImageDraw.Draw(canvas)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
    except Exception:
        font = ImageFont.load_default()

    for row in range(rows):
        # Row label
        draw.text((4, row * cell + cell // 2 - 6), str(row), fill=(0, 0, 0), font=font)

        for col in range(cols):
            tile = sheet.crop((col*32, row*32, col*32+32, row*32+32))
            tile = tile.resize((cell, cell), Image.NEAREST)

            # White bg for transparency
            bg = Image.new("RGBA", (cell, cell), (255, 255, 255, 255))
            bg.paste(tile, mask=tile)
            canvas.paste(bg.convert("RGB"), (LABEL_W + col * cell, row * cell))

        # Row separator
        draw.line([(0, row * cell), (canvas_w, row * cell)], fill=(180, 180, 180), width=1)

    out = os.path.join(ASSET_DIR, "debug_sprites.png")
    canvas.save(out)
    print(f"Saved: {out}  ({rows} rows x {cols} cols, sprite size 32x32 scaled {SCALE}x)")


if __name__ == "__main__":
    debug_positions()
    debug_sprites()
    print("\nDone. Open the two images in assets/ to review positions and sprite rows.")
