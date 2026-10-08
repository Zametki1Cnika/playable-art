"""Command line: python -m rigwalk LEG.png -o out/ [--frames 14] [--stride 0.4] ...

Writes out/walk_00.png ... (RGBA), out/walk.gif (preview on a dark background), out/sheet.png and out/joints.json.
"""

import argparse
import json
import os

from PIL import Image

from .walk import Gait, LegWalker


def main():
    ap = argparse.ArgumentParser(prog="rigwalk", description="Procedural side-view walk cycle from one painted leg.")
    ap.add_argument("leg", help="picture of ONE leg with the pelvis on top, side view facing right; transparent or magenta (#FF00FF) background")
    ap.add_argument("-o", "--out", default="walk_out", help="output folder")
    g = Gait()
    for name in ("frames", "stance", "stride", "lift", "hip_drop", "toe_off", "heel_strike", "ankle_flex", "reach", "far_keep"):
        ap.add_argument("--" + name.replace("_", "-"), type=type(getattr(g, name)), default=getattr(g, name))
    ap.add_argument("--ms", type=int, default=80, help="preview frame time, ms")
    args = ap.parse_args()
    gait = Gait(**{k: getattr(args, k) for k in ("frames", "stance", "stride", "lift", "hip_drop", "toe_off",
                                                 "heel_strike", "ankle_flex", "reach", "far_keep")})
    os.makedirs(args.out, exist_ok=True)
    walker = LegWalker(args.leg, gait)
    frames = walker.frames()
    joints = []
    previews = []
    for i, (img, jj) in enumerate(frames):
        img.save(os.path.join(args.out, f"walk_{i:02d}.png"))
        joints.append({k: {n: [round(c, 1) for c in p] for n, p in v.items()} for k, v in jj.items()})
        bg = Image.new("RGBA", img.size, (31, 34, 27, 255))
        bg.alpha_composite(img)
        previews.append(bg.convert("RGB"))
    previews[0].save(os.path.join(args.out, "walk.gif"), save_all=True, append_images=previews[1:], duration=args.ms, loop=0)
    w, h = previews[0].size
    cols = (len(previews) + 1) // 2
    sheet = Image.new("RGB", (w * cols, h * 2))
    for i, p in enumerate(previews):
        sheet.paste(p, ((i % cols) * w, (i // cols) * h))
    sheet.save(os.path.join(args.out, "sheet.png"))
    json.dump({"rest": {k: [round(c, 1) for c in v] for k, v in walker.j.items()}, "frames": joints},
              open(os.path.join(args.out, "joints.json"), "w"), indent=1)
    print(f"{len(frames)} frames -> {args.out}")


if __name__ == "__main__":
    main()
