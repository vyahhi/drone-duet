# Isaac on this Apple M4 Mac

Installed and verified on November 1, 2026, on the local MacBook Air M4 (10-core GPU, 16 GB unified memory).

## What is installed

The community [RobotFlow-Labs/IsaacLab-mlx](https://github.com/RobotFlow-Labs/IsaacLab-mlx) port at `c490515ae250ef5f01a432b56888841fb5665845` is installed editable from ignored `vendor/isaaclab-mlx`, in isolated `.venv-isaac-mlx`. It does not change `.venv-flight` or install system-wide packages.

Key installed versions: Isaac Lab fork 0.54.3, MLX/MLX-Metal 0.32.4, PyTorch 2.15.0, NumPy 1.26.4. This is a community port, not NVIDIA’s full Isaac Sim application.

Reproduce installation from the project root with Python 3.11 available:

```sh
bash scripts/setup_isaac_apple.sh
```

## Verified locally

- MLX sees `Device(gpu, 0)` / `Apple M4`. An evaluated GPU matrix operation passes.
- The fork’s unmodified `play_quadcopter.py` completes two episodes.
- Its original `test_mac_quadcopter.py` and `test_runtime.py` pass: **34 tests**.
- Two independent quadcopter task instances hold 1 m height for 100 steps / 2 simulated seconds under analytic neutral thrust. They are separate reference tasks, not two Tellos sharing the original mapped room.
- The organizers’ **unmodified** `tello_dynamics.py` runs 100 controller steps for two drones on PyTorch `mps`, with finite forces/torques and hover thrust about 0.8534 N. This checks its firmware/rotor controller, not the complete rigid-body simulator.

Run our compute/controller probe:

```sh
.venv-isaac-mlx/bin/python -u -m duet.apple_probe
```

Detailed output is saved to `outputs/apple-isaac/probe.json`. GPU access is required: the Codex filesystem/process sandbox hid Metal, so GPU runs were performed with approved unsandboxed execution. A normal local terminal can access the GPU.

Run the fork’s original example and tests:

```sh
.venv-isaac-mlx/bin/python -u \
  vendor/isaaclab-mlx/scripts/reinforcement_learning/mlx/play_quadcopter.py \
  --num-envs 2 --episodes 2 --episode-length-s 0.5 --max-steps 100 \
  --thrust-action 0.052631578947 --no-random-actions

.venv-isaac-mlx/bin/python -m pytest \
  vendor/isaaclab-mlx/source/isaaclab/test/backends/test_mac_quadcopter.py \
  vendor/isaaclab-mlx/source/isaaclab/test/backends/test_runtime.py -q
```

## Why the original MP4 recorder still cannot run

The Apple port explicitly reports **`cameras=False` and `contacts=False`** for its quadcopter backend. Its Mac `AppLauncher` creates a placeholder app; it does not start Omniverse Kit or provide its viewport capture API. Its quadcopter simulation discards the `render` argument. Therefore installing it does not provide the organizers’ `TelloRoomEnv`, PhysX scene, AprilTag camera pipeline or original MP4 renderer.

An actual NVIDIA package compatibility check was attempted with:

```sh
.venv-flight/bin/python -m pip install --dry-run 'isaacsim==5.1.0.0' \
  --extra-index-url https://pypi.nvidia.com
```

The NVIDIA installer found Linux ARM64, Linux x86_64 and Windows x86_64 wheels, and failed with `Didn't find wheel for isaacsim 5.1.0.0` on Darwin ARM64. No Isaac Sim package or NVIDIA driver was installed. Official [Isaac Sim requirements](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/requirements.html) require supported NVIDIA RTX hardware; Apple Metal is not an equivalent runtime for those binaries.

This installation makes local MLX quadcopter experiments and the original Tello controller usable. An MP4 made with another renderer would require a separate port and would not be the organizers’ original Isaac visualization. No such substitution or MP4 is claimed here.
