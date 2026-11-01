"""Checks for the user-approved local USD/MuJoCo port (optional dependencies)."""
import importlib.util
import math
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

READY = all(importlib.util.find_spec(name) is not None for name in ("mujoco", "pxr", "torch"))


@unittest.skipUnless(READY, "requires requirements-metal.txt")
class MetalPortTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires ffmpeg/ffprobe")
    def test_music_encode_contains_audio_credit_and_preserves_clean_frames(self):
        import cv2
        import numpy as np
        from duet.metal_record import encode
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "frames").mkdir()
            for i in range(48):
                cv2.imwrite(str(out / f"frames/frame_{i}.png"), np.full((64, 64, 3), 170, dtype=np.uint8))
            original = (out / "frames/frame_0.png").read_bytes()
            report = {"fps": 24, "frame_count": 48}
            video = out / "duet.mp4"
            encode(out, report, video, music=True)
            probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams",
                                                       "-show_format", "-of", "json", str(video)], text=True))
            audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
            self.assertEqual(audio["codec_name"], "aac")
            self.assertEqual(audio["sample_rate"], "48000")
            self.assertAlmostEqual(float(audio["duration"]), 2.0, delta=0.03)
            self.assertIn("Five Armies", probe["format"]["tags"]["copyright"])
            self.assertEqual((out / "frames/frame_0.png").read_bytes(), original)
            provenance = json.loads((out / "duet.encoding.json").read_text())
            self.assertFalse(provenance["music"]["beat_synchronized"])
            self.assertEqual(provenance["full_decode_check"], "passed")
            with self.assertRaises(ValueError):
                encode(out, report, out / "invalid.mp4", music=True, music_start=155)

    def test_optional_telemetry_preserves_clean_frames_and_is_repeatable(self):
        import cv2
        import numpy as np
        from duet.metal_record import telemetry_frames
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "frames").mkdir()
            original = out / "frames/frame_0.png"
            cv2.imwrite(str(original), np.full((720, 1280, 3), 170, dtype=np.uint8))
            clean_bytes = original.read_bytes()
            report = {"min_separation_m": 1.6, "frames": [{"row": 0, "t": 0, "positions": [(0, 0, 0)] * 2}],
                      "rows": [{"phase": "ground", "moves": ["lead", "mirror"],
                                "fix_ages": [None, None], "rc": [(0, 0, 0, 0)] * 2}]}
            destination = telemetry_frames(out, report) / "frame_0.png"
            first = destination.read_bytes()
            telemetry_frames(out, report)
            self.assertEqual(original.read_bytes(), clean_bytes)
            self.assertEqual(destination.read_bytes(), first)
            self.assertEqual(int(cv2.imread(str(destination))[0, 0, 0]), 0)
            self.assertEqual(int(cv2.imread(str(original))[0, 0, 0]), 170)

    def test_rigid_model_preserves_original_urdf_mass_inertia_and_geometry(self):
        from duet.metal_record import rigid_bodies_from_urdf
        from duet.metal_scene import UPSTREAM
        import numpy as np
        import mujoco
        path = UPSTREAM / "simulation_infra/assets/tello/tello.urdf"
        model, data, ids, mass, inertia = rigid_bodies_from_urdf(path, 0.002)
        original = ET.parse(path).find("link[@name='base_link']")
        self.assertEqual(mass, float(original.find("inertial/mass").attrib["value"]))
        self.assertEqual(model.nq, 14)  # two free rigid bodies in ONE world
        self.assertEqual(len(ids), 2)
        self.assertAlmostEqual(model.opt.timestep, 0.002)
        for body in ids:
            np.testing.assert_allclose(model.body_mass[body], mass)
            # MuJoCo diagonalizes/reorders inertia into its own inertial frame.
            rotation = np.zeros(9)
            mujoco.mju_quat2Mat(rotation, model.body_iquat[body])
            rotation = rotation.reshape(3, 3)
            np.testing.assert_allclose(rotation @ np.diag(model.body_inertia[body]) @ rotation.T,
                                       np.diag(inertia), atol=1e-12)
            collision = next(i for i, b in enumerate(model.geom_bodyid) if b == body)
            original_size = [float(v) / 2 for v in original.find("collision/geometry/box").attrib["size"].split()]
            np.testing.assert_allclose(model.geom_size[collision], original_size)
        self.assertGreater(math.dist(data.xpos[ids[0]], data.xpos[ids[1]]), 1.5)
        for body in ids:
            self.assertAlmostEqual(data.xpos[body][2], original_size[2] + 0.011)

    def test_ground_takeoff_dance_and_landing_use_integrated_rigid_bodies(self):
        from duet.metal_record import simulate
        with tempfile.TemporaryDirectory() as tmp:
            report = simulate(Path(tmp), dance_seconds=28)
        self.assertTrue(report["completed"])
        self.assertFalse(report["drone_contacts"])
        rows = report["rows"]
        self.assertEqual(rows[0]["phase"], "ground")
        for row in rows:
            for i, position in enumerate(row["positions"]):
                if row["t"] < 1.5 + i * 0.5:
                    self.assertAlmostEqual(position[2], 0.0315, delta=0.001)
                    self.assertEqual(row["rc"][i], (0, 0, 0, 0))
        self.assertTrue(any(r["phase"] == "takeoff" and r["positions"][0][2] > 0.3
                            for r in rows))
        first_dance = next(r for r in rows if r["phase"] == "dance")
        self.assertTrue(all(p[2] > 1.0 for p in first_dance["positions"]))
        self.assertTrue(all(p[2] < 0.04 for p in report["frames"][-1]["positions"]))
        self.assertGreater(report["takeoff_complete_s"], 2)
        self.assertGreater(report["min_separation_m"], 1.2)
        # Exercise the full feedback loop with tag delay and the original firmware,
        # including role swaps and every measured-motion response mode.
        for i in range(2):
            choices = [e for e in report["events"] if e.get("drone") == i and "move" in e]
            self.assertEqual({e["move"] for e in choices}, {"lead", "mirror", "echo", "reply"})
        self.assertGreaterEqual(sum("handoff" in e for e in report["events"]), 2)
        dance = [row for row in rows if row["phase"] == "dance"]
        for i in range(2):
            travel_x = max(r["positions"][i][0] for r in dance) - min(r["positions"][i][0] for r in dance)
            self.assertGreater(travel_x, 0.80)  # actual rigid-body travel, not target amplitude
        ballet_height = max(r["positions"][0][2] for r in dance) - min(r["positions"][0][2] for r in dance)
        self.assertGreater(ballet_height, 0.25)
        import numpy as np
        positions = np.array([r["positions"] for r in dance])
        speed = np.linalg.norm(np.array([r["velocities"] for r in dance]), axis=2)
        # Measure the executed style, rather than checking style labels alone.
        self.assertGreater(positions[:, 0, 2].mean() - positions[:, 1, 2].mean(), 0.30)
        stops = (speed < 0.025).mean(axis=0)
        self.assertLess(stops[0], 0.05)  # sustained Ballet
        self.assertGreater(stops[1], 0.10)  # Krump stop accents
        holds = np.array([r["dancers"][1]["hold"] for r in dance])
        starts = np.flatnonzero(holds & ~np.roll(holds, 1))
        ends = np.flatnonzero(holds & ~np.roll(holds, -1))
        # Firmware needs time to brake; compare the start/end of each hold.
        self.assertLess(speed[ends, 1].mean(), speed[starts, 1].mean() * 0.50)

    def test_original_usd_scene_is_usable_and_only_portable_stage_hook_is_patched(self):
        from duet.metal_scene import create_scene, visible_tags
        from pxr import Gf, UsdGeom
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            stage, transforms = create_scene(out)
            self.assertTrue(stage.GetPrimAtPath("/World/Room/tag_10/face"))
            self.assertTrue(stage.GetPrimAtPath("/World/RecordCam"))
            self.assertEqual(len(transforms), 2)
            # The original URDF contributes 6 base primitives + 1 camera sphere.
            for i in range(2):
                shapes = [p for p in stage.Traverse() if p.GetPath().pathString.startswith(f"/World/Drone_{i}/")
                          and p.GetName() == "Shape"]
                self.assertEqual(len(shapes), 7)
            self.assertEqual(UsdGeom.GetStageUpAxis(stage), "Z")
            from action_space_kit.tags.room_map import load_room_tags
            tags = load_room_tags(1.22)
            kept = visible_tags(stage, tags)
            self.assertIn(10, kept)
            self.assertNotIn(4, kept)  # the partial AprilTag previously poking through the floor
            for tag_id in kept:
                mesh = UsdGeom.Mesh(stage.GetPrimAtPath(f"/World/Room/tag_{tag_id}/face"))
                transform = UsdGeom.XformCache().GetLocalToWorldTransform(mesh.GetPrim())
                self.assertGreater(min(transform.Transform(Gf.Vec3d(p))[2]
                                       for p in mesh.GetPointsAttr().Get()), 0)
            patch = (out / "usd-stage-port.patch").read_text()
            self.assertIn("+def spawn_room(stage, root:", patch)
            self.assertNotIn("-def spawn_tag", patch)
            self.assertNotIn("-def spawn_wall", patch)


if __name__ == "__main__":
    unittest.main()
