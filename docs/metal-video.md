# Original organizer scene, local Metal MP4

[Watch/download the duet](../media/drone-duet-metal.mp4).

The user approved using the organizers’ scene/code with a local renderer after NVIDIA Isaac Sim proved incompatible with this Apple M4 Mac. This video is rendered by macOS’s built-in `/usr/bin/usdrecord --renderer Metal`, using Apple’s Hydra/Storm USD renderer. It is not the independent Three.js browser demo and is not claimed to be NVIDIA RTX output.

## Result

H.264 MP4, 1280×720, 24 fps, 829 frames, 34.54 seconds. The two drones start hovering, perform 28 seconds of autonomous lane-bounded choreography, return to their pads, and land. Minimum 3D separation is 1.398 m; no drone-to-drone contacts were detected. Maximum tilt is 1.97°. The MP4 was decoded in full and frames from the start, dance and landing were visually checked.

## What actually comes from the organizers

All organizer sources are pinned to `jaromero3rd/Action_Space` commit `cd6536a458c3ba034a727ea00f57adac6bed9471`:

- `tags/spawn.py`: **executed** original `spawn_room`, `spawn_tag`, `spawn_wall`, material/shader and tag placement functions. The only source patch gives `spawn_room` an explicit USD stage argument instead of asking `omni.usd` for the current stage.
- `tags/room_map.py`, `tags/textures.py`, `config/map.yaml`, `config/tags.yaml`: actual mapped geometry and generated original AprilTag bitmaps. One-channel grayscale images are repeated into RGB without changing pixel values because Metal rejects one-channel sRGB textures.
- `TelloRoomEnv._room_walls`: the original wall specification executes directly from its source function.
- `assets/tello/tello.urdf`: the original seven visual primitives, offsets, materials and fixed camera transform are converted literally to USD. No custom drone geometry is substituted. Its base mass, full inertia and collision box feed the local rigid-body engine.
- `control/tello_dynamics.py`, `control/rc_action.py`, `tello_motion_fit.yaml`: original Tello firmware/rotor dynamics, RC mapping, fitted response and 500 Hz control loop, executed without changes.
- `swarm_formation.control`: original feedback controller turns our duet targets into RC commands.
- `tags/sensing.sighting`: original camera visibility geometry and 150 ms positional delay. This nominal demonstration disables random dropouts/noise. Velocity and yaw observations are ideal simulator values.
- `record_room.setup_camera`, `record_room.overlay`: original camera transform and telemetry panel code. Camera framing/lights suit this scene; the unused RL reward label is replaced with minimum separation.

Our code supplies the autonomous mission, source-loading/portability layer, literal URDF-to-USD/MuJoCo conversion, trajectory export, and video orchestration. The local physics backend is **MuJoCo CPU**, rather than Isaac PhysX; rendered poses come from the simulated rigid bodies, not direct animation of target coordinates. All two-drone physics runs in one world with contacts enabled. The camera sphere’s negligible fixed-link mass is omitted; the original base inertia/mass/collision box is retained. Walls are visual; the mission’s measured flight envelope guards room limits.

The new lane-bounded mission is a smaller physical-flight design than the browser’s large paths. It uses seeded procedural choices and measured partner response, not LFM3 or trained-policy weights. Hardware safety and transfer have not been established by this video.

## Reproduce

Requires Apple Silicon macOS with `/usr/bin/usdrecord` advertising the `Metal` renderer, Python 3.11, and ffmpeg on PATH. Use a normal local terminal with GPU access; Codex sandboxed processes cannot access Metal.

```sh
python3.11 -m venv .venv-metal
source .venv-metal/bin/activate
python -m pip install -r requirements-metal.txt
python -m duet.bootstrap
python -u -m duet.metal_record --output-dir "$PWD/outputs/metal-duet"
```

On the already configured local Mac, use `.venv-isaac-mlx/bin/python` instead. No Isaac/Omniverse package is required for this rendering path.

The command generates `duet.usda`, `simulation.json` (actual frames, RC, tag fixes, mission decisions and contact checks), `provenance.json`, `usd-stage-port.patch`, PNG frames, `render.log`, and `drone-duet.mp4` in the output directory. For Apple USD Tools 0.24.3, numeric frame placeholders produce unpadded filenames; encoding uses `frame_%d.png`.

Useful stages:

```sh
python -u -m duet.metal_record --simulate-only
python -u -m duet.metal_record --render-only
python -u -m duet.metal_record --encode-only
python -m unittest discover -s tests -v
```

The scene/model tests verify original URDF mass, full inertia (accounting for MuJoCo’s principal-frame reordering), collision geometry, two free bodies in one world, source patch scope and expected USD scene contents. The shipped [provenance report](../media/drone-duet-metal.provenance.json) records original source hashes and output metrics. Organizer and URDF licenses remain applicable; see their `THIRD_PARTY.md`.
