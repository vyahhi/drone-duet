"""Hooks for the ORIGINAL organizers' record_room.py, not a new renderer."""
from __future__ import annotations

import json
from pathlib import Path

from .mission import HOMES, Mission, State
from .upstream import REVISION, formation, rc_for_pair


def configure(cfg):
    import copy
    import torch
    from action_space_kit.tasks.direct.tello_room.tello_room_env import TelloRoomEnv

    original = cfg.possible_agents[0]
    obs, act = cfg.observation_spaces[original], cfg.action_spaces[original]
    cfg.num_drones = cfg.spot_count = 2
    cfg.possible_agents = ["drone_0", "drone_1"]
    cfg.observation_spaces = {a: copy.deepcopy(obs) for a in cfg.possible_agents}
    cfg.action_spaces = {a: copy.deepcopy(act) for a in cfg.possible_agents}
    cfg.spot_distance, cfg.spot_spacing = 2.5, 1.6
    cfg.random_assignment = False
    cfg.spawn_height = (1.22, 1.22)
    cfg.start_on_floor = False
    cfg.spawn_yaw_noise = cfg.spawn_search_prob = 0.0
    cfg.episode_length_s = 61.0
    # Exact two marked-pad starts; everything after reset uses original PhysX dynamics.
    def starts(env, n):
        return torch.tensor([h[:2] for h in HOMES], device=env.device).expand(n, -1, -1).clone()
    TelloRoomEnv._sample_starts = starts


class DuetPilot:
    def __init__(self, u, seed):
        self.u, self.module = u, formation()
        self.mission = Mission(seed)
        self.rows = []
        self.decision = None

    def act(self, obs):
        import numpy as np
        u = self.u
        states = [State(
            position=tuple(u.pub_pos[0, i].cpu().tolist()) if bool(u.acquired[0, i]) else None,
            yaw=float(u.pub_yaw[0, i]), fix_age=float(u.fix_age[0, i]),
            velocity=tuple(u.kf.v[0, i].cpu().tolist()),
        ) for i in range(2)]
        t = len(self.rows) * u.step_dt
        d = self.decision = self.mission.step(states, t)
        rc = rc_for_pair(self.module, states, d)
        if d.land:
            # Real SDK land is unconditional. Route the mission's fail-safe landing into
            # the upstream firmware descent; its RL landing-accuracy gate is for racing.
            u.landing[:] = True
        actions = [[*(v / 100 for v in row), 1.0 if d.land else -1.0] for row in rc]
        self.rows.append({"t": t, "phase": d.phase, "moves": list(self.mission.moves),
                          "reason": d.reason, "targets": d.targets, "rc": rc,
                          "published_positions": [s.position for s in states],
                          "true_positions_diagnostic_only": u._positions()[0].cpu().tolist()})
        return np.asarray(actions, dtype=np.float32).reshape(1, 10)

    def annotate(self, rec):
        for i, row in enumerate(rec["drones"]):
            row["phase"] = f"{self.mission.phase}: {self.mission.moves[i]}"

    def save(self, path):
        import math
        payload = {"organizer_repository": "https://github.com/jaromero3rd/Action_Space",
                   "organizer_revision": REVISION, "renderer": "original record_room.py / Isaac Kit viewport",
                   "physics": "original TelloRoomEnv / TelloCascadeController / PhysX",
                   "control": "original swarm_formation.control + new bounded duet mission",
                   "start": "already hovering over two pads (takeoff excluded from this clip)",
                   "same_physics_environment": True, "physical_flight_tested": False,
                   "final_phase": self.mission.phase, "reason": self.mission.reason,
                   "min_measured_horizontal_gap_m": self.mission.min_measured_gap
                   if math.isfinite(self.mission.min_measured_gap) else None,
                   "events": self.mission.events, "frames": self.rows}
        Path(path).write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
