# Drone Duet — Classical Ballet vs. Krump

Autonomous choreography for two Ryze Tello EDU drones, built on the Sundai organizers’ [Action_Space](https://github.com/jaromero3rd/Action_Space) flight and simulation stack.

[**Watch the LFM3 Ballet/Krump duet with music**](media/drone-duet-lfm3-ballet-krump.mp4) · [Video provenance](media/drone-duet-lfm3-ballet-krump.provenance.json) · [Actual inference validation](reports/lfm3-check.json)

The MP4 follows both drones from resting on their pads through staggered takeoff, 28 seconds of dancing, role exchanges, return and landing. It uses the organizers’ room-building code, Tello model and controller, with **MuJoCo physics and Apple Metal rendering**. The frames show integrated rigid-body motion from a real-time simulation with **four applied LFM3 choices, two per dancer**, at 1280×720 / 24 fps over 44.29 seconds. Minimum separation was 1.600 m; there was no drone contact. Physical flight remains untested.

The Python controller runs on a **shared Linux flight computer** and sends takeoff, RC and landing commands through two Wi-Fi adapters. The drones retain their stock onboard firmware. Each camera localizes against mapped room AprilTags; the controller uses both position estimates to coordinate the duet. The same mission and dance policy run in the simulators. Optional offboard LFM3 phrase selection is connected to the local physics recorder and Linux flight adapter.

**Current controller:** optional **LFM3-1.7B through local Ollama** gives each dancer its own phrase-selection agent and short-term memory. Python retains trajectories, style, leadership and safety checks. Without `--llm-model`, sustained partner turns, rises, dips and pauses can trigger a new response before the phrase timeout. Partner speed continuously adjusts phrase tempo and echo delay. This remains centralized control with two stateful policies. The linked MP4 records the dynamic policy with actual local LFM3 phrase decisions. The earlier rules-only video is retained separately with its original provenance. [Dynamic validation](reports/dynamic-choreography-check.json).

## The duet

| Dancer | Human dance inspiration | Movement vocabulary |
| --- | --- | --- |
| Ari, orange pad | Classical Ballet | Sustained adagio arcs, elevated arabesques, sweeping port de bras |
| Sol, cyan pad | Krump | Low stomps, forceful traveling jabs, chest-pop accents and deliberate stops |

Style persists through every response. Ballet smooths and elevates the partner’s movement into continuous curves. Krump amplifies horizontal movement into stepped accents, stays low, and sends zero RC for 0.65 of every two phrase seconds to brake into a hold. These are whole-drone interpretations of human dance styles.

| Interaction | What the dancer does |
| --- | --- |
| Lead | Chooses a phrase from its own vocabulary using partner motion and move history |
| Mirror | Reflects the partner’s measured movement, interpreted in its own style |
| Echo | Responds to the partner’s measured movement from 0.8–1.6 seconds earlier, depending on partner speed |
| Reply | Captures a three-second partner motif and transforms it into a four-second answer |

They trade the lead after sustained measured engagement, and the leader slows when the partner lags. Reactive rules provide the default behavior and fallback. With `--llm-model lfm3:latest`, two separate agents choose bounded phrases using local model inference. Both policies share state on the flight computer. The drones infer partner motion through their room-relative position estimates; they do not visually recognize each other or communicate directly.

Targets allow up to 1.40 m of forward/back travel, 55 cm of lateral travel per lane and 84 cm of height travel. Ballet targets slew at 0.32 m/s and Krump targets at 0.80 m/s; firmware response and RC caps determine actual motion. In the new LFM3 clip, the drones travel **0.96 m and 0.89 m forward/back**, with Ballet **34 cm higher on average**. Exact model responses and motion measurements accompany the video. See [policy details](docs/choreography.md) for measured motion and interaction rules.

Music: [“Five Armies” by Kevin MacLeod](https://incompetech.com/music/royalty-free/index.html?isrc=USUAN1100875), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The video uses an excerpt with loudness adjustment and fades. Music is added during encoding and does not drive or synchronize flight. [Full attribution and edit details](media/music/README.md).

## Run LFM3 locally

Ollama on the Mac serves the already installed `lfm3:latest` model (LFM3-1.7B, MLX backend). Use the simulation environment described below:

```sh
# Check the installed model and both dancer prompts.
python -m duet.ollama_agent --llm-model lfm3:latest

# Run a real-time physics flight with actual model decisions, without rendering.
python -u -m duet.metal_record --simulate-only --llm-model lfm3:latest \
  --output-dir outputs/lfm3-duet
```

The model chooses style-specific gestures when leading, or mirror/echo/reply when following, plus a small tempo adjustment. Inference runs asynchronously; invalid, expired or late answers are rejected and reactive rules continue. No model runs onboard the Tellos. [Architecture, deadlines and Linux-to-Mac connection](docs/lfm3.md) · [Actual model-run validation](reports/lfm3-check.json).

## Run with real drones

Requires Python 3.11, Git, the organizers’ Linux networking setup, two USB Wi-Fi adapters, and the actual fleet’s room map and camera calibrations.

```sh
python3.11 -m venv .venv-flight
source .venv-flight/bin/activate
python -m pip install -r requirements-flight.txt
python -m duet.bootstrap
```

Use a deployment configuration directory containing the current `dongles.json`, `map.yaml`, `tags.yaml`, and matching `camera/tello_<id>.yaml` calibrations. The adapter checks each selected drone’s calibration SSID. Mark pads 2.5 m in front of tag 10 and 0.8 m to each side, with both cameras facing the tag. Supply the measured tag-center height using `--tag-height` if it differs from 1.22 m.

The IDs below are examples; replace them with the two configured drones in negative-Y, positive-Y lane order.

```sh
# Read-only preflight; sends no takeoff, RC or landing commands.
python -u -m duet.fly --only 4,8 --config-dir /absolute/path/to/current/config

# Enable physical flight at the cleared flight space.
python -u -m duet.fly --only 4,8 --config-dir /absolute/path/to/current/config --fly
```

The mission performs staggered takeoff, acquires localization, settles, dances for 28 seconds, returns home and lands. It monitors localization freshness, predicted separation, flight envelope, battery, status and loop stalls. Logs include measured positions, targets, RC commands, dancer styles, response choices and role handoffs.

**Physical flight remains untested.** Organizer approval for two drones flying has been granted; simulation does not establish hardware reliability. See [deployment instructions and implemented guards](docs/organizer-stack.md) before using the flight adapter.

## Simulation and MP4

The local pipeline executes the organizers’ USD room-building code, original Tello model, firmware/rotor controller and tag-visibility model. It runs on Apple Silicon without an NVIDIA GPU, using **MuJoCo CPU physics + Apple Hydra Metal rendering**. This is a local port of the organizer stack; the recording is not NVIDIA Isaac PhysX/RTX output. [Source hashes, metrics and video provenance](media/drone-duet-lfm3-ballet-krump.provenance.json) accompany the clip.

The new MP4 shows the dynamic Ballet/Krump policy with actual LFM3 choices, measured-motion responses and three leadership handoffs. It is clean 3D output without telemetry panels; measurements and decisions accompany it in the provenance report. Mapped tags that intersect the floor are suppressed in both local rendering and simulated sensing, rather than appearing as clipped fragments.

Requires Apple Silicon macOS with `/usr/bin/usdrecord` supporting Metal, Python 3.11, Git, and ffmpeg/ffprobe on PATH:

```sh
python3.11 -m venv .venv-metal
source .venv-metal/bin/activate
python -m pip install -r requirements-metal.txt
python -m duet.bootstrap

# Run physics, record decisions and export USD poses without rendering a video.
python -u -m duet.metal_record --simulate-only --output-dir outputs/duet-check

# Simulate with real LFM3 inference, then render and encode with music.
python -u -m duet.metal_record --llm-model lfm3:latest --music --output-dir outputs/duet-video

# Re-encode existing frames with music, without rerunning physics or rendering.
python -u -m duet.metal_record --encode-only --music --output-dir outputs/duet-video
```

The output directory contains `drone-duet.mp4`, USD poses, rendered frames, simulation decisions and encoding provenance. Omit `--music` for a silent video; use `--music-start SECONDS` to choose another excerpt from the bundled track. The checked MP4 is kept in `media/`; generated working files stay in ignored `outputs/`.

[MP4 reproduction and provenance](docs/metal-video.md) describe the organizers-based recording pipeline. A separate [original Isaac recorder](docs/organizer-stack.md#original-3d-visualization--mp4) is available for an already configured Linux NVIDIA Isaac host; that backend remains unvalidated here.

## Verification

```sh
python -m unittest discover -s tests -v
python -m duet.record --prepare-only
```

The flight environment runs policy, hardware-adapter and recorder-preparation checks. Installing `requirements-metal.txt` also enables the rigid-body and USD scene checks; ffmpeg/ffprobe enable the music-encoding check. **All 39 tests pass locally.** The checks cover style contrast in actual simulated motion, measured-motion responses, braking holds, takeoff/landing, flight guards, audio encoding and credits. Three nominal runs of the dynamic policy completed without drone contact; their smallest separation was **1.571 m**. The earlier video’s validation remains in its own provenance report. These checks use simulated sensing and do not replace physical flight validation.

## Code

| Path | Purpose |
| --- | --- |
| `duet/ollama_agent.py` | Local model client, independent dancer contexts, bounded asynchronous inference |
| `duet/choreography.py` | Dance styles, measured-motion responses, memory and role handoffs |
| `duet/mission.py` | Mission phases, target smoothing and pair guards |
| `duet/fly.py` | Linux two-drone deployment, telemetry, watchdog and flight logs |
| `duet/upstream.py`, `duet/bootstrap.py` | Pinned organizer source and coordinate/RC adapter |
| `duet/metal_scene.py`, `duet/metal_record.py` | Original scene/model conversion, local physics checks and MP4 generation |
| `duet/isaac_pilot.py`, `duet/record.py` | Original organizer Isaac recorder integration |
| `tests/` | Policy, deployment, controller, scene and physics tests |
| `media/`, `reports/` | Existing MP4, provenance and measured validation results |

## Organizer sources and license

Organizer source is fetched into ignored `vendor/action-space`, pinned to commit `cd6536a458c3ba034a727ea00f57adac6bed9471`, and checked for modifications before use. The original [drone-race-hacks](https://github.com/jaromero3rd/drone-race-hacks) kit links to this fuller multi-drone stack.

Our code is MIT. Organizer code, external runtimes, Tello assets and music retain their own terms; see [third-party credits](media/THIRD_PARTY.md).
