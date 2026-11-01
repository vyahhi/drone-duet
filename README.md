# Drone Duet

**Two independent minds. One shared rhythm.**

A live experiment in autonomous choreography, built for Sundai’s drone hack at Harvard i-labs, November 1, 2026. The browser demo shows two Tello-inspired virtual drones improvising a duet.

The project now also includes a **two-Tello flight adapter** and an **Isaac MP4 recorder using the organizers’ original simulation code**. Organizer approval for two drones flying has been granted. The flight/Isaac controller uses a separate, smaller, lane-bounded dance suited to tag tracking; it does not send the browser’s large trajectories to hardware.

**Video delivered:** [34.5-second drone duet MP4](media/drone-duet-metal.mp4), rendered locally from the organizers’ actual USD room-building code and original Tello URDF. It uses their Tello firmware, RC controller and tag sensor model, with our autonomous duet mission. As approved for this Mac, the backend is **MuJoCo physics + Apple Hydra Metal**, rather than NVIDIA PhysX/RTX. See [render instructions and provenance](docs/metal-video.md).

**Validation status:** browser and Python mission/controller tests pass, including local rigid-body/scene checks. The experimental community IsaacLab-MLX port also runs on this Mac’s M4 GPU; its original quadcopter example and 34 runtime/quadcopter tests pass. Physical flight and the NVIDIA Isaac Sim backend remain unvalidated.

See [Apple Silicon installation and verified limits](docs/isaac-apple.md).

See [physical flight and original-renderer instructions](docs/organizer-stack.md). Prepare the organizers’ pinned recorder locally with:

```sh
python3 -m duet.bootstrap
python3 -m duet.record --prepare-only
```

The browser demo below runs on a Mac or other laptop with WebGL2; it does not require Isaac or drone hardware.

## Run

Requires Node.js 22.12+ (or a current Node 24 LTS release).

```sh
npm ci
npm run dev
```

Open **http://127.0.0.1:5173**. The duet starts automatically. Enable sound to hear the original procedural score. Drag the scene to orbit, scroll to zoom, switch to top/front view, or enter fullscreen. Space pauses/resumes. The reset button starts a new seeded session. Export saves the decision history and session metrics as JSON.

The circular record button captures up to 60 seconds of the 3D canvas as a downloadable WebM (or MP4 where supported). Click again to save sooner. This captures the rendered scene without the HTML overlays or audio.

For a production build:

```sh
npm run build
npm start
```

The server binds to loopback by default. Set `PORT` or `HOST` explicitly if needed. The UI uses optional Google Fonts with system fallbacks; the simulation and synthesized soundtrack need no external service.

## What is autonomous?

Each dancer observes the other’s current movement, position, and velocity, plus the shared musical beat and energy. They choose from six designed motion primitives: **orbit, mirror, weave, ripple, spiral, solo**.

- **Ari, the explorer**, puts more weight on novel moves.
- **Sol, the connector**, puts more weight on complementary replies.
- Each makes an independent decision every eight beats; their decision times are staggered by four beats.
- The default policy scores novelty, partner response, musical energy, variation, and seeded randomness. The order of moves is generated during the session, not scripted.
- The visible conversation displays the actual decisions and their intentions. Local intentions are templated explanations of the selected action; they are not language-model reasoning.

This is high-level autonomous choreography over designed motion primitives. It is **not** a trained flight policy, a physics-accurate Tello digital twin, or a claim of emergent learning. Agents adapt their choices to one another during a session but do not update model weights.

## Optional LFM3 choreography

The application also has a real server-side inference adapter for **LFM3-1.7B** or another model served through an OpenAI-compatible `/chat/completions` endpoint. A text model is sufficient because it receives structured observations from the simulation. No screenshot or vision model is needed for this version.

1. Download/load LFM3 in a compatible local inference runtime (for example, a current LM Studio version that supports the model), and start its model server.
2. Copy `.env.example` to `.env`.
3. Set `DUET_MODEL_BASE_URL` to your endpoint’s API base and `DUET_MODEL_NAME` to the **exact model identifier** exposed by that server. Add `DUET_MODEL_API_KEY` only if required.
4. Restart this application, click **Local autonomy** in the footer, and choose **Use configured model**.

Example configuration:

```dotenv
DUET_MODEL_BASE_URL=http://127.0.0.1:1234/v1
DUET_MODEL_NAME=LFM3-1.7B
```

Each agent sends its own observation and receives a JSON move and short intention. Requests time out after 10 seconds; responses more than eight simulation beats old are rejected. Invalid/failed decisions fall back to the local policy, explicitly labeled **LOCAL FALLBACK**. While waiting, the previous phrase continues. For smooth model-driven choreography, use an endpoint that responds within a phrase (roughly 4–7 seconds depending on the track).

API keys remain in the Node server and are never included in the browser bundle. `.env` is ignored by Git. The endpoint is configured only on the server; browser requests cannot choose an arbitrary upstream URL. Enabling a remote endpoint sends only the simulated dance state to that endpoint. LFM3 is **optional and not bundled**; the default demo uses local policies, not a hidden or simulated model connection. Model weights retain their own licenses.

## Movement and metrics

The fixed 60 Hz simulation uses damped acceleration toward continuously moving phrase targets. Speed and acceleration are limited. Predictive repulsion and a hard minimum-distance projection keep the virtual drones at least **1.35 m** apart. This is a visualization constraint, not a certified physical safety controller.

- **Rhythm affinity:** Pearson correlation between the dancers’ speed magnitudes over up to 480 simulation ticks (8 seconds), mapped from `[-1, 1]` to `[0, 100]`. It measures motion similarity, not artistic quality or beat-tracking accuracy.
- **Partner distance:** current 3D distance between centers.
- **Creative vocabulary:** number of distinct primitives selected by either agent.
- **Decisions made:** total applied phrase choices, excluding their initial moves.

The three tracks are original synthesized loops, with different tempos and energy profiles. A shared beat clock drives the simulation. Audio is scheduled in Web Audio when enabled; browser scheduling latency means this is not a sample-accurate audio/visual synchronization system. Hidden tabs suspend the simulation and sound; returning resumes without catching up elapsed wall time.

## Architecture

| File | Responsibility |
| --- | --- |
| `src/engine.js` | Independent agents, observations, move scoring, motion controller, separation guard, metrics |
| `src/scene.js` | Three.js Tello-inspired models, lit stage, shadows, camera controls, trails, labels |
| `src/audio.js` | Original procedural score via Web Audio |
| `src/main.js` | Controls, telemetry, decision log, inference integration, session export |
| `server.mjs` | Vite development / production static server, private inference proxy |
| `test/engine.test.js` | Partner response, reproducibility, separation, bounded motion, action validation |
| `test/server.test.js` | Production serving, inference protocol, invalid-output handling, credential isolation |

```sh
npm test
```

Tests simulate three tracks across multiple seeds, checking separation and finite/bounded motion at every tick, plus independent decisions and deterministic replay. Browser validation is needed in addition to the engine tests to check WebGL and interaction.

## Relationship to the event toolkit

The browser scene is independently implemented. The Python adapter uses the organizers’ full [Action_Space](https://github.com/jaromero3rd/Action_Space) repository at `cd6536a458c3ba034a727ea00f57adac6bed9471`, which contains the multi-drone infrastructure omitted from the smaller [drone-race-hacks](https://github.com/jaromero3rd/drone-race-hacks) kit.

`duet/fly.py --fly` can send physical takeoff, RC and landing commands through the organizers’ Linux multi-dongle stack. Default mode only performs preflight. `duet/record.py` runs the original Isaac room recorder with audited policy/configuration hooks, retaining its Tello assets, physics, viewport capture and ffmpeg encoder. Source hashes and a patch accompany each prepared recording. The third-party checkout is fetched separately and is not redistributed or relicensed here.

## License

Our code is MIT. Browser drone geometry and soundtrack are original procedural assets. Three.js and Vite retain their respective licenses. Organizer code and Tello assets are separate dependencies under their own terms; see [provenance](docs/organizer-stack.md).
