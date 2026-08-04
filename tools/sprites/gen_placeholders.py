#!/usr/bin/env python3
"""Generate placeholder sprite headers (hue-rotated base sprite) + sprites.h aggregator.

Usage: python3 gen_placeholders.py <base_32x32.png> <outdir>
"""
import sys
import colorsys
from PIL import Image
from convert_sprite import to_c_array, checker_preview

FORMS = [  # (name, hue_shift 0..1, sat_mul, val_mul)
    ("baby", 0.55, 0.25, 1.15),        # pale cream
    ("child_a", 0.75, 0.75, 1.0),      # light green
    ("child_b", 0.48, 0.9, 1.0),       # orange
    ("adult_leaf", 0.82, 1.0, 0.9),    # deep green
    ("adult_muscle", 0.42, 1.0, 0.95), # red
    ("adult_marine", 0.0, 1.0, 1.0),   # blue (base)
    ("adult_candy", 0.25, 0.6, 1.1),   # pink
    ("adult_rainbow", 0.0, 0.15, 1.2), # pearl white
]
FRAMES = ["idle_a", "idle_b", "eat", "happy"]


def hue_shift(img, dh, sm, vm):
    out = img.copy()
    px = out.load()
    for y in range(out.size[1]):
        for x in range(out.size[0]):
            r, g, b, a = px[x, y]
            if a < 128:
                continue
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            h = (h + dh) % 1.0
            s = min(1.0, s * sm)
            v = min(1.0, v * vm)
            r2, g2, b2 = colorsys.hsv_to_rgb(h, s, v)
            px[x, y] = (int(r2 * 255), int(g2 * 255), int(b2 * 255), 255)
    return out


def squash(img, ratio=0.75):
    w, h = img.size
    nh = int(h * ratio)
    sq = img.resize((w, nh), Image.NEAREST)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(sq, (0, h - nh))
    return out


def main():
    base = Image.open(sys.argv[1]).convert("RGBA")
    outdir = sys.argv[2]
    import os
    os.makedirs(outdir, exist_ok=True)

    for name, dh, sm, vm in FORMS:
        idle_a = hue_shift(base, dh, sm, vm)
        frames = [idle_a, squash(idle_a), idle_a, idle_a]  # placeholder: eat/happy = idle_a
        arrays = [to_c_array(f, f"SPR_{name.upper()}_{fr.upper()}") for f, fr in zip(frames, FRAMES)]
        guard = f"TOI_SPRITE_{name.upper()}_H"
        with open(f"{outdir}/{name}.h", "w") as f:
            f.write(f"// Auto-generated placeholder (hue-rotated base) — will be replaced by gpt-image-2 art\n"
                    f"// 32x32 RGB332, transparent key 0xE3\n"
                    f"#ifndef {guard}\n#define {guard}\n#include <pgmspace.h>\n\n")
            f.write("\n\n".join(arrays))
            f.write(f"\n\n#endif // {guard}\n")
        checker_preview(frames).save(f"{outdir}/{name}_preview.png")
        print("placeholder:", name)

    with open(f"{outdir}/sprites.h", "w") as f:
        f.write("// Sprite aggregator — symbol contract is FIXED (form ids 0..7, 4 frames each).\n"
                "// Frame data files are regenerated from art; this table layout must not change.\n"
                "#ifndef TOI_SPRITES_H\n#define TOI_SPRITES_H\n#include <pgmspace.h>\n\n")
        for name, *_ in FORMS:
            f.write(f'#include "{name}.h"\n')
        f.write("\nstatic const int TOI_SPR_SIZE = 32;\n"
                "static const uint8_t TOI_SPR_TRANSPARENT = 0xE3;\n\n"
                "struct ToiSpriteSet {\n"
                "  const uint8_t *idle_a;\n  const uint8_t *idle_b;\n"
                "  const uint8_t *eat;\n  const uint8_t *happy;\n};\n\n"
                "// index = form id: 0=baby 1=child_a 2=child_b 3=leaf 4=muscle 5=marine 6=candy 7=rainbow\n"
                "static const ToiSpriteSet TOI_SPRITES[8] = {\n")
        for name, *_ in FORMS:
            u = name.upper()
            f.write(f"  {{ SPR_{u}_IDLE_A, SPR_{u}_IDLE_B, SPR_{u}_EAT, SPR_{u}_HAPPY }},\n")
        f.write("};\n\n#endif // TOI_SPRITES_H\n")
    print("aggregator: sprites.h")


if __name__ == "__main__":
    main()
