"""Bounded, partner-responsive choreography. No networking or rendering here."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .choreography import Choreography, MOVES, TARGET_SPEED

Vec = tuple[float, float, float]
HOMES: tuple[Vec, Vec] = ((2.5, -0.8, 1.22), (2.5, 0.8, 1.22))


def distance(a, b):
    return math.dist(a, b)


@dataclass(frozen=True)
class State:
    position: Vec | None
    yaw: float = math.pi  # world heading: +X = 0, +Y = pi/2
    fix_age: float = math.inf
    status_age: float = 0.0
    battery: float = 100.0
    velocity: Vec = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class Decision:
    phase: str
    targets: tuple[Vec, Vec] | None
    land: bool = False
    reason: str = ""


class Mission:
    """Two lanes, fresh measured state required, pair-wide fail/land decisions.

    World frame matches upstream Isaac room: X out of tag 10, Y right, Z up.
    Lane 0 stays at negative Y; lane 1 at positive Y. No path crosses the other.
    """

    def __init__(self, seed=7, dance_seconds=28.0):
        if not 4 <= dance_seconds <= 28:
            raise ValueError("dance_seconds must be between 4 and 28")
        self.dance_seconds = dance_seconds
        self.phase, self.reason = "acquire", ""
        self.phase_at = self.last_t = 0.0
        self.dance_t = 0.0
        self.stable_at = self.paused_at = None
        self.moves = ["lead", "mirror"]
        self.targets = list(HOMES)
        self.events = []
        self.choreography = Choreography(HOMES, seed, self.events)
        self.min_measured_gap = math.inf

    def stop(self, reason):
        self.phase, self.reason = "land", reason
        return Decision("land", None, True, reason)

    def _phase(self, phase, t):
        self.phase, self.phase_at, self.stable_at = phase, t, None
        self.events.append({"t": round(t, 3), "phase": phase})

    def _pause(self, t, reason):
        self.stable_at = None
        if self.paused_at is None:
            self.paused_at = t
        if t - self.paused_at >= 2.0:
            return self.stop(reason + " for 2 s")
        return Decision(self.phase, None, reason=reason)

    def step(self, states, t):
        if len(states) != 2:
            return self.stop("exactly two drones required")
        if not math.isfinite(t) or t < self.last_t:
            return self.stop("invalid mission clock")
        if self.phase == "land":
            return Decision("land", None, True, self.reason)
        dt = min(0.2, t - self.last_t)
        self.last_t = t
        if t >= 60:
            return self.stop("60 s flight limit")
        for s in states:
            scalars = (s.status_age, s.battery, s.yaw, *s.velocity)
            if not all(math.isfinite(v) for v in scalars):
                return self.stop("nonfinite telemetry")
            if s.status_age > 1.0:
                return self.stop("status link stale")
            if s.battery < 20:
                return self.stop("battery below 20%")
            if s.position is not None and not all(math.isfinite(v) for v in s.position):
                return self.stop("nonfinite position")
        fresh = all(s.position is not None and math.isfinite(s.fix_age)
                    and 0 <= s.fix_age <= 0.35 for s in states)
        if not fresh:
            if self.phase == "acquire":
                return self.stop("no shared tag fix within 8 s") if t >= 8 else Decision("acquire", None)
            return self._pause(t, "AprilTag localization stale")
        positions = [s.position for s in states]
        gap = math.hypot(positions[0][0] - positions[1][0], positions[0][1] - positions[1][1])
        self.min_measured_gap = min(self.min_measured_gap, gap)
        if gap < 1.05:
            return self.stop("measured horizontal separation below 1.05 m")
        for i, p in enumerate(positions):
            if not (1.5 <= p[0] <= 3.6 and -1.4 <= p[1] <= 1.4 and 0.6 <= p[2] <= 1.8):
                return self.stop("outside measured flight envelope")
            if (i == 0 and p[1] > -0.25) or (i == 1 and p[1] < 0.25):
                return self.stop("wrong lane; place drones on their marked pads")
        relative = [positions[0][k] - positions[1][k] for k in (0, 1)]
        velocity = [states[0].velocity[k] - states[1].velocity[k] for k in (0, 1)]
        v2 = sum(v * v for v in velocity)
        closest_t = max(0.0, min(0.7, -sum(r * v for r, v in zip(relative, velocity)) / v2)) if v2 else 0.0
        future_gap = math.hypot(*(r + closest_t * v for r, v in zip(relative, velocity)))
        if min(gap, future_gap) < 1.2:
            return self._pause(t, "pair spacing guard")
        self.paused_at = None
        if self.phase == "acquire":
            self.targets = list(positions)
            self._phase("settle", t)
        if self.phase in ("settle", "return"):
            near = all(distance(p, h) < 0.18 for p, h in zip(positions, HOMES))
            self.stable_at = (t if self.stable_at is None else self.stable_at) if near else None
            if self.stable_at is not None and t - self.stable_at >= 1.0:
                if self.phase == "return":
                    return self.stop("duet complete")
                self._phase("dance", t)
            elif t - self.phase_at > (12 if self.phase == "settle" else 8):
                return self.stop(self.phase + " timed out")
        if self.phase == "dance":
            self.dance_t += dt
            if self.dance_t >= self.dance_seconds:
                self._phase("return", t)
        raw = self.choreography.step(states, self.dance_t, t) if self.phase == "dance" else HOMES
        self.moves = [d.mode for d in self.choreography.dancers]
        # Smooth phrase changes, including the return to home.
        for i, target in enumerate(raw):
            delta = tuple(target[k] - self.targets[i][k] for k in range(3))
            scale = min(1.0, TARGET_SPEED * dt / max(1e-12, math.dist(target, self.targets[i])))
            self.targets[i] = tuple(self.targets[i][k] + scale * delta[k] for k in range(3))
        return Decision(self.phase, tuple(self.targets))
