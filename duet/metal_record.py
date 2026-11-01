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
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import mujoco
import torch
from pxr import Gf, Usd

from .metal_scene import COLORS, KIT, create_scene, load_file, visible_tags
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
        # Match the USD landing pads; start resting on their top surfaces.
        ET.SubElement(world, "geom", name=f"pad_{i}", type="cylinder", size="0.3 0.005",
                      pos=f"{home[0]} {home[1]} 0.006")
        yaw = math.atan2(-home[1], -home[0])
        body = ET.SubElement(world, "body", name=f"drone_{i}", pos=f"{home[0]} {home[1]} {size[2] + 0.011}",
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


def takeoff_rc(t, positions, vertical_gain):
    """Local SDK-takeoff approximation: stagger liftoff and taper the climb.

    Uses nominal onboard altitude, like an SDK takeoff, before room localization.
    The original firmware/rotor controller still produces all applied forces.
    """
    commands, armed = [], []
    for i, (position, home) in enumerate(zip(positions, HOMES)):
        active = t >= 1.5 + 0.5 * i
        speed = min(0.30, max(0.0, 1.2 * (home[2] - position[2]))) if active else 0.0
        commands.append((0, 0, round(speed / vertical_gain), 0))
        armed.append(active)
    return commands, armed


def simulate(output, *, seed=7, fps=24, dance_seconds=28, planner=None):
    start_wall = time.monotonic()
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    dynamics = load_file("organizer_port_dynamics", KIT / "control/tello_dynamics.py")
    rc_module = load_file("organizer_port_rc", KIT / "control/rc_action.py")
    sensing = load_file("organizer_port_sensing", KIT / "tags/sensing.py")
    scene, transforms = create_scene(output, fps=fps)
    module = formation()
    from action_space_kit.tags.room_map import load_room_tags

    scene_tags = visible_tags(scene, load_room_tags(1.22))
    tags = list(scene_tags.values())
    tag_pos = torch.tensor(np.asarray([t.pos for t in tags]), dtype=torch.float32)
    tag_normal = torch.tensor(np.asarray([t.normal for t in tags]), dtype=torch.float32)
    tag_size = torch.tensor([t.size_m for t in tags], dtype=torch.float32)
    sensor = sensing.TagSensorCfg(video_delay_steps=3)
    # Deterministic nominal visualization: geometric visibility and a 150 ms video
    # delay remain enabled. Pixel noise and random missed detections are disabled.
    mission = Mission(seed, dance_seconds, planner=planner)
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
    mission_at = None
    lifecycle_events = [{"t": 0.0, "phase": "ground"},
                        {"t": 1.5, "phase": "takeoff", "drone": 0},
                        {"t": 2.0, "phase": "takeoff", "drone": 1}]
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
        armed = [False, False]
        motors_stopped = [False, False]
        phase = "ground"
        tick = 0
        flight_wall = time.monotonic()
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
                if planner:
                    # Live model deadlines must see real flight time, rather than
                    # a 45-second episode compressed into a few wall seconds.
                    time.sleep(max(0, flight_wall + t - time.monotonic()))
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
                if mission_at is None:
                    commands, armed = takeoff_rc(t, positions, fit["up"]["gain"])
                    phase = "takeoff" if any(armed) else "ground"
                    if t >= 2 and all(abs(p[2] - h[2]) < 0.08 and abs(v[2]) < 0.1
                                      for p, h, v in zip(positions, HOMES, vworld)):
                        mission_at = t
                        lifecycle_events.append({"t": t, "phase": "takeoff_complete"})
                        print(f"[metal] both takeoffs complete at {t:.2f}s", flush=True)
                    elif t > 14:
                        raise RuntimeError("Simulated takeoff timed out")
                if mission_at is not None and landed_at is None:
                    decision = mission.step(states, t - mission_at)
                    phase = decision.phase
                    commands = rc_for_pair(module, states, decision)
                    if decision.land:
                        landed_at = t
                        print(f"[metal] land at {t:.2f}s: {decision.reason}", flush=True)
                command = rc.command(torch.tensor(commands, dtype=torch.float32))
                if landed_at is not None:
                    commands = [(0, 0, round(-0.4 / fit["up"]["gain"]), 0)
                                if p[2] >= 0.043 else (0, 0, 0, 0) for p in positions]
                    command = rc.command(torch.tensor(commands, dtype=torch.float32))
                controller.set_command(command)
                rows.append({"t": t, "phase": phase, "moves": list(mission.moves),
                             "dancers": mission.choreography.snapshot(),
                             "velocities": vworld,
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
            idle = [i for i in range(2) if not armed[i] or motors_stopped[i]]
            if idle:
                # Keep idle controller integrators and rotor state at rest; no
                # hidden hover spin-up or accumulated climb before liftoff.
                ids = torch.tensor(idle)
                controller.reset(ids, randomize=False)
                controller.motor_speeds[ids] = 0
                controller._motor_speeds_des[ids] = 0
            data.xfrc_applied[:] = 0
            for i, body in enumerate(bodies):
                if landed_at is not None and positions[i][2] < 0.043:
                    motors_stopped[i] = True
                if not armed[i] or motors_stopped[i]:
                    continue
                rotation = data.xmat[body].reshape(3, 3)
                data.xfrc_applied[body, :3] = rotation @ force[i].numpy()
                data.xfrc_applied[body, 3:] = rotation @ torque[i].numpy()
                tilt = math.degrees(math.acos(max(-1, min(1, rotation[2, 2]))))
                max_tilt = max(max_tilt, tilt)
            mujoco.mj_step(model, data)
            tick += 1
            if tick % 2500 == 0:
                print(f"[metal] simulated {t:.1f}s; phase={phase}; gap={gap:.2f}m", flush=True)
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
                  "sensing_tag_ids": list(scene_tags),
                  "velocity_observation": "ideal simulator velocity; not camera-estimated",
                  "start": "resting on pads, motors off; 1.5 s ground hold then staggered powered takeoff",
                  "takeoff_model": "altitude-based SDK approximation, original firmware/rotor forces; ideal onboard altitude",
                  "takeoff_complete_s": mission_at, "physical_flight_tested": False,
                  "choreography": "Classical Ballet vs Krump: measured replies, dynamic timing, RC holds" +
                                  ("; local Ollama phrase agents" if planner else "; reactive rules"),
                  "phrase_planner": planner.metadata if planner else None,
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
                  "events": sorted(lifecycle_events + [{**event, "t": round(event["t"] + mission_at, 3)}
                                                      for event in mission.events], key=lambda e: e["t"]),
                  "rows": rows, "frames": frames}
        (output / "simulation.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        return report


def telemetry_frames(output, report):
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
    frames = output / "telemetry-frames"
    frames.mkdir(exist_ok=True)
    for i, frame in enumerate(report["frames"]):
        path = frames / f"frame_{i}.png"
        original = output / "frames" / path.name
        if not original.is_file():
            raise RuntimeError("Missing rendered frame: " + str(original))
        shutil.copy2(original, path)
        row = report["rows"][frame["row"]]
        labels = [row["phase"] + ": " + move for move in row["moves"]]
        if row["phase"] == "dance" and "dancers" in row:
            labels = [f"{d['name']}/{d['style']} {d['mode']}" for d in row["dancers"]]
        rec = {"head": "DUET | Action Space scene + Tello model | Apple Metal", "t": frame["t"], "gap": report["min_separation_m"],
               "drones": [{"pad": k, "phase": labels[k],
                           "lost": bool((row["fix_ages"][k] or 0) > 0.35) and row["phase"] not in ("land", "ground", "takeoff"),
                           "rc": row["rc"][k], "fix_age": row["fix_ages"][k] or 0}
                          for k in range(2)]}
        if row["phase"] in ("ground", "takeoff"):
            for k in range(2):
                rec["drones"][k]["phase"] = "TAKEOFF" if row["rc"][k][2] else "ON PAD | motors off"
        if row["phase"] == "land":
            for k in range(2):
                rec["drones"][k]["phase"] = "LANDED on spot" if frame["positions"][k][2] < 0.04 else "LANDING"
        overlay(str(path), rec, colors, None)
    return frames


def encode(output, report, video, *, telemetry=False, music=False, music_start=32.0):
    frames = telemetry_frames(output, report) if telemetry else output / "frames"
    cmd = ["ffmpeg", "-v", "error", "-y", "-framerate", str(report["fps"]),
           "-i", str(frames / "frame_%d.png")]
    encoding = {"telemetry_overlay": telemetry, "music": None}
    if music:
        source = ROOT / "media/music/five-armies-kevin-macleod.mp3"
        credit = json.loads((source.parent / "attribution.json").read_text())
        duration = report["frame_count"] / report["fps"]
        probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_format",
                                                   "-of", "json", str(source)], text=True))
        if not math.isfinite(music_start) or music_start < 0 or music_start + duration > float(probe["format"]["duration"]):
            raise ValueError("Music excerpt must fit within the source track")
        filters = (f"atrim=duration={duration},asetpts=PTS-STARTPTS,"
                   "loudnorm=I=-20:TP=-2:LRA=11,afade=t=in:d=1.5,"
                   f"afade=t=out:st={max(0, duration - 2)}:d=2")
        cmd += ["-ss", str(music_start), "-i", str(source), "-map", "0:v:0", "-map", "1:a:0",
                "-af", filters, "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-metadata", "title=Drone Duet: Classical Ballet vs Krump",
                "-metadata", f"artist={credit['artist']}",
                "-metadata", f"copyright={credit['attribution']}",
                "-metadata", "comment=Music excerpt, loudness adjustment and fades; simulated drone flight."]
        encoding["music"] = {**credit, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                              "start_s": music_start, "duration_s": duration, "audio_filter": filters,
                              "codec": "AAC 192 kb/s, 48 kHz stereo", "beat_synchronized": False}
    cmd += ["-t", str(report["frame_count"] / report["fps"]),
            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video)]
    subprocess.run(cmd, check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-f", "null", "-"], check=True)
    encoding["video_sha256"] = hashlib.sha256(video.read_bytes()).hexdigest()
    encoding["full_decode_check"] = "passed"
    (output / (video.stem + ".encoding.json")).write_text(json.dumps(encoding, indent=2) + "\n")
    print("[metal] MP4:", video, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    from .ollama_agent import add_arguments, from_arguments
    add_arguments(parser)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/metal-duet")
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--dance-seconds", type=float, default=28)
    parser.add_argument("--simulate-only", action="store_true")
    parser.add_argument("--render-only", action="store_true")
    parser.add_argument("--encode-only", action="store_true")
    parser.add_argument("--telemetry", action="store_true", help="Add original recorder diagnostic panels; default is clean 3D")
    parser.add_argument("--music", action="store_true", help="Add credited CC BY 4.0 Five Armies soundtrack")
    parser.add_argument("--music-start", type=float, default=32.0, help="Excerpt start in source music, seconds")
    args = parser.parse_args()
    if not 1 <= args.fps <= 60:
        parser.error("--fps must be between 1 and 60")
    output = args.output_dir.resolve()
    if args.render_only or args.encode_only:
        if args.llm_model:
            parser.error("--llm-model is for new simulations; existing frames retain their recorded policy")
        report = json.loads((output / "simulation.json").read_text())
    else:
        planner = from_arguments(args)
        try:
            report = simulate(output, seed=args.seed, fps=args.fps, dance_seconds=args.dance_seconds, planner=planner)
        finally:
            if planner:
                planner.close()
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
    video = output / ("drone-duet-telemetry.mp4" if args.telemetry else "drone-duet.mp4")
    encode(output, report, video, telemetry=args.telemetry, music=args.music, music_start=args.music_start)


if __name__ == "__main__":
    main()
