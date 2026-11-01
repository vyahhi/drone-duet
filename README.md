# Drone Duet

Autonomous choreography for two Ryze Tello EDU drones, built on the Sundai organizers’ [Action_Space](https://github.com/jaromero3rd/Action_Space) flight and simulation stack.

The Python controller runs on a **shared Linux flight computer** and sends takeoff, RC and landing commands through two Wi-Fi adapters. The drones retain their stock onboard firmware. Each camera localizes against mapped room AprilTags; the controller uses both position estimates to coordinate the duet. The same mission and dance policy run in the simulators.

## The duet

| Dancer | Human dance inspiration | Movement vocabulary |
| --- | --- | --- |
| Ari, orange pad | Classical Ballet | Sustained adagio arcs, elevated arabesques, sweeping port de bras |
| Sol, cyan pad | Krump | Low stomps, forceful traveling jabs, chest-pop accents and deliberate stops |

Style persists through every response: Ballet smooths the partner’s movement into elevated curves; Krump quantizes it into low accents with RC braking holds.

Each dancer can **lead, mirror observed motion, echo it after a delay, or answer a recorded phrase in its own style**. They trade the lead after sustained measured engagement, and the leader slows when the partner lags. Choices depend on motion observations and move history. This is feedback-driven, rule-based autonomy; no LFM inference is implemented.

Targets allow up to 1.40 m of forward/back travel, 55 cm of lateral travel per lane and 84 cm of height travel. Command smoothing and firmware response reduce actual motion. In the nominal seed-7 physics run, the drones traveled **0.85 m and 0.88 m forward/back**. Ballet stays **35 cm higher on average**, while Krump brakes into repeated holds. See [policy details](docs/choreography.md) and [recorded validation](reports/choreography-check.json).

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

[Watch/download the 44.3-second Ballet/Krump MP4](media/drone-duet-ballet-krump.mp4): ground start → staggered takeoff → larger partner-responsive dance → return → landing.

The video executes the organizers’ USD room-building code, original Tello model, firmware/rotor controller and tag-visibility model. The approved local backend is **MuJoCo physics + Apple Hydra Metal rendering**. It is not NVIDIA Isaac PhysX/RTX output. [Source hashes, metrics and video provenance](media/drone-duet-ballet-krump.provenance.json) accompany the clip.

The MP4 shows the current Ballet/Krump policy, including mirrored responses, delayed echoes, replies and three leadership handoffs. It is clean 3D output without telemetry panels; measurements and decisions accompany it in the provenance report. Mapped tags that intersect the floor are suppressed in both local rendering and simulated sensing, rather than appearing as clipped fragments.

On Apple Silicon macOS, install the local simulation dependencies:

```sh
python3.11 -m venv .venv-metal
source .venv-metal/bin/activate
python -m pip install -r requirements-metal.txt
python -m duet.bootstrap

# Run physics, record decisions and export USD poses without rendering a video.
python -u -m duet.metal_record --simulate-only --output-dir outputs/duet-check

# Simulate, render and encode a clean MP4 using macOS USD Metal and ffmpeg.
python -u -m duet.metal_record --music --output-dir outputs/duet-video
```

[MP4 reproduction and provenance](docs/metal-video.md) describe the organizers-based recording pipeline. A separate [original Isaac recorder](docs/organizer-stack.md#original-3d-visualization--mp4) is available for an already configured Linux NVIDIA Isaac host; that backend remains unvalidated here.

Music: [“Five Armies” by Kevin MacLeod](https://incompetech.com/music/royalty-free/index.html?isrc=USUAN1100875), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The excerpt has loudness adjustment and fades; it does not drive the flight policy. [Music credit and edit details](media/music/README.md).

## Verification

```sh
python -m unittest discover -s tests -v
python -m duet.record --prepare-only
```

The flight environment runs policy, hardware-adapter and recorder-preparation checks. Installing `requirements-metal.txt` also enables the rigid-body and USD scene checks. All 27 tests pass with those dependencies installed. Three nominal physics runs completed the larger duet without drone contact; their smallest separation was 1.587 m. These checks use simulated sensing and do not replace physical flight validation.

## Code

| Path | Purpose |
| --- | --- |
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

Our code is MIT. Organizer code, external runtimes and Tello assets and music retain their own terms; see [third-party credits](media/THIRD_PARTY.md).
