"""Importa um 3MF do Bambu Studio (objetos com componentes) para o Blender, em milimetros (1 BU = 1 mm).
Uso: blender -b --python import_bambu_3mf.py -- <arquivo.3mf> <saida.blend>"""
import sys, re, zipfile, numpy as np, bpy
src,out=sys.argv[sys.argv.index("--")+1:][:2]
z=zipfile.ZipFile(src)
bpy.ops.wm.read_factory_settings(use_empty=True)
sc=bpy.context.scene; sc.unit_settings.system='METRIC'; sc.unit_settings.scale_length=0.001; sc.unit_settings.length_unit='MILLIMETERS'
m=z.read('3D/3dmodel.model').decode('utf-8')
comp={}
for oid,body in re.findall(r'<object id="(\d+)"[^>]*>(.*?)</object>',m,flags=re.S):
    cs=re.findall(r'<component p:path="([^"]+)" objectid="(\d+)"[^>]*transform="([^"]+)"',body)
    if cs: comp[oid]=cs
items=re.findall(r'<item objectid="(\d+)"[^>]*transform="([^"]+)"',m)
cfg=z.read('Metadata/model_settings.config').decode('utf-8','replace')
ext=dict(re.findall(r'<object id="(\d+)">.*?<metadata key="extruder" value="(\d+)"',cfg,flags=re.S))
cache={}
def load(path):
    if path in cache: return cache[path]
    x=z.read(path.lstrip('/')).decode('utf-8')
    v=np.array(re.findall(r'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"',x),dtype=np.float64)
    t=np.array(re.findall(r'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"',x),dtype=np.int64)
    cache[path]=(v,t); return cache[path]
def affine(s):
    a=[float(u) for u in s.split()]; M=np.array(a[:9]).reshape(3,3); return M,np.array(a[9:12])
col=bpy.data.collections.new("Nomes"); sc.collection.children.link(col)
for n,(oid,tr) in enumerate(items,1):
    Mi,ti=affine(tr)
    V=[];T=[];off=0
    for path,cid,ctr in comp[oid]:
        v,t=load(path); Mc,tc=affine(ctr); v=(v@Mc+tc)@Mi+ti; V.append(v); T.append(t+off); off+=len(v)
    V=np.concatenate(V); T=np.concatenate(T)
    me=bpy.data.meshes.new("nome_%02d"%n); me.vertices.add(len(V)); me.vertices.foreach_set('co',V.ravel().astype(np.float32))
    me.loops.add(len(T)*3); me.polygons.add(len(T)); me.loops.foreach_set('vertex_index',T.ravel().astype(np.int32))
    me.polygons.foreach_set('loop_start',np.arange(0,len(T)*3,3)); me.polygons.foreach_set('loop_total',np.full(len(T),3)); me.update(calc_edges=True)
    o=bpy.data.objects.new("nome_%02d"%n,me); col.objects.link(o)
    o["bambu_object_id"]=int(oid); o["filamento"]=int(ext.get(oid,1))
    print("IMP",o.name,"tris",len(T),"bbox",np.round(V.min(0),1),np.round(V.max(0),1))
bpy.ops.wm.save_as_mainfile(filepath=out)
