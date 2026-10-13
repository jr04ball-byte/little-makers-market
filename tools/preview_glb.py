"""Render a 3-angle preview strip of a .glb with Blender (EEVEE).

blender -b -P preview_glb.py -- <model.glb> <out.png>
"""
import math
import sys

import bpy
from mathutils import Vector

glb, out = sys.argv[sys.argv.index("--") + 1:][:2]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]

# frame the model: centre at origin, height 2
lo = Vector((min(v[i] for o in meshes for v in (o.matrix_world @ Vector(c) for c in o.bound_box)) for i in range(3)))
hi = Vector((max(v[i] for o in meshes for v in (o.matrix_world @ Vector(c) for c in o.bound_box)) for i in range(3)))
size = max(hi - lo)
pivot = bpy.data.objects.new("pivot", None)
bpy.context.scene.collection.objects.link(pivot)
for o in meshes:
    if o.parent is None:
        o.parent = pivot
pivot.location = -(lo + hi) / 2 * (2 / size)
pivot.scale = (2 / size,) * 3

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = scene.render.resolution_y = 512
scene.render.film_transparent = False
world = bpy.data.worlds.new("w")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.92, 0.92, 0.95, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
scene.world = world

sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
sun.data.energy = 3
sun.rotation_euler = (math.radians(50), 0, math.radians(30))
scene.collection.objects.link(sun)

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scene.collection.objects.link(cam)
scene.camera = cam

import os
frames = []
for i, ang in enumerate((20, 90, 160)):
    a = math.radians(ang)
    cam.location = (4.2 * math.sin(a), -4.2 * math.cos(a), 0.8)
    cam.rotation_euler = (Vector((0, 0, 0)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    p = f"{out}.{i}.png"
    scene.render.filepath = p
    bpy.ops.render.render(write_still=True)
    frames.append(p)

# stitch with Blender's image API
imgs = [bpy.data.images.load(p) for p in frames]
w, h = imgs[0].size
strip = bpy.data.images.new("strip", w * len(imgs), h)
px = [0.0] * (w * len(imgs) * h * 4)
for k, im in enumerate(imgs):
    src = list(im.pixels)
    for y in range(h):
        row = src[y * w * 4:(y + 1) * w * 4]
        start = (y * w * len(imgs) + k * w) * 4
        px[start:start + w * 4] = row
strip.pixels = px
strip.filepath_raw = out
strip.file_format = "PNG"
strip.save()
for p in frames:
    os.remove(p)
