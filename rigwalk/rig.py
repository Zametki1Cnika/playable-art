"""Cut-out leg rig: find leg joints in a picture, cut a painted leg into parts, place parts on new bones.

All coordinates are (x, y) in canvas pixels, y pointing down.
"""

import math

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra


def load(path, size=None, key=(255, 0, 255)):
    """Load a leg picture. Background is either transparent or a flat key colour (magenta by default).

    Returns (rgb uint8 array, foreground mask). Only the largest connected blob is kept.
    """
    im = Image.open(path)
    if size:
        im = im.resize(size, Image.LANCZOS)
    rgba = np.array(im.convert("RGBA")).astype(int)
    rgb = rgba[..., :3]
    if (rgba[..., 3] < 255).any():
        mask = rgba[..., 3] >= 128
    else:
        k = np.array(key)
        mask = np.abs(rgb - k).sum(axis=2) > 150
    lab, n = ndimage.label(mask)
    if n > 1:
        sizes = ndimage.sum(mask, lab, range(1, n + 1))
        mask = lab == (1 + int(np.argmax(sizes)))
    return rgb.astype(np.uint8), mask


def pose(mask, split=0.165, knee_at=0.37, ankle_at=0.86, down=2):
    """Joints of a side-view leg (hip, knee, ankle, toe) found in its silhouette.

    - waist line: top of the mask + `split` of its height; hip = middle of the mask on that line;
    - toe: the farthest point of the leg from the hip, measured along the leg;
    - a path from hip to toe runs along the middle of the leg (Dijkstra, cheaper far from the edge);
    - knee and ankle are points on that path at `knee_at` and `ankle_at` of its length.
    """
    ys = np.where(mask.any(axis=1))[0]
    top, bot = ys.min(), ys.max()
    hip_y = int(top + split * (bot - top))
    hip = (float(np.where(mask[hip_y])[0].mean()), float(hip_y))
    small = mask[::down, ::down].copy()
    small[: hip_y // down] = False
    edt = ndimage.distance_transform_edt(small)
    idx = -np.ones(small.shape, int)
    pts = np.argwhere(small)
    idx[pts[:, 0], pts[:, 1]] = np.arange(len(pts))
    rows, cols, w_len, w_mid = [], [], [], []
    for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
        y2, x2 = pts[:, 0] + dy, pts[:, 1] + dx
        ok = (y2 >= 0) & (y2 < small.shape[0]) & (x2 >= 0) & (x2 < small.shape[1])
        ok[ok] &= small[y2[ok], x2[ok]]
        a = idx[pts[ok, 0], pts[ok, 1]]
        b = idx[y2[ok], x2[ok]]
        step = math.hypot(dy, dx)
        mid = step / (0.5 + (edt[pts[ok, 0], pts[ok, 1]] + edt[y2[ok], x2[ok]]) / 2) ** 2
        rows += [a, b]
        cols += [b, a]
        w_len += [np.full(len(a), step)] * 2
        w_mid += [mid, mid]
    rows, cols = np.concatenate(rows), np.concatenate(cols)
    n = len(pts)
    g_len = coo_matrix((np.concatenate(w_len), (rows, cols)), shape=(n, n)).tocsr()
    g_mid = coo_matrix((np.concatenate(w_mid), (rows, cols)), shape=(n, n)).tocsr()
    start = int(np.argmin((pts[:, 0] - (hip[1] / down + 1)) ** 2 + (pts[:, 1] - hip[0] / down) ** 2))
    dist = dijkstra(g_len, indices=start)
    dist[~np.isfinite(dist)] = -1
    toe_i = int(np.argmax(dist))
    _, pred = dijkstra(g_mid, indices=start, return_predecessors=True)
    path = [toe_i]
    while path[-1] != start and pred[path[-1]] >= 0:
        path.append(pred[path[-1]])
    p = pts[path[::-1]][:, ::-1].astype(float) * down
    p[0] = hip
    cum = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(p, axis=0).T))])

    def at(f):
        L = f * cum[-1]
        i = min(max(int(np.searchsorted(cum, L)), 1), len(p) - 1)
        t = (L - cum[i - 1]) / max(cum[i] - cum[i - 1], 1e-6)
        return tuple(p[i - 1] + t * (p[i] - p[i - 1]))

    return {"hip": hip, "knee": at(knee_at), "ankle": at(ankle_at), "toe": tuple(p[-1])}


def _seg_dist(P, a, b):
    a, b = np.array(a), np.array(b)
    v = b - a
    t = np.clip(((P - a) @ v) / max(v @ v, 1e-6), 0, 1)
    return np.hypot(*(P - (a + t[:, None] * v)).T)


def split_parts(mask, j, knee_blend=1.4):
    """Masks of the painted leg parts: thigh, shin, foot, pelvis (above the waist line), plus a soft knee blend.

    Each pixel goes to the nearest bone. Every part also takes a round "cap" around both of its joints
    (radius = half the leg thickness there), so a bent joint shows no gap and nothing sticks out.
    Around the knee the thigh fades over the shin (`thigh_alpha`), so the knee bends instead of turning as a disc.
    """
    yy, xx = np.nonzero(mask)
    P = np.stack([xx, yy], axis=1).astype(float)
    d = np.stack([_seg_dist(P, j["hip"], j["knee"]), _seg_dist(P, j["knee"], j["ankle"]),
                  _seg_dist(P, j["ankle"], j["toe"])], axis=1)
    owner = d.argmin(axis=1)
    pelvis_rows = yy < j["hip"][1]
    owner[pelvis_rows] = -1
    edt = ndimage.distance_transform_edt(mask)

    def cap(pt):
        x = min(max(int(round(pt[0])), 0), mask.shape[1] - 1)
        y = min(max(int(round(pt[1])), 0), mask.shape[0] - 1)
        return max(8.0, float(edt[y, x]) * 1.05)

    parts = {"pelvis": np.zeros(mask.shape, bool)}
    parts["pelvis"][yy[pelvis_rows], xx[pelvis_rows]] = True
    for k, name, joint, lower in ((0, "thigh", "hip", "knee"), (1, "shin", "knee", "ankle"), (2, "foot", "ankle", "toe")):
        near = (np.hypot(xx - j[joint][0], yy - j[joint][1]) < cap(j[joint])) | \
               (np.hypot(xx - j[lower][0], yy - j[lower][1]) < cap(j[lower]))
        if name == "foot":  # no boot shaft in the foot part, or a high boot "breaks" at the ankle
            near &= yy > j["ankle"][1] - 4
        sel = (owner == k) | near
        m = np.zeros(mask.shape, bool)
        m[yy[sel], xx[sel]] = True
        parts[name] = m
    # soft knee: a band across the leg; the shin owns it below the knee, the thigh fades over it
    rk = max(10.0, cap(j["knee"]) * knee_blend)
    dvec = np.subtract(j["ankle"], j["knee"])
    dvec = dvec / max(np.hypot(*dvec), 1e-6)
    gy, gx = np.mgrid[0:mask.shape[0], 0:mask.shape[1]]
    s = (gx - j["knee"][0]) * dvec[0] + (gy - j["knee"][1]) * dvec[1]
    band = mask & (gy >= j["hip"][1]) & (np.abs(s) < rk) & (np.hypot(gx - j["knee"][0], gy - j["knee"][1]) < rk * 2.2)
    parts["shin_full"] = parts["shin"] | (band & (s > -0.3 * rk))
    parts["thigh_soft"] = (parts["thigh"] | band) & (s < rk)
    parts["thigh_alpha"] = np.where(parts["thigh_soft"], 255 * np.clip(0.5 - s / (2 * rk), 0, 1), 0)
    return parts


def place(img, part_mask, a, b, a2, b2, size, alpha=None, max_stretch=0.25):
    """Move a part so that its bone a->b lies on a2->b2 (rotate, scale within ±max_stretch, translate).

    Returns an RGBA canvas of `size`. With `alpha` the part keeps a soft alpha (for blending), otherwise its edge is crisp.
    """
    v, v2 = np.subtract(b, a), np.subtract(b2, a2)
    s = float(np.clip(math.hypot(*v2) / max(math.hypot(*v), 1e-6), 1 - max_stretch, 1 + max_stretch))
    ang = math.atan2(v2[1], v2[0]) - math.atan2(v[1], v[0])
    c, sn = math.cos(ang), math.sin(ang)
    inv = np.array([[c / s, sn / s], [-sn / s, c / s]])
    off = np.array(a) - inv @ np.array(a2)
    # colour around the part = colour of its nearest pixel: smooth rotation never pulls in a foreign colour
    idx = ndimage.distance_transform_edt(~part_mask, return_distances=False, return_indices=True)
    filled = img[idx[0], idx[1]]
    a_ch = alpha.astype(np.uint8) if alpha is not None else np.where(part_mask, 255, 0).astype(np.uint8)
    src = Image.fromarray(np.dstack([filled, a_ch]), "RGBA")
    out = np.array(src.transform(size, Image.AFFINE, (inv[0, 0], inv[0, 1], off[0], inv[1, 0], inv[1, 1], off[1]),
                                 resample=Image.BICUBIC))
    if alpha is None:
        out[..., 3] = np.where(out[..., 3] >= 128, 255, 0)
    return out
