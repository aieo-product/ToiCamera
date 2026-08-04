#!/usr/bin/env python3
"""Compose 466x466 home-screen mocks with the final #13 layout + real sprites.

Usage: python3 make_home_mock.py <final_dir> <outdir>
Layout constants mirror firmware/stopwatch/src/main.cpp (drawHome, #13 rework).
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

FORMS = ["baby", "child_a", "child_b", "adult_leaf", "adult_muscle",
         "adult_marine", "adult_candy", "adult_rainbow"]
NAMES = {"baby": "たまぷに", "child_a": "すこやかぷに", "child_b": "もりもりぷに",
         "adult_leaf": "リーフぷに", "adult_muscle": "マッスルぷに",
         "adult_marine": "マリンぷに", "adult_candy": "キャンディぷに",
         "adult_rainbow": "レインボーぷに"}

W = H = 466
CHAR_CX, CHAR_CY, ZOOM = 232, 264, 6
PILL_W, PILL_H, PILL_Y = 240, 48, 378


def load_font(size):
    for path in ["/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc",
                 "/System/Library/Fonts/Hiragino Sans GB.ttc",
                 "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def center_text(d, xy, text, font, fill):
    d.text(xy, text, font=font, fill=fill, anchor="mm")


def mock(final_dir, form, out_png):
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([1, 1, W - 2, H - 2], outline=(40, 40, 40), width=2)  # round bezel

    f16 = load_font(16)
    f64 = load_font(58)
    f22 = load_font(22)

    center_text(d, (W // 2, 40), "82%", f16, (200, 200, 200))
    center_text(d, (W // 2, 80), "8/4(火)", f16, (200, 200, 200))
    center_text(d, (W // 2, 130), "12:34", f64, (255, 255, 255))

    spr = Image.open(f"{final_dir}/{form}/{form}_idle_a.png").convert("RGBA")
    big = spr.resize((spr.size[0] * ZOOM, spr.size[1] * ZOOM), Image.NEAREST)
    img.paste(big, (CHAR_CX - big.size[0] // 2, CHAR_CY - big.size[1] // 2), big)

    center_text(d, (W // 2, 362), "1234歩 ・ 560kcal", f16, (0, 255, 255))

    px = (W - PILL_W) // 2
    d.rounded_rectangle([px, PILL_Y, px + PILL_W, PILL_Y + PILL_H],
                        radius=PILL_H // 2, outline=(120, 120, 120), width=2)
    center_text(d, (W // 2, PILL_Y + PILL_H // 2 + 1), "設定", f22, (220, 220, 220))

    center_text(d, (W // 2, 438), "黄:カメラ 青:スリープ", f16, (110, 110, 110))
    img.save(out_png)


def main():
    final_dir, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)
    cell_w, cell_h = W // 2 + 20, H // 2 + 46
    sheet = Image.new("RGB", (cell_w * 4, cell_h * 2), (25, 25, 25))
    dd = ImageDraw.Draw(sheet)
    f14 = load_font(14)
    for i, form in enumerate(FORMS):
        out = f"{outdir}/home_{form}.png"
        mock(final_dir, form, out)
        thumb = Image.open(out).resize((W // 2, H // 2), Image.LANCZOS)
        cx, cy = (i % 4) * cell_w + 10, (i // 4) * cell_h + 6
        sheet.paste(thumb, (cx, cy))
        dd.text((cx + W // 4, cy + H // 2 + 16),
                f"{NAMES[form]} ({form})", font=f14, fill=(230, 230, 230), anchor="mm")
    sheet.save(f"{outdir}/home_all.png")
    print("mocks ->", outdir)


if __name__ == "__main__":
    main()
