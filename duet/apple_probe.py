"""Verify the experimental Apple port and original organizer controller separately.

This is a compute/simulation smoke check. It does not implement a replacement renderer.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import platform
import subprocess
import sys
from pathlib import Path

from .upstream import ROOT, UPSTREAM, verify

APPLE_REVISION = "c490515ae250ef5f01a432b56888841fb5665845"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "outputs/apple-isaac/probe.json")
    args = parser.parse_args()
    import mlx.core as mx
    import torch
    import isaaclab
    from isaaclab.backends.mac_sim import MacQuadcopterEnv, MacQuadcopterEnvCfg

    fork = ROOT / "vendor/isaaclab-mlx"
    rev = subprocess.check_output(["git", "-C", str(fork), "rev-parse", "HEAD"], text=True).strip()
    if rev != APPLE_REVISION:
        raise RuntimeError("Apple fork revision differs from the inspected version")
    if not mx.metal.is_available():
        raise RuntimeError("Apple Metal GPU is unavailable to MLX")
    mx.set_default_device(mx.gpu)
    matrix = mx.ones((128, 128)) @ mx.ones((128, 128))
    mx.eval(matrix)
    assert float(matrix[0, 0].item()) == 128

    env = MacQuadcopterEnv(MacQuadcopterEnvCfg(num_envs=2, episode_length_s=5, seed=7))
    obs, _ = env.reset()
    assert obs["policy"].shape == (2, 12)
    # Analytic neutral thrust holds two independent reference quadcopters at 1 m.
    # These are the community port's task instances, not a coupled Tello room scene.
    hover = 2 / env.cfg.thrust_to_weight - 1
    actions = mx.array([[hover, 0, 0, 0], [hover, 0, 0, 0]], dtype=mx.float32)
    for _ in range(100):
        obs, reward, terminated, truncated, _ = env.step(actions)
        mx.eval(obs["policy"], reward, terminated, truncated)
        assert not bool(mx.any(terminated).item())
    pos = env.sim_backend.root_pos_w.tolist()
    assert all(abs(p[2] - 1) < 0.01 for p in pos)

    # Import ONLY the original pure-torch controller file. Importing its enclosing
    # simulator package would require Omniverse, which this Mac does not provide.
    verify()
    source = UPSTREAM / "simulation_infra/source/action_space_kit/action_space_kit/control/tello_dynamics.py"
    spec = importlib.util.spec_from_file_location("organizer_tello_dynamics_probe", source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    cfg = module.TelloDynamicsCfg(domain_randomization=False, latency_steps=[0])
    controller = module.TelloCascadeController(cfg, 2, 0.087,
        torch.diag(torch.tensor([0.000068, 0.000068, 0.00013])), 0.002, device)
    zero = torch.zeros((2, 3), device=device)
    quat = torch.tensor([[1., 0, 0, 0]] * 2, device=device)
    controller.set_command(torch.zeros((2, 4), device=device))
    for _ in range(100):
        force, torque = controller.compute(zero, quat, zero, zero)
    assert bool(torch.isfinite(force).all().item()) and bool(torch.isfinite(torque).all().item())
    assert bool((force[:, 2] > 0).all().item())

    payload = {
        "platform": {"os": platform.system(), "architecture": platform.machine()},
        "apple_fork": {"repository": "https://github.com/RobotFlow-Labs/IsaacLab-mlx", "revision": rev,
                       "package_version": isaaclab.__version__},
        "mlx": {"metal_available": mx.metal.is_available(), "device": str(mx.default_device()),
                "device_info": mx.device_info(), "gpu_matrix_check": "passed"},
        "quadcopter_smoke": {"instances": 2, "steps": 100, "simulated_seconds": 100 * env.step_dt,
                            "final_positions": pos, "capabilities": dataclasses.asdict(env.sim_backend.capabilities),
                            "same_physics_room": False},
        "original_tello_controller": {"revision": verify(), "device": device,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "steps": 100,
            "force_b": force.cpu().tolist(), "torque_b": torque.cpu().tolist(),
            "full_rigid_body_simulation": False},
        "original_isaac_renderer_available": False,
        "mp4_produced": False,
        "limitation": "Community mac-sim has no Omniverse viewport, cameras, contacts or original Tello room support.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    print("Report:", args.out)


if __name__ == "__main__":
    main()
