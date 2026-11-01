# Partner-responsive drone duet

The same `duet/mission.py` / `duet/choreography.py` policy runs in the hardware adapter, the original Isaac recorder hooks, and the local Metal/MuJoCo simulator.

## Two styles

| Dancer | Style | Leading phrases | Response preferences |
| --- | --- | --- | --- |
| Ari, orange pad | Hopak-inspired | Rising hop accents, low squat-like dips, broad sweeping travel | Echoes and replies that turn footwork into hop accents |
| Sol, cyan pad | Country line dance-inspired | Two-step travel, side shuffles, rectangular box steps and bows | Mirroring and held steps that answer the partner's hops |

These are playful translations of human dance vocabulary into whole-drone travel. They do not reproduce human footwork or body articulation. All target changes pass through a 0.30 m/s smoothing limit before the organizers' RC controller; hop accents are powered rises and dips, not ballistic jumps or flips. Cameras remain pointed toward the room tags.

## How they interact

Each policy has its own style, seeded random generator, move history, phrase state and decision scores. They observe both drones' measured positions relative to their pads. They retain up to 16 seconds of observations and estimate motion direction and speed over an 0.8-second window.

- **Lead:** choose a phrase from the dancer's own vocabulary, scoring novelty and its fit to the partner's measured direction. Reconsider the phrase after seven seconds. Slow phrase progression to 70% when the partner's reflected displacement differs by more than 30 cm.
- **Mirror:** reflect the partner's currently observed X/Y/Z displacement across the center plane between the two pads. This uses observed motion, not the partner's planned trajectory.
- **Echo:** reflect the partner's motion from 1.2 seconds earlier, interpolating the observation buffer.
- **Reply:** capture the preceding three seconds of partner motion and reinterpret that recorded motif over a four-second answer. Ari answers traveling steps with a sweep and a hop accent. Sol answers hops with reversed travel in held 16 cm steps and a shallow bow. Future observations cannot rewrite an already captured reply.

The follower reconsiders its response every four seconds. Utility scores combine style preferences, current observed partner speed, sufficient history, novelty and a small seeded tie-breaking term. There is no fixed move sequence.

Ari starts the invitation. A shared coordinator keeps exactly one leading role. After at least seven seconds in that role, a sustained measured response from the follower (speed above 1.2 cm/s for 0.8 seconds) permits a handoff. A stationary partner does not trigger a handoff merely because time elapsed. Roles can swap several times; each dancer keeps its own style when leading or reinterpreting a reply.

This is feedback-driven, rule-based autonomy. It is not learning, language-model reasoning or a distributed protocol running onboard the drones. LFM is not connected to this Python policy.

## Localization, coordination and limits

The policies run on a shared offboard computer. Each hardware drone's camera observes mapped room AprilTags; the organizers' tracker supplies its position in a shared coordinate frame. The computer shares state between the two dancer policies and sends RC commands over separate Wi-Fi interfaces. Neither drone visually recognizes its partner or communicates directly with it.

The movement envelope is substantially larger than the shipped clip: targets can travel ±70 cm in X and ±42 cm in Z from the hover point. Lateral travel extends 45 cm outward and at most 10 cm inward, keeping target lanes at least 1.40 m apart. The horizontal RC cap increases from 15 to 35; the original controller's vertical/yaw caps remain 20/25. Target slew increases from 0.10 to 0.30 m/s. These are command limits, not claims that actual motion perfectly tracks the targets.

Existing measured flight-envelope, predictive separation, stale-localization, battery, status and watchdog checks remain active. Stale fixes freeze both choreography time and motion memory; a persistent failure requests pair landing. The simulator uses nominal delayed tag visibility with ideal velocity/yaw; real flight, including these larger commands, remains untested.

Flight JSONL, Isaac pilot logs and local simulation JSON now include each dancer's name, style, mode, gesture, observed partner motion, phrase rate and decision reason. Decision events also include utility scores and role handoffs. These are recorded policy explanations, not fabricated model thoughts.

## Validation without video rendering

```sh
python -m unittest discover -s tests -v
python -m duet.metal_record --simulate-only --output-dir outputs/reactive-duet-check
```

The tests check causal mirroring, delayed echo, captured-motif replies, distinct styles, feedback-dependent handoffs, adaptive pacing, stale-fix freezing, bounded trajectories, controller integration and complete takeoff-to-landing rigid-body simulation. They also require at least 65 cm of actual X travel per drone and 22 cm of Hopak height travel in the nominal seed-7 run, so increasing only target values cannot pass the amplitude check. The shipped [clean MP4](../media/drone-duet-hopak-country.mp4) now shows this larger Hopak/country policy, from ground start through landing.

Three nominal physics runs (seeds 7, 1, 13) completed the mission with no drone contact; the lowest separation across them was 1.587 m. The seed-7 run used all four interaction modes for each drone and passed the lead three times. [Recorded decisions and measurements](../reports/choreography-check.json) include source hashes for the checked policy.

| Actual peak-to-peak travel during the dance, seed 7 | Earlier shipped clip | Current physics run |
| --- | --- | --- |
| Ari forward/back | 0.336 m | 0.760 m |
| Sol forward/back | 0.322 m | 0.869 m |
| Ari height | 0.019 m | 0.281 m |
| Sol height | 0.033 m | 0.100 m |

These are integrated rigid-body positions during the dance, excluding takeoff/landing. They are not target amplitudes or hardware measurements.
