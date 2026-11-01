# Partner-responsive drone duet

The same `duet/mission.py` / `duet/choreography.py` policy runs in the hardware adapter, original Isaac recorder hooks and local Metal/MuJoCo simulator.

## Classical Ballet vs Krump

| Dancer | Leading vocabulary | Style retained while responding |
| --- | --- | --- |
| Ari, orange pad: Classical Ballet | Sustained adagio arcs, elevated arabesques and broad port-de-bras sweeps | Elevated, amplified travel with a 0.65 s smoothing time constant; continuous phrasing |
| Sol, cyan pad: Krump | Low stomps, strong traveling jabs and chest-pop height accents | Amplified horizontal responses quantized into 18 cm / 12 cm accents; low center; 0.65 s braking holds every 2 s |

Human dance vocabulary becomes whole-drone travel, rather than literal human articulation. Ballet target slew is 0.32 m/s; Krump target slew is 0.80 m/s. The organizers' position controller and RC limits determine actual speed. Krump holds send zero RC through the stock velocity-control model, so the rigid body decelerates rather than freezing in place. Cameras continue facing the room tags; there are no flips or yaw spins.

## How they interact

Each dancer has its own style, seeded random generator, move history, phrase state and decision scores. They observe measured positions relative to the pads, retain 16 seconds of observations, and estimate partner direction/speed over an 0.8 s window.

- **Lead:** score phrases for novelty and fit to the partner's measured motion. Reconsider after seven seconds. Slow progression to 70% when reflected displacement differs from the partner by more than 30 cm.
- **Mirror:** reflect the partner's observed displacement across the lane center plane, then apply the responder's style. This is an interpretation rather than an exact geometric copy.
- **Echo:** interpret the partner's measured movement from 1.2 seconds earlier, interpolating the observation buffer.
- **Reply:** capture the previous three seconds of partner movement, rotate that motif into an answering phrase and replay it over four seconds through the responder's style. Future observations cannot rewrite the captured motif.

Ballet smooths and elevates **all** follower modes. Krump quantizes, lowers and punctuates **all** follower modes. A dancer retains its own style when answering a partner with a different style.

The follower reconsiders every four seconds. Scores combine style preferences, partner speed, available history, novelty and seeded tie breaking. Ari starts. A shared coordinator permits a leadership handoff after at least seven seconds and measured follower speed above 1.2 cm/s for 0.8 s. A stationary follower does not cause a timed handoff.

This is feedback-driven, rule-based autonomy. LFM, learning and music-driven control are unimplemented. The soundtrack is added during MP4 encoding and does not affect the mission.

## Localization and limits

Both policies run on one offboard computer. Each Tello camera localizes against mapped room AprilTags using the organizers' tracker. Shared state gives each policy its partner's estimated position; separate Wi-Fi interfaces carry RC commands. The drones do not visually recognize or directly communicate with each other.

Targets allow ±70 cm in X and ±42 cm in Z around hover, 45 cm outward and 10 cm inward per lane. Target lane separation remains at least 1.40 m. Horizontal RC cap is 35, with the original vertical/yaw caps 20/25. Measured envelope, predictive separation, stale-fix, battery, status and watchdog guards remain active. Stale fixes pause choreography and memory; persistent failure requests landing.

The local simulator uses delayed geometric tag visibility, ideal velocity/yaw and nominal dynamics without random detection noise. Physical flight remains untested.

## Measured validation

```sh
python -m unittest discover -s tests -v
python -m duet.metal_record --simulate-only --output-dir outputs/duet-check
```

The tests cover causal responses, captured memory, style persistence, RC holds, feedback-dependent handoffs, stale-fix freezing, deployment guards, original controller integration and a complete rigid-body flight. The seed-7 integration test requires over 80 cm of actual X travel for each drone, over 25 cm of Ballet height travel, a mean height contrast above 30 cm, sustained Ballet motion and measurable Krump braking. Increasing target amplitudes alone cannot satisfy these checks.

| Integrated dance motion, seed 7 | Ballet | Krump |
| --- | --- | --- |
| Forward/back peak-to-peak | 0.847 m | 0.878 m |
| Sideways peak-to-peak | 0.239 m | 0.255 m |
| Height peak-to-peak | 0.278 m | 0.271 m |
| Mean height | 1.405 m | 1.059 m |
| Time below 2.5 cm/s | 1.8% | 12.7% |

Krump mean speed falls from 0.110 to 0.033 m/s across the holds. The seed-7 run uses all four interaction modes for both dancers and three leadership handoffs. Seeds 7, 1 and 13 all complete without drone contact; lowest separation across them is 1.502 m. These are nominal simulator results, excluding takeoff/landing, rather than hardware measurements.

[Validation data](../reports/choreography-check.json), [MP4](../media/drone-duet-ballet-krump.mp4), and [provenance](../media/drone-duet-ballet-krump.provenance.json) record the checked version.
