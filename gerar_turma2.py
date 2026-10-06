"""Turma 2: só o primeiro nome, em duas listas (femininos e masculinos), cada uma no seu arquivo/cor.

Uso:  python gerar_turma2.py
Saída: saida/turma2/Femininos e saida/turma2/Masculinos (3MF + STL).
"""
import os
from collections import Counter

os.environ.setdefault("PONTEIRAS_MESHER", "skimage")
import ponteiras_core as core

FEMININOS_COMPLETOS = """ALICE
ANNA CÉLIA
ANNA LUÍSA
CATIANNY
ÉLOA
ELOAH
HELENA
HELOANNY
LUIZA
MARIA EDUARDA
REBECCA
SOPHIA
STACY
STEFANY
VALENTINA"""

MASCULINOS_COMPLETOS = """ARTHUR
BENÍCIO
BENJAMIN
DAVI
JOÃO MIGUEL
LORENZO BARBOSA
LORENZO FARIA
LUAN
MIGUEL
NICOLAS MENEZES
NICOLLAS ÁVILA
VICENTE"""


def primeiros(texto):
    return Counter(ln.split()[0] for ln in texto.splitlines() if ln.strip())


saida = os.path.join(core.HERE, "saida", "turma2")
p = core.Params(caixa="maiusculas")
for rotulo, texto in (("Femininos", FEMININOS_COMPLETOS), ("Masculinos", MASCULINOS_COMPLETOS)):
    cont = primeiros(texto)
    itens = [(n, q, p) for n, q in sorted(cont.items())]
    print(f"\n== {rotulo}: {len(cont)} nomes diferentes, {sum(cont.values())} peças")
    arqs = core.gerar_tudo(itens, os.path.join(core.HERE, "saida"), log=lambda m: print(m.encode("ascii", "replace").decode()),
                           pasta_pedido=os.path.join(saida, rotulo))
    print("arquivos:", [os.path.basename(a) for a in arqs])
print("\nPronto:", saida)
