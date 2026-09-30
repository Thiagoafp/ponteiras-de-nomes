"""(Blender, sem interface) Converte os voxels 'blocky' dos nomes em malhas suaves e fechadas (STL em mm).
Uso: blender -b --python mesh_nomes.py -- <pasta_tmp> <pasta_stl> <voxel_mm>
"""
import os
import sys

import bmesh
import bpy
import numpy as np

tmp, out, vs = sys.argv[sys.argv.index("--") + 1:][:3]
vs = float(vs)
os.makedirs(out, exist_ok=True)


def apply_mod(o, mod):
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.modifier_apply(modifier=mod.name)


for f in sorted(os.listdir(tmp)):
    if not f.endswith(".npz"):
        continue
    name = f[:-4]
    d = np.load(os.path.join(tmp, f))
    v, q = d["v"], d["q"]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(v))
    me.vertices.foreach_set("co", v.ravel())
    me.loops.add(len(q) * 4)
    me.polygons.add(len(q))
    me.loops.foreach_set("vertex_index", q.ravel())
    me.polygons.foreach_set("loop_start", np.arange(0, len(q) * 4, 4))
    me.polygons.foreach_set("loop_total", np.full(len(q), 4))
    me.update(calc_edges=True)
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)

    r = o.modifiers.new("R", "REMESH")
    r.mode = "VOXEL"
    r.voxel_size = vs
    r.adaptivity = 0.0
    apply_mod(o, r)
    s = o.modifiers.new("S", "SMOOTH")
    s.factor = 0.6
    s.iterations = 14
    apply_mod(o, s)
    de = o.modifiers.new("D", "DECIMATE")
    de.ratio = min(1.0, 70000.0 / max(1, len(o.data.polygons) * 2))  # alvo ~70 mil triangulos por nome
    apply_mod(o, de)

    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=vs * 0.05)
    bd = [e for e in bm.edges if e.is_boundary]
    if bd:
        bmesh.ops.holes_fill(bm, edges=bd, sides=12)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.normal_update()
    vol = bm.calc_volume(signed=True)
    bm.to_mesh(o.data)
    bm.free()

    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.wm.stl_export(filepath=os.path.join(out, name + ".stl"), export_selected_objects=True,
                          global_scale=1.0, use_scene_unit=False)
    print("OK", name, "tris", len(o.data.polygons), "vol_mm3 %.0f" % vol)
