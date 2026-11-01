"""Two stateful dancer policies over measured room-relative motion.

No LFM, shared sinusoidal dance script or image-based partner recognition. Each
dancer has a style, motion memory and utility scores. A leadership lease avoids
two followers waiting on each other; handoffs require measured engagement.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
import random

MOVES = ("lead", "mirror", "echo", "reply")
LIMITS = (0.70, 0.45, 0.42)
TARGET_SPEED = 0.30  # m/s, a target slew limit; actual RC/physics motion is logged
RC_XY_CAP = 35


def bounded(offset):
    return tuple(max(-limit, min(limit, value)) for value, limit in zip(offset, LIMITS))


def reflect(offset):
    """Reflection across the room's Y=0 plane, in pad-relative coordinates."""
    return (offset[0], -offset[1], offset[2])


def lane_offset(offset, drone):
    """Use the room width outward; keep inward targets >= 1.40 m apart."""
    x, y, z = bounded(offset)
    return (x, min(y, 0.10) if drone == 0 else max(y, -0.10), z)


@dataclass(frozen=True)
class Style:
    name: str
    style: str
    gestures: tuple[str, ...]
    period: float
    response_bias: tuple[float, float, float]  # mirror, echo, reply


STYLES = (
    Style("Ari", "Hopak", ("hop", "squat", "sweep"), 10.0, (0.1, 0.6, 0.4)),
    Style("Sol", "Country", ("two_step", "shuffle", "box_step"), 10.0, (0.6, 0.1, 0.5)),
)


@dataclass
class Dancer:
    profile: Style
    rng: random.Random
    mode: str = "lead"
    gesture: str = ""
    since: float = 0.0
    phrase: float = 0.0
    phrase_rate: float = 1.0
    visits: dict = field(default_factory=dict)
    reason: str = "waiting for partner observations"
    scores: dict = field(default_factory=dict)
    reply: list = field(default_factory=list)
    observed: str = "still"


class Choreography:
    def __init__(self, homes, seed, events):
        self.homes, self.events = homes, events
        self.dancers = [Dancer(p, random.Random(seed + i * 1009)) for i, p in enumerate(STYLES)]
        self.dancers[1].mode = "mirror"
        self.history = deque(maxlen=320)  # 16 s at the 20 Hz policy rate
        self.leader, self.leader_since = 0, 0.0
        self.started, self.last_t = False, 0.0
        self.engaged_at = None

    def sample(self, at, drone):
        """Interpolate measured positions, never another dancer's target."""
        if not self.history:
            return (0.0, 0.0, 0.0)
        previous = self.history[0]
        for current in self.history:
            if current[0] >= at:
                span = current[0] - previous[0]
                f = max(0.0, min(1.0, (at - previous[0]) / span)) if span else 0.0
                return tuple(previous[1][drone][k] * (1 - f) + current[1][drone][k] * f for k in range(3))
            previous = current
        return self.history[-1][1][drone]

    def motion(self, drone, t):
        a, b = self.sample(t - 0.8, drone), self.sample(t, drone)
        v = tuple((b[k] - a[k]) / 0.8 for k in range(3))
        speed = math.sqrt(sum(x * x for x in v))
        axis = max(range(3), key=lambda k: abs(v[k]))
        signature = ("forward" if v[0] > 0 else "back", "side", "rise" if v[2] > 0 else "dip")[axis]
        return (signature if speed > 0.012 else "still"), speed

    def _record(self, i, t, wall_t):
        d, p = self.dancers[i], self.dancers[1 - i]
        self.events.append({"t": round(wall_t, 3), "dance_t": round(t, 3), "drone": i,
                            "name": d.profile.name, "style": d.profile.style, "move": d.mode,
                            "gesture": d.gesture, "partner": p.mode, "leader": self.leader,
                            "observed_partner_motion": d.observed, "reason": d.reason,
                            "scores": {k: round(v, 3) for k, v in d.scores.items()}})

    def _lead(self, i, t, wall_t, reason):
        d = self.dancers[i]
        d.observed, _ = self.motion(1 - i, t)
        # Novelty competes with a style-specific response to the partner's motion.
        preferred = ({"rise": "squat", "dip": "hop", "side": "sweep", "still": "hop"} if i == 0 else
                     {"rise": "two_step", "dip": "shuffle", "side": "box_step", "still": "two_step"}).get(d.observed)
        d.scores = {g: 1.0 / (1 + d.visits.get(g, 0)) + (0.5 if g == preferred else 0)
                   + d.rng.uniform(0, 0.15) - (0.5 if g == d.gesture else 0)
                   for g in d.profile.gestures}
        d.gesture = max(d.scores, key=d.scores.get)
        d.mode, d.since, d.phrase = "lead", t, 0.0
        d.visits[d.gesture] = d.visits.get(d.gesture, 0) + 1
        d.reason = reason
        self._record(i, t, wall_t)

    def _respond(self, i, t, wall_t, *, initial=False):
        d = self.dancers[i]
        d.observed, speed = self.motion(1 - i, t)
        enough_history = t - self.history[0][0] >= 1.2
        cues = {"mirror": 0.6 if speed > 0.018 else 0.0,
                "echo": 0.5 if enough_history else -2.0,
                "reply": (0.8 if speed < 0.035 else 0.15) if enough_history else -2.0}
        d.scores = {}
        for mode, bias in zip(MOVES[1:], d.profile.response_bias):
            d.scores[mode] = bias + cues[mode] + 0.8 / (1 + d.visits.get(mode, 0)) \
                - (0.8 if mode == d.mode else 0) + d.rng.uniform(0, 0.1)
        d.mode = "mirror" if initial else max(d.scores, key=d.scores.get)
        d.gesture = self.dancers[1 - i].gesture
        d.since = t
        d.visits[d.mode] = d.visits.get(d.mode, 0) + 1
        # A reply replays a recorded partner motif in the responder's own style.
        # Copying the buffer here means this phrase cannot accidentally read future poses.
        d.reply = [(sample_t - max(self.history[0][0], t - 3), offsets[1 - i])
                   for sample_t, offsets in self.history if sample_t >= t - 3]
        d.reason = {"mirror": "reflect partner's measured motion across the two lanes",
                    "echo": "follow partner's measured motion 1.2 seconds later",
                    "reply": "answer a recorded partner motif in my own style"}[d.mode]
        self._record(i, t, wall_t)

    def _reply_offset(self, d, t):
        if len(d.reply) < 2 or d.reply[-1][0] <= 0:
            return (0.0, 0.0, 0.0)
        at = min(d.reply[-1][0], (t - d.since) * d.reply[-1][0] / 4.0)
        a = d.reply[0]
        offset = a[1]
        for b in d.reply[1:]:
            if b[0] >= at:
                f = max(0.0, min(1.0, (at - a[0]) / max(1e-9, b[0] - a[0])))
                offset = tuple(a[1][k] * (1 - f) + b[1][k] * f for k in range(3))
                break
            a, offset = b, b[1]
        x, y, z = offset
        if d.profile.style == "Hopak":
            # Answer lateral footwork with a broad sweep and vertical hop accent.
            return bounded((1.1 * x, -y, 0.8 * abs(x) - 0.20 + 0.4 * z))
        # Translate a hop into held country steps and a shallow bow. Discrete
        # targets still pass through the mission's continuous slew limiter.
        return bounded((round(-x / 0.16) * 0.16, -y, -0.14 - 0.15 * z))

    def _lead_offset(self, d):
        a = 2 * math.pi * d.phrase / d.profile.period
        # Human dance vocabulary translated into whole-drone travel, without
        # flips or yaw spins that would turn the cameras away from the room tags.
        outward = -1 if d.profile.style == "Hopak" else 1
        corner = int(d.phrase / 2.5) % 4
        offsets = {
            "hop": (0.65 * math.sin(a), outward * 0.32 * math.sin(a / 2) ** 2, 0.42 * math.cos(a)),
            "squat": (0.65 if math.sin(a) >= 0 else -0.65, outward * 0.25, -0.40 if math.cos(a) >= 0 else 0.38),
            "sweep": (0.70 * math.cos(a), outward * (0.20 + 0.20 * math.sin(a)), 0.32 * math.sin(a)),
            "two_step": (0.68 if math.sin(a) >= 0 else -0.68, outward * 0.22, -0.12),
            "shuffle": (0.65 * math.cos(a), outward * (0.22 + 0.20 * math.sin(a)), -0.25 * math.sin(a) ** 2),
            "box_step": ((0.68, 0.68, -0.68, -0.68)[corner],
                         outward * (0.0, 0.42, 0.42, 0.0)[corner], -0.16 if corner == 3 else 0.06),
        }
        return bounded(offsets[d.gesture])

    def step(self, states, t, wall_t):
        offsets = tuple(tuple(s.position[k] - h[k] for k in range(3)) for s, h in zip(states, self.homes))
        self.history.append((t, offsets))
        dt, self.last_t = max(0.0, min(0.2, t - self.last_t)), t
        if not self.started:
            self.started = True
            self._lead(0, t, wall_t, "invite partner with my own style")
            self._respond(1, t, wall_t, initial=True)
        follower = 1 - self.leader
        lead = self.dancers[self.leader]
        _, speed = self.motion(follower, t)
        self.engaged_at = (t if self.engaged_at is None else self.engaged_at) if speed > 0.012 else None
        # A stationary partner does not trigger a role swap.
        if t - self.leader_since >= 7 and self.engaged_at is not None and t - self.engaged_at >= 0.8:
            previous = self.leader
            self.leader, self.leader_since, self.engaged_at = follower, t, None
            self._lead(follower, t, wall_t, "take the lead after sustained measured engagement")
            self._respond(previous, t, wall_t)
            self.events.append({"t": round(wall_t, 3), "dance_t": round(t, 3), "handoff": [previous, follower],
                                "reason": "partner moving for at least 0.8 s; leadership lease released"})
        elif t - lead.since >= 7.0:
            self._lead(self.leader, t, wall_t, "vary my motif using partner motion and my move history")
        follower = 1 - self.leader
        follow = self.dancers[follower]
        if t - follow.since >= 4.0:
            self._respond(follower, t, wall_t)
        result = []
        for i, d in enumerate(self.dancers):
            partner = self.sample(t, 1 - i)
            d.observed, _ = self.motion(1 - i, t)
            if d.mode == "lead":
                # Slow an invitation when the partner lags instead of blindly keeping time.
                mismatch = math.dist(reflect(offsets[i]), partner)
                d.phrase_rate = 0.70 if mismatch > 0.30 else 1.0
                d.phrase += dt * d.phrase_rate
                offset = self._lead_offset(d)
            elif d.mode == "mirror":
                offset = reflect(partner)
            elif d.mode == "echo":
                offset = reflect(self.sample(t - 1.2, 1 - i))
            else:
                offset = self._reply_offset(d, t)
            result.append(tuple(h + v for h, v in zip(self.homes[i], lane_offset(offset, i))))
        return tuple(result)

    def snapshot(self):
        return [{"name": d.profile.name, "style": d.profile.style, "mode": d.mode,
                 "gesture": d.gesture, "reason": d.reason, "observed_partner_motion": d.observed,
                 "phrase_rate": d.phrase_rate} for d in self.dancers]
