"""Original organizer scene/assets/controller, MuJoCo rigid bodies, Apple USD rendering.

User-approved local rendering port; not NVIDIA Isaac Sim or an RTX/PhysX result.
"""
from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import mujoco
import torch
from pxr import Gf, Usd

from .metal_scene import COLORS, KIT, create_scene, load_file, original_function
from .mission import HOMES, Mission, State
from .upstream import ROOT, UPSTREAM, formation, rc_for_pair


def rigid_bodies_from_urdf(urdf, physics_dt):
    # Preserve the original base link's mass, full inertia and collision box. The
    # camera sphere fits inside that box; its negligible fixed-link mass is omitted.
    robot = ET.parse(urdf).getroot()
    base = robot.find("link[@name='base_link']")
    mass = float(base.find("inertial/mass").attrib["value"])
    inertia = base.find("inertial/inertia").attrib
    size = [float(v) / 2 for v in base.find("collision/geometry/box").attrib["size"].split()]
    root = ET.Element("mujoco", model="original_tello_duet")
    ET.SubElement(root, "option", timestep=str(physics_dt), gravity="0 0 -9.81", integrator="RK4")
    world = ET.SubElement(root, "worldbody")
    ET.SubElement(world, "geom", name="floor", type="plane", size="10 10 0.1")
    for i, home in enumerate(HOMES):
        yaw = math.atan2(-home[1], -home[0])
        body = ET.SubElement(world, "body", name=f"drone_{i}", pos=" ".join(str(v) for v in home),
                             quat=f"{math.cos(yaw / 2)} 0 0 {math.sin(yaw / 2)}")
        ET.SubElement(body, "freejoint", name=f"joint_{i}")
        ET.SubElement(body, "inertial", pos="0 0 0", mass=str(mass),
                      fullinertia=" ".join(inertia[k] for k in ("ixx", "iyy", "izz", "ixy", "ixz", "iyz")))
        ET.SubElement(body, "geom", type="box", size=" ".join(str(v) for v in size))
    model = mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    ids = [model.body(f"drone_{i}").id for i in range(2)]
    return model, data, ids, mass, [float(inertia[k]) for k in ("ixx", "iyy", "izz")]


def simulate(output, *, seed=7, fps=24, dance_seconds=28):
    start_wall = time.monotonic()
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    dynamics = load_file("organizer_port_dynamics", KIT / "control/tello_dynamics.py")
    rc_module = load_file("organizer_port_rc", KIT / "control/rc_action.py")
    sensing = load_file("organizer_port_sensing", KIT / "tags/sensing.py")
    scene, transforms = create_scene(output, fps=fps)
    module = formation()
    from action_space_kit.tags.room_map import load_room_tags

    tags = list(load_room_tags(1.22).values())
    tag_pos = torch.tensor(np.asarray([t.pos for t in tags]), dtype=torch.float32)
    tag_normal = torch.tensor(np.asarray([t.normal for t in tags]), dtype=torch.float32)
    tag_size = torch.tensor([t.size_m for t in tags], dtype=torch.float32)
    sensor = sensing.TagSensorCfg(video_delay_steps=3)
    # Deterministic nominal visualization: geometric visibility and a 150 ms video
    # delay remain enabled. Pixel noise and random missed detections are disabled.
    mission = Mission(seed, dance_seconds)
    physics_dt, command_steps = 0.002, 25
    cfg = dynamics.TelloDynamicsCfg(domain_randomization=False)
    fit = rc_module.load_motion_fit()
    rc_module.apply_motion_fit(cfg, fit, 0.05)
    rc = rc_module.RcAction(rc_module.RcActionCfg(rc_limit=(100, 100, 100, 100), use_envelope=False),
                             2, cfg.max_speed_xy, cfg.max_speed_z, cfg.max_yaw_rate, "cpu")
    rc.randomize(torch.arange(2), enabled=False)
    frames, rows = [], []
    min_gap, max_tilt, landed_at = math.inf, 0.0, None
    contacts = False
    with torch.inference_mode():
        urdf = str(UPSTREAM / "simulation_infra/assets/tello/tello.urdf")
        model, data, bodies, mass, inertia = rigid_bodies_from_urdf(urdf, physics_dt)
        controller = dynamics.TelloCascadeController(cfg, 2, mass, torch.diag(torch.tensor(inertia)), physics_dt, "cpu")
        command = torch.zeros((2, 4))
        history = deque(maxlen=4)
        last_fix = [None, None]
        last_fix_t = [-math.inf, -math.inf]
        decision = None
        commands = [(0, 0, 0, 0)] * 2
        tick = 0
        while tick < 60 / physics_dt:
            t = tick * physics_dt
            positions, quats, vworld, wbody, vbody = [], [], [], [], []
            for body in bodies:
                p, q = data.xpos[body].copy(), data.xquat[body].copy()
                rot = data.xmat[body].reshape(3, 3)
                spatial = np.zeros(6)
                mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_BODY, body, spatial, 0)
                omega, v = spatial[:3], spatial[3:]
                positions.append(p.tolist())
                quats.append(q.tolist())
                vworld.append(v.tolist())
                vbody.append(rot.T @ v)
                wbody.append(rot.T @ omega)
            p_t = torch.tensor(positions, dtype=torch.float32)
            q_t = torch.tensor(quats, dtype=torch.float32)
            v_t = torch.tensor(vworld, dtype=torch.float32)
            wb_t = torch.tensor(np.asarray(wbody), dtype=torch.float32)
            vb_t = torch.tensor(np.asarray(vbody), dtype=torch.float32)
            gap = float(torch.linalg.norm(p_t[0] - p_t[1]))
            min_gap = min(min_gap, gap)
            if not bool(torch.isfinite(p_t).all()) or gap < 1.05:
                raise RuntimeError("Rigid-body trajectory failed pair separation/finite-state check")
            if any(model.geom_bodyid[c.geom1] in bodies and model.geom_bodyid[c.geom2] in bodies
                   for c in data.contact):
                contacts = True
                raise RuntimeError("Drone-to-drone contact")
            if tick % command_steps == 0:
                rotation = dynamics._quat_to_rot(q_t)
                camera_rotation = sensing.camera_axes(rotation, sensor.camera_pitch)
                offset = torch.einsum("nij,j->ni", rotation, torch.tensor(sensor.camera_offset))
                fix, visible, _ = sensing.sighting(sensor, p_t + offset, camera_rotation,
                    tag_pos, tag_normal, tag_size, noise=False)
                history.append((fix - offset, visible, t))
                if len(history) == 4:
                    delayed, found, captured_t = history[0]
                    for i in range(2):
                        if bool(found[i]):
                            last_fix[i] = tuple(delayed[i].tolist())
                            last_fix_t[i] = captured_t
                states = [State(last_fix[i], math.atan2(float(rotation[i, 1, 0]), float(rotation[i, 0, 0])),
                                t - last_fix_t[i], velocity=tuple(vworld[i])) for i in range(2)]
                if landed_at is None:
                    decision = mission.step(states, t)
                    commands = rc_for_pair(module, states, decision)
                    if decision.land:
                        landed_at = t
                        print(f"[metal] land at {t:.2f}s: {decision.reason}", flush=True)
                command = rc.command(torch.tensor(commands, dtype=torch.float32))
                if landed_at is not None:
                    command[:] = 0
                    command[:, 2] = -0.4 / cfg.max_speed_z
                controller.set_command(command)
                rows.append({"t": t, "phase": mission.phase, "moves": list(mission.moves),
                             "reason": mission.reason, "rc": commands, "positions": positions,
                             "published_positions": last_fix.copy(),
                             "fix_ages": [None if not math.isfinite(s.fix_age) else s.fix_age for s in states],
                             "targets": decision.targets if decision else None})
            # Capture at evenly spaced USD frame times; animation is interpolated from
            # actual rigid-body poses, never from target positions.
            if t + physics_dt / 2 >= len(frames) / fps:
                frame = len(frames)
                for i, (translation, orientation) in enumerate(transforms):
                    translation.Set(Gf.Vec3d(*positions[i]), Usd.TimeCode(frame))
                    orientation.Set(Gf.Quatf(*[float(v) for v in quats[i]]), Usd.TimeCode(frame))
                frames.append({"t": t, "row": len(rows) - 1, "positions": positions})
            force, torque = controller.compute(v_t, q_t, wb_t, vb_t)
            data.xfrc_applied[:] = 0
            for i, body in enumerate(bodies):
                if landed_at is not None and positions[i][2] < 0.032:
                    continue
                rotation = data.xmat[body].reshape(3, 3)
                data.xfrc_applied[body, :3] = rotation @ force[i].numpy()
                data.xfrc_applied[body, 3:] = rotation @ torque[i].numpy()
                tilt = math.degrees(math.acos(max(-1, min(1, rotation[2, 2]))))
                max_tilt = max(max_tilt, tilt)
            mujoco.mj_step(model, data)
            tick += 1
            if tick % 2500 == 0:
                print(f"[metal] simulated {t:.1f}s; phase={mission.phase}; gap={gap:.2f}m", flush=True)
            if landed_at is not None and all(p[2] < 0.04 for p in positions) and t - landed_at > 4:
                break
        if mission.reason != "duet complete":
            raise RuntimeError("Duet aborted: " + mission.reason)
        if not all(p[2] < 0.04 for p in positions):
            raise RuntimeError("Both landings not completed")
        scene.SetStartTimeCode(0)
        scene.SetEndTimeCode(len(frames) - 1)
        scene.GetRootLayer().Save()
        report = {"renderer": "Apple Hydra Metal / usdrecord", "physics": "MuJoCo CPU, not Isaac PhysX",
                  "controller": "original TelloCascadeController + RcAction + swarm_formation.control",
                  "sensing": "original sighting() geometric model, no random noise, 150 ms delay",
                  "velocity_observation": "ideal simulator velocity; not camera-estimated",
                  "start": "already hovering; takeoff excluded", "physical_flight_tested": False,
                  "fps": fps, "frame_count": len(frames), "duration_s": len(frames) / fps,
                  "dance_seconds": dance_seconds, "seed": seed, "min_separation_m": min_gap,
                  "max_tilt_deg": max_tilt, "drone_contacts": contacts, "completed": True,
                  "wall_seconds_simulating": time.monotonic() - start_wall,
                  "source_sha256": {str(p.relative_to(UPSTREAM)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in [KIT / "control/tello_dynamics.py", KIT / "control/rc_action.py", KIT / "tags/sensing.py",
                                KIT / "control/tello_motion_fit.yaml",
                                UPSTREAM / "drone_deployment_infra/swarm_ops/swarm_formation.py",
                                UPSTREAM / "drone_deployment_infra/config/map.yaml",
                                UPSTREAM / "drone_deployment_infra/config/tags.yaml"]},
                  "events": mission.events, "rows": rows, "frames": frames}
        (output / "simulation.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        return report


def encode(output, report, video):
    # Keep the original recorder's panel drawing; replace its RL reward label with
    # a measured separation metric (this mission does not compute a race reward).
    overlay_path = UPSTREAM / "simulation_infra/scripts/record_room.py"
    import ast
    tree = ast.parse(overlay_path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "overlay")
    source = ast.get_source_segment(overlay_path.read_text(), node)
    source = source.replace("team return {rec['ret']:+8.0f}", "min gap {rec['gap']:.2f} m")
    namespace = {"cv2": cv2}
    exec(compile(source, str(overlay_path), "exec"), namespace)
    overlay = namespace["overlay"]
    colors = [tuple(int(255 * c) for c in reversed(rgb)) for rgb in COLORS]
    frames = output / "frames"
    for i, frame in enumerate(report["frames"]):
        path = frames / f"frame_{i}.png"
        if not path.is_file():
            raise RuntimeError("Missing rendered frame: " + str(path))
        row = report["rows"][frame["row"]]
        rec = {"head": "DUET | Action Space scene + Tello model | Apple Metal", "t": frame["t"], "gap": report["min_separation_m"],
               "drones": [{"pad": k, "phase": row["phase"] + ": " + row["moves"][k],
                           "lost": bool((row["fix_ages"][k] or 0) > 0.35) and row["phase"] != "land",
                           "rc": row["rc"][k], "fix_age": row["fix_ages"][k] or 0}
                          for k in range(2)]}
        if row["phase"] == "land":
            for k in range(2):
                rec["drones"][k]["phase"] = "LANDED on spot" if frame["positions"][k][2] < 0.04 else "LANDING"
        overlay(str(path), rec, colors, None)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(report["fps"]),
                    "-i", str(frames / "frame_%d.png"), "-c:v", "libx264", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-f", "null", "-"], check=True)
    print("[metal] MP4:", video, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/metal-duet")
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--dance-seconds", type=float, default=28)
    parser.add_argument("--simulate-only", action="store_true")
    parser.add_argument("--render-only", action="store_true")
    parser.add_argument("--encode-only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.fps <= 60:
        parser.error("--fps must be between 1 and 60")
    output = args.output_dir.resolve()
    if args.render_only or args.encode_only:
        report = json.loads((output / "simulation.json").read_text())
    else:
        report = simulate(output, seed=args.seed, fps=args.fps, dance_seconds=args.dance_seconds)
    if args.simulate_only:
        return
    frames = output / "frames"
    frames.mkdir(exist_ok=True)
    if not args.encode_only:
        cmd = ["/usr/bin/usdrecord", "--renderer", "Metal", "--camera", "/World/RecordCam",
               "--imageWidth", "1280", "--frames", f"0:{report['frame_count'] - 1}",
               str(output / "duet.usda"), str(frames / "frame_####.png")]
        print("[metal] rendering", report["frame_count"], "frames", flush=True)
        with (output / "render.log").open("w") as log:
            subprocess.run(cmd, check=True, stdout=log, stderr=subprocess.STDOUT)
    encode(output, report, output / "drone-duet.mp4")


if __name__ == "__main__":
    main()
