"""Draws the app icon (a concert ticket on the hero's glow) and writes every size.
Run: python3 icons/make_icons.py   (needs Pillow)"""
import math, os
from PIL import Image, ImageDraw, ImageFilter

S = 1024
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

bg = Image.new("RGB", (S, S), (11, 10, 16))
glow = Image.new("RGB", (S, S), (0, 0, 0))
g = ImageDraw.Draw(glow)
g.ellipse((-200, -250, 620, 520), fill=(124, 92, 255))
g.ellipse((480, -200, 1250, 560), fill=(255, 77, 141))
g.ellipse((250, 620, 1050, 1300), fill=(255, 163, 72))
bg = Image.blend(bg, glow.filter(ImageFilter.GaussianBlur(170)), 0.6)

t = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(t)
x0, y0, x1, y1 = 170, 300, 854, 724
d.rounded_rectangle((x0, y0, x1, y1), radius=56, fill=(255, 255, 255, 255))
r = 58
for cx in (x0, x1):  # punched notches
    d.ellipse((cx - r, (y0 + y1) // 2 - r, cx + r, (y0 + y1) // 2 + r), fill=(0, 0, 0, 0))
for y in range(y0 + 34, y1 - 20, 44):  # perforation
    d.rounded_rectangle((374, y, 386, y + 24), radius=6, fill=(217, 213, 232, 255))
note = (98, 80, 214, 255)
d.ellipse((520, 560, 640, 650), fill=note)
d.rectangle((612, 380, 640, 610), fill=note)
d.polygon([(640, 380), (730, 420), (730, 470), (640, 436)], fill=note)
cx, cy = 275, 512
d.polygon([(cx + (62 if i % 2 == 0 else 26) * math.cos(-math.pi / 2 + i * math.pi / 5),
            cy + (62 if i % 2 == 0 else 26) * math.sin(-math.pi / 2 + i * math.pi / 5)) for i in range(10)],
          fill=(255, 77, 141, 255))
t = t.rotate(-10, resample=Image.BICUBIC, center=(S / 2, S / 2))
shadow = t.split()[3].filter(ImageFilter.GaussianBlur(30)).point(lambda v: int(v * 0.5))
bg.paste((0, 0, 0), (0, 24), shadow)
bg.paste(t, (0, 0), t)

for n in (512, 192, 180, 32):
    bg.resize((n, n), Image.LANCZOS).save(os.path.join(ROOT, "icons", f"icon-{n}.png"))
bg.save(os.path.join(ROOT, "ios", "Concerts", "Assets.xcassets", "AppIcon.appiconset", "icon-1024.png"))
print("icons written")
