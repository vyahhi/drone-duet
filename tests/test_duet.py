import dataclasses
import json
import math
import tempfile
import time
import unittest
import sys
from pathlib import Path
from unittest.mock import Mock, patch

from duet import fly
from duet.fly import PairWatchdog, calibration_check, land_pair
from duet.mission import HOMES, MOVES, Mission, State
from duet.record import prepare
from duet.upstream import formation, from_internal, rc_for_pair, to_internal, yaw_from_internal


def home_states():
    return [State(h, math.atan2(-h[1], -h[0]), 0.0) for h in HOMES]


class MissionTests(unittest.TestCase):
    def test_autonomous_replies_and_bounded_targets(self):
        for seed in range(30):
            m = Mission(seed)
            states = home_states()
            old = None
            for tick in range(1100):
                d = m.step(states, tick * 0.05)
                if d.land:
                    self.assertEqual(d.reason, "duet complete")
                    break
                if d.targets:
                    a, b = d.targets
                    self.assertLessEqual(a[1], -0.68 + 1e-6)
                    self.assertGreaterEqual(b[1], 0.68 - 1e-6)
                    self.assertGreater(math.hypot(a[0] - b[0], a[1] - b[1]), 1.25)
                    if old:
                        self.assertTrue(all(math.dist(p, q) <= 0.005001 for p, q in zip(old, d.targets)))
                    old = d.targets
                    states = [dataclasses.replace(s, position=p) for s, p in zip(states, d.targets)]
            else:
                self.fail("mission did not finish")
            events = [e for e in m.events if "move" in e]
            self.assertEqual({e["drone"] for e in events}, {0, 1})
            self.assertTrue(all(e["move"] in MOVES and "partner" in e for e in events))

    def test_stale_fix_zeros_pair_then_lands(self):
        m, states = Mission(), home_states()
        m.step(states, 0)
        stale = [dataclasses.replace(states[0], fix_age=0.6), states[1]]
        d = m.step(stale, 0.1)
        self.assertIsNone(d.targets)
        self.assertFalse(d.land)
        self.assertEqual(rc_for_pair(Mock(), stale, d), [(0, 0, 0, 0)] * 2)
        self.assertTrue(m.step(stale, 2.2).land)

    def test_stale_fix_does_not_advance_music(self):
        m, states = Mission(), home_states()
        for tick in range(40):
            m.step(states, tick * 0.05)
        before = m.dance_t
        stale = [dataclasses.replace(s, fix_age=0.6) for s in states]
        m.step(stale, 2.0)
        m.step(stale, 2.5)
        self.assertEqual(m.dance_t, before)

    def test_pair_failure_conditions(self):
        cases = [
            dataclasses.replace(home_states()[0], battery=19),
            dataclasses.replace(home_states()[0], status_age=1.1),
            dataclasses.replace(home_states()[0], position=(math.nan, -0.8, 1.22)),
            dataclasses.replace(home_states()[0], position=(2.5, 0.0, 1.22)),
            dataclasses.replace(home_states()[0], position=(3.9, -0.8, 1.22)),
            dataclasses.replace(home_states()[0], velocity=(math.inf, 0, 0)),
        ]
        for bad in cases:
            with self.subTest(bad=bad):
                self.assertTrue(Mission().step([bad, home_states()[1]], 0).land)
        self.assertTrue(Mission().step([], 0).land)
        self.assertTrue(Mission().step(home_states(), 60).land)

    def test_predicted_approach_freezes_before_distance_violation(self):
        states = home_states()
        states[0] = dataclasses.replace(states[0], velocity=(0, 1.0, 0))
        d = Mission().step(states, 0)
        self.assertIsNone(d.targets)
        self.assertIn("spacing", d.reason)
        # Catch an intermediate crossing even if the horizon endpoint is far apart.
        states[0] = dataclasses.replace(states[0], velocity=(0, 8.0, 0))
        self.assertIsNone(Mission().step(states, 0).targets)

    def test_clock_and_acquisition_timeout(self):
        self.assertTrue(Mission().step([State(None), State(None)], 8.1).land)
        m = Mission()
        m.step(home_states(), 1)
        self.assertTrue(m.step(home_states(), 0).land)
        self.assertTrue(Mission().step(home_states(), math.nan).land)

    def test_deterministic_replay(self):
        a, b = Mission(123), Mission(123)
        for tick in range(900):
            self.assertEqual(a.step(home_states(), tick * 0.05), b.step(home_states(), tick * 0.05))
        self.assertEqual(a.events, b.events)


class AdapterTests(unittest.TestCase):
    def test_coordinate_round_trip(self):
        for h in HOMES:
            for tag_height in (1.0, 1.22, 1.5):
                self.assertEqual(from_internal(to_internal(h, tag_height), tag_height), h)
        self.assertAlmostEqual(abs(yaw_from_internal(0)), math.pi)
        self.assertAlmostEqual(yaw_from_internal(90), math.pi / 2)

    def test_controller_uses_original_and_respects_rc_bounds(self):
        module = formation()
        states, m = home_states(), Mission()
        d = m.step(states, 0)
        self.assertEqual(rc_for_pair(module, states, d), [(0, 0, 0, 0)] * 2)
        d = dataclasses.replace(d, targets=((2.6, -0.9, 1.3), (2.6, 0.9, 1.3)))
        commands = rc_for_pair(module, states, d)
        for command in commands:
            self.assertTrue(all(abs(v) <= cap for v, cap in zip(command, (15, 15, 20, 25))))
            self.assertGreater(command[2], 0)
        self.assertLess(commands[0][0], 0)  # drone facing the tag, negative Y is left
        self.assertGreater(commands[1][0], 0)

    def test_original_controller_closed_loop_kinematic_check(self):
        # A controller integration check, NOT an Isaac or physical flight validation.
        module = formation()
        for seed in range(5):
            m = Mission(seed)
            positions = [list(h) for h in HOMES]
            yaws = [math.atan2(-h[1], -h[0]) for h in HOMES]
            velocities = [(0, 0, 0)] * 2
            for tick in range(1200):
                states = [State(tuple(p), yaw, 0, velocity=v) for p, yaw, v in zip(positions, yaws, velocities)]
                d = m.step(states, tick * 0.05)
                if d.land:
                    self.assertEqual(d.reason, "duet complete")
                    break
                commands = rc_for_pair(module, states, d)
                for i, (right, forward, up, yaw) in enumerate(commands):
                    c, s = math.cos(yaws[i]), math.sin(yaws[i])
                    vx = c * forward * 0.00731 + s * right * 0.008
                    vy = s * forward * 0.00731 - c * right * 0.008
                    vz = up * 0.006 if abs(up) >= 5 else 0
                    velocities[i] = (vx, vy, vz)
                    for k, v in enumerate(velocities[i]):
                        positions[i][k] += v * 0.05
                    yaws[i] -= math.radians(yaw * 0.6) * 0.05
            else:
                self.fail("original-controller integration did not finish")
            self.assertGreater(m.min_measured_gap, 1.25)

    def test_watchdog_stall_sends_zero_and_lands_pair(self):
        drones, module = [Mock(), Mock()], Mock()
        w = PairWatchdog(drones, module)
        w.last_tick -= 3
        w.thread.start()
        try:
            self.assertTrue(w.tripped.wait(1))
            for d in drones:
                d.send_noreply.assert_called_with("rc 0 0 0 0")
            self.assertEqual(module.land_async.call_count, 2)
        finally:
            w.stop.set()
            w.thread.join(1)

    def test_one_failed_socket_does_not_prevent_partner_landing(self):
        drones, module = [Mock(), Mock()], Mock()
        module.land_async.side_effect = [OSError("lost interface"), None]
        land_pair(module, drones, "test stop")
        self.assertEqual(module.land_async.call_count, 2)

    def test_calibration_identity_blocks_wrong_drone(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            config = [{"number": n, "ssid": f"TELLO-{n}", "iface": f"wlan{n}"} for n in (4, 8)]
            for n in (4, 8):
                (directory / f"tello_{n}.yaml").write_text(f"ssid: TELLO-{n}\n")
            calibration_check(directory, {4, 8}, config)
            (directory / "tello_4.yaml").write_text("ssid: TELLO-9\n")
            with self.assertRaisesRegex(ValueError, "SSID mismatch"):
                calibration_check(directory, {4, 8}, config)

    def test_original_recorder_hooks_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            path = prepare(out)
            compile(path.read_text(), str(path), "exec")
            patch = (out / "recorder-hooks.patch").read_text()
            self.assertIn("act = pilot.act", patch)
            self.assertNotIn("-        capture_viewport_to_file", patch)
            self.assertNotIn("-        imageio_ffmpeg", patch)
            provenance = json.loads((out / "renderer-provenance.json").read_text())
            self.assertFalse(provenance["upstream_checkout_modified"])
            self.assertEqual(len(provenance["original_sha256"]), 64)


class FlightLifecycleTests(unittest.TestCase):
    def run_main(self, *, flying=False, preflight=True, takeoff_ok=True):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "camera").mkdir()
            entries = [{"number": n, "ssid": f"TELLO-{n}", "iface": f"wlan{n}"} for n in (4, 8)]
            (directory / "dongles.json").write_text(json.dumps(entries))
            for n in (4, 8):
                (directory / f"camera/tello_{n}.yaml").write_text(f"ssid: TELLO-{n}\n")
            module = Mock()
            drones = []
            for n in (4, 8):
                d = Mock(num=n, battery=100, st_t=time.time(), airborne=False, landed=False, land_thread=None)
                d.est.return_value = None  # ground camera need not see the elevated tag
                d.send.return_value = "ok" if takeoff_ok else "error"
                drones.append(d)
            module.load_drones.return_value = list(reversed(drones))
            module.load_tag_files.return_value = (10, {}, {})
            module.parallel.return_value = {n: preflight for n in (4, 8)}
            def land(d, reason, enable):
                if d.airborne:
                    d.send_noreply("rc 0 0 0 0")
                    d.send_noreply("land")
                    d.landed = True
            module.land_async.side_effect = land
            argv = ["duet.fly", "--only", "4,8", "--config-dir", str(directory), "--log", str(directory / "flight.jsonl")]
            if flying:
                argv.append("--fly")
            with patch.object(sys, "argv", argv), patch.object(sys, "platform", "linux"), \
                 patch.object(fly, "formation", return_value=module), patch.object(fly.signal, "signal"):
                try:
                    result = fly.main()
                    error = None
                except RuntimeError as ex:
                    result, error = None, str(ex)
            return result, error, drones, module

    def test_read_only_preflight_sends_no_flight_commands(self):
        result, error, drones, module = self.run_main()
        self.assertEqual(result, 0)
        self.assertIsNone(error)
        for d in drones:
            d.send.assert_not_called()
            d.send_noreply.assert_not_called()
            d.close.assert_called_once()
        module.land_async.assert_not_called()

    def test_pair_preflight_failure_never_takes_off(self):
        _, error, drones, _ = self.run_main(flying=True, preflight=False)
        self.assertIn("preflight failed", error)
        for d in drones:
            d.send.assert_not_called()
            d.send_noreply.assert_not_called()

    def test_takeoff_failure_lands_both_drones(self):
        _, error, drones, module = self.run_main(flying=True, takeoff_ok=False)
        self.assertIn("takeoff not acknowledged", error)
        for d in drones:
            d.send.assert_called_with("takeoff", 10)
            d.send_noreply.assert_any_call("land")
            d.close.assert_called_once()
        self.assertEqual(module.land_async.call_count, 2)


if __name__ == "__main__":
    unittest.main()
