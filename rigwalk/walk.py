"""Procedural side-view walk from ONE painted leg.

The leg is cut into thigh, shin, foot and pelvis (rig.py). Every frame:
- the near leg and the far leg are the same painted leg; the far one is darkened and drawn behind,
  their phases are half a cycle apart (in a side view the near leg is always the same leg);
- stance: the foot lies flat and slides back at constant speed; heel strike pivots around the heel,
  heel-off pivots around the toe; swing: the foot rises early, then travels low; a stiff boot keeps the foot
  almost in line with the shin while in the air;
- the knee is found by two-bone inverse kinematics (thigh and shin keep their length), the knee points forward;
- the pelvis is highest over the straight stance leg and lowest with both feet down;
- gaps inside the silhouette are filled with the colour of the nearest pixel, one dark outline goes around it.
The painting itself never changes between frames, so folds and shading do not flicker.
"""

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy import ndimage

from . import rig


@dataclass
class Gait:
    frames: int = 14          # frames per full cycle (two steps)
    stance: float = 0.6       # share of the cycle a foot is on the ground
    stride: float = 0.80      # stride length as a share of the leg length (hip->ankle)
    lift: float = 0.066       # swing foot lift as a share of the leg length
    hip_drop: float = 0.042   # pelvis drop with both feet down, share of the leg length
    toe_off: float = 18.0     # degrees, heel lift at the end of stance
    heel_strike: float = 13.0  # degrees, toes up before contact
    ankle_flex: float = 12.0  # degrees, max foot-vs-shin angle in the air (stiff boot)
    reach: float = 0.98       # how straight the stance leg is (share of thigh+shin)
    far_keep: float = 0.62    # far leg: how much of its own colour stays
    far_to: tuple = (28, 34, 46)  # ...the rest is this dark colour
    outline: tuple = (26, 31, 28)


def ease(u):
    return u * u * (3 - 2 * u)


def rot(v, deg):
    a = math.radians(deg)
    return (v[0] * math.cos(a) - v[1] * math.sin(a), v[0] * math.sin(a) + v[1] * math.cos(a))


def ik(hip, ankle, l1, l2):
    dx, dy = ankle[0] - hip[0], ankle[1] - hip[1]
    d = min(math.hypot(dx, dy), l1 + l2 - 0.5)
    base = math.atan2(dy, dx)
    a = math.acos(max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d))))
    c1 = (hip[0] + l1 * math.cos(base - a), hip[1] + l1 * math.sin(base - a))
    c2 = (hip[0] + l1 * math.cos(base + a), hip[1] + l1 * math.sin(base + a))
    return c1 if c1[0] > c2[0] else c2   # knee forward (facing right)


class LegWalker:
    def __init__(self, leg_path, gait=None, size=None):
        self.g = gait or Gait()
        self.img, self.mask = rig.load(leg_path, size)
        self.size = (self.img.shape[1], self.img.shape[0])
        self.j = rig.pose(self.mask)
        # put the knee a bit lower than the path estimate: thigh and shin come out about equal
        j = self.j
        j["knee"] = (j["knee"][0] + 0.1 * (j["ankle"][0] - j["knee"][0]), j["knee"][1] + 0.1 * (j["ankle"][1] - j["knee"][1]))
        self.parts = rig.split_parts(self.mask, j)
        self.l1 = math.dist(j["hip"], j["knee"])
        self.l2 = math.dist(j["knee"], j["ankle"])
        self.foot_vec = (j["toe"][0] - j["ankle"][0], j["toe"][1] - j["ankle"][1])
        self.floor = float(np.where(self.mask.any(axis=1))[0].max())
        self.ground_ankle = j["ankle"][1]
        self.heel_vec = (-0.1 * math.hypot(*self.foot_vec), self.floor - self.ground_ankle)
        L = self.l1 + self.l2
        self.stride, self.lift, self.hip_drop = self.g.stride * L, self.g.lift * L, self.g.hip_drop * L

    def foot_pose(self, phase, hip_x):
        g = self.g
        if phase < g.stance:
            u = phase / g.stance
            x = hip_x + self.stride / 2 - self.stride * u
            if u > 0.72:  # heel off: pivot around the toe
                ang = g.toe_off * ease((u - 0.72) / 0.28)
                toe0 = (x + self.foot_vec[0], self.ground_ankle + self.foot_vec[1])
                fv = rot(self.foot_vec, ang)
                return (toe0[0] - fv[0], toe0[1] - fv[1]), ang
            if u < 0.1:  # heel strike: lower the foot around the heel
                ang = -g.heel_strike * (1 - ease(u / 0.1))
                heel0 = (x + self.heel_vec[0], self.ground_ankle + self.heel_vec[1])
                hv = rot(self.heel_vec, ang)
                return (heel0[0] - hv[0], heel0[1] - hv[1]), ang
            return (x, self.ground_ankle), 0.0
        u = (phase - g.stance) / (1 - g.stance)
        x = hip_x - self.stride / 2 + self.stride * u ** 0.7
        lift = self.lift * math.sin(math.pi * u ** 0.6)
        if u > 0.6:
            lift = min(lift, self.lift * 0.6)
        ang = g.toe_off * (1 - ease(min(1.0, u * 2))) - g.heel_strike * ease(max(0.0, (u - 0.6) / 0.4))
        return (x, self.ground_ankle - lift), ang

    def leg(self, hip, ankle, foot_ang, follow):
        j0, P = self.j, self.parts
        knee = ik(hip, ankle, self.l1, self.l2)
        shin_rot = math.degrees(math.atan2(ankle[1] - knee[1], ankle[0] - knee[0])
                                - math.atan2(j0["ankle"][1] - j0["knee"][1], j0["ankle"][0] - j0["knee"][0]))
        foot_ang = foot_ang * (1 - follow) + shin_rot * follow
        if follow > 0:
            foot_ang = shin_rot + max(-self.g.ankle_flex, min(self.g.ankle_flex, foot_ang - shin_rot))
        tv, hv = rot(self.foot_vec, foot_ang), rot(self.heel_vec, foot_ang)
        low = max(ankle[1] + tv[1], ankle[1] + hv[1])
        if low > self.floor:  # toe or heel below the floor: lift the foot
            ankle = (ankle[0], ankle[1] - (low - self.floor))
            knee = ik(hip, ankle, self.l1, self.l2)
        # the painted sole may reach lower than the toe/heel points: measure the placed foot itself
        for _ in range(3):   # the whole boot (foot + shaft) must stay above the floor
            foot = rig.place(self.img, P["foot"], j0["ankle"], j0["toe"], ankle, (ankle[0] + tv[0], ankle[1] + tv[1]), self.size)
            shin = rig.place(self.img, P["shin_full"], j0["knee"], j0["ankle"], knee, ankle, self.size)
            rows = np.where(((foot[..., 3] > 0) | (shin[..., 3] > 0)).any(axis=1))[0]
            excess = (rows.max() - self.floor) if rows.size else 0
            if excess <= 0.5:
                break
            ankle = (ankle[0], ankle[1] - excess)
            knee = ik(hip, ankle, self.l1, self.l2)
        j = {"hip": hip, "knee": knee, "ankle": ankle, "toe": (ankle[0] + tv[0], ankle[1] + tv[1])}
        out = np.zeros((self.size[1], self.size[0], 4), np.uint8)
        for layer in (foot, shin):
            sel = layer[..., 3] > 0
            out[sel] = layer[sel]
        th = rig.place(self.img, P["thigh_soft"], j0["hip"], j0["knee"], j["hip"], j["knee"], self.size,
                       alpha=P["thigh_alpha"]).astype(float)
        a = th[..., 3:4] / 255.0
        has = out[..., 3:4] > 0
        rgb = np.where(has, th[..., :3] * a + out[..., :3] * (1 - a), th[..., :3])
        alpha = np.maximum(out[..., 3], np.where(th[..., 3] >= 128, 255, 0)).astype(np.uint8)
        out = np.dstack([rgb.clip(0, 255).astype(np.uint8), alpha])
        pel = rig.place(self.img, P["pelvis"], j0["hip"], (j0["hip"][0], j0["hip"][1] + 10), hip, (hip[0], hip[1] + 10), self.size)
        sel = pel[..., 3] > 0
        out[sel] = pel[sel]
        return self.fill_gaps(out), j

    def fill_gaps(self, out):
        m = out[..., 3] > 0
        closed = ndimage.binary_fill_holes(ndimage.binary_closing(m, structure=np.ones((3, 3)), iterations=9))
        gaps = closed & ~m
        if gaps.any():
            idx = ndimage.distance_transform_edt(~m, return_distances=False, return_indices=True)
            out[gaps, :3] = out[idx[0][gaps], idx[1][gaps], :3]
            out[gaps, 3] = 255
        m = out[..., 3] > 0
        ring = m & ~ndimage.binary_erosion(m, iterations=1)
        out[ring, :3] = self.g.outline
        return out

    def frames(self):
        """List of (RGBA image, {"near": joints, "far": joints}) for one cycle."""
        g, j0 = self.g, self.j
        reach = g.reach * (self.l1 + self.l2)
        hip_x = j0["hip"][0]
        result = []
        for f in range(g.frames):
            t = f / g.frames
            bob = 0.5 - 0.5 * math.cos(4 * math.pi * (t - 0.05))   # 0 both feet down, 1 over the stance leg
            hip_y = self.ground_ankle - reach + self.hip_drop * (1 - bob)
            poses = [self.foot_pose(ph, hip_x) for ph in ((t + 0.5) % 1.0, t)]
            for (ax, ay), _ in poses:   # the pelvis drops just enough for a straight leg to reach each foot (no stretched shin)
                lim = (self.l1 + self.l2 - 1.0) ** 2 - (ax - hip_x) ** 2
                if lim > 0:
                    hip_y = max(hip_y, ay - math.sqrt(lim))
            hip = (hip_x, hip_y)
            legs, joints = [], []
            for ph, (ankle, ang) in zip(((t + 0.5) % 1.0, t), poses):   # far leg first, then near
                follow = 0.0
                if ph >= g.stance:
                    u = (ph - g.stance) / (1 - g.stance)
                    follow = ease(min(1.0, u / 0.08)) * (1 - ease(max(0.0, (u - 0.85) / 0.15)))
                layer, jj = self.leg(hip, ankle, ang, follow)
                legs.append(layer)
                joints.append(jj)
            far, near = legs
            fm, nm = far[..., 3] > 0, near[..., 3] > 0
            far_rgb = far[..., :3].astype(float) * g.far_keep + np.array(g.far_to, float) * (1 - g.far_keep)
            out = np.zeros((self.size[1], self.size[0], 4), np.uint8)
            out[fm, :3] = far_rgb[fm].astype(np.uint8)
            out[fm, 3] = 255
            out[nm] = near[nm]
            result.append((Image.fromarray(out, "RGBA"), {"far": joints[0], "near": joints[1]}))
        return result
