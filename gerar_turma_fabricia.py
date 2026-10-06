"""Turma da professora Fabricia: só o primeiro nome, femininos (laranja) e masculinos (azul), PLA Basic P1S.

Uso:  python gerar_turma_fabricia.py
Saída: saida/turma_fabricia/Femininos e saida/turma_fabricia/Masculinos (3MF + STL).
"""
import glob
import json
import os
import shutil
import zipfile
from collections import Counter

os.environ.setdefault("PONTEIRAS_MESHER", "skimage")
import ponteiras_core as core

FEMININOS_COMPLETOS = """ANTONELLA
AUGUSTA
EMILLY
HELENA
HELOISA
JASMYN
MARIA LAURA
POLIANA
REBECCA
VALENTINA"""

MASCULINOS_COMPLETOS = """ARTHUR ARCANJO
ARTHUR ELIAS
ARTHUR LIMA
AUGUSTO
BENJAMIN
CARLOS EDUARDO
ENZO DANTAS
ENZO VAZ
HENRIQUE
JOÃO GUILHERME NOLETO
JOÃO GUILHERME ALVES
JOÃO LUCAS
KAUÃ
LIAN
LORENZO ARCANJO
LORENZO CRUZ
MATIAS
SAYMON
YAGO"""

AZUL = "#0A2989FF"


def primeiros(texto):
    return Counter(ln.split()[0] for ln in texto.splitlines() if ln.strip())


def pintar(arq, cor):
    tmp = arq + ".tmp"
    with zipfile.ZipFile(arq) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for it in zin.infolist():
            data = zin.read(it.filename)
            if it.filename == "Metadata/project_settings.config":
                c = json.loads(data)
                for k in ("filament_colour", "filament_multi_colour"):
                    c[k] = [cor]
                data = json.dumps(c, ensure_ascii=False, indent=4).encode("utf-8")
            zout.writestr(it, data)
    shutil.move(tmp, arq)


saida = os.path.join(core.HERE, "saida", "turma_fabricia")
p = core.Params(caixa="maiusculas")
for rotulo, texto in (("Femininos", FEMININOS_COMPLETOS), ("Masculinos", MASCULINOS_COMPLETOS)):
    cont = primeiros(texto)
    itens = [(n, q, p) for n, q in sorted(cont.items())]
    print(f"\n== {rotulo}: {len(cont)} nomes diferentes, {sum(cont.values())} peças")
    pasta = os.path.join(saida, rotulo)
    arqs = core.gerar_tudo(itens, os.path.join(core.HERE, "saida"), log=lambda m: print(m.encode("ascii", "replace").decode()),
                           pasta_pedido=pasta, material="PLA")
    if rotulo == "Masculinos":
        for a in glob.glob(os.path.join(pasta, "*.3mf")):
            pintar(a, AZUL)
    print("arquivos:", [os.path.basename(a) for a in arqs])
print("\nPronto:", saida)
