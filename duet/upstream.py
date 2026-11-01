"""Pinned organizer dependency and coordinate/RC adapter. No replacement renderer."""
from __future__ import annotations

import importlib
import math
import subprocess
import sys
from pathlib import Path

from .choreography import RC_XY_CAP

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "vendor/action-space"
REVISION = "cd6536a458c3ba034a727ea00f57adac6bed9471"


def verify():
    if not (UPSTREAM / ".git").exists():
        raise RuntimeError("Run python -m duet.bootstrap first")
    rev = subprocess.check_output(["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(UPSTREAM), "status", "--porcelain", "--untracked-files=no"], text=True)
    if rev != REVISION or dirty:
        raise RuntimeError("Organizer checkout must be clean at pinned revision " + REVISION)
    return rev


def formation():
    verify()
    path = UPSTREAM / "drone_deployment_infra/swarm_ops"
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
    return importlib.import_module("swarm_formation")


def to_internal(position, tag_height=1.22):
    x, y, z = position
    return (y, tag_height - z, -x)


def from_internal(position, tag_height=1.22):
    x, y, z = position
    return (-z, x, tag_height - y)


def yaw_from_internal(psi_deg):
    return (math.pi - math.radians(psi_deg) + math.pi) % (2 * math.pi) - math.pi


def rc_for_pair(module, states, decision, tag_height=1.22):
    if decision.land or decision.targets is None:
        return [(0, 0, 0, 0)] * 2
    import numpy as np

    positions = [np.asarray(to_internal(s.position, tag_height)) for s in states]
    result = []
    for i, s in enumerate(states):
        psi = (180 - math.degrees(s.yaw) + 180) % 360 - 180
        rc, _, _ = module.control(positions[i], psi,
                                  np.asarray(to_internal(decision.targets[i], tag_height)),
                                  [(positions[1 - i], 0.0)], cap=RC_XY_CAP)
        result.append(rc)
    return result
