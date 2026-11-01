"""Two stateful dancer policies over measured room-relative motion.

Optional offboard Ollama phrase agents; no image-based partner recognition. Each
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
TARGET_SPEED = 0.80  # maximum target slew; each style uses its own lower/equal limit
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
    target_speed: float


STYLES = (
    Style("Ari", "Classical Ballet", ("adagio", "arabesque", "port_de_bras"), 10.0, (0.1, 0.7, 0.3), 0.32),
    Style("Sol", "Krump", ("stomp", "jab", "chest_pop"), 12.0, (0.3, 0.1, 0.8), 0.80),
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
    response_offset: tuple = (0.0, 0.0, 0.0)
    hold: bool = False
    partner_speed: float = 0.0
    tempo: float = 1.0
    echo_delay: float = 1.2
    accent_phase: float = 0.0
    stable_motion: str = "still"
    candidate_motion: str = "still"
    candidate_since: float = 0.0
    cue: str = ""
    llm_until: float = 0.0
    llm_tempo: float = 1.0
    decision_source: str = "rules"


class Choreography:
    def __init__(self, homes, seed, events, planner=None):
        self.homes, self.events = homes, events
        self.planner = planner
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
                            "trigger": d.cue or "phrase boundary",
                            "decision_source": d.decision_source,
                            "tempo": round(d.tempo, 3), "echo_delay_s": round(d.echo_delay, 3),
                            "scores": {k: round(v, 3) for k, v in d.scores.items()}})

    def _observe(self, i, t, dt):
        """Debounce measured changes; continuously adapt without resetting clocks."""
        d = self.dancers[i]
        d.observed, speed = self.motion(1 - i, t)
        alpha = 1 - math.exp(-dt / 0.6)
        d.partner_speed += alpha * (speed - d.partner_speed)
        energy = min(1.0, d.partner_speed / 0.12)
        d.tempo = 0.90 + 0.20 * energy
        d.echo_delay = 1.60 - 0.80 * energy
        d.accent_phase += dt * d.tempo * d.llm_tempo
        if d.observed != d.candidate_motion:
            d.candidate_motion, d.candidate_since = d.observed, t
        dwell = 0.60 if d.candidate_motion == "still" else 0.30
        if d.candidate_motion != d.stable_motion and t - d.candidate_since >= dwell:
            previous, d.stable_motion = d.stable_motion, d.candidate_motion
            d.cue = ("partner paused" if d.stable_motion == "still" else
                     f"partner changed from {previous} to {d.stable_motion}")

    def _lead(self, i, t, wall_t, reason, choice=None):
        d = self.dancers[i]
        continuing = d.mode == "lead" and bool(d.gesture)
        d.observed, _ = self.motion(1 - i, t)
        # Novelty competes with a style-specific response to the partner's motion.
        preferred = ({"rise": "arabesque", "dip": "adagio", "side": "port_de_bras", "still": "adagio"} if i == 0 else
                     {"rise": "stomp", "dip": "chest_pop", "side": "jab", "still": "jab"}).get(d.observed)
        d.scores = {g: 1.0 / (1 + d.visits.get(g, 0)) + (0.5 if g == preferred else 0)
                   + d.rng.uniform(0, 0.15) - (0.5 if g == d.gesture else 0)
                   for g in d.profile.gestures}
        d.gesture = choice.action if choice else max(d.scores, key=d.scores.get)
        d.decision_source = "ollama" if choice else "rules"
        if choice is None:
            d.llm_until, d.llm_tempo = 0.0, 1.0
        d.mode, d.since = "lead", t
        if not continuing:
            d.phrase = 0.0
        d.visits[d.gesture] = d.visits.get(d.gesture, 0) + 1
        d.reason = reason
        self._record(i, t, wall_t)

    def _respond(self, i, t, wall_t, *, initial=False, choice=None):
        d = self.dancers[i]
        d.observed, speed = self.motion(1 - i, t)
        enough_history = t - self.history[0][0] >= 1.2
        cues = {"mirror": 0.6 if speed > 0.018 else 0.0,
                "echo": 0.5 if enough_history else -2.0,
                "reply": (0.8 if speed < 0.035 else 0.15) if enough_history else -2.0}
        if d.cue == "partner paused" and enough_history:
            cues["reply"] += 1.2
        elif d.cue:
            cues["mirror"] += 0.5
        d.scores = {}
        for mode, bias in zip(MOVES[1:], d.profile.response_bias):
            d.scores[mode] = bias + cues[mode] + 0.8 / (1 + d.visits.get(mode, 0)) \
                - (0.8 if mode == d.mode else 0) + d.rng.uniform(0, 0.1)
        d.mode = choice.action if choice else ("mirror" if initial else max(d.scores, key=d.scores.get))
        d.decision_source = "ollama" if choice else "rules"
        if choice is None:
            d.llm_until, d.llm_tempo = 0.0, 1.0
        d.gesture = self.dancers[1 - i].gesture
        d.since = t
        d.visits[d.mode] = d.visits.get(d.mode, 0) + 1
        # A reply replays a recorded partner motif in the responder's own style.
        # Copying the buffer here means this phrase cannot accidentally read future poses.
        d.reply = [(sample_t - max(self.history[0][0], t - 3), offsets[1 - i])
                   for sample_t, offsets in self.history if sample_t >= t - 3]
        d.reason = {"mirror": "reflect partner's measured motion across the two lanes",
                    "echo": "follow partner's measured motion with a speed-adapted delay",
                    "reply": "answer a recorded partner motif in my own style"}[d.mode]
        if choice:
            d.reason = choice.reason
        self._record(i, t, wall_t)

    def _model_step(self, t, wall_t):
        if self.planner is None:
            return
        import time
        from .ollama_agent import TEMPOS
        for result in self.planner.drain():
            i, context = result["drone"], result["context"]
            d = self.dancers[i]
            role = "leader" if i == self.leader else "follower"
            rejection = result.get("error")
            age = t - context["dance_t"]
            if not rejection and (age < 0 or age > self.planner.max_age or
                                  time.monotonic() - result["issued_wall"] > self.planner.max_age):
                rejection = "stale observations"
            if not rejection and (context["role"] != role or context["leader_since"] != self.leader_since):
                rejection = "leadership changed since request"
            if not rejection and d.mode == "reply" and t - d.since < 4.0:
                rejection = "preserve captured reply until complete"
            event = {"t": round(wall_t, 3), "dance_t": round(t, 3), "drone": i,
                     "model_result": "rejected" if rejection else "applied",
                     "model": self.planner.model, "observation_dance_t": context["dance_t"],
                     "latency_s": result["latency_s"], "error": rejection,
                     "inference": result.get("stats")}
            if not rejection:
                choice = result["choice"]
                if role == "leader":
                    self._lead(i, t, wall_t, choice.reason, choice=choice)
                else:
                    self._respond(i, t, wall_t, choice=choice)
                d.llm_until, d.llm_tempo = t + 4.5, TEMPOS[choice.tempo]
                self.planner.remember(i, choice)
                event["choice"] = choice.__dict__
            self.events.append(event)
        for i, d in enumerate(self.dancers):
            recent = [(round(at, 2), tuple(tuple(round(v, 3) for v in p) for p in offsets))
                      for at, offsets in list(self.history)[-41::20]]
            context = {"dance_t": round(t, 3), "role": "leader" if i == self.leader else "follower",
                       "your_drone_index": i,
                       "leader_since": self.leader_since, "your_mode": d.mode, "your_gesture": d.gesture,
                       "partner_style": self.dancers[1-i].profile.style,
                       "partner_motion": d.observed, "partner_speed_mps": round(d.partner_speed, 3),
                       "partner_mode": self.dancers[1-i].mode, "pending_cue": d.cue,
                       "measured_history": recent}
            self.planner.submit(i, context)

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
        # Rotate the recorded motif into an answering phrase, then apply the same
        # style interpretation used for mirror/echo. No style-neutral following.
        return bounded((0.9 * z + 0.6 * x, -y, -0.65 * x))

    def _interpret_response(self, d, offset, dt):
        x, y, z = offset
        if d.profile.style == "Classical Ballet":
            desired = bounded((1.40 * x, 0.85 * y, 0.24 + 0.50 * z))
            alpha = 1 - math.exp(-dt / 0.65)
            d.response_offset = tuple(old + alpha * (new - old)
                                      for old, new in zip(d.response_offset, desired))
        else:
            # Strong horizontal accents and a low center; holding is enforced by
            # the actual RC adapter as well as the target generator.
            d.response_offset = bounded((round(2.00 * x / 0.18) * 0.18,
                                         round(y / 0.12) * 0.12, -0.24 + 0.30 * z))
        return d.response_offset

    def _lead_offset(self, d):
        a = 2 * math.pi * d.phrase / d.profile.period - math.pi / 2
        # Human dance vocabulary translated into whole-drone travel, without
        # flips or yaw spins that would turn the cameras away from the room tags.
        accent = int(d.phrase / 3.0) % 4
        offsets = {
            "adagio": (0.68 * math.sin(a), -0.38 * math.sin(a / 2) ** 2, 0.22 + 0.17 * math.sin(a)),
            "arabesque": (0.64 * math.sin(a), -0.30 * math.sin(a / 2) ** 2, 0.32 + 0.06 * math.cos(a)),
            "port_de_bras": (0.65 * math.sin(a), -0.42 * math.sin(a) ** 2, 0.18 + 0.18 * math.sin(2 * a)),
            "stomp": ((0.64, -0.64, 0.50, -0.50)[accent], (0.12, 0.42, 0.12, 0.42)[accent], -0.38),
            "jab": ((0.70, -0.70, 0.70, -0.70)[accent], (0.40, 0.02, 0.40, 0.02)[accent], -0.20),
            "chest_pop": ((0.62, -0.62, -0.62, 0.62)[accent], 0.32,
                          (-0.08, -0.38, -0.08, -0.38)[accent]),
        }
        x, y, z = offsets[d.gesture]
        return bounded((1.2 * x, y, z))

    def step(self, states, t, wall_t):
        offsets = tuple(tuple(s.position[k] - h[k] for k in range(3)) for s, h in zip(states, self.homes))
        self.history.append((t, offsets))
        dt, self.last_t = max(0.0, min(0.2, t - self.last_t)), t
        if not self.started:
            self.started = True
            self._lead(0, t, wall_t, "invite partner with my own style")
            self._respond(1, t, wall_t, initial=True)
        for i in range(2):
            self._observe(i, t, dt)
            d = self.dancers[i]
            if d.llm_until and t >= d.llm_until:
                if i == self.leader:
                    self._lead(i, t, wall_t, "model phrase expired; resume reactive rules")
                else:
                    self._respond(i, t, wall_t)
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
        elif not lead.llm_until and (t - lead.since >= 7.0 or (lead.cue and t - lead.since >= 5.0)):
            self._lead(self.leader, t, wall_t, lead.cue or "vary my motif using partner motion and my move history")
        self.dancers[self.leader].cue = ""
        follower = 1 - self.leader
        follow = self.dancers[follower]
        # Preserve a captured four-second reply; other responses can change after
        # three seconds when a debounced movement cue arrives. Timeouts prevent stalling.
        dwell = 4.0 if follow.mode == "reply" else 3.0
        if not follow.llm_until and (t - follow.since >= 4.0 or (follow.cue and t - follow.since >= dwell)):
            self._respond(follower, t, wall_t)
            follow.cue = ""
        self._model_step(t, wall_t)
        result = []
        for i, d in enumerate(self.dancers):
            partner = self.sample(t, 1 - i)
            d.observed, _ = self.motion(1 - i, t)
            # A two-second burst/stop articulation persists in every Krump mode,
            # including mirrors. Ballet keeps a continuous sustained line.
            d.hold = d.profile.style == "Krump" and d.accent_phase % 2.0 >= 1.35
            if d.mode == "lead":
                # Slow an invitation when the partner lags instead of blindly keeping time.
                mismatch = math.dist(reflect(offsets[i]), partner)
                d.phrase_rate = (0.70 if mismatch > 0.30 else 1.0) * d.tempo * d.llm_tempo
                d.phrase += dt * d.phrase_rate
                offset = self._lead_offset(d)
            elif d.mode == "mirror":
                offset = self._interpret_response(d, reflect(partner), dt)
            elif d.mode == "echo":
                offset = self._interpret_response(d, reflect(self.sample(t - d.echo_delay, 1 - i)), dt)
            else:
                offset = self._interpret_response(d, self._reply_offset(d, t), dt)
            result.append(tuple(h + v for h, v in zip(self.homes[i], lane_offset(offset, i))))
        return tuple(result)

    def snapshot(self):
        return [{"name": d.profile.name, "style": d.profile.style, "mode": d.mode,
                 "gesture": d.gesture, "reason": d.reason, "observed_partner_motion": d.observed,
                 "phrase_rate": d.phrase_rate, "target_speed_mps": d.profile.target_speed,
                 "tempo": d.tempo, "echo_delay_s": d.echo_delay,
                 "partner_speed_mps": d.partner_speed, "stable_partner_motion": d.stable_motion,
                 "pending_cue": d.cue,
                 "decision_source": d.decision_source, "model_phrase_until": d.llm_until,
                 "model_tempo_multiplier": d.llm_tempo,
                 "hold": d.hold} for d in self.dancers]
