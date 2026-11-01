#!/usr/bin/env bash
# Experimental community port. Does not install NVIDIA Isaac Sim or its renderer.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo "This setup is for Apple Silicon macOS only." >&2
  exit 2
fi
apple_revision=c490515ae250ef5f01a432b56888841fb5665845
apple_checkout=vendor/isaaclab-mlx
if [[ ! -d "$apple_checkout" ]]; then
  git clone --filter=blob:none --no-checkout https://github.com/RobotFlow-Labs/IsaacLab-mlx.git "$apple_checkout"
  git -C "$apple_checkout" checkout --detach "$apple_revision"
fi
if [[ "$(git -C "$apple_checkout" rev-parse HEAD)" != "$apple_revision" ]]; then
  echo "Existing Apple port is at a different revision; leaving it untouched." >&2
  exit 2
fi
python3.11 -m venv .venv-isaac-mlx
.venv-isaac-mlx/bin/python -m pip install toml setuptools wheel
.venv-isaac-mlx/bin/python -m pip install --no-build-isolation -e "$apple_checkout/source/isaaclab[macos-mlx,dev]"
.venv-isaac-mlx/bin/python -m duet.bootstrap
.venv-isaac-mlx/bin/python -m duet.apple_probe
