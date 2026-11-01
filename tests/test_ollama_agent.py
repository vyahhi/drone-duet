"""Bounded model decisions, deadlines, lifecycle and nonblocking control."""
import dataclasses
import json
import math
from queue import Empty
import threading
import time
import unittest
from unittest.mock import patch

from duet.choreography import Choreography
from duet.mission import HOMES, Mission, State
from duet.ollama_agent import Choice, OllamaPlanner, validate_choice


def states():
    return [State(h, fix_age=0) for h in HOMES]


class FakePlanner:
    model, max_age = "test-model", 4.5
    def __init__(self):
        self.results, self.submissions, self.memories = [], [], []
    def drain(self):
        results, self.results = self.results, []
        return results
    def submit(self, drone, context):
        self.submissions.append((drone, context))
    def remember(self, drone, choice):
        self.memories.append((drone, choice))


def result(drone, context, action, *, issued_wall=None, error=None):
    return {"drone": drone, "context": context, "choice": Choice(action, "accent", "Answer the measured partner"),
            "issued_wall": time.monotonic() if issued_wall is None else issued_wall,
            "latency_s": 0.2, "error": error, "stats": {"raw_content": action}}


class ModelBoundaryTests(unittest.TestCase):
    def test_only_role_and_style_vocabulary_is_accepted(self):
        self.assertEqual(validate_choice({"action": "arabesque", "tempo": "sustain", "reason": "Rise"}, 0, "leader").action, "arabesque")
        for value in [
            {"action": "stomp", "tempo": "match", "reason": "wrong style"},
            {"action": "land", "tempo": "match", "reason": "flight command"},
            {"action": "arabesque", "tempo": "fast", "reason": "wrong tempo"},
            {"action": "arabesque", "tempo": "match", "reason": ""},
            {"action": "arabesque", "tempo": "match", "reason": "x", "rc": [100, 0, 0, 0]},
        ]:
            with self.assertRaises(ValueError):
                validate_choice(value, 0, "leader")

    def test_incomplete_json_or_truncated_answers_are_not_applied(self):
        p = OllamaPlanner()
        context = {"role": "leader"}
        for response in [
            {"done": True, "done_reason": "length", "message": {"content": '{}'}},
            {"done": True, "done_reason": "stop", "message": {"content": 'not JSON'}},
        ]:
            with patch.object(p, "_http", return_value=response), self.assertRaises(ValueError):
                p.request(0, context)

    def test_local_origin_and_model_preflight(self):
        for url in ("https://example.com", "http://192.168.1.1:11434", "http://127.0.0.1/path", "http://x@localhost"):
            with self.assertRaises(ValueError):
                OllamaPlanner(url=url)
        p = OllamaPlanner()
        with patch.object(p, "_http", return_value={"models": []}), self.assertRaises(RuntimeError):
            p.prepare()
        self.assertIsNone(p.thread)

    def test_slow_model_does_not_block_submit_or_control(self):
        p = OllamaPlanner()
        entered, release = threading.Event(), threading.Event()
        def slow(*_):
            entered.set()
            release.wait(2)
            return Choice("adagio", "match", "Slow response"), {}
        p.request = slow
        p.thread = threading.Thread(target=p._run, daemon=True)
        p.thread.start()
        c = Choreography(HOMES, 7, [], planner=p)
        try:
            c.step(states(), 0, 0)
            self.assertTrue(entered.wait(1))
            for tick in range(1, 101):
                c.step(states(), tick * .05, tick * .05)
            self.assertFalse(release.is_set())
            self.assertLessEqual(p.tasks.qsize(), 1)
            self.assertTrue(all(p.pending))
        finally:
            p.stop.set()
            release.set()
            p.close()

    def test_queued_agent_uses_latest_observations_before_inference(self):
        p = OllamaPlanner()
        p.thread = threading.Thread(target=p._run, daemon=True)
        p.submit(1, {"dance_t": 0, "role": "follower"})
        p.submit(1, {"dance_t": 2, "role": "leader"})
        with patch.object(p, "request", return_value=(Choice("stomp", "match", "Answer"), {})) as request:
            p.thread.start()
            try:
                deadline = time.monotonic() + 1
                while p.results.empty() and time.monotonic() < deadline:
                    time.sleep(.005)
                answer = p.drain()[0]
                self.assertEqual(answer["context"]["dance_t"], 2)
                self.assertEqual(request.call_args.args[1]["role"], "leader")
            finally:
                p.close()

    def test_choices_apply_to_both_policies_without_changing_roles_or_limits(self):
        planner = FakePlanner()
        c = Choreography(HOMES, 7, [], planner=planner)
        c.step(states(), 0, 0)
        contexts = {i: context for i, context in planner.submissions}
        planner.results = [result(0, contexts[0], "arabesque"), result(1, contexts[1], "echo")]
        targets = c.step(states(), .05, .05)
        self.assertEqual(c.leader, 0)
        self.assertEqual(c.dancers[0].gesture, "arabesque")
        self.assertEqual(c.dancers[1].mode, "echo")
        self.assertEqual(len(planner.memories), 2)
        self.assertTrue(all(d.decision_source == "ollama" for d in c.dancers))
        self.assertLessEqual(targets[0][1], -.70)
        self.assertGreaterEqual(targets[1][1], .70)
        for tick in range(2, 101):
            c.step(states(), tick * .05, tick * .05)
        self.assertTrue(all(d.decision_source == "rules" for d in c.dancers))

    def test_stale_wrong_role_and_failed_inference_are_rejected(self):
        for kind in ("wall", "dance", "role", "epoch", "timeout"):
            p = FakePlanner()
            c = Choreography(HOMES, 7, [], planner=p)
            c.step(states(), 0, 0)
            context = dict(p.submissions[0][1])
            answer = result(0, context, "arabesque")
            if kind == "wall": answer["issued_wall"] -= 10
            if kind == "dance": context["dance_t"] -= 10
            if kind == "role": context["role"] = "follower"
            if kind == "epoch": context["leader_since"] = -1
            if kind == "timeout": answer["error"] = "TimeoutError"
            p.results = [answer]
            c.step(states(), .05, .05)
            self.assertEqual(c.events[-1]["model_result"], "rejected")
            self.assertEqual(c.dancers[0].decision_source, "rules")
            self.assertFalse(p.memories)

    def test_model_replies_are_preserved_and_stale_fix_guards_run_first(self):
        p = FakePlanner()
        m = Mission(planner=p)
        for tick in range(25):
            m.step(states(), tick * .05)
        contexts = {i: context for i, context in p.submissions}
        p.results = [result(1, contexts[1], "reply")]
        m.step(states(), 1.25)
        d = m.choreography.dancers[1]
        captured = list(d.reply)
        context = dict(p.submissions[-1][1])
        p.results = [result(1, context, "mirror")]
        m.step(states(), 1.30)
        self.assertEqual(d.mode, "reply")
        self.assertEqual(d.reply, captured)
        self.assertEqual(m.events[-1]["error"], "preserve captured reply until complete")
        p.results = [result(0, contexts[0], "arabesque")]
        paused = m.step([dataclasses.replace(s, fix_age=.6) for s in states()], 1.35)
        self.assertIsNone(paused.targets)
        self.assertEqual(len(p.results), 1)  # no model application while localization is stale
        failed = m.step([dataclasses.replace(s, battery=10) for s in states()], 1.40)
        self.assertTrue(failed.land)
        self.assertEqual(len(p.results), 1)


if __name__ == "__main__":
    unittest.main()
