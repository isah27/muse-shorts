"""Draw clean, editorial label call-outs for segmented structures."""
from __future__ import annotations
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from .. import config as C

ACCENT = (125, 211, 252)

def _font(size, bold=True):
    p = C.FONT_DIR / "Inter/Inter-VariableFont_opsz,wght.ttf"
    f = ImageFont.truetype(str(p), size)
    try:
        f.set_variation_by_name("Bold" if bold else "Regular")
    except Exception:
        pass
    return f

def draw_labels(src: str, dst: str, segments) -> str:
    img = Image.open(src).convert("RGBA")
    W, H = img.size
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    f = _font(int(W * 0.036))
    used = []
    for i, s in enumerate(segments):
        x1, y1, x2, y2 = s.box
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        if s.mask is not None:
            edge = s.mask.convert("L").filter(ImageFilter.FIND_EDGES).point(lambda v: 200 if v > 60 else 0)
            over.paste((*ACCENT, 255), (0, 0), edge)
        else:
            d.rounded_rectangle([x1, y1, x2, y2], radius=28, outline=(*ACCENT, 230), width=4)
        d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=(255, 255, 255, 255))
        text = s.label.upper()
        tw = d.textlength(text, font=f)
        side = 1 if cx < W / 2 else -1
        lx = cx + side * int(W * 0.16)
        ly = max(int(H * 0.12), min(int(H * 0.8), cy - int(H * 0.06)))
        while any(abs(ly - u) < 90 for u in used):
            ly += 95
        used.append(ly)
        bx = lx if side > 0 else lx - tw - 48
        bx = max(24, min(W - tw - 72, bx))
        d.line([cx, cy, lx, ly + 34], fill=(255, 255, 255, 220), width=3)
        d.rounded_rectangle([bx, ly, bx + tw + 48, ly + 68], radius=34, fill=(10, 12, 20, 210), outline=(*ACCENT, 255), width=3)
        d.text((bx + 24, ly + 12), text, font=f, fill=(255, 255, 255, 255))
    Image.alpha_composite(img, over).convert("RGB").save(dst)
    return dst
