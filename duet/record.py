"""Run the organizers' original room MP4 recorder with small, auditable policy hooks."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .upstream import ROOT, REVISION, UPSTREAM, verify


def prepare(out_dir):
    verify()
    source_path = UPSTREAM / "simulation_infra/scripts/record_room.py"
    original = source_path.read_text()
    source = original
    replacements = [
        ('choices=["policy", "zero"]', 'choices=["policy", "zero", "duet"]'),
        ('    cfg.debug_vis = True\n', '    cfg.debug_vis = True\n    from duet.isaac_pilot import configure, DuetPilot\n    configure(cfg)\n'),
        ('    else:\n        head = head or "zero sticks"',
         '    elif args.pilot == "duet":\n        pilot = DuetPilot(u, args.seed)\n        head = "Autonomous duet | original Action Space / Isaac renderer"\n        act = pilot.act\n    else:\n        head = head or "zero sticks"'),
        ('            capture(rec)\n', '            if args.pilot == "duet":\n                pilot.annotate(rec)\n            capture(rec)\n'),
        ('    print(f"[rec] wrote {args.out} ({os.path.getsize(args.out)} bytes)", flush=True)\n',
         '    print(f"[rec] wrote {args.out} ({os.path.getsize(args.out)} bytes)", flush=True)\n    if args.pilot == "duet":\n        pilot.save(args.out + ".duet.json")\n'),
        ('"overview": ((9.4, 0.0, 2.5), (3.0, 0.0, 0.6), 15.0)',
         '"overview": ((5.6, 0.0, 2.4), (2.5, 0.0, 1.0), 20.0)'),
    ]
    for old, new in replacements:
        if source.count(old) != 1:
            raise RuntimeError("Pinned recorder hook did not match: " + old[:100])
        source = source.replace(old, new, 1)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated = out_dir / "record_room_duet.py"
    generated.write_text(source)
    compile(source, str(generated), "exec")
    diff = "".join(difflib.unified_diff(original.splitlines(True), source.splitlines(True),
                                     fromfile="organizer/record_room.py", tofile="duet/record_room.py"))
    (out_dir / "recorder-hooks.patch").write_text(diff)
    (out_dir / "renderer-provenance.json").write_text(json.dumps({
        "repository": "https://github.com/jaromero3rd/Action_Space", "revision": REVISION,
        "source": str(source_path.relative_to(ROOT)),
        "original_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "executed_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "changes": "two-drone scene/start, duet pilot hook, camera framing and original-panel labels",
        "upstream_checkout_modified": False,
    }, indent=2) + "\n")
    return generated


def check_runtime():
    problems = []
    for name in ("isaaclab", "torch", "cv2", "stable_baselines3", "imageio_ffmpeg"):
        if importlib.util.find_spec(name) is None:
            problems.append("missing Python package: " + name)
    gpu = shutil.which("nvidia-smi")
    if not gpu:
        problems.append("NVIDIA GPU/driver unavailable (nvidia-smi missing)")
    elif subprocess.run([gpu, "--query-gpu=name", "--format=csv,noheader"], capture_output=True, timeout=10).returncode:
        problems.append("NVIDIA GPU/driver check failed")
    asset = os.environ.get("TELLO_USD_PATH", "")
    if not asset or not Path(asset).is_file():
        problems.append("TELLO_USD_PATH must point to the organizers' converted tello.usd")
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true", help="Generate original-recorder hooks, no Isaac required")
    parser.add_argument("--out", type=Path, default=ROOT / "outputs/videos/duet-isaac.mp4")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    generated = prepare(out.parent / "recorder")
    print("Original organizer recorder prepared:", generated, flush=True)
    if args.prepare_only:
        return 0
    problems = check_runtime()
    if problems:
        print("Cannot render through original Isaac stack:\n- " + "\n- ".join(problems), file=sys.stderr)
        return 2
    if any(p.exists() for p in (out, Path(str(out) + ".duet.json"), Path(str(out) + ".room.json"))):
        print("Choose a new --out path; refusing to mix an old video/report with a new run", file=sys.stderr)
        return 2
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(UPSTREAM / "simulation_infra/source/action_space_kit"),
                                           env.get("PYTHONPATH", "")])
    frame_dir = out.parent / "recorder/frames"
    command = [sys.executable, "-u", str(generated), "--pilot", "duet", "--episodes", "1",
               "--max_seconds", "58", "--no_dr", "--hide_waypoints", "--seed", str(args.seed),
               "--out", str(out), "--frame_dir", str(frame_dir), "--report", str(out) + ".room.json"]
    log_path = out.with_suffix(".log")
    print("Rendering original Isaac viewport; log:", log_path, flush=True)
    # Do not set/accept software licenses here; use the host's already configured Isaac environment.
    with log_path.open("w") as log:
        result = subprocess.run(command, cwd=UPSTREAM / "simulation_infra", env=env, stdout=log, stderr=subprocess.STDOUT)
    expected = [out, Path(str(out) + ".duet.json"), Path(str(out) + ".room.json")]
    if result.returncode or not all(p.is_file() and p.stat().st_size for p in expected):
        print("Isaac render failed; inspect " + str(log_path), file=sys.stderr)
        return 1
    trace = json.loads(Path(str(out) + ".duet.json").read_text())
    room = json.loads(Path(str(out) + ".room.json").read_text())
    episodes = room.get("episodes", [])
    if (trace.get("reason") != "duet complete" or not episodes or not episodes[0].get("complete")
            or not episodes[0].get("outcome", {}).get("success")):
        print("Video captured, but duet/landing validation failed; inspect reports and log", file=sys.stderr)
        return 1
    import imageio_ffmpeg
    decoded = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(out),
                              "-frames:v", "1", "-f", "null", "-"], capture_output=True, timeout=30)
    if decoded.returncode:
        print("Captured MP4 failed frame decoding", file=sys.stderr)
        return 1
    print("Recorded:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
