"""Gait checks on the demo leg: run with `pytest`."""

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rigwalk import LegWalker  # noqa: E402
from rigwalk import qa  # noqa: E402


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    leg = tmp_path_factory.mktemp("leg") / "demo_leg.png"
    subprocess.run([sys.executable, os.path.join(ROOT, "make_demo_leg.py"), str(leg)], check=True)
    walker = LegWalker(str(leg))
    frames = walker.frames()
    return walker, frames, qa.check(walker, frames)


def test_cycle_has_all_frames(result):
    walker, frames, _ = result
    assert len(frames) == walker.g.frames


def test_feet_stay_on_the_floor(result):
    assert result[2]["floor_error_px"] <= qa.FLOOR_TOL


def test_planted_foot_does_not_skate(result):
    assert result[2]["foot_slide"] <= qa.SLIDE_TOL


def test_knee_bends_forward_and_not_too_far(result):
    lo, hi = result[2]["knee_bend_deg"]
    assert lo >= -2 and hi <= qa.KNEE_MAX


def test_bones_keep_their_length(result):
    assert result[2]["bone_stretch"] <= 0.01


def test_pelvis_bobs_and_does_not_limp(result):
    assert result[2]["pelvis_bob_px"] > 0
    assert result[2]["limp"] <= qa.LIMP_TOL


def test_no_problems_reported(result):
    assert result[2]["problems"] == []
