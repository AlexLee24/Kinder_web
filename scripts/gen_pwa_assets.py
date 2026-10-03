"""Generate every image the installable web app (PWA) needs from the Kinder logo.

    .venv/bin/python scripts/gen_pwa_assets.py

Writes to app/blueprints/basic/static/pwa/ (manifest.json and _pwa_head.html reference these
exact names). Re-run after changing the logo. Adapted from EAU_Web's scripts/gen_pwa_assets.py.

- icon-<n>.png            app icon: logo on a dark rounded square (desktop Chrome/Edge, Android "any")
- maskable-<n>.png        Android adaptive icon: full-bleed dark square, logo inside the 80 % safe zone
- apple-touch-icon-<n>    iOS home-screen icon (iOS turns transparency black, so it must be opaque)
- splash/<w>x<h>.png      iOS launch screens (without them iOS shows a white screen while the app starts)
- shortcut-<name>.png     long-press shortcut icons (96 x 96)
- logo-<h>.png            the transparent logo at <h> px tall, for the navbar / home / login / offline page
                          (the source PNG is 2.7 MB — far too heavy to show at 30 px on a phone)
"""
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app', 'blueprints', 'basic')
LOGO = os.path.join(ROOT, 'icon', 'Kinder_light.png')
OUT = os.path.join(ROOT, 'static', 'pwa')

BG = (11, 13, 20, 255)          # #0B0D14 = --kw-bg and manifest background_color / theme_color
TILE = (20, 23, 33, 255)        # #141721 = --kw-bg-elevated
GOLD = (212, 176, 106, 255)     # #D4B06A = --kw-accent
INK = (26, 20, 8, 255)          # #1A1408 = --kw-accent-contrast
FONTS = ['/System/Library/Fonts/SFNS.ttf', '/System/Library/Fonts/Helvetica.ttc', '/Library/Fonts/Arial.ttf']

# iOS devices, portrait only: (CSS width, CSS height, pixel ratio). A launch image is used only when it
# matches device-width / device-height / ratio exactly; _pwa_head.html lists the same set.
IOS_DEVICES = [
    (440, 956, 3), (402, 874, 3), (430, 932, 3), (393, 852, 3), (428, 926, 3), (390, 844, 3),
    (375, 812, 3), (414, 896, 3), (414, 896, 2), (414, 736, 3), (375, 667, 2),
    (1024, 1366, 2), (834, 1194, 2), (820, 1180, 2), (810, 1080, 2), (768, 1024, 2),
]

SHORTCUTS = {'marshal': 'M', 'trigger': 'T', 'detect': 'D', 'planner': 'V'}


def logo():
    im = Image.open(LOGO).convert('RGBA')
    bbox = im.getchannel('A').point(lambda a: 255 if a > 8 else 0).getbbox()
    return im.crop(bbox) if bbox else im


def place(canvas, lg, height_frac):
    """Scale the (tall) logo so its height is height_frac of the canvas height, centred."""
    w, h = canvas.size
    th = int(round(h * height_frac))
    tw = int(round(lg.width * th / lg.height))
    canvas.alpha_composite(lg.resize((tw, th), Image.LANCZOS), ((w - tw) // 2, (h - th) // 2))
    return canvas


def rounded(size, radius_frac, fill):
    im = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((0, 0, size - 1, size - 1), radius=int(size * radius_frac), fill=fill)
    return im


def save(im, name, quantize=False):
    path = os.path.join(OUT, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if quantize:
        im = im.convert('RGB').quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    im.save(path, optimize=True)
    return path


def font(size):
    for f in FONTS:
        if os.path.isfile(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def main():
    lg = logo()
    written = []
    for n in (48, 72, 96, 128, 144, 192, 256, 384, 512):
        written.append(save(place(rounded(n, 0.22, TILE), lg, 0.80), f'icon-{n}.png'))
    for n in (192, 512):
        written.append(save(place(Image.new('RGBA', (n, n), TILE), lg, 0.62), f'maskable-{n}.png'))
    for n in (120, 152, 167, 180):
        written.append(save(place(Image.new('RGBA', (n, n), TILE), lg, 0.78), f'apple-touch-icon-{n}.png'))
    for w, h, r in IOS_DEVICES:
        pw, ph = w * r, h * r
        written.append(save(place(Image.new('RGBA', (pw, ph), BG), lg, 0.22), f'splash/{pw}x{ph}.png', quantize=True))
    for h in (64, 128, 256):
        w = int(round(lg.width * h / lg.height))
        written.append(save(lg.resize((w, h), Image.LANCZOS), f'logo-{h}.png'))
    for name, letter in SHORTCUTS.items():
        im = rounded(96, 0.24, GOLD)
        d = ImageDraw.Draw(im)
        f = font(52)
        box = d.textbbox((0, 0), letter, font=f)
        d.text(((96 - (box[2] - box[0])) / 2 - box[0], (96 - (box[3] - box[1])) / 2 - box[1]), letter, font=f, fill=INK)
        written.append(save(im, f'shortcut-{name}.png'))
    total = sum(os.path.getsize(p) for p in written)
    print(f'{len(written)} files, {total / 1024:.0f} KB -> {os.path.relpath(OUT)}')


if __name__ == '__main__':
    main()
