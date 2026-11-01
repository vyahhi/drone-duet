"""Bounded, partner-responsive choreography. No networking or rendering here."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

Vec = tuple[float, float, float]
HOMES: tuple[Vec, Vec] = ((2.5, -0.8, 1.22), (2.5, 0.8, 1.22))
MOVES = ("mirror", "canon", "breath", "bow")


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
        self.rng = random.Random(seed)
        self.dance_seconds = dance_seconds
        self.phase, self.reason = "acquire", ""
        self.phase_at = self.last_t = 0.0
        self.dance_t = 0.0
        self.stable_at = self.paused_at = None
        self.moves = ["mirror", "canon"]
        self.next_choice = [0.0, 4.0]
        self.targets = list(HOMES)
        self.events = []
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
        raw = self._dance_targets(t, positions) if self.phase == "dance" else HOMES
        # Smooth phrase changes, including the return to home. At most 0.1 m/s.
        for i, target in enumerate(raw):
            delta = tuple(target[k] - self.targets[i][k] for k in range(3))
            scale = min(1.0, 0.1 * dt / max(1e-12, math.dist(target, self.targets[i])))
            self.targets[i] = tuple(self.targets[i][k] + scale * delta[k] for k in range(3))
        return Decision(self.phase, tuple(self.targets))

    def _dance_targets(self, t, positions):
        for i in range(2):
            if self.dance_t >= self.next_choice[i]:
                partner = self.moves[1 - i]
                choices = [m for m in MOVES if m != self.moves[i]]
                # Each dancer responds to the partner independently, on staggered phrases.
                reply = {"mirror": "canon", "canon": "breath", "breath": "bow", "bow": "mirror"}[partner]
                weights = [3 if m == reply else 1 for m in choices]
                self.moves[i] = self.rng.choices(choices, weights=weights)[0]
                self.next_choice[i] += 8
                self.events.append({"t": round(t, 3), "drone": i, "move": self.moves[i], "partner": partner})
        result = []
        for i, home in enumerate(HOMES):
            move = self.moves[i]
            phase = 2 * math.pi * self.dance_t / 12
            # Canon responds to the partner's measured vertical displacement.
            echo = max(-0.09, min(0.09, positions[1 - i][2] - HOMES[1 - i][2]))
            offsets = {
                "mirror": (0.16 * math.sin(phase), (1 if i else -1) * 0.12 * math.cos(phase), 0.07 * math.sin(phase)),
                "canon": (0.14 * math.sin(phase - math.pi / 2), 0.10 * math.cos(phase), echo),
                "breath": (0.08 * math.sin(phase), (1 if i else -1) * 0.10 * math.sin(phase), 0.09 * math.sin(phase)),
                "bow": (0.16 * math.sin(phase), 0.0, -0.08 * (1 + math.sin(phase)) / 2),
            }[move]
            result.append(tuple(home[k] + offsets[k] for k in range(3)))
        return result
