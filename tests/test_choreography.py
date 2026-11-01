"""Causal interaction tests: observed motion, styles, memory and handoffs."""
import dataclasses
import math
import unittest

from duet.choreography import Choreography
from duet.mission import HOMES, Mission, State


def observations(offsets=((0, 0, 0), (0, 0, 0))):
    return [State(tuple(h[k] + p[k] for k in range(3)), fix_age=0)
            for h, p in zip(HOMES, offsets)]


class InteractionTests(unittest.TestCase):
    def test_sustained_partner_turn_changes_response_before_timeout(self):
        c = Choreography(HOMES, 7, [])
        for tick in range(62):
            t = tick * 0.05
            c.step(observations(), t, t)
        before = c.dancers[1].since
        self.assertLess(before, 0.1)
        for tick in range(62, 75):
            t = tick * 0.05
            c.step(observations(((0.1 * (t - 3.05), 0, 0), (0, 0, 0))), t, t)
        self.assertGreater(c.dancers[1].since, 3.05)
        self.assertLess(c.dancers[1].since, 4.0)
        event = next(e for e in reversed(c.events) if e.get("drone") == 1)
        self.assertIn("partner changed", event["trigger"])

    def test_tempo_and_delay_adapt_to_measured_motion_not_clock(self):
        still, moving = (Choreography(HOMES, 7, []) for _ in range(2))
        for tick in range(61):
            t = tick * 0.05
            still.step(observations(), t, t)
            moving.step(observations(((0.12 * t, 0, 0), (0, 0, 0))), t, t)
        self.assertGreater(moving.dancers[1].tempo, still.dancers[1].tempo)
        self.assertLess(moving.dancers[1].echo_delay, still.dancers[1].echo_delay)
        self.assertNotEqual(moving.dancers[1].accent_phase, still.dancers[1].accent_phase)
        # A single observation spike cannot trigger a new response.
        before = still.dancers[1].since
        still.step(observations(((0.5, 0, 0), (0, 0, 0))), 3.05, 3.05)
        self.assertEqual(still.dancers[1].since, before)

    def test_mirror_changes_with_observed_partner_in_all_three_axes(self):
        c = Choreography(HOMES, 7, [])
        c.step(observations(), 0, 0)
        offset = (0.18, 0.08, -0.10)
        target = c.step(observations((offset, (0, 0, 0))), 0.05, 0.05)[1]
        expected = (HOMES[1][0] + 0.36, HOMES[1][1] - 0.10, HOMES[1][2] - 0.27)
        self.assertEqual(target, expected)
        self.assertNotEqual(target, HOMES[1])
        # Identical clocks/seeds, different observations -> different decisions/targets.
        still = Choreography(HOMES, 7, [])
        still.step(observations(), 0, 0)
        self.assertNotEqual(still.step(observations(), 0.05, 0.05)[1], target)

    def test_echo_uses_measured_past_not_current_partner_pose(self):
        c = Choreography(HOMES, 7, [])
        for tick in range(41):
            t = tick * 0.05
            c.step(observations(((t * 0.20, 0, t * 0.04), (0, 0, 0))), t, t)
        c.dancers[1].mode = "echo"
        target = c.step(observations(((0.23, 0, 0.17), (0, 0, 0))), 2.05, 2.05)[1]
        delay = c.dancers[1].echo_delay
        past = c.sample(2.05 - delay, 0)
        self.assertAlmostEqual(target[0] - HOMES[1][0], round(2.00 * past[0] / 0.18) * 0.18)
        self.assertAlmostEqual(target[2] - HOMES[1][2], -0.24 + 0.30 * past[2])
        self.assertNotAlmostEqual(past[2], 0.17)

    def test_reply_captures_motif_and_reinterprets_in_own_style(self):
        c = Choreography(HOMES, 7, [])
        for tick in range(61):
            t = tick * 0.05
            c.step(observations(((0.15 * math.sin(t), 0.06, 0.1), (0, 0, 0))), t, t)
        c._respond(1, 3, 3)
        d = c.dancers[1]
        self.assertTrue(d.reply)
        captured = list(d.reply)
        target = c._reply_offset(d, 5)
        interpreted = c._interpret_response(d, target, 0.05)
        self.assertAlmostEqual(interpreted[0] / 0.18, round(interpreted[0] / 0.18))
        self.assertLess(interpreted[2], -0.20)  # low Krump answer to an elevated motif
        c.history.append((4, ((-0.24, -0.12, -0.18), (0, 0, 0))))
        self.assertEqual(c._reply_offset(d, 5), target)
        self.assertEqual(d.reply, captured)

    def test_distinct_styles_and_measured_engagement_required_for_handoff(self):
        events = []
        c = Choreography(HOMES, 7, events)
        for tick in range(200):
            t = tick * 0.05
            c.step(observations(), t, t)
        self.assertEqual(c.leader, 0)  # no timed handoff when partner never moves
        self.assertFalse(any("handoff" in e for e in events))
        for tick in range(200, 250):
            t = tick * 0.05
            c.step(observations(((0, 0, 0), (0.08 * math.sin(t), 0, 0.08 * math.cos(t)))), t, t)
        self.assertEqual(c.leader, 1)
        self.assertTrue(any("handoff" in e for e in events))
        ari, sol = c.dancers
        self.assertEqual((ari.profile.style, sol.profile.style), ("Classical Ballet", "Krump"))
        self.assertIn(sol.gesture, ("stomp", "jab", "chest_pop"))
        self.assertTrue(all("reason" in e for e in events if "move" in e))

    def test_style_persists_in_every_response_mode_and_holds_brake_rc(self):
        from duet.upstream import rc_for_pair
        from duet.mission import Decision
        from unittest.mock import Mock
        c = Choreography(HOMES, 7, [])
        for mode in ("mirror", "echo", "reply"):
            for d in c.dancers:
                d.mode = mode
                for _ in range(60):
                    c._interpret_response(d, (0.30, -0.10, 0.10), 0.05)
            ballet, krump = (d.response_offset for d in c.dancers)
            self.assertGreater(ballet[2], 0.28)
            self.assertLess(krump[2], -0.20)
            self.assertAlmostEqual(krump[0] / 0.18, round(krump[0] / 0.18))
        c.step(observations(), 0, 0)
        for tick in range(1, 35):
            c.step(observations(), tick * 0.05, tick * 0.05)
        self.assertFalse(c.dancers[0].hold)
        self.assertTrue(c.dancers[1].hold)
        module = Mock()
        module.control.return_value = ((3, 4, 5, 6), 0, 0)
        decision = Decision("dance", HOMES, holds=(False, True))
        self.assertEqual(rc_for_pair(module, observations(), decision), [(3, 4, 5, 6), (0, 0, 0, 0)])
        self.assertEqual(module.control.call_count, 1)
        for tick in range(35, 50):
            c.step(observations(), tick * 0.05, tick * 0.05)
        self.assertFalse(c.dancers[1].hold)

    def test_leader_slows_when_partner_lags(self):
        c = Choreography(HOMES, 7, [])
        c.step(observations(), 0, 0)
        c.step(observations(((0.2, 0, 0.15), (-0.2, 0, -0.15))), 0.05, 0.05)
        self.assertAlmostEqual(c.dancers[0].phrase_rate / c.dancers[0].tempo, 0.70)
        c.step(observations(((0.2, 0, 0.15), (0.2, 0, 0.15))), 0.1, 0.1)
        self.assertAlmostEqual(c.dancers[0].phrase_rate / c.dancers[0].tempo, 1.0)

    def test_stale_fix_freezes_interaction_memory_and_decisions(self):
        m = Mission()
        states = observations()
        for tick in range(50):
            m.step(states, tick * 0.05)
        before = (list(m.choreography.history), list(m.events), m.choreography.snapshot())
        m.step([dataclasses.replace(s, fix_age=0.6) for s in states], 2.5)
        self.assertEqual(before, (list(m.choreography.history), list(m.events), m.choreography.snapshot()))


if __name__ == "__main__":
    unittest.main()
