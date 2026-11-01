# Drone duet on the organizers’ stack

Organizer approval for two drones flying has been granted. No physical flight has been performed by this project. This is an implemented, locally tested adapter awaiting hardware and Isaac validation.

## Original 3D visualization → MP4

The renderer is the organizers’ [`simulation_infra/scripts/record_room.py`](https://github.com/jaromero3rd/Action_Space/blob/cd6536a458c3ba034a727ea00f57adac6bed9471/simulation_infra/scripts/record_room.py), at pinned commit `cd6536a458c3ba034a727ea00f57adac6bed9471`. It uses their mapped room, converted Tello USD asset, PhysX simulation, fitted RC firmware dynamics, Isaac Kit viewport camera, telemetry overlay, and ffmpeg MP4 writer.

Our additions are the two-drone scene configuration, pad starts, duet policy callback, camera framing and panel labels. The recorder is generated from the original source at runtime with six checked replacements. The upstream checkout stays untouched. This is an adaptation of the original renderer, not a claim that the organizers wrote our choreography.

The simulated clip begins already hovering over two marked pads. It includes the dance, return to pads and simulated landing. Positions delivered to the policy come from the original delayed/noisy AprilTag feed; true positions are logged only as diagnostics. Rendering uses nominal dynamics (`--no_dr`), not a robustness qualification. The mission invokes the original firmware descent directly for landing, because the room task’s learned-policy landing gate is intended for race scoring. No trained policy checkpoint or LFM3 inference is used by this controller.

On a Linux NVIDIA host with an **already installed and configured Isaac Sim 5.1 / Isaac Lab 2.3 environment**, activate its Python environment, then from this repo:

```sh
python -m duet.bootstrap
python -m pip install -r requirements-isaac.txt
python -m pip install -e vendor/action-space/simulation_infra/source/action_space_kit
export TELLO_USD_PATH=/absolute/path/to/isaac/assets/tello.usd
python -u -m duet.record --out "$PWD/outputs/videos/duet-isaac.mp4"
```

Follow the organizers’ setup guide for a new Isaac machine. The wrapper does not install Isaac, change system drivers, or accept software licenses on your behalf. It fails before rendering if the runtime/GPU/asset checks fail.

Outputs:

- `outputs/videos/duet-isaac.mp4`: original Isaac viewport encoded as H.264, 1280×720, 30 fps.
- `duet-isaac.mp4.duet.json`: actual policy state, moves, targets, RC, published fixes and diagnostic ground truth.
- `duet-isaac.mp4.room.json`: original recorder’s episode outcome and collision report.
- `duet-isaac.log`: full Isaac process log.
- `recorder/recorder-hooks.patch` and `recorder/renderer-provenance.json`: exact differences and source hashes.

The command checks the actual files and reports after the renderer exits. It requires `duet complete`, a completed episode and successful landing; an Isaac process exit code alone is insufficient. A failed attempt may leave a diagnostic video; it is not a successful duet. Choose a new `--out` path for each retry.

On this Mac you can prepare the original recorder without running its NVIDIA renderer:

```sh
python3 -m duet.bootstrap
python3 -m duet.record --prepare-only
```

**No MP4 has been rendered or visually checked yet.** The [community Apple port is installed and verified](isaac-apple.md), but it lacks the original Omniverse renderer. NVIDIA Isaac Sim has no compatible macOS package, and no remote GPU host is available. The browser recording is not a substitute for the requested original-renderer MP4.

## Physical two-Tello duet

Use the organizers’ Linux drone computer with two USB Wi-Fi adapters, one per Tello, already connected through their networking setup. Each drone has the same IP; the original `SO_BINDTODEVICE` transport keeps the links separate. This does not run from macOS.

From this repo, create the flight environment:

```sh
python3.11 -m venv .venv-flight
source .venv-flight/bin/activate
python -m pip install -r requirements-flight.txt
python -m duet.bootstrap
```

Use the **actual current room map, measured tag sizes, dongle/SSID configuration and matching per-drone camera calibration** in your deployment config directory. The bundled calibration files cannot be assumed correct for another fleet; the adapter rejects missing or mismatched SSID identities instead of using the upstream default-camera fallback.

Mark two floor pads **2.5 m in front of tag 10**, **0.8 m to each side** of its center line. Place each drone on its pad facing tag 10, giving 1.6 m center separation. Tag height defaults to the organizers’ documented 1.22 m; pass the measured current value using `--tag-height` if different. Keep the mapped flight volume clear.

The order of IDs in `--only` fixes lane identity: first = negative world Y, second = positive world Y. World coordinates match the original Isaac room: X out of tag 10, Y tag-right, Z up. This code converts them to the original flight controller’s internal tag frame.

```sh
# Read-only pair preflight: SDK handshake, video, status, batteries, calibration checks.
python -u -m duet.fly --only 4,8 --config-dir /absolute/path/to/current/config

# Physical flight, enabled explicitly by the operator at the cleared flight space.
python -u -m duet.fly --only 4,8 --config-dir /absolute/path/to/current/config --fly
```

The controller performs these phases without speech or pilot prompts:

1. Both pass the organizers’ link, battery and video checks. Takeoffs are staggered 0.5 s; either failure lands the pair.
2. Hover while both acquire fresh mapped tag fixes, up to 8 s. Floor-level cameras may not see elevated tags before takeoff, so placement must be on the marked pads. The measured envelope/lane checks apply on acquisition.
3. Settle at homes, with 1 s stable dwell.
4. Dance for 28 s. Each agent selects mirror/canon/breath/bow independently every 8 s, staggered by 4 s, with choices weighted toward a complementary reply. Canon also follows the partner’s measured vertical motion. Targets move at most 0.1 m/s. This is bounded procedural autonomy, not learned flight or LFM3.
5. Return home, dwell, land both and wait for the organizers’ landing-confirmation routine.

The original `swarm_formation.control` converts targets to bounded RC commands: horizontal cap 15, vertical cap 20 and yaw cap 25. Drones keep cameras facing tag 10 rather than turning toward one another. The dance is deliberately small: approximately 32 cm depth travel, 24 cm lateral travel per lane and 18 cm height travel.

Safety behavior implemented:

- Both hover when either tag fix exceeds 0.35 s, or measured/predicted horizontal spacing falls below 1.2 m. Persistent interruption for 2 s lands both. The dance clock pauses during interruptions.
- Land both below 1.05 m measured horizontal separation, on wrong-lane/envelope violation, status older than 1 s, battery below 20%, nonfinite telemetry, or mission timeout. Preflight battery minimum is the organizers’ 40%.
- Flight envelope: X 1.5–3.6 m, Y −1.4–1.4 m, Z 0.6–1.8 m. Each drone must remain in its own Y half-lane.
- An independent watchdog sends zero RC after a 0.4 s policy-loop stall and initiates pair landing after 2 s.
- Ctrl-C/SIGTERM, exceptions and completion initiate pair landing. A socket failure on one link does not suppress the partner’s landing attempt. Total airborne runtime is limited to 60 s including takeoff.

Landing is an attempted SDK action, not a guarantee on a disconnected radio. An unconfirmed landing is reported for immediate operator intervention. These guards do not establish collision-proof flight: localization, calibration, latency, aerodynamic interaction and flight behavior still need hardware qualification.

## Verification and provenance

```sh
python -m unittest discover -s tests -v
npm test
```

Python tests cover deterministic partner replies, target bounds and slew limits across seeds, stale tracking, telemetry failures, prediction-based stopping, coordinate transforms, original-controller RC output, a simple kinematic closed-loop integration, calibration identity checks, watchdog behavior and original recorder patch/provenance generation. The kinematic test is not Isaac or a drone flight test.

Organizer sources are fetched into ignored `vendor/action-space`, pinned and checked for tracked modifications before use. They are not bundled under this project’s MIT license. Their [THIRD_PARTY.md](https://github.com/jaromero3rd/Action_Space/blob/cd6536a458c3ba034a727ea00f57adac6bed9471/THIRD_PARTY.md) credits the BSD-3-Clause Tello URDF from Clyde McQueen and Peter Mullen’s `tello_ros`; assets and external runtimes retain their own terms.
