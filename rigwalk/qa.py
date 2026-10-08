"""Measured gait checks: numbers instead of a glance.

check(walker, frames) -> dict of measurements and a list of problems. Checks:
- floor: no frame has foot pixels below the floor line (tolerance FLOOR_TOL px);
- foot slide: while a foot is planted (flat stance), its ankle moves back at a constant speed — the deviation from
  that steady slide is a skate in the game;
- knee: the knee bends only forward and never past KNEE_MAX degrees;
- bone length: thigh and shin keep their painted length (IK must never stretch them);
- bob: the pelvis is highest over the stance leg and lowest with both feet down, and both steps dip equally (no limp).
"""

import math

import numpy as np

FLOOR_TOL = 3.0
SLIDE_TOL = 0.02     # share of the leg length
KNEE_MAX = 75.0
LIMP_TOL = 0.01      # share of the leg length


def _knee_bend(j):
    a = math.atan2(j["knee"][1] - j["hip"][1], j["knee"][0] - j["hip"][0])
    b = math.atan2(j["ankle"][1] - j["knee"][1], j["ankle"][0] - j["knee"][0])
    return math.degrees(b - a)   # >0: knee forward (facing right; y points down)


def check(walker, frames=None):
    frames = frames or walker.frames()
    g = walker.g
    L = walker.l1 + walker.l2
    problems = []
    lows = []
    for img, _ in frames:
        a = np.array(img)
        lows.append(float(np.where((a[..., 3] > 0).any(axis=1))[0].max()))
    floor_err = max(lows) - walker.floor
    if floor_err > FLOOR_TOL:
        problems.append(f"foot below the floor by {floor_err:.1f} px")
    n = len(frames)
    slide = 0.0
    for side in ("near", "far"):
        xs, ts = [], []
        for f, (_, jj) in enumerate(frames):
            ph = (f / n + (0.0 if side == "near" else 0.5)) % 1.0
            u = ph / g.stance
            if 0.12 < u < 0.7:   # flat stance only (heel strike and heel off pivot on purpose)
                xs.append(jj[side]["ankle"][0])
                ts.append(ph)
        if len(xs) >= 3:
            k, b = np.polyfit(ts, xs, 1)
            slide = max(slide, float(np.abs(np.array(xs) - (k * np.array(ts) + b)).max()) / L)
    if slide > SLIDE_TOL:
        problems.append(f"planted foot skates: {slide:.3f} of leg length")
    bends = [_knee_bend(jj[s]) for _, jj in frames for s in ("near", "far")]
    if min(bends) < -2:
        problems.append(f"knee bends backwards: {min(bends):.1f} deg")
    if max(bends) > KNEE_MAX:
        problems.append(f"knee bends too far: {max(bends):.1f} deg")
    stretch = 0.0
    for _, jj in frames:
        for s in ("near", "far"):
            j = jj[s]
            stretch = max(stretch, abs(math.dist(j["hip"], j["knee"]) - walker.l1) / walker.l1,
                          abs(math.dist(j["knee"], j["ankle"]) - walker.l2) / walker.l2)
    if stretch > 0.01:
        problems.append(f"bone stretched by {stretch:.1%}")
    hips = np.array([jj["near"]["hip"][1] for _, jj in frames])
    half = n // 2
    limp = abs(hips[:half].max() - hips[half:].max()) / L
    if limp > LIMP_TOL:
        problems.append(f"limp: the two steps dip differently ({limp:.3f} of leg length)")
    return {
        "floor_error_px": round(floor_err, 2),
        "foot_slide": round(slide, 4),
        "knee_bend_deg": [round(min(bends), 1), round(max(bends), 1)],
        "bone_stretch": round(stretch, 4),
        "pelvis_bob_px": round(float(hips.max() - hips.min()), 1),
        "limp": round(limp, 4),
        "problems": problems,
    }
