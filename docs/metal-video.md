# Original organizer scene, local Metal MP4

[Watch/download the LFM3 duet](../media/drone-duet-lfm3-ballet-krump.mp4) · [Earlier rules-only video](../media/drone-duet-ballet-krump.mp4).

The user approved using the organizers’ scene/code with a local renderer after NVIDIA Isaac Sim proved incompatible with this Apple M4 Mac. This video is rendered by macOS’s built-in `/usr/bin/usdrecord --renderer Metal`, using Apple’s Hydra/Storm USD renderer. It is not claimed to be NVIDIA RTX output.

## Result

H.264 MP4, 1280×720, 24 fps, 1,063 frames, 44.29 seconds, with stereo AAC music. The two drones start resting on their pads with motors off. After a 1.5-second ground hold, they take off half a second apart, reach hover, perform 28 seconds of Classical Ballet/Krump choreography, return to their pads, and land. Minimum 3D separation is 1.600 m; no drone-to-drone contacts were detected. Maximum tilt is 2.41°. The three leadership handoffs occur at 14.30, 21.35 and 28.35 seconds.

The oblique camera uses the original recorder’s camera construction, positioned inside the room to reveal forward/back travel.

The delivered video contains the clean 3D frames, without the black diagnostic header or bottom telemetry panel. Measurements, policy choices and provenance are separate JSON data. The earlier four-move video remains recoverable from Git history at commit `2f4eed2`.

The original firmware/rotor model drives the ascent; poses are integrated by MuJoCo, not animated to target heights. The local takeoff procedure approximates the SDK's onboard altitude control using ideal simulated altitude; it is not a reproduction of proprietary Tello takeoff firmware. Both takeoffs complete at 6.35 seconds. The MP4 is decoded in full and frames from the ground start, takeoff, dance and landing are visually checked.

Music is [“Five Armies” by Kevin MacLeod](https://incompetech.com/music/royalty-free/index.html?isrc=USUAN1100875), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The excerpt starts at 32 seconds, spans the video, has loudness adjustment, 1.5-second fade in and 2-second fade out. It is background music, not beat-synchronized flight control. Attribution is embedded in MP4 metadata and the provenance JSON; see [music credits](../media/music/README.md).

## What actually comes from the organizers

All organizer sources are pinned to `jaromero3rd/Action_Space` commit `cd6536a458c3ba034a727ea00f57adac6bed9471`:

- `tags/spawn.py`: **executed** original `spawn_room`, `spawn_tag`, `spawn_wall`, material/shader and tag placement functions. The only source patch gives `spawn_room` an explicit USD stage argument instead of asking `omni.usd` for the current stage.
- `tags/room_map.py`, `tags/textures.py`, `config/map.yaml`, `config/tags.yaml`: actual mapped geometry and generated original AprilTag bitmaps. One-channel grayscale images are repeated into RGB without changing pixel values because Metal rejects one-channel sRGB textures.
- `TelloRoomEnv._room_walls`: the original wall specification executes directly from its source function.
- `assets/tello/tello.urdf`: the original seven visual primitives, offsets, materials and fixed camera transform are converted literally to USD. No custom drone geometry is substituted. Its base mass, full inertia and collision box feed the local rigid-body engine.
- `control/tello_dynamics.py`, `control/rc_action.py`, `tello_motion_fit.yaml`: original Tello firmware/rotor dynamics, RC mapping, fitted response and 500 Hz control loop, executed without changes.
- `swarm_formation.control`: original feedback controller turns our duet targets into RC commands.
- `tags/sensing.sighting`: original camera visibility geometry and 150 ms positional delay. This nominal demonstration disables random dropouts/noise. Velocity and yaw observations are ideal simulator values.
- `record_room.setup_camera`: original camera transform code, with duet framing. The original `overlay` function remains available through `--telemetry` for a separate diagnostic MP4; it is not applied to the delivered clean video.

Our code supplies the autonomous mission, source-loading/portability layer, literal URDF-to-USD/MuJoCo conversion, trajectory export, and video orchestration. The local physics backend is **MuJoCo CPU**, rather than Isaac PhysX; rendered poses come from the simulated rigid bodies, not direct animation of target coordinates. All two-drone physics runs in one world with contacts enabled. The camera sphere’s negligible fixed-link mass is omitted; the original base inertia/mass/collision box is retained. Walls are visual; the mission’s measured flight envelope guards room limits.

Floor cleanup suppresses tag IDs 1, 2, 4, 7, 11, 22 and 24 because their original mapped face intersects or lies below the added Z=0 floor. This avoids showing the partial prints seen in the earlier video. The source map and remaining tag poses are unchanged. The local geometric sensor uses the same visible subset (5, 6, 8, 9, 10, 12, 23, 25), so it does not receive fixes from hidden tags. This is a documented scene adaptation, not a correction to the physical room's calibration.

The lane-bounded mission combines measured partner responses, reactive rules and bounded phrase decisions from local LFM3-1.7B through Ollama. The model does not generate coordinates or RC commands. Hardware safety and transfer have not been established by this video.

## Dance selection and coordination

The controller uses debounced movement cues, speed-adapted tempo and variable echo delay. Two local LFM3 agent contexts choose high-level phrases asynchronously. The new MP4 renders the actual integrated poses from the checked real-time inference run; it does not rerun or invent decisions during rendering. [Model identity, raw outputs and validation](../reports/lfm3-check.json) accompany it.

**The shipped MP4 records the LFM3-enabled Ballet/Krump [partner-responsive policy](choreography.md)** with four applied model choices, two per dancer. Ari selects adagio at 10.80 s and 27.30 s; Sol selects stomp at 19.90 s and reply at 24.90 s. Five other model answers are rejected because roles changed or a captured reply was unfinished. Reactive rules fill the remaining intervals. The seed-7 recording shows 0.957 m / 0.889 m of actual forward/back travel and mean heights 1.403 m / 1.059 m. Inference ran during the simulation; rendering replays its recorded physical state. There is no training or learning.

Both dancer policies run in one computer process and share move/state information. The hardware adapter receives each drone's camera stream, uses the organizers' AprilTag tracker to estimate its position in the shared room map, and sends RC commands over separate Wi-Fi interfaces. It infers partner position from the two room-relative estimates. The drones do not visually detect each other or communicate directly. In this nominal video, tag visibility and 150 ms delay use the original geometric sensor model, with ideal velocity/yaw and no pixel-detection pipeline or random missed detections.

[Local LFM3 phrase agents](lfm3.md) are wired into the local recorder and Linux flight adapter. The earlier rules-only MP4 remains separately available with its original provenance. Physical flight remains untested.

## Reproduce

Requires Apple Silicon macOS with `/usr/bin/usdrecord` advertising the `Metal` renderer, Python 3.11, and ffmpeg on PATH. Use a normal local terminal with GPU access; Codex sandboxed processes cannot access Metal.

```sh
python3.11 -m venv .venv-metal
source .venv-metal/bin/activate
python -m pip install -r requirements-metal.txt
python -m duet.bootstrap
python -u -m duet.metal_record --llm-model lfm3:latest --music --output-dir "$PWD/outputs/metal-duet"
```

Ollama must be running locally with `lfm3:latest` installed. No Isaac/Omniverse package is required for this rendering path. A new live inference run may select different phrases and timings; the published video is tied to its recorded responses and source hashes.

The command generates `duet.usda`, `simulation.json` (actual frames, RC, tag fixes, mission decisions and contact checks), `provenance.json`, `usd-stage-port.patch`, PNG frames, `render.log`, and `drone-duet.mp4` in the output directory. For Apple USD Tools 0.24.3, numeric frame placeholders produce unpadded filenames; encoding uses `frame_%d.png`.

Use `--music` to include the bundled licensed track; `--music-start SECONDS` selects its excerpt. Encoding records attribution, source hash, exact filters and the full-decode result in `drone-duet.encoding.json`. Omit `--music` for a silent MP4.

For the organizers' diagnostic panels, add `--telemetry`. This writes `drone-duet-telemetry.mp4` using separate `telemetry-frames/` copies, preserving the clean rendered PNGs and MP4. Telemetry encoding is repeatable without accumulating overlays on the source frames.

Useful stages:

```sh
python -u -m duet.metal_record --simulate-only --llm-model lfm3:latest
python -u -m duet.metal_record --render-only --music
python -u -m duet.metal_record --encode-only --music
python -m unittest discover -s tests -v
```

The scene/model tests verify original URDF mass, full inertia (accounting for MuJoCo’s principal-frame reordering), collision geometry, two free bodies in one world, source patch scope and expected USD scene contents. The shipped [provenance report](../media/drone-duet-lfm3-ballet-krump.provenance.json) records original source hashes and output metrics. Organizer and URDF licenses remain applicable; see their `THIRD_PARTY.md`.
