"""Two-Tello flight adapter using the organizers' Linux networking and tag tracking."""
from __future__ import annotations

import argparse
import json
import math
import signal
import sys
import threading
import time
from pathlib import Path

from .mission import HOMES, Mission, State
from .upstream import ROOT, UPSTREAM, formation, from_internal, rc_for_pair, yaw_from_internal


def land_pair(module, drones, reason):
    # A failed socket on one drone must never suppress the other drone's landing.
    for d in drones:
        try:
            module.land_async(d, reason, True)
        except Exception as ex:
            print(f"Landing dispatch failed for drone {d.num}: {ex}", file=sys.stderr)


class PairWatchdog:
    """Independent of the policy loop: zero RC at 0.4 s stall, land at 2 s."""
    def __init__(self, drones, module):
        self.drones, self.module = drones, module
        self.last_tick = time.monotonic()
        self.stop = threading.Event()
        self.tripped = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def tick(self):
        self.last_tick = time.monotonic()

    def run(self):
        while not self.stop.wait(0.05):
            age = time.monotonic() - self.last_tick
            if age > 0.4:
                for d in self.drones:
                    try:
                        d.send_noreply("rc 0 0 0 0")
                    except OSError:
                        pass
            if age > 2:
                self.tripped.set()
                land_pair(self.module, self.drones, "policy watchdog expired")


def sample(drones, now, previous, tag_height):
    states = []
    for d in drones:
        est = d.est(now)
        pos = from_internal(est[0], tag_height) if est is not None else None
        vel = (0.0, 0.0, 0.0)
        # Velocity from accepted fixes, not repeated ticks of a frozen pose.
        if pos is not None:
            fix_t = now - est[2]
            old = previous.get(d.num)
            if old is not None:
                p0, t0, v0 = old
                if fix_t > t0:
                    dt = fix_t - t0
                    vel = tuple(0.5 * v0[k] + 0.5 * (pos[k] - p0[k]) / dt for k in range(3))
                else:
                    vel = v0
            previous[d.num] = (pos, fix_t, vel)
        states.append(State(pos, yaw_from_internal(est[1]) if est else math.pi,
                            est[2] if est else math.inf, now - d.st_t,
                            float(d.battery) if d.battery is not None else 0.0, vel))
    return states


def calibration_check(directory, numbers, config):
    """Upstream falls back to a default camera; physical duet requires matching identities."""
    import yaml
    entries = config.get("dongles", []) if isinstance(config, dict) else config
    selected = {int(e["number"]): e for e in entries if int(e["number"]) in numbers}
    if len(selected) != 2 or len({e["iface"] for e in selected.values()}) != 2:
        raise ValueError("Choose exactly two configured drones on distinct dongles")
    for num in numbers:
        path = directory / f"tello_{num}.yaml"
        if not path.is_file():
            raise ValueError(f"Missing per-drone calibration: {path}")
        data = yaml.safe_load(path.read_text())
        if data.get("ssid") != selected[num]["ssid"]:
            raise ValueError(f"Calibration SSID mismatch in {path}; calibrate this physical drone first")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", required=True, help="Two drone IDs in lane order: negative Y, positive Y; e.g. 4,8")
    parser.add_argument("--config-dir", type=Path, default=UPSTREAM / "drone_deployment_infra/config")
    parser.add_argument("--tag-height", type=float, default=1.22, help="Measured tag-10 center height above floor, m")
    parser.add_argument("--fly", action="store_true", help="Enable takeoff/RC/land; default is read-only preflight")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--dance-seconds", type=float, default=28)
    parser.add_argument("--log", type=Path, default=ROOT / "outputs/flight.jsonl")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("The organizers' SO_BINDTODEVICE multi-dongle stack requires Linux")
    try:
        ordered_numbers = [int(x) for x in args.only.split(",")]
        numbers = set(ordered_numbers)
        if len(numbers) != 2 or len(ordered_numbers) != 2:
            raise ValueError("--only must select exactly two distinct drone IDs")
        if not math.isfinite(args.tag_height) or not 0.8 <= args.tag_height <= 1.6:
            raise ValueError("--tag-height must be the measured height in [0.8, 1.6] m")
        mission = Mission(args.seed, args.dance_seconds)
        directory = args.config_dir.resolve()
        config_path = directory / "dongles.json"
        calibration_check(directory / "camera", numbers, json.loads(config_path.read_text()))
    except (ValueError, OSError) as ex:
        parser.error(str(ex))
    module = formation()
    origin, tag_map, sizes = module.load_tag_files(str(directory / "map.yaml"), str(directory / "tags.yaml"))
    if origin != 10:
        parser.error("Duet requires a shared map with origin_tag 10")
    drones = []
    watchdog = None
    stop = threading.Event()
    previous = {}
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    args.log.parent.mkdir(parents=True, exist_ok=True)
    try:
        drones = module.load_drones(str(config_path), numbers, str(directory / "camera"),
                                    args.fly, tag_map, sizes, module.MapCheck(tag_map))
        drones.sort(key=lambda d: ordered_numbers.index(d.num))
        passed = module.parallel(drones, lambda d: module.preflight(d, args.fly))
        if not all(passed.values()) or stop.is_set():
            raise RuntimeError("Pair preflight failed; no takeoff")
        now = time.time()
        states = sample(drones, now, previous, args.tag_height)
        if not all(s.status_age <= 0.5 for s in states):
            raise RuntimeError("Both drones need fresh status packets before takeoff")
        # A floor-level camera may not see the elevated tag. Placement is on marked
        # pads; measured lane/envelope checks begin as soon as the airborne fix arrives.
        print("Marked-pad lane IDs:", [d.num for d in drones], flush=True)
        print("Pads: X=2.5 m, Y=-0.8/+0.8 m from tag 10, cameras facing tag 10.", flush=True)
        if not args.fly:
            print("PAIR PREFLIGHT PASS. Dry-run: no takeoff, RC or land sent.")
            return 0
        watchdog = PairWatchdog(drones, module)
        watchdog.thread.start()
        # Mark before dispatch so finally also covers lost takeoff acknowledgements.
        for d in drones:
            d.airborne = True
        results = {}
        def takeoff(d, delay):
            if not stop.wait(delay):
                results[d.num] = d.send("takeoff", 10) == "ok"
        threads = [threading.Thread(target=takeoff, args=(d, i * 0.5), daemon=True) for i, d in enumerate(drones)]
        for thread in threads:
            thread.start()
        takeoff_at = time.monotonic()
        while any(thread.is_alive() for thread in threads):
            watchdog.tick()
            if stop.is_set() or time.monotonic() - takeoff_at > 11:
                raise RuntimeError("Takeoff interrupted/timed out")
            now = time.time()
            if any(now - d.st_t > 1 or (d.battery or 0) < 20 for d in drones):
                raise RuntimeError("Status/battery failed during takeoff")
            time.sleep(0.05)
        if not all(results.get(d.num, False) for d in drones):
            raise RuntimeError("Pair takeoff not acknowledged")
        # Allow the firmware to finish leveling after its acknowledgement.
        ready_deadline = time.monotonic() + 3
        while not all((d.height_cm() or 0) >= 70 for d in drones):
            watchdog.tick()
            if stop.is_set() or time.monotonic() > ready_deadline:
                raise RuntimeError("Takeoff height not confirmed")
            time.sleep(0.05)
        started = time.monotonic()
        with args.log.open("w") as log:
            log.write(json.dumps({"event": "start", "lane_ids": [d.num for d in drones],
                                  "tag_height": args.tag_height, "seed": args.seed}) + "\n")
            while not stop.is_set() and not watchdog.tripped.is_set():
                tick, now = time.monotonic(), time.time()
                watchdog.tick()
                states = sample(drones, now, previous, args.tag_height)
                decision = mission.step(states, tick - started)
                commands = rc_for_pair(module, states, decision, args.tag_height)
                if any(d.landing or d.landed for d in drones):
                    raise RuntimeError("A drone left the airborne pair")
                if stop.is_set() or watchdog.tripped.is_set():
                    raise RuntimeError("Operator stop or watchdog")
                for d, rc in zip(drones, commands):
                    d.last_rc = rc
                    d.send_noreply("rc " + " ".join(str(v) for v in rc))
                log.write(json.dumps({"t": tick - started, "phase": decision.phase, "reason": decision.reason,
                                      "moves": list(mission.moves), "targets": decision.targets, "rc": commands,
                                      "positions": [s.position for s in states]}) + "\n")
                log.flush()
                if decision.land:
                    print("Landing pair:", decision.reason)
                    return 0 if decision.reason == "duet complete" else 1
                # The total airborne limit includes takeoff, not only choreography.
                if tick - takeoff_at >= 60:
                    raise RuntimeError("60 s airborne limit")
                stop.wait(max(0, 0.05 - (time.monotonic() - tick)))
        raise RuntimeError("Operator stop or watchdog")
    finally:
        stop.set()
        if args.fly:
            land_pair(module, drones, "duet shutdown")
            # Keep watchdog active through landing; never close the link before attempts finish.
            for d in drones:
                if d.land_thread:
                    d.land_thread.join(timeout=40)
            for d in drones:
                if d.airborne and not d.landed:
                    print(f"LANDING UNCONFIRMED: drone {d.num}; operator must intervene", file=sys.stderr)
        if watchdog:
            watchdog.stop.set()
            watchdog.thread.join(timeout=1)
        for d in drones:
            d.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as ex:
        print("Duet stopped:", ex, file=sys.stderr)
        raise SystemExit(1)
