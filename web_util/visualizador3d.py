"""Visualizador 3D interativo (three.js) para o Streamlit: gira, aproxima, mostra o prato de 256 x 256 mm da P1S."""
import base64
import json

import numpy as np

CDN_THREE = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
CDN_ORBIT = "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"


def dados_malhas(pecas, alvo_tris=9000):
    """pecas = [(nome, vertices, faces, (x, y))]: vértices em mm com origem no canto mínimo da peça; (x, y) = posição no prato.
    Reduz cada malha (só para visualizar) e devolve dados compactos, indexados, em base64."""
    objs = []
    for item in pecas:
        nome, v, f, (x, y) = item[:4]
        cor_obj = item[4] if len(item) > 4 else None
        v = np.asarray(v, np.float32)
        f = np.asarray(f, np.int32)
        if len(f) > alvo_tris:
            import fast_simplification
            v, f = fast_simplification.simplify(v, f, target_reduction=min(0.98, 1 - alvo_tris / len(f)))
            v = np.asarray(v, np.float32)
            f = np.asarray(f, np.uint32)
        objs.append({
            "nome": nome, "x": float(x), "y": float(y),
            "v": base64.b64encode(np.asarray(v, np.float32).tobytes()).decode("ascii"),
            "f": base64.b64encode(np.asarray(f, np.uint32).tobytes()).decode("ascii"),
            "nv": int(len(v)), "nf": int(len(f)), "cor": cor_obj,
        })
    return objs


def html_visualizador(objs, prato=None, cor="#ff8a1f", altura=520, tema="claro"):
    """HTML autônomo do visualizador. prato=(largura, profundidade) desenha a mesa da impressora (ex.: (256, 256))."""
    dados = json.dumps({"objs": objs, "prato": prato, "cor": cor, "escuro": tema != "claro"})
    info_cor = "#5b6477" if tema == "claro" else "#8f99b3"
    botao_bg = "rgba(255,255,255,.92)" if tema == "claro" else "rgba(40,44,56,.92)"
    botao_fg = "#2b3350" if tema == "claro" else "#dfe5f5"
    botao_prato = '<button data-v="p">Prato</button>' if prato else ""
    fundo = "linear-gradient(160deg,#f4f6ff 0%,#e9edf9 100%)" if tema == "claro" else "radial-gradient(circle at 50% 35%,#242832 0%,#14161c 75%)"
    if prato:
        fundo = "#e7e8e9"
        info_cor = "#5b6477"
    rot_prato = ('<div style="position:absolute;left:14px;bottom:8px;font-size:22px;font-weight:700;color:#00ae42">Plate 1</div>'
                 '<div style="position:absolute;right:22px;bottom:28px;font-size:22px;font-weight:700;color:#00ae42">01</div>') if prato else ""
    return f"""
<div id="wrap" style="position:relative;width:100%;height:{altura}px;border-radius:18px;overflow:hidden;background:{fundo};
     box-shadow:0 6px 24px rgba(40,50,90,.15);font-family:Inter,Segoe UI,sans-serif">
  <div id="v" style="width:100%;height:100%"></div>
  <div id="bar" style="position:absolute;left:12px;top:12px;display:flex;gap:6px;flex-wrap:wrap">
    <button data-v="q">3/4</button>{botao_prato}<button data-v="t">Topo</button><button data-v="f">Frente</button><button data-v="l">Lado</button>
    <button id="rot">Girar</button><button id="wire">Malha</button>
  </div>
  {rot_prato}
  <div id="info" style="position:absolute;right:14px;bottom:10px;font-size:12px;color:{info_cor}"></div>
</div>
<style>
  #bar button{{border:0;border-radius:10px;padding:6px 11px;background:{botao_bg};color:{botao_fg};font-size:12.5px;
    font-weight:600;cursor:pointer;box-shadow:0 1px 4px rgba(0,0,0,.12)}}
  #bar button:hover{{background:#6c4dff;color:#fff}}
  #bar button.on{{background:#6c4dff;color:#fff}}
</style>
<script src="{CDN_THREE}"></script>
<script src="{CDN_ORBIT}"></script>
<script>
(function() {{
  const D = {dados};
  const el = document.getElementById('v');
  const W = el.clientWidth || 800, H = el.clientHeight || {altura};
  const renderer = new THREE.WebGLRenderer({{antialias:true, alpha:true}});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(W, H);
  el.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, W / H, 0.5, 5000);
  camera.up.set(0, 0, 1);                       // Z para cima, como no fatiador

  scene.add(new THREE.HemisphereLight(0xffffff, 0x9aa3c0, 0.75));
  const key = new THREE.DirectionalLight(0xffffff, 0.85); key.position.set(-120, -160, 220); scene.add(key);
  const rim = new THREE.DirectionalLight(0xbfd0ff, 0.35); rim.position.set(160, 120, 80); scene.add(rim);

  function dec(b64, Type) {{
    const bin = atob(b64), n = bin.length, u8 = new Uint8Array(n);
    for (let i = 0; i < n; i++) u8[i] = bin.charCodeAt(i);
    return new Type(u8.buffer);
  }}

  const grupo = new THREE.Group(); scene.add(grupo);
  const mats = [];
  let minP = new THREE.Vector3(1e9, 1e9, 1e9), maxP = new THREE.Vector3(-1e9, -1e9, -1e9);
  let tris = 0;
  D.objs.forEach(o => {{
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(dec(o.v, Float32Array), 3));
    g.setIndex(new THREE.BufferAttribute(dec(o.f, Uint32Array), 1));
    g.computeVertexNormals();
    const m = new THREE.MeshStandardMaterial({{color: o.cor || D.cor, roughness: 0.42, metalness: 0.04}});
    mats.push(m);
    const mesh = new THREE.Mesh(g, m);
    mesh.position.set(o.x, o.y, 0);
    grupo.add(mesh);
    tris += o.nf;
    g.computeBoundingBox();
    const b = g.boundingBox.clone().translate(mesh.position);
    minP.min(b.min); maxP.max(b.max);
  }});

  // mesa da impressora (ou chão) + grade
  let cx, cy;
  if (D.prato) {{
    const pw = D.prato[0], pd = D.prato[1];
    function rrect(x, y, w, h, r) {{
      const sh = new THREE.Shape();
      sh.moveTo(x + r, y); sh.lineTo(x + w - r, y); sh.quadraticCurveTo(x + w, y, x + w, y + r);
      sh.lineTo(x + w, y + h - r); sh.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
      sh.lineTo(x + r, y + h); sh.quadraticCurveTo(x, y + h, x, y + h - r);
      sh.lineTo(x, y + r); sh.quadraticCurveTo(x, y, x + r, y);
      return sh;
    }}
    function slab(shape, depth, color, z0) {{
      const g = new THREE.ExtrudeGeometry(shape, {{depth: depth, bevelEnabled: false}});
      const m = new THREE.Mesh(g, new THREE.MeshBasicMaterial({{color: color}}));
      m.position.z = z0; scene.add(m); return m;
    }}
    function rotulo(txt, w, h, fg, bg, px, fonte) {{
      const c = document.createElement('canvas'); c.width = 1024; c.height = Math.round(1024 * h / w);
      const k = c.getContext('2d');
      if (bg) {{ k.fillStyle = bg; k.fillRect(0, 0, c.width, c.height); }}
      k.fillStyle = fg; k.font = (fonte || '600') + ' ' + px + 'px Segoe UI, Arial, sans-serif'; k.textAlign = 'center'; k.textBaseline = 'middle';
      k.fillText(txt, c.width / 2, c.height / 2);
      const t = new THREE.CanvasTexture(c);
      return new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({{map: t, transparent: !bg}}));
    }}
    // moldura e placa de PEI (cinza escuro, cantos arredondados) — como na mesa da Bambu Lab
    slab(rrect(-6, -6, pw + 12, pd + 12, 9), 3, 0x8c9092, -3.2);
    slab(rrect(0, 0, pw, pd, 4), 0.2, 0x4b4e50, -0.22);
    // aba traseira (puxador) e faixa frontal com a identificação
    slab(rrect(pw / 2 - 38, pd + 4, 76, 10, 4), 3, 0x6b6f71, -3.2);
    const fenda = slab(rrect(pw / 2 - 20, pd + 7.5, 40, 3, 1.4), 0.4, 0xe8eaeb, -0.2);
    slab(rrect(18, -24, pw - 36, 15, 5), 3, 0xb9bdbf, -3.2);
    const rf = rotulo('PLA/ABS/PETG', 120, 10, '#444', null, 74, '700'); rf.position.set(pw / 2 - 12, -16.5, 0.1); scene.add(rf);
    const rq = rotulo('HOT SURFACE', 46, 10, '#555', null, 62, '600'); rq.position.set(pw - 52, -16.5, 0.1); scene.add(rq);
    // grade: células de 10 mm; linhas mais claras a cada 50 mm
    const pos = [], pos2 = [];
    for (let x = 0; x <= pw + 0.01; x += 10) {{ (x % 50 === 0 ? pos2 : pos).push(x, 0, 0.05, x, pd, 0.05); }}
    for (let y = 0; y <= pd + 0.01; y += 10) {{ (y % 50 === 0 ? pos2 : pos).push(0, y, 0.05, pw, y, 0.05); }}
    [[pos, 0x777b7d], [pos2, 0xa5a9ab]].forEach(([arr, col]) => {{
      const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(arr, 3));
      scene.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({{color: col}})));
    }});
    // marca da origem (quadrado claro no canto) e eixos X (vermelho), Y (verde), Z (azul)
    slab(rrect(0, 0, 22, 22, 4), 0.3, 0xcfd2d3, -0.1);
    function eixo(dx, dy, dz, col) {{
      const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute([0, 0, 0.6, dx, dy, dz + 0.6], 3));
      scene.add(new THREE.Line(g, new THREE.LineBasicMaterial({{color: col, linewidth: 3}})));
      const c = new THREE.Mesh(new THREE.ConeGeometry(2, 6, 12), new THREE.MeshBasicMaterial({{color: col}}));
      c.position.set(dx, dy, dz + 0.6);
      c.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), new THREE.Vector3(dx, dy, dz).normalize());
      scene.add(c);
    }}
    eixo(36, 0, 0, 0xd82020); eixo(0, 36, 0, 0x20b020); eixo(0, 0, 36, 0x2020c0);
    cx = pw / 2; cy = pd / 2;
  }} else {{
    const s = Math.max(maxP.x - minP.x, maxP.y - minP.y) * 2.2 + 20;
    const grid = new THREE.GridHelper(s, 20, D.escuro ? 0x5a6378 : 0x8d97b8, D.escuro ? 0x3d4456 : 0xc7cee4);
    grid.rotation.x = Math.PI / 2; grid.position.set((minP.x + maxP.x) / 2, (minP.y + maxP.y) / 2, -0.02); scene.add(grid);
    cx = (minP.x + maxP.x) / 2; cy = (minP.y + maxP.y) / 2;
  }}
  const centroP = new THREE.Vector3((minP.x + maxP.x) / 2, (minP.y + maxP.y) / 2, (minP.z + maxP.z) / 2);
  const target = centroP.clone();
  let span = Math.max(maxP.x - minP.x, maxP.y - minP.y, maxP.z - minP.z) * 1.35 + 18;
  if (D.prato) span = Math.max(span, 110);
  const spanPrato = D.prato ? Math.max(D.prato[0], D.prato[1]) * 0.95 : span;
  const centroPrato = D.prato ? new THREE.Vector3(cx, cy, 0) : centroP;

  const controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = 0.08; controls.target.copy(target);
  function vista(nome) {{
    let d = span, tg = centroP;
    if (nome === 'p') {{ d = spanPrato * 1.75; tg = centroPrato; nome = 'p0'; }}
    const p = {{q: [-0.55, -0.9, 0.75], p0: [0, -0.62, 0.78], t: [0, -0.001, 1.25], f: [0, -1.3, 0.35], l: [1.3, 0, 0.35]}}[nome] || [-0.55, -0.9, 0.75];
    controls.target.copy(tg);
    camera.position.set(tg.x + p[0] * d, tg.y + p[1] * d, tg.z + p[2] * d);
    controls.update();
  }}
  vista(D.prato ? 'p' : 'q');
  document.querySelectorAll('#bar button[data-v]').forEach(b => b.onclick = () => vista(b.dataset.v));
  const rot = document.getElementById('rot');
  rot.onclick = () => {{ controls.autoRotate = !controls.autoRotate; controls.autoRotateSpeed = 2.2; rot.classList.toggle('on', controls.autoRotate); }};
  const wire = document.getElementById('wire');
  wire.onclick = () => {{ const on = !mats[0].wireframe; mats.forEach(m => m.wireframe = on); wire.classList.toggle('on', on); }};
  document.getElementById('info').textContent = D.objs.length + (D.objs.length > 1 ? ' peças' : ' peça') + ' · ' + tris.toLocaleString('pt-BR') + ' triângulos (visualização)';

  function anim() {{ requestAnimationFrame(anim); controls.update(); renderer.render(scene, camera); }}
  anim();
  window.addEventListener('resize', () => {{
    const w = el.clientWidth, h = el.clientHeight; renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
  }});
}})();
</script>
"""
