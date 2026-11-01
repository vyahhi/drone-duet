"""Local Ollama phrase selection. Model workers never send flight commands."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from queue import Empty, Queue
import threading
import time
import urllib.request
from urllib.parse import urlsplit

from .choreography import MOVES, STYLES

TEMPOS = {"sustain": 0.95, "match": 1.0, "accent": 1.05}


@dataclass(frozen=True)
class Choice:
    action: str
    tempo: str
    reason: str


def allowed_actions(drone, role):
    return STYLES[drone].gestures if role == "leader" else MOVES[1:]


def validate_choice(value, drone, role):
    if not isinstance(value, dict) or set(value) != {"action", "tempo", "reason"}:
        raise ValueError("Expected exactly action, tempo and reason")
    if value["action"] not in allowed_actions(drone, role) or value["tempo"] not in TEMPOS:
        raise ValueError("Action/tempo is outside the dancer's permitted vocabulary")
    reason = value["reason"]
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 240:
        raise ValueError("Expected a short nonempty reason")
    return Choice(value["action"], value["tempo"], " ".join(reason.split()))


class OllamaPlanner:
    """One bounded queue; separate per-dancer context and memory, one shared model.

    The control thread only exchanges small queue items. HTTP and inference happen
    on a daemon worker, with request deadlines and no unbounded backlog.
    """
    def __init__(self, model="lfm3:latest", url="http://127.0.0.1:11434", *,
                 timeout=4.0, interval=3.0, max_age=4.5):
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1", "::1") or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("Ollama URL must be a local HTTP origin; use an SSH tunnel for a remote flight host")
        if not model or not all(math.isfinite(v) and v > 0 for v in (timeout, interval, max_age)):
            raise ValueError("Model and positive finite time limits are required")
        self.model, self.url = model, url.rstrip("/")
        self.timeout, self.interval, self.max_age = timeout, interval, max_age
        self.metadata = {"model": model, "url": self.url, "mode": "asynchronous high-level phrase selection"}
        self.tasks, self.results = Queue(maxsize=2), Queue(maxsize=2)
        self.pending = [False, False]
        self.last_submit = [-math.inf, -math.inf]
        self.memory = [[], []]
        self.latest = [None, None]
        self.stop = threading.Event()
        self.thread = None
        # Never use environment HTTP proxies for local telemetry/model requests.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _http(self, path, payload=None, *, timeout=None):
        request = urllib.request.Request(self.url + path,
            data=json.dumps(payload, allow_nan=False).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"})
        with self.opener.open(request, timeout=timeout or self.timeout) as response:
            raw = response.read(262145)
        if len(raw) > 262144:
            raise ValueError("Ollama response exceeds size limit")
        return json.loads(raw)

    def request(self, drone, context):
        role = context["role"]
        profile = STYLES[drone]
        schema = {"type": "object", "properties": {
            "action": {"type": "string", "enum": list(allowed_actions(drone, role))},
            "tempo": {"type": "string", "enum": list(TEMPOS)},
            "reason": {"type": "string", "maxLength": 80}},
            "required": ["action", "tempo", "reason"], "additionalProperties": False}
        system = (f"You are {profile.name}, a drone dancer with Classical Ballet style." if drone == 0 else
                  f"You are {profile.name}, a drone dancer with Krump style.")
        system += (" Select a phrase reacting to measured partner motion. Ballet: elevated flowing arcs. "
                   "Krump: low sharp accents. Mirror=current motion, echo=delayed motion, reply=transform a motif. "
                   "Keep your style and vary recent choices. Inputs are position estimates, not images. "
                   "Python owns flight and safety. JSON only; reason under 45 characters.")
        response = self._http("/api/chat", {
            "model": self.model, "stream": False, "think": False, "format": schema,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps({"observations": context,
                                                                   "your_recent_choices": self.memory[drone]}, allow_nan=False, separators=(",", ":"))}],
            "options": {"temperature": 0.3, "num_predict": 80, "num_ctx": 2048}, "keep_alive": "30m"})
        if response.get("done") is not True or response.get("done_reason") != "stop":
            raise ValueError("Incomplete or truncated model answer")
        raw = response["message"]["content"]
        choice = validate_choice(json.loads(raw), drone, role)
        return choice, {"raw_content": raw, "eval_count": response.get("eval_count"),
                        "total_duration_ns": response.get("total_duration"), "model": response.get("model")}

    def prepare(self):
        """Verify the exact installed model and warm it before any physical takeoff."""
        tags = self._http("/api/tags")
        model = next((m for m in tags.get("models", []) if m.get("name") == self.model), None)
        if model is None:
            raise RuntimeError(f"Ollama model {self.model!r} is not installed; run ollama pull {self.model}")
        details = self._http("/api/show", {"model": self.model})
        self.metadata.update(digest=model["digest"], details=details.get("details"), warmup=[])
        # A load-only request avoids spending flight time loading model weights.
        self._http("/api/generate", {"model": self.model, "stream": False, "keep_alive": "30m"}, timeout=30)
        for i in range(2):
            context = {"role": "leader" if i == 0 else "follower", "dance_t": 0,
                       "partner_motion": "still", "instruction": "Choose an opening invitation or response."}
            start = time.monotonic()
            choice, stats = self.request(i, context)
            self.metadata["warmup"].append({"drone": i, "choice": choice.__dict__,
                                            "wall_seconds": time.monotonic() - start, **stats})
        self.thread = threading.Thread(target=self._run, daemon=True, name="ollama-phrase-planner")
        self.thread.start()
        return self.metadata

    def _run(self):
        while not self.stop.is_set():
            try:
                job = self.tasks.get(timeout=0.1)
            except Empty:
                continue
            if self.stop.is_set():
                break
            i, context, issued_wall = job
            # The second dancer may wait while the shared GPU serves the first.
            # Refresh its observation packet immediately before starting inference.
            if self.latest[i] is not None:
                context, issued_wall = self.latest[i]
            outcome = {"drone": i, "context": context, "issued_wall": issued_wall}
            try:
                if time.monotonic() - issued_wall > self.max_age:
                    raise TimeoutError("Observation expired while queued")
                choice, stats = self.request(i, context)
                outcome.update(choice=choice, stats=stats)
            except Exception as ex:
                outcome["error"] = f"{type(ex).__name__}: {str(ex)[:240]}"
            outcome["latency_s"] = time.monotonic() - issued_wall
            self.results.put_nowait(outcome)  # at most one outstanding job per dancer

    def submit(self, drone, context):
        t = context["dance_t"]
        self.latest[drone] = (context, time.monotonic())
        if self.thread is None or self.stop.is_set() or self.pending[drone] or t - self.last_submit[drone] < self.interval:
            return
        self.tasks.put_nowait((drone, context, time.monotonic()))
        self.pending[drone], self.last_submit[drone] = True, t

    def drain(self):
        outcomes = []
        while True:
            try:
                outcome = self.results.get_nowait()
            except Empty:
                return outcomes
            self.pending[outcome["drone"]] = False
            outcomes.append(outcome)

    def remember(self, drone, choice):
        self.memory[drone].append({"action": choice.action, "tempo": choice.tempo})
        self.memory[drone] = self.memory[drone][-3:]

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=0.2)


def add_arguments(parser):
    parser.add_argument("--llm-model", help="Enable local Ollama phrase agents, e.g. lfm3:latest")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")


def from_arguments(args):
    if not args.llm_model:
        return None
    planner = OllamaPlanner(args.llm_model, args.ollama_url)
    try:
        planner.prepare()
    except Exception:
        planner.close()
        raise
    return planner


def main():
    parser = argparse.ArgumentParser(description="Verify and warm both local dance agents; sends no flight commands")
    add_arguments(parser)
    args = parser.parse_args()
    args.llm_model = args.llm_model or "lfm3:latest"
    planner = from_arguments(args)
    try:
        print(json.dumps(planner.metadata, indent=2))
    finally:
        planner.close()


if __name__ == "__main__":
    main()
