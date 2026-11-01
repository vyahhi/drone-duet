"""Render the organizers' actual USD room and Tello URDF with native macOS USD Metal.

The scene functions and camera math execute from pinned organizer source. The only
scene-function edit replaces Omniverse's current-stage lookup with an explicit stage.
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import importlib.util
import json
import math
import sys
import types
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import torch
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdShade

from .mission import HOMES
from .upstream import ROOT, UPSTREAM, REVISION, verify

KIT = UPSTREAM / "simulation_infra/source/action_space_kit/action_space_kit"
COLORS = [(1.0, 0.5, 0.0), (0.0, 0.8, 1.0)]  # original room's first two drone colors


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_portable_sources(output):
    verify()
    # Load narrow pure-USD/Torch modules without executing the package's Isaac task
    # registration __init__. No fake physics, renderer or omni API is provided.
    for name, path in (("action_space_kit", KIT), ("action_space_kit.tags", KIT / "tags")):
        if name not in sys.modules:
            package = types.ModuleType(name)
            package.__path__ = [str(path)]
            sys.modules[name] = package
    room = load_file("action_space_kit.tags.room_map", KIT / "tags/room_map.py")
    textures = load_file("action_space_kit.tags.textures", KIT / "tags/textures.py")
    textures.TEXTURE_DIR = output / "textures"
    spawn = load_file("action_space_kit.tags.spawn", KIT / "tags/spawn.py")
    original = (KIT / "tags/spawn.py").read_text()
    portable = original.replace("def spawn_room(root: str,", "def spawn_room(stage, root: str,", 1)
    portable = portable.replace("    import omni.usd\n", "", 1)
    portable = portable.replace("    stage = omni.usd.get_context().get_stage()\n", "", 1)
    if portable == original or "omni.usd" in portable:
        raise RuntimeError("Organizer USD portability patch did not match")
    exec(compile(portable, str(KIT / "tags/spawn.py"), "exec"), spawn.__dict__)
    (output / "usd-stage-port.patch").write_text("".join(difflib.unified_diff(
        original.splitlines(True), portable.splitlines(True), fromfile="original/spawn.py", tofile="portable/spawn.py")))
    return room, spawn


def original_function(path, name, namespace):
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


def material(stage, name, rgb):
    mat = UsdShade.Material.Define(stage, name)
    shader = UsdShade.Shader.Define(stage, name + "/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*rgb))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.65)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return mat


def _rpy(rpy):
    r, p, y = rpy
    return (Gf.Rotation(Gf.Vec3d(0, 0, 1), math.degrees(y)) *
            Gf.Rotation(Gf.Vec3d(0, 1, 0), math.degrees(p)) *
            Gf.Rotation(Gf.Vec3d(1, 0, 0), math.degrees(r))).GetQuat()


def import_urdf_visuals(stage, root, path):
    """Translate original URDF primitives/materials, without redesigning the drone."""
    robot = ET.parse(path).getroot()
    materials = {m.attrib["name"]: tuple(float(v) for v in m.find("color").attrib["rgba"].split())[:3]
                 for m in robot.findall("material")}
    links = {}
    for joint in robot.findall("joint"):
        origin = joint.find("origin")
        links[joint.find("child").attrib["link"]] = (
            [float(v) for v in origin.attrib.get("xyz", "0 0 0").split()],
            [float(v) for v in origin.attrib.get("rpy", "0 0 0").split()])
    for link in robot.findall("link"):
        lpath = f"{root}/{link.attrib['name']}"
        lx = UsdGeom.Xform.Define(stage, lpath)
        pos, angles = links.get(link.attrib["name"], ([0, 0, 0], [0, 0, 0]))
        lx.AddTranslateOp().Set(Gf.Vec3d(*pos))
        lx.AddOrientOp(UsdGeom.XformOp.PrecisionDouble).Set(_rpy(angles))
        for i, visual in enumerate(link.findall("visual")):
            vpath = f"{lpath}/Visual_{i}"
            vx = UsdGeom.Xform.Define(stage, vpath)
            origin = visual.find("origin")
            attrs = origin.attrib if origin is not None else {}
            vx.AddTranslateOp().Set(Gf.Vec3d(*[float(v) for v in attrs.get("xyz", "0 0 0").split()]))
            vx.AddOrientOp(UsdGeom.XformOp.PrecisionDouble).Set(_rpy([float(v) for v in attrs.get("rpy", "0 0 0").split()]))
            geom = visual.find("geometry")[0]
            if geom.tag == "box":
                shape = UsdGeom.Cube.Define(stage, vpath + "/Shape")
                shape.CreateSizeAttr(1)
                shape.AddScaleOp().Set(Gf.Vec3f(*[float(v) for v in geom.attrib["size"].split()]))
            elif geom.tag == "cylinder":
                shape = UsdGeom.Cylinder.Define(stage, vpath + "/Shape")
                shape.CreateRadiusAttr(float(geom.attrib["radius"]))
                shape.CreateHeightAttr(float(geom.attrib["length"]))
                shape.CreateAxisAttr("Z")
            elif geom.tag == "sphere":
                shape = UsdGeom.Sphere.Define(stage, vpath + "/Shape")
                shape.CreateRadiusAttr(float(geom.attrib["radius"]))
            else:
                raise ValueError("Unsupported original URDF visual: " + geom.tag)
            name = visual.find("material").attrib["name"]
            mat = material(stage, vpath + "/Material", materials[name])
            UsdShade.MaterialBindingAPI.Apply(shape.GetPrim()).Bind(mat)


def suppress_floor_intersections(stage, tags):
    """Omit invalid near-floor mapped prints, rather than show clipped fragments.

    Source poses are untouched. The local sensor uses the same visible subset.
    """
    cache = UsdGeom.XformCache()
    hidden = []
    for tag_id in tags:
        root = f"/World/Room/tag_{tag_id}"
        mesh = UsdGeom.Mesh(stage.GetPrimAtPath(root + "/face"))
        transform = cache.GetLocalToWorldTransform(mesh.GetPrim())
        bottom = min(transform.Transform(Gf.Vec3d(p))[2] for p in mesh.GetPointsAttr().Get())
        if bottom <= 0:
            UsdGeom.Imageable(stage.GetPrimAtPath(root)).MakeInvisible()
            hidden.append(tag_id)
    return hidden


def visible_tags(stage, tags):
    return {tag_id: tag for tag_id, tag in tags.items()
            if UsdGeom.Imageable(stage.GetPrimAtPath(f"/World/Room/tag_{tag_id}")).ComputeVisibility()
            != UsdGeom.Tokens.invisible}


def create_scene(output, width=1280, height=720, fps=24):
    output.mkdir(parents=True, exist_ok=True)
    room, spawn = load_portable_sources(output)
    stage = Usd.Stage.CreateNew(str(output / "duet.usda"))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1)
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, "/World").GetPrim())
    stage.SetTimeCodesPerSecond(fps)
    stage.SetFramesPerSecond(fps)
    # Execute the ORIGINAL room env's wall specification with its original defaults.
    cfg = types.SimpleNamespace(room_x_max=8.5, wall_x=-0.1, side_wall_y=1.7, room_y_min=-2, ceiling=2.74)
    path = KIT / "tasks/direct/tello_room/tello_room_env.py"
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TelloRoomEnv")
    walls_node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_room_walls")
    namespace = {"Wall": spawn.Wall}
    exec(compile(ast.Module(body=[walls_node], type_ignores=[]), str(path), "exec"), namespace)
    walls = namespace["_room_walls"](types.SimpleNamespace(cfg=cfg))
    tags = room.load_room_tags(tag10_height=1.22)
    spawn.spawn_room(stage, "/World/Room", tags, walls)
    hidden_tags = suppress_floor_intersections(stage, tags)
    # Storm/Metal rejects one-channel sRGB textures. Preserve the original tag pixels
    # exactly while repeating grayscale into RGB, which the renderer can sample.
    import cv2
    for texture in (output / "textures").glob("*.png"):
        pixels = cv2.imread(str(texture), cv2.IMREAD_GRAYSCALE)
        cv2.imwrite(str(texture), cv2.cvtColor(pixels, cv2.COLOR_GRAY2BGR))
    spawn.spawn_wall(stage, "/World", spawn.Wall("Floor", (4, 0, -0.04), (12, 8, 0.08), (0.55, 0.56, 0.59)))
    transforms = []
    for i, home in enumerate(HOMES):
        root = f"/World/Drone_{i}"
        xf = UsdGeom.Xform.Define(stage, root)
        transforms.append((xf.AddTranslateOp(), xf.AddOrientOp()))
        import_urdf_visuals(stage, root, UPSTREAM / "simulation_infra/assets/tello/tello.urdf")
        transforms[-1][0].Set(Gf.Vec3d(*home))
        transforms[-1][1].Set(Gf.Quatf(0, 0, 0, 1))
        pad = UsdGeom.Cylinder.Define(stage, f"/World/Pad_{i}")
        pad.CreateRadiusAttr(0.3)
        pad.CreateHeightAttr(0.01)
        pad.AddTranslateOp().Set(Gf.Vec3d(home[0], home[1], 0.006))
        UsdShade.MaterialBindingAPI.Apply(pad.GetPrim()).Bind(material(stage, f"/World/PadMaterial_{i}", COLORS[i]))
    dome = UsdLux.DomeLight.Define(stage, "/World/Light")
    dome.CreateIntensityAttr(0.4)
    sun = UsdLux.DistantLight.Define(stage, "/World/Key")
    sun.CreateIntensityAttr(2.0)
    sun.CreateAngleAttr(15)
    UsdGeom.Xformable(sun).AddRotateXYZOp().Set(Gf.Vec3f(-25, 30, 0))
    # Execute the original recorder's camera construction and coordinate math.
    viewport = types.SimpleNamespace()
    camera_namespace = {"np": np, "H_AP": 20.955, "get_active_viewport": lambda: viewport,
        "args": types.SimpleNamespace(view="overview", width=width, height=height),
        "VIEWS": {"overview": ((5.5, 0.0, 2.1), (2.5, 0.0, 0.9), 18.0)}}
    camera = original_function(UPSTREAM / "simulation_infra/scripts/record_room.py", "setup_camera", camera_namespace)
    camera(types.SimpleNamespace(scene=types.SimpleNamespace(env_origins=torch.zeros((1, 3)))), stage)
    stage.GetRootLayer().Save()
    paths = [KIT / "tags/spawn.py", KIT / "tags/room_map.py", KIT / "tags/textures.py", path,
             UPSTREAM / "simulation_infra/scripts/record_room.py", UPSTREAM / "simulation_infra/assets/tello/tello.urdf"]
    (output / "provenance.json").write_text(json.dumps({
        "organizer_repository": "https://github.com/jaromero3rd/Action_Space", "revision": REVISION,
        "original_scene_functions": ["spawn_room", "spawn_tag", "spawn_wall", "_preview_material", "_room_walls", "setup_camera"],
        "scene_port": "Explicit USD stage parameter; duet camera framing; grayscale tags expanded losslessly to RGB for Metal; local lighting",
        "floor_tag_cleanup": {"suppressed_tag_ids": hidden_tags,
                              "reason": "mapped printed face intersects or lies below Z=0 floor",
                              "sensing": "same visible subset; original map file and remaining poses unchanged"},
        "drone_geometry": "literal primitives, offsets and materials from original tello.urdf; no custom drone model",
        "renderer": "/usr/bin/usdrecord --renderer Metal (Apple Hydra), not NVIDIA RTX",
        "source_sha256": {str(p.relative_to(UPSTREAM)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
    }, indent=2) + "\n")
    return stage, transforms


if __name__ == "__main__":
    create_scene(ROOT / "outputs/metal-duet")
    print(ROOT / "outputs/metal-duet/duet.usda")
