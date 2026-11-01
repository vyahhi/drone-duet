# LFM3 phrase agents through local Ollama

Two agents share one locally loaded **LFM3-1.7B** model, with separate dancer prompts, recent-choice memories and measured observation packets. Ari keeps Classical Ballet; Sol keeps Krump. Inference runs on this Mac through Ollama's MLX GPU backend. Nothing is installed on the stock Tello EDU drones.

## Run on this Mac

Ollama must be running at `http://127.0.0.1:11434`, with `lfm3:latest` installed. The initial setup verified an existing 1.7 GB NVFP4 model; the exact digest, backend and raw responses are recorded in the [live validation report](../reports/lfm3-check.json).

```sh
# If needed on another Mac:
ollama pull lfm3:latest

# Verify model identity and test both prompts; no flight commands.
python -m duet.ollama_agent --llm-model lfm3:latest

# Full real-time physics flight with actual inference; no video rendering.
python -u -m duet.metal_record --simulate-only --llm-model lfm3:latest \
  --output-dir outputs/lfm3-duet

# Render those exact recorded physics poses afterward; no new model decisions.
python -u -m duet.metal_record --render-only --music --output-dir outputs/lfm3-duet
```

Use the Python environment with `requirements-metal.txt` installed for simulation. Model-enabled simulation is paced to real time so a 28-second dance gives the asynchronous agents 28 seconds of real inference time. Omitting `--llm-model` retains the deterministic reactive policy and fast simulation.

The shipped MP4 predates LFM3. Its source hashes and provenance remain unchanged. The model-enabled validation is a separate run; a new LFM3 video has not been rendered.

## Checked result

The checked full flight accepted four real LFM3 choices, two for each dancer. Five other answers were rejected because a leadership epoch changed or a captured reply was still running; there were no HTTP timeouts in this final run. Completed-request latencies were 2.28–3.42 seconds. Both drones completed takeoff, dance, return and landing with no drone contact and minimum 3D separation 1.600 m. This is one nominal local simulation, not hardware or robustness validation. Raw outputs and exact source hashes are in the report.

## Model decisions and controller authority

Every agent receives its role, style, current movement, partner's measured motion/speed, recent pad-relative positions for both drones, and its own recent choices. These are AprilTag-derived position estimates on hardware and delayed geometric tag observations in the local simulator. Images are not sent to LFM3. The model does not visually identify the other drone.

The requested JSON contains only:

```json
{"action":"echo","tempo":"match","reason":"Answer the partner's rising phrase"}
```

Leaders may choose only gestures in their own style: `adagio`, `arabesque`, `port_de_bras` for Ballet; `stomp`, `jab`, `chest_pop` for Krump. Followers choose `mirror`, `echo` or `reply`. Tempo choices are `sustain`, `match` or `accent` (0.95×, 1×, 1.05×). The multiplier affects leader phrase progression and Krump's accent clock; Ballet follower smoothing and the observation-driven echo delay remain in Python. The model's reason is a short generated explanation, not evidence of hidden reasoning or reliable physical understanding.

Python still owns role handoffs, target generation, style interpretation, target slew, RC limits, separation, localization checks, takeoff and landing. The model cannot request coordinates, RC values or flight commands. Model results are applied only during a fresh, guarded dance tick. Replies keep their full captured four-second motif.

## Timing and fallback

One daemon worker serves the shared model; there is at most one outstanding task per dancer. Each agent can request a new decision at most every three dance seconds. The queued observation packet is refreshed immediately before inference begins. HTTP requests time out after four seconds. Results older than 4.5 seconds in either wall time or dance time are discarded, as are results whose leadership role/epoch changed, malformed output, unsupported choices or incomplete generation. Applied choices expire after 4.5 dance seconds. Reactive rules continue when inference fails or expires; the fast flight loop never waits for a model answer.

The model is verified and warmed before any physical takeoff. Startup fails explicitly if the model is missing or the two prompt checks fail. During a flight, later inference failures fall back to rules. The model weights are kept loaded for 30 minutes by Ollama; stopping the duet stops its worker, not the shared Ollama service.

Logs include the model digest, warmup responses, applied/rejected choices, latency, output text, generated reason and each dancer's decision source. `outputs/` contains complete simulation telemetry; the checked report preserves a compact summary and model events. The first prototype hit request deadlines; prompt compaction and refreshed queued observations were tested with actual inference rather than treating a rules-only fallback run as model success.

## Physical deployment

The original multi-dongle flight adapter still requires Linux. To use this Mac's Ollama from that Linux flight computer, create a local SSH tunnel **on Linux**, using the Mac's reachable SSH account:

```sh
ssh -N -L 11434:127.0.0.1:11434 your-mac-ssh-host
```

Then run the existing Linux preflight/flight command with `--llm-model lfm3:latest`. `--ollama-url` accepts only a loopback HTTP origin; no public Ollama listener is needed. Follow the [hardware setup](organizer-stack.md) for the fleet's calibrated maps and dongles. This tunnel and physical LFM3 flight have not been tested here.

```sh
# Read-only preflight including LFM3 startup checks; no takeoff.
python -u -m duet.fly --only 4,8 --config-dir /absolute/path/to/current/config \
  --llm-model lfm3:latest

# Flight at the approved space after hardware setup.
python -u -m duet.fly --only 4,8 --config-dir /absolute/path/to/current/config \
  --llm-model lfm3:latest --fly
```

The original NVIDIA Isaac recorder currently uses the reactive policy; these Ollama CLI flags are implemented for the local physics recorder and the Linux flight adapter.
