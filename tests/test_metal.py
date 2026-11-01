"""Checks for the user-approved local USD/MuJoCo port (optional dependencies)."""
import importlib.util
import math
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

READY = all(importlib.util.find_spec(name) is not None for name in ("mujoco", "pxr", "torch"))


@unittest.skipUnless(READY, "requires requirements-metal.txt")
class MetalPortTests(unittest.TestCase):
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
            report = simulate(Path(tmp), dance_seconds=4)
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

    def test_original_usd_scene_is_usable_and_only_portable_stage_hook_is_patched(self):
        from duet.metal_scene import create_scene
        from pxr import UsdGeom
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
            patch = (out / "usd-stage-port.patch").read_text()
            self.assertIn("+def spawn_room(stage, root:", patch)
            self.assertNotIn("-def spawn_tag", patch)
            self.assertNotIn("-def spawn_wall", patch)


if __name__ == "__main__":
    unittest.main()
