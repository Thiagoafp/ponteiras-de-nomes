"""Linha de comando do gerador de ponteiras (Bambu Lab P1S).

Exemplos:
  python gerar_ponteiras.py --nomes "Helena:3, Ana Clara:2:ariblk, Bia"
  python gerar_ponteiras.py --arquivo nomes.csv            (linhas: NOME;QUANTIDADE;FONTE opcional)
  python gerar_ponteiras.py --listar-fontes
Saída: pasta saida/ com Ponteiras_prato_1.3mf, prato_2..., e os STL em saida/stl/.
Para a interface gráfica:  python ponteiras_gui.py
"""
import argparse
import os
import re
import sys
from dataclasses import replace

import ponteiras_core as core

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--nomes", help='"Nome:qtd[:fonte[:furo]], Nome2:qtd"')
ap.add_argument("--arquivo", help="CSV/TXT: NOME;QTD;FONTE;FURO (tudo depois do nome é opcional)")
ap.add_argument("--saida", default=os.path.join(core.HERE, "saida"))
ap.add_argument("--fonte", default=core.Params().fonte, help="fonte padrão (caminho, arquivo ou nome)")
ap.add_argument("--lapis", choices=["comum", "jumbo"], default="comum", help="tipo de lápis: define medidas do furo, altura e espessura padrão")
ap.add_argument("--gabarito", help='gera peça de teste de encaixe com furos dessas medidas, ex.: "7.0,7.2,7.4,7.6,7.8,8.0" (usa --furo-formato)')
ap.add_argument("--altura", type=float, default=None, help="altura da letra maiúscula, mm")
ap.add_argument("--espessura", type=float, default=None, help="espessura da peça, mm")
ap.add_argument("--raio", type=float, default=2.2, help="arredondado da borda, mm")
ap.add_argument("--engrossar", type=float, default=0.45, help="engrossa o traço, mm por lado")
ap.add_argument("--espaco", type=float, default=-0.6, help="espaço extra entre letras, mm (negativo junta)")
ap.add_argument("--furo-formato", choices=["circular", "hexagonal", "triangular"], default="circular", help="formato do furo do lápis")
ap.add_argument("--furo", type=float, default=None, help="medida do furo, mm (padrão: circular 8,0 · hexagonal 7,5 · triangular 7,5)")
ap.add_argument("--furo-folga", type=float, default=0.0, help="folga extra somada à medida, mm")
ap.add_argument("--furo-rot", type=float, default=0.0, help="giro do furo, graus")
ap.add_argument("--furo-canto", type=float, default=1.2, help="raio dos cantos do triângulo, mm")
ap.add_argument("--largura", type=float, default=0.72, help="compressão horizontal das letras (1 = normal)")
ap.add_argument("--ponte", type=float, default=2.4, help="largura das pontes que ligam letras soltas, mm")
ap.add_argument("--estilo", choices=["fechada", "vazada", "base"], default="fechada", help="fechada = letra sólida · vazada = só o contorno · base = borda em degrau em volta")
ap.add_argument("--borda", type=float, default=1.6, help="vazada: espessura da parede do contorno; base: largura da borda, mm")
ap.add_argument("--fundo", type=float, default=1.0, help="vazada: espessura do fundo, mm (0 = vazada de lado a lado)")
ap.add_argument("--altura-borda", type=float, default=4.0, help="base: altura do degrau da borda, mm")
ap.add_argument("--manter-caixa", action="store_true", help="não converte o nome para maiúsculas")
ap.add_argument("--qualidade", choices=["rascunho", "normal", "alta"], default="normal")
ap.add_argument("--base-arredondada", action="store_true")
ap.add_argument("--refazer", action="store_true", help="ignora o cache de STL")
ap.add_argument("--listar-fontes", action="store_true")
a = ap.parse_args()

if a.listar_fontes:
    for n, p in core.listar_fontes().items():
        print(f"{n:45s} {os.path.basename(p)}")
    sys.exit(0)

_alt, _esp = core.aplicar_preset({'comum': 'Comum (lápis de 7 a 7,5 mm)', 'jumbo': 'Jumbo (lápis de 10 a 10,5 mm)'}[a.lapis])
if a.altura is None:
    a.altura = _alt
if a.espessura is None:
    a.espessura = _esp
vox = {"rascunho": 0.20, "normal": 0.10, "alta": 0.06}[a.qualidade]
base = core.Params(fonte=core.resolver_fonte(a.fonte), altura=a.altura, espessura=a.espessura, raio=a.raio,
                   engrossar=a.engrossar, espaco=a.espaco, furo=a.furo if a.furo is not None else dict(core.FORMATOS_FURO.values())[a.furo_formato], furo_formato=a.furo_formato, furo_folga=a.furo_folga, furo_rot=a.furo_rot, furo_canto=a.furo_canto, estilo=a.estilo, borda=a.borda, fundo=a.fundo, altura_borda=a.altura_borda, maiusculas=not a.manter_caixa, largura=a.largura, ponte=a.ponte, base_arredondada=a.base_arredondada, voxel=vox)
itens = []
if a.nomes:
    for parte in a.nomes.split(","):
        parte = parte.strip()
        if not parte:
            continue
        parte = re.sub(r"\{([A-Za-z0-9_\-]+)\}", lambda m: "" + m.group(1) + "", parte)   # {coracao} = :coracao:
        cols = [c.strip().replace("", ":") for c in parte.split(":")]
        nome, qtd, fonte, furo = cols[0], 1, None, None
        if len(cols) > 1 and cols[1].isdigit():
            qtd = int(cols[1])
        if len(cols) > 2 and cols[2]:
            fonte = cols[2]
        if len(cols) > 3 and cols[3]:
            furo = cols[3]
        itens.append((nome, qtd, fonte, furo))
if a.arquivo:
    for ln in open(a.arquivo, encoding="utf-8-sig"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        c = [x.strip() for x in re.split(r"[;\t]", ln)]
        itens.append((c[0], int(c[1]) if len(c) > 1 and c[1].isdigit() else 1, c[2] if len(c) > 2 and c[2] else None, c[3] if len(c) > 3 and c[3] else None))
if a.gabarito:
    meds = [float(x) for x in a.gabarito.replace(";", ",").split(",") if x.strip()]
    core.gerar_gabarito(a.furo_formato, meds, a.saida, folga=a.furo_folga, rot=a.furo_rot, canto=a.furo_canto)
    sys.exit(0)
if not itens:
    sys.exit("Informe --nomes ou --arquivo (veja --help)")
def _params(f, fu):
    p = replace(base, fonte=core.resolver_fonte(f)) if f else base
    if fu:
        fmt = next((k for k in ("circular", "hexagonal", "triangular") if k.startswith(fu.lower()[:4])), None)
        if not fmt:
            sys.exit(f"Formato de furo inválido: {fu} (use circular, hexagonal ou triangular)")
        if fmt != p.furo_formato:
            p = replace(p, furo_formato=fmt, furo=dict(core.FORMATOS_FURO.values())[fmt])
    return p


final = [(n, q, _params(f, fu)) for n, q, f, fu in itens]
arqs = core.gerar_tudo(final, a.saida, refazer=a.refazer)
print("\nPronto! Abra os 3MF no Bambu Studio:", *arqs, sep="\n  ")
