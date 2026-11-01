"""Causal interaction tests: observed motion, styles, memory and handoffs."""
import dataclasses
import math
import unittest

from duet.choreography import Choreography, reflect
from duet.mission import HOMES, Mission, State


def observations(offsets=((0, 0, 0), (0, 0, 0))):
    return [State(tuple(h[k] + p[k] for k in range(3)), fix_age=0)
            for h, p in zip(HOMES, offsets)]


class InteractionTests(unittest.TestCase):
    def test_mirror_changes_with_observed_partner_in_all_three_axes(self):
        c = Choreography(HOMES, 7, [])
        c.step(observations(), 0, 0)
        offset = (0.18, 0.08, -0.10)
        target = c.step(observations((offset, (0, 0, 0))), 0.05, 0.05)[1]
        expected = tuple(h + p for h, p in zip(HOMES[1], reflect(offset)))
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
            c.step(observations(((t * 0.08, 0, t * 0.04), (0, 0, 0))), t, t)
        c.dancers[1].mode = "echo"
        target = c.step(observations(((0.23, 0, 0.17), (0, 0, 0))), 2.05, 2.05)[1]
        self.assertAlmostEqual(target[0] - HOMES[1][0], 0.85 * 0.08)
        self.assertAlmostEqual(target[2] - HOMES[1][2], 0.85 * 0.04)

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
        self.assertAlmostEqual(target[0] / 0.16, round(target[0] / 0.16))
        self.assertLess(target[2], 0)  # a country bow answers the partner's hop
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
        self.assertEqual((ari.profile.style, sol.profile.style), ("Hopak", "Country"))
        self.assertIn(sol.gesture, ("two_step", "shuffle", "box_step"))
        self.assertTrue(all("reason" in e for e in events if "move" in e))

    def test_leader_slows_when_partner_lags(self):
        c = Choreography(HOMES, 7, [])
        c.step(observations(), 0, 0)
        c.step(observations(((0.2, 0, 0.15), (-0.2, 0, -0.15))), 0.05, 0.05)
        self.assertEqual(c.dancers[0].phrase_rate, 0.70)
        c.step(observations(((0.2, 0, 0.15), (0.2, 0, 0.15))), 0.1, 0.1)
        self.assertEqual(c.dancers[0].phrase_rate, 1.0)

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
