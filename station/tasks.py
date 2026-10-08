"""Task folders: the unit of work of the generation station.

A task is a folder with:
  prompt.txt          what to draw (one subject per task: ask the model for little at a time)
  reference*.png      pictures attached to the request (style etalon, scale, the accepted previous frame...)
  result/             generated pictures land here as <folder>_v1.png, _v2.png, ...
  needs.txt           optional: lines "other/task/folder|reference_name.png" — wait until that task is ACCEPTED,
                      then copy its accepted picture here under that name (chains: etalon -> parts -> frames)
  ACCEPTED.txt        written by a human (or an auto-accept rule): the accepted file name
  CLAIMED.txt         someone works on it by hand; the pool leaves it alone
A PRIORITY.txt file in the root lists path fragments, top first; matching tasks go first.
"""

import glob
import os

import numpy as np
from PIL import Image

IMG = (".png", ".jpg", ".jpeg", ".webp")


def task_dirs(root):
    return sorted(os.path.dirname(p) for p in glob.glob(os.path.join(root, "**", "prompt.txt"), recursive=True))


def results(task):
    return sorted((f for f in glob.glob(os.path.join(task, "result", "*")) if f.lower().endswith(IMG)), key=os.path.getmtime)


def next_name(task):
    base = os.path.basename(task)
    n = 1
    while os.path.exists(os.path.join(task, "result", f"{base}_v{n}.png")):
        n += 1
    return f"{base}_v{n}.png"


def accepted(task):
    mark = os.path.join(task, "ACCEPTED.txt")
    if not os.path.exists(mark):
        return None
    name = open(mark, encoding="utf-8").read().split()[0]
    p = os.path.join(task, "result", name)
    return p if os.path.exists(p) else None


def needs_ready(root, task):
    """True when every dependency is accepted; copies the accepted pictures in as references."""
    import shutil
    path = os.path.join(task, "needs.txt")
    if not os.path.exists(path):
        return True
    for line in open(path, encoding="utf-8"):
        if "|" not in line:
            continue
        dep, name = (x.strip() for x in line.split("|", 1))
        src = accepted(os.path.join(root, dep))
        if not src:
            return False
        dst = os.path.join(task, name)
        if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
            shutil.copy(src, dst)
    return True


def priority(root):
    p = os.path.join(root, "PRIORITY.txt")
    if not os.path.exists(p):
        return []
    return [ln.strip() for ln in open(p, encoding="utf-8") if ln.strip() and not ln.startswith("#")]


def queue(root):
    """Tasks without a result, ready to run, in priority order."""
    prio = priority(root)

    def rank(t):
        r = os.path.relpath(t, root).replace("\\", "/")
        return next((i for i, frag in enumerate(prio) if frag in r), len(prio))

    todo = [t for t in task_dirs(root) if not results(t) and not os.path.exists(os.path.join(t, "CLAIMED.txt")) and needs_ready(root, t)]
    return sorted(todo, key=rank)


def check_image(path, key_background=True):
    """Automatic checks of a generated picture; returns a list of problems (empty = fine)."""
    problems = []
    try:
        im = Image.open(path).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        return [f"cannot open: {exc}"]
    w, h = im.size
    if max(w, h) < 1024:
        problems.append(f"too small: {w}x{h}")
    a = np.array(im).astype(int)
    if key_background:
        corners = np.concatenate([a[:20, :20].reshape(-1, 3), a[:20, -20:].reshape(-1, 3), a[-20:, :20].reshape(-1, 3), a[-20:, -20:].reshape(-1, 3)])
        if ((corners[:, 0] > 170) & (corners[:, 1] < 120) & (corners[:, 2] > 170)).mean() < 0.5:
            problems.append("background is not flat magenta #FF00FF")
        content = np.abs(a - np.array([255, 0, 255])).sum(axis=2) > 200
        for side, strip in (("top", content[:2, :].any(axis=0)), ("left", content[:, :2].any(axis=1)), ("right", content[:, -2:].any(axis=1))):
            if strip.sum() > max(6, len(strip) * 0.02):
                problems.append(f"cut at the {side} edge")
    if (np.abs(a - a.mean(axis=(0, 1))).sum(axis=2) < 6).mean() > 0.97:
        problems.append("almost empty")
    return problems
