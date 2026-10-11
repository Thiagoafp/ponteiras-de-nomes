"""Núcleo do gerador de ponteiras de nomes (letras 3D arredondadas) para Bambu Lab P1S.

Fluxo: texto -> máscara 2D (fonte TTF) -> relevo 3D por distância da borda -> malha suave (Blender sem
interface) -> STL por nome -> pratos 3MF do Bambu Studio (um objeto por cópia, quantidades livres).
"""
import hashlib
import os
import re
import shutil
import struct
import subprocess
import zipfile
from dataclasses import dataclass, asdict, replace
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from scipy import ndimage as ndi

HERE = os.path.dirname(os.path.abspath(__file__))
BLENDER = r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
# Gerador da malha: "blender" (local, sem interface) ou "skimage" (marching cubes; usado no servidor web, sem Blender).
MESHER = os.environ.get("PONTEIRAS_MESHER") or ("blender" if os.path.isfile(BLENDER) else "skimage")
ALVO_TRIS = 70000            # triângulos por nome no STL final
FONTS_DIR = r"C:\Windows\Fonts"
IMAGENS_DIR = os.path.join(HERE, "imagens")          # imagens (logos, silhuetas) para usar junto das letras
FONTES_LOCAIS = os.path.join(HERE, "fontes")
FONTES_PADRAO = os.path.join(FONTES_LOCAIS, "padrao")            # fontes comuns incluídas no app (servidor não tem as do Windows)
FONTES_IMPORTADAS = os.path.join(FONTES_LOCAIS, "importadas")   # fontes que VOCÊ importa pelo botão   # fontes extras (estilo Lobster, infantis, Disney...)
BASE_CFG = os.path.join(HERE, "base_bambu", "project_settings.config")  # perfil P1S / PLA / PEI do seu projeto

QUALIDADE = {"Rascunho (rápido)": 0.20, "Normal": 0.10, "Alta (profissional)": 0.06}


@dataclass
class Params:
    fonte: str = os.path.join(FONTS_DIR, "ARLRDBD.TTF")
    altura: float = 12.0        # altura da letra maiúscula (mm)
    espessura: float = 10.0     # espessura da peça (mm)
    raio: float = 1.0           # arredondado da borda de cima (mm)
    engrossar: float = 0.7      # engrossa o traço (mm por lado)
    espaco: float = -1.0        # espaço extra entre letras (mm; negativo junta as letras)
    furo_formato: str = "circular"  # circular | hexagonal | triangular (triângulo abaloado)
    furo: float = 8.0           # medida do furo (mm): circular = diâmetro; hexagonal = entre faces; triangular = altura (da face ao canto oposto)
    furo_folga: float = 0.0     # folga extra somada à medida (mm). Use 0,2–0,3 se a medida acima for a do LÁPIS
    furo_rot: float = 0.0       # gira o formato do furo (graus). 0 = hexágono com faces em cima/embaixo e triângulo com ponta para cima
    furo_canto: float = 1.2     # raio dos cantos do triângulo abaloado (mm)
    parede_base: float = 1.0    # parede entre o furo e a base (mm)
    estilo: str = "fechada"     # fechada | vazada (só contorno) | base (borda em degrau em volta das letras)
    borda: float = 1.6          # vazada: espessura da parede do contorno; base: largura da borda em volta (mm)
    fundo: float = 1.0          # vazada: espessura do fundo (0 = vazada de lado a lado)
    altura_borda: float = 4.0   # base: altura do degrau da borda (mm)
    maiusculas: bool = True     # (antigo) True = MAIÚSCULAS; só vale quando caixa == 'auto'
    caixa: str = "auto"         # auto | maiusculas | minusculas | digitado | capitalizar (Primeira Maiúscula de cada palavra)
    dois_lados: bool = False    # nome legível nos dois lados: metade de cima normal, metade de baixo espelhada (ao girar o lápis 180° lê-se de pé)
    modo: str = "uniforme"      # uniforme | zigzag (letras com alturas alternadas) | cores (cada letra alterna cor A/B para o AMS)
    zigzag: float = 1.0         # modo zigzag: quanto as letras pares sobem e as ímpares descem (mm)
    largura: float = 0.9        # 1.0 = largura normal da fonte; <1 comprime as letras (o original é condensado)
    ligar_letras: bool = True   # liga letras/acentos soltos com pontes (False: deixa o espaço entre palavras; o chaveiro com base já une tudo pela base)
    ponte: float = 2.4          # largura das pontes que ligam letras/acentos soltos (mm)
    base_arredondada: bool = False
    voxel: float = 0.10         # resolução (mm)
    produto: str = "ponteira"   # ponteira (furo do lápis atravessando o nome) | chaveiro (argola com furo na ponta, sem furo de lápis)
    argola_ext: float = 11.0    # chaveiro: diâmetro externo da argola (mm)
    argola_furo: float = 4.5    # chaveiro: diâmetro do furo da argola (mm)
    argola_lado: str = "esquerda"   # chaveiro: esquerda | direita
    elo_largo: float = 15.0     # corrente: comprimento de cada elo (mm)
    elo_ancho: float = 12.0     # corrente: largura do elo (mm)
    elo_alto: float = 6.0       # corrente: altura/espessura do elo (mm)
    elo_espaco: float = 1.0     # corrente: vão entre elos (mm)
    elo_forma: str = "quadrado"  # corrente: quadrado (cantos e arestas arredondados) | reto (bloco com chanfro, como o modelo original)
    elo_canto: float = 3.0      # corrente quadrado: raio dos cantos vistos de cima (mm)
    elo_borda: float = 1.0      # corrente quadrado: arredondado das arestas de cima e de baixo (mm)
    elo_primeiro: bool = True   # corrente: argola (pino) na primeira peça, para pendurar
    elo_ultimo: bool = False    # corrente: argola também na última peça (pulseira)
    emblema: str = ""           # marcador: caminho de uma imagem (brasão/logo redondo) para usar no lugar do nome
    emblema_d: float = 55.0     # marcador: diâmetro do emblema (mm)
    marc_cores: int = 4         # marcador: 4 filamentos (base, letras, rosto, capelo) ou 2 (base + nome/emoji; boca e óculos viram vazados)
    livro_pos: str = "inicio"   # marcador: livrinho aberto no inicio | fim | ambos | nenhum
    emoji: bool = False         # marcador: emoji de professor (capelo + óculos) antes do nome
    emoji_d: float = 18.0       # marcador: diâmetro do rosto do emoji (mm)
    marc_larg: float = 25.2     # marcador: largura da haste do clip (mm)
    marc_braco: float = 4.8     # marcador: largura de cada braço da moldura da haste (mm)
    marc_fenda: float = 2.2     # marcador: fenda entre a moldura e a lingueta (mm)
    marc_cab_alt: float = 23.0  # marcador singelo: altura da cabeça com a logo (mm); 36 mantém a proporção original da logo (18 x 23) em 28 mm de largura
    marc_cab: float = 28.0      # marcador singelo: largura da cabeça com a logo (mm); a base segue o formato da logo
    marc_clip: float = 28.0     # marcador singelo: comprimento da parte do clip (moldura em U com lingueta), de baixo para cima (mm)
    marc_comp: float = 100.0    # marcador: comprimento da haste abaixo do nome (mm)
    base_alt: float = 2.0       # chaveiro com base de contorno: espessura da base (mm); a letra sobe `relevo` acima dela
    relevo: float = 1.0         # corrente: relevo da letra (negativo = afundada)
    inclinacao: float = 6.0     # cada letra gira até ±este ângulo (graus), alternando o sentido (efeito "letras dançando")
    ondula: float = 0.8         # cada letra sobe/desce até este valor (mm) da linha


# ----------------------------------------------------------------------------- fontes
INFO_FONTE = {}   # nome amigável -> (família, estilo), usado pela interface para mostrar cada fonte no próprio estilo


def listar_fontes():
    """{nome amigável: caminho}: primeiro as fontes da pasta 'fontes' (extras), depois as instaladas no Windows."""
    out = {}
    for pasta in (FONTES_IMPORTADAS, FONTES_LOCAIS, FONTES_PADRAO, FONTS_DIR):
        if not os.path.isdir(pasta):
            continue
        for f in sorted(os.listdir(pasta)):
            if not f.lower().endswith((".ttf", ".otf")):
                continue
            p = os.path.join(pasta, f)
            try:
                fam, sty = ImageFont.truetype(p, 20).getname()
                nome = fam if sty.lower() in ("regular", "normal") else f"{fam} {sty}"
            except Exception:
                continue
            if any(x in nome.lower() for x in ("symbol", "wingdings", "webdings", "marlett", "emoji", "mdl2", "holo")):
                continue
            if nome not in out:
                out[nome] = p
                INFO_FONTE[nome] = (fam, sty)
    return out


def resolver_fonte(f):
    """Aceita caminho completo, nome do arquivo (comicbd) ou nome amigável."""
    if os.path.isfile(f):
        return f
    for pasta in (FONTES_IMPORTADAS, FONTES_LOCAIS, FONTES_PADRAO, FONTS_DIR):
        for ext in ("", ".ttf", ".otf", ".TTF", ".OTF"):
            p = os.path.join(pasta, f + ext)
            if os.path.isfile(p):
                return p
    fontes = listar_fontes()
    for k, p in fontes.items():
        if k.lower() == f.lower():
            return p
    raise FileNotFoundError(f"Fonte não encontrada: {f}")


# ----------------------------------------------------------------------------- geometria
ATALHOS = {   # digite ":nome:" no nome para inserir o símbolo
    ":coracao:": "❤", ":coracao2:": "♥", ":coracaovazio:": "♡", ":flor:": "✿", ":flor2:": "❀", ":flor3:": "❁", ":flor4:": "✾",
    ":florzinha:": "🌸", ":margarida:": "🌼", ":tulipa:": "🌷", ":rosa:": "🌹", ":estrela:": "★", ":estrela2:": "☆", ":coroa:": "👑",
    ":borboleta:": "🦋", ":gato:": "🐱", ":cachorro:": "🐶", ":arcoiris:": "🌈", ":sol:": "☀", ":lua:": "☾", ":nota:": "♪",
    ":diamante:": "💎", ":caveira:": "☠", ":espadas:": "⚔", ":ancora:": "⚓", ":trevo:": "☘", ":carinha:": "☺", ":raio:": "⚡",
}


def expandir_atalhos(texto):
    for k, v in ATALHOS.items():
        texto = texto.replace(k, v)
    return texto


# ----------------------------------------------------------------------------- imagens junto do texto
def listar_imagens():
    """{nome (minúsculo, sem extensão): caminho} das imagens importadas. No nome, use :nome: para inserir a imagem."""
    out = {}
    if os.path.isdir(IMAGENS_DIR):
        for f in sorted(os.listdir(IMAGENS_DIR)):
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")):
                out[os.path.splitext(f)[0].lower()] = os.path.join(IMAGENS_DIR, f)
    return out


def _nome_arquivo(n):
    import unicodedata
    t = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9_-]+", "_", t).strip("_") or "img"


def importar_imagem(caminho, nome=None):
    """Copia a imagem para a pasta 'imagens' (PNG, até 900 px) e devolve o atalho, ex.: ':gatinho:'."""
    os.makedirs(IMAGENS_DIR, exist_ok=True)
    nome = _nome_arquivo(nome or os.path.splitext(os.path.basename(caminho))[0])
    if nome in ATALHOS or (":" + nome + ":") in ATALHOS:
        nome += "_img"
    im = ImageOps.exif_transpose(Image.open(caminho)).convert("RGBA")
    im.thumbnail((900, 900))
    im.save(os.path.join(IMAGENS_DIR, nome + ".png"))
    return f":{nome}:"


def importar_fonte(caminho):
    """Copia a fonte (.ttf/.otf) para a pasta 'fontes/importadas' e devolve o nome amigável. Levanta ValueError se o arquivo não for uma fonte."""
    os.makedirs(FONTES_IMPORTADAS, exist_ok=True)
    try:
        fam, sty = ImageFont.truetype(caminho, 20).getname()
    except Exception:
        raise ValueError("Esse arquivo não parece ser uma fonte válida (.ttf ou .otf).")
    destino = os.path.join(FONTES_IMPORTADAS, os.path.basename(caminho))
    if os.path.abspath(caminho) != os.path.abspath(destino):
        shutil.copy2(caminho, destino)
    return fam if sty.lower() in ("regular", "normal") else f"{fam} {sty}"


def _otsu(g):
    hist, _ = np.histogram(g, bins=256, range=(0, 256))
    tot, soma = g.size, (np.arange(256) * hist).sum()
    wb = sb = 0.0
    melhor, thr = 0.0, 127
    for t in range(256):
        wb += hist[t]
        if wb == 0:
            continue
        wf = tot - wb
        if wf == 0:
            break
        sb += t * hist[t]
        v = wb * wf * (sb / wb - (soma - sb) / wf) ** 2
        if v > melhor:
            melhor, thr = v, t
    return thr


def _mascara_imagem(caminho, alto_px):
    """Silhueta (bool) da imagem na altura pedida: usa a transparência (PNG) ou, se não houver, separa escuro/claro (Otsu)."""
    im = ImageOps.exif_transpose(Image.open(caminho)).convert("RGBA")
    a = np.asarray(im)
    alfa = a[..., 3]
    if (alfa < 128).any() and (alfa >= 128).any():
        sil = alfa >= 128
    else:
        g = np.asarray(im.convert("L")).astype(float)
        sil = g < _otsu(g)
        borda = np.concatenate([g[0], g[-1], g[:, 0], g[:, -1]]).mean()
        if borda < 110:                 # fundo escuro: o desenho é o claro
            sil = ~sil
    ys, xs = np.where(sil)
    if len(ys) == 0:
        raise ValueError(f"Não consegui extrair um desenho de {os.path.basename(caminho)}")
    sil = sil[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    esc = alto_px / sil.shape[0]
    novo = (max(2, int(sil.shape[1] * esc)), max(2, int(alto_px)))
    m = np.asarray(Image.fromarray((sil * 255).astype(np.uint8)).resize(novo, Image.LANCZOS)) > 127
    lab, n = ndi.label(m)
    if n > 1:                            # remove sujeira (pedaços minúsculos)
        tam = ndi.sum(m, lab, range(1, n + 1))
        m = np.isin(lab, 1 + np.where(tam >= max(20, 0.002 * m.size))[0])
    return m


_TOKEN = re.compile(r":([A-Za-z0-9_\-]+):")


def _elementos(texto, imagens):
    """Divide o texto em elementos: ('ch', caractere) ou ('img', caminho). ':coracao:' vira símbolo; ':gatinho:' vira a imagem."""
    out, pos = [], 0
    for mo in _TOKEN.finditer(texto):
        chave = ":" + mo.group(1).lower() + ":"
        if chave in ATALHOS or mo.group(1).lower() in imagens:
            out += [("ch", c) for c in texto[pos:mo.start()]]
            out.append(("ch", ATALHOS[chave]) if chave in ATALHOS else ("img", imagens[mo.group(1).lower()]))
            pos = mo.end()
    out += [("ch", c) for c in texto[pos:]]
    return out


def _assinatura_imagens(texto):
    """Para o cache: muda se uma imagem usada no nome for trocada."""
    imgs = listar_imagens()
    sig = []
    for mo in _TOKEN.finditer(texto):
        k = mo.group(1).lower()
        if k in imgs and (":" + k + ":") not in ATALHOS:
            st = os.stat(imgs[k])
            sig.append((k, st.st_size, int(st.st_mtime)))
    return sig


def _fontes_reserva():
    """Fontes de símbolos/emojis usadas quando a fonte escolhida não tem o caractere."""
    # ordem de preferência: símbolos sólidos (melhores para imprimir) antes dos emojis de contorno
    cand = [os.path.join(FONTES_LOCAIS, "NotoSansSymbols2-Regular.ttf"), os.path.join(FONTS_DIR, "seguisym.ttf"),
            os.path.join(FONTES_LOCAIS, "NotoEmoji.ttf"), os.path.join(FONTS_DIR, "seguiemj.ttf")]
    return [c for c in cand if os.path.isfile(c)]


def _fonte_reserva(caminho, tamanho):
    """Abre a fonte de reserva; o Noto Emoji (variável) é aberto no peso mais grosso para o traço imprimir bem."""
    f = ImageFont.truetype(caminho, tamanho)
    if "NotoEmoji" in caminho:
        try:
            f.set_variation_by_axes([700])
        except Exception:
            pass
    return f


def _desenha(font, ch, tam=None):
    tam = tam or max(90, int(getattr(font, "size", 60) * 1.1))      # a tela acompanha o tamanho da fonte (letras grandes saíam da tela fixa e viravam "glifo ausente")
    im = Image.new("L", (tam * 2, tam * 2), 0)
    ImageDraw.Draw(im).text((10, 10), ch, font=font, fill=255)
    return np.asarray(im)


def _tem_glifo(font, ch):
    """True se a fonte realmente desenha o caractere (e não o quadradinho de 'glifo ausente')."""
    if ch.isspace():
        return True
    a = _desenha(font, ch)
    if not a.any():
        return False
    return not np.array_equal(a, _desenha(font, "\uFFFF"))


def mascara(texto, p):
    """Retorna (máscara 2D [linhas de cima p/ baixo], yc_mm = centro da faixa das maiúsculas medido a partir de baixo)."""
    m, yc, _ = mascara_rotulada(texto, p)
    return m, yc


_PADRAO_BALANCO = [1.0, -0.7, 0.5, -1.0, 0.8, -0.4, 0.9, -0.8]


def mascara_rotulada(texto, p):
    """Como mascara(), mas devolve também, para cada coluna da máscara, o índice da letra/símbolo a que ela pertence
    (usado no modo 'cores', que alterna a cor por letra). Modo 'zigzag': letras pares mais altas e ímpares mais baixas.
    Caracteres que a fonte não tem (corações, flores...) vêm de uma fonte de reserva; ':nome:' insere uma imagem importada."""
    res = p.voxel
    f0 = ImageFont.truetype(p.fonte, 200)
    bb = f0.getbbox("H")
    size = 200 * (p.altura / res) / (bb[3] - bb[1])
    f = ImageFont.truetype(p.fonte, max(8, int(round(size))))
    cap_h = size * (bb[3] - bb[1]) / 200
    track = p.espaco / res
    reservas = [_fonte_reserva(c, 200) for c in _fontes_reserva()]
    pad = int(6 / res)
    bh = f.getbbox("H")
    cap_top0 = bh[1]
    zig = p.modo == "zigzag" and p.zigzag > 0
    fontes_zz = {}

    def fonte_zz(sinal):
        if sinal not in fontes_zz:
            esc = max(0.5, 1 + sinal * p.zigzag / max(p.altura, 1.0))
            ft = ImageFont.truetype(p.fonte, max(8, int(round(size * esc))))
            fontes_zz[sinal] = (ft, ft.getbbox("H"))
        return fontes_zz[sinal]

    x, itens, inicios = 0.0, [], []     # itens: ("ch", x, ch, fonte, dx, dy) | ("img", x, mascara, dy); inicios: x de cada letra visível
    n_vis = 0
    for tipo, val in _elementos(texto, listar_imagens()):
        if tipo == "img":
            mi = _mascara_imagem(val, int(round(cap_h * 1.1)))
            dy = cap_top0 + (cap_h - mi.shape[0]) / 2
            itens.append(("img", x, mi, dy))
            inicios.append(x)
            n_vis += 1
            x += mi.shape[1] + 0.12 * size + track
            continue
        ch = val
        usar, dx, dy, simbolo = f, 0.0, 0.0, False
        if not _tem_glifo(f, ch) and not ch.isspace():
            for r in reservas:
                if _tem_glifo(r, ch):
                    l, t, rr, bt = r.getbbox(ch)
                    esc = max(1.0, cap_h * 1.05) / max(1, bt - t)
                    usar = _fonte_reserva(r.path, max(8, int(round(200 * esc))))
                    l, t, rr, bt = usar.getbbox(ch)
                    dx = -l
                    dy = cap_top0 + (cap_h - (bt - t)) / 2 - t          # centraliza o símbolo na faixa das maiúsculas
                    simbolo = True
                    break
        elif zig and not ch.isspace():
            usar, bz = fonte_zz(1 if n_vis % 2 == 0 else -1)
            dy = (cap_top0 + cap_h / 2) - (bz[1] + (bz[3] - bz[1]) / 2)    # mantém o centro das maiúsculas alinhado
        adv = (usar.getbbox(ch)[2] - usar.getbbox(ch)[0]) + 0.12 * size if simbolo else usar.getlength(ch)
        itens.append(("ch", x, ch, usar, dx, dy))
        if not ch.isspace():
            inicios.append(x)
            n_vis += 1
        x += adv + track
    img = Image.new("L", (int(x) + 2 * pad + int(size), int(size * 2) + 2 * pad), 0)
    d = ImageDraw.Draw(img)
    n_d = 0
    for it in itens:
        if it[0] == "img":
            _, gx, mi, dy = it
            img.paste(255, (int(pad + gx), int(pad + dy)), Image.fromarray((mi * 255).astype(np.uint8)))
        else:
            _, gx, ch, fnt, dx, dy = it
            if (p.inclinacao or p.ondula) and not ch.isspace():
                k_v = _PADRAO_BALANCO[n_d % len(_PADRAO_BALANCO)]
                n_d += 1
                ang = p.inclinacao * k_v
                dyo = p.ondula / res * _PADRAO_BALANCO[(n_d * 3 + 1) % len(_PADRAO_BALANCO)]
                L = int(size * 2)
                tmp = Image.new("L", (L, L), 0)
                ImageDraw.Draw(tmp).text((L / 4 + dx, L / 4 + dy), ch, font=fnt, fill=255)
                bb_t = tmp.getbbox()
                if bb_t:
                    cx = (bb_t[0] + bb_t[2]) / 2
                    cy = cap_top0 + L / 4 + cap_h / 2           # gira em torno do meio das maiúsculas
                    tmp = tmp.rotate(ang, resample=Image.BICUBIC, center=(cx, cy))
                    img.paste(255, (int(pad + gx - L / 4), int(pad - L / 4 + dyo)), tmp)
                continue
            d.text((pad + gx + dx, pad + dy), ch, font=fnt, fill=255)
    k = 1.0
    if abs(p.largura - 1.0) > 1e-3:
        w0 = img.width
        img = img.resize((max(8, int(img.width * p.largura)), img.height), Image.LANCZOS)
        k = img.width / w0
    cap_top, cap_bot = pad + bh[1], pad + bh[3]
    m = np.asarray(img) > 127
    m = ndi.gaussian_filter(m.astype(float), 1.2) > 0.5
    if p.engrossar > 0:
        m = ndi.distance_transform_edt(~m) <= p.engrossar / res
    ys, xs = np.where(m)
    if len(ys) == 0:
        raise ValueError(f"A fonte não tem glifos para '{texto}'")
    if p.ligar_letras:
        m = _ligar(m, p)
    off_x = 0
    if p.produto == "chaveiro":
        m, off_x = _argola(m, p, (cap_top + cap_bot) / 2)
        m = _ligar(m, Params(**{**asdict(p), "ponte": max(p.ponte, 0.5 * p.argola_ext)}))   # ligação larga: o chaveiro puxa por aqui
    ys, xs = np.where(m)
    y0, y1, x0, x1 = ys.min() - 2, ys.max() + 3, xs.min() - 2, xs.max() + 3
    m = m[y0:y1, x0:x1]
    centro_linha = (cap_top + cap_bot) / 2 - y0            # linhas a partir do topo
    yc = (m.shape[0] - centro_linha) * res
    starts = np.array([(pad + g) * k + off_x for g in inicios]) - x0
    cols = np.arange(m.shape[1])
    rot = np.clip(np.searchsorted(starts, cols, side="right") - 1, 0, None) if len(starts) else np.zeros(len(cols), int)
    return m, yc, rot


def _argola(m, p, cy):
    """Chaveiro: acrescenta à máscara uma argola (disco com furo) colada na primeira (ou última) letra, na altura do meio das maiúsculas.
    Devolve (máscara, deslocamento_em_colunas_à_esquerda)."""
    res = p.voxel
    R, r = p.argola_ext / 2 / res, p.argola_furo / 2 / res
    sol = 2.0 / res                                       # quanto a argola entra na letra
    extra = int(np.ceil(2 * R)) + 6
    esq = p.argola_lado != "direita"
    m = np.pad(m, ((0, 0), (extra, 0) if esq else (0, extra)))
    off = extra if esq else 0
    xs = np.where(m.any(axis=0))[0]
    cx = xs.min() - R + sol if esq else xs.max() + R - sol
    borda = xs.min() if esq else xs.max()                 # a argola acompanha onde a letra de ponta realmente está (T, L, A...)
    faixa = m[:, borda:borda + int(3.0 / res)] if esq else m[:, borda - int(3.0 / res):borda + 1]
    linhas = np.where(faixa.any(axis=1))[0]
    if len(linhas):
        cy = float(np.clip(linhas.mean(), cy - 4.0 / res, cy + 4.0 / res))
    yy, xx = np.ogrid[:m.shape[0], :m.shape[1]]
    d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    m = (m | (d2 <= R ** 2)) & ~(d2 <= r ** 2)
    return m, off


def _ligar(m, p):
    """Garante UMA peça só: liga letras/acentos soltos ao conjunto com pequenas pontes (linha grossa entre os pontos mais próximos)."""
    res = p.voxel
    w = max(3, int(round(p.ponte / res)))
    for _ in range(40):
        lab, n = ndi.label(m, structure=np.ones((3, 3)))
        if n <= 1:
            break
        sizes = ndi.sum(m, lab, range(1, n + 1))
        main = 1 + int(np.argmax(sizes))
        base = lab == main
        dist, (iy, ix) = ndi.distance_transform_edt(~base, return_indices=True)
        melhor = None
        for c in range(1, n + 1):
            if c == main:
                continue
            ys, xs = np.where(lab == c)
            k = np.argmin(dist[ys, xs])
            d = dist[ys[k], xs[k]]
            if melhor is None or d < melhor[0]:
                melhor = (d, xs[k], ys[k], ix[ys[k], xs[k]], iy[ys[k], xs[k]])
        _, ax, ay, bx, by = melhor
        im = Image.fromarray(m.astype(np.uint8) * 255)
        dr = ImageDraw.Draw(im)
        dr.line([(int(ax), int(ay)), (int(bx), int(by))], fill=255, width=w)
        dr.ellipse((ax - w / 2, ay - w / 2, ax + w / 2, ay + w / 2), fill=255)
        dr.ellipse((bx - w / 2, by - w / 2, bx + w / 2, by + w / 2), fill=255)
        m = np.asarray(im) > 127
    return m


def _perfil(z, T, rf, p):
    t = T - z
    g = np.where(t >= rf, 0.0, rf - np.sqrt(np.clip(rf ** 2 - (rf - t) ** 2, 0, None)))
    if p.base_arredondada:
        g = np.maximum(g, np.where(z >= rf, 0.0, rf - np.sqrt(np.clip(rf ** 2 - (rf - z) ** 2, 0, None))))
    return g



PRESETS_LAPIS = {   # tipo de lápis -> (medidas do furo por formato, altura da letra, espessura da peça)
    "Comum (lápis de 7 a 7,5 mm)": ({"Circular": 8.0, "Hexagonal": 7.5, "Triangular abaloado": 7.5}, 11.5, 10.9),
    "Jumbo (lápis de 10 a 10,5 mm)": ({"Circular": 10.8, "Hexagonal": 10.4, "Triangular abaloado": 10.6}, 15.5, 13.5),
}


def aplicar_preset(nome):
    """Atualiza FORMATOS_FURO com as medidas do tipo de lápis. Retorna (altura, espessura) sugeridas."""
    med, alt, esp = PRESETS_LAPIS[nome]
    for k, v in med.items():
        FORMATOS_FURO[k] = (FORMATOS_FURO[k][0], v)
    return alt, esp


FORMATOS_FURO = {   # nome na interface -> (formato, medida padrão em mm)
    "Circular": ("circular", 8.0),
    "Hexagonal": ("hexagonal", 7.5),
    "Triangular abaloado": ("triangular", 7.5),
}


def _sd_triangulo(u, v, r0):
    """Distância (com sinal) de pontos (u, v) a um triângulo equilátero de circunraio r0 com ponta para cima."""
    ri = r0 / 2
    ang = np.radians([-90, 30, 150])
    dentro = np.ones(u.shape, bool)
    for a in ang:
        dentro &= (u * np.cos(a) + v * np.sin(a)) <= ri
    vx = np.array([0, -r0 * np.cos(np.radians(30)), r0 * np.cos(np.radians(30))])
    vy = np.array([r0, -r0 / 2, -r0 / 2])
    dmin = np.full(u.shape, np.inf)
    for i in range(3):
        ax, ay, bx, by = vx[i], vy[i], vx[(i + 1) % 3], vy[(i + 1) % 3]
        ex, ey = bx - ax, by - ay
        t = np.clip(((u - ax) * ex + (v - ay) * ey) / (ex * ex + ey * ey), 0, 1)
        dmin = np.minimum(dmin, np.hypot(u - (ax + t * ex), v - (ay + t * ey)))
    return np.where(dentro, -dmin, dmin)


def furo_mascara(p, dy, dz):
    """True onde há furo. (dy, dz) = posição relativa ao eixo do furo, no plano da seção (y = largura da letra, z = altura)."""
    th = np.radians(p.furo_rot)
    u = dy * np.cos(th) + dz * np.sin(th)
    v = -dy * np.sin(th) + dz * np.cos(th)
    med = p.furo + p.furo_folga
    if p.furo_formato == "hexagonal":
        ap = med / 2
        ok = np.ones(np.broadcast(u, v).shape, bool)
        for a in np.radians([90, 30, 150]):
            ok &= np.abs(u * np.cos(a) + v * np.sin(a)) <= ap
        return ok
    if p.furo_formato == "triangular":
        rc = min(p.furo_canto, med * 0.2)
        r0 = (med - 2 * rc) / 1.5                          # altura total = 1,5·r0 + 2·rc = med
        return _sd_triangulo(u + 0 * v, v + 0 * u, r0) <= rc
    return u ** 2 + v ** 2 <= (med / 2) ** 2


def furo_limites(p):
    """(ymin, ymax, zmin, zmax) do furo em relação ao seu centro."""
    g = np.arange(-9, 9.001, 0.05)
    m = furo_mascara(p, g[:, None], g[None, :])
    iy, iz = np.where(m)
    return g[iy.min()], g[iy.max()], g[iz.min()], g[iz.max()]


def furo_centro_z(p):
    """Altura (z) do centro do furo: a parede da base fica sob o ponto mais baixo do furo."""
    return p.parede_base - furo_limites(p)[2]


def ocupacao(m, yc, p, rot=None):
    """Volume (x, y, z) das letras (fundidas numa peça) com o furo do lápis atravessando o nome inteiro (eixo X).
    Estilos: fechada (sólida) · vazada (só o contorno, com fundo opcional) · base (borda em degrau em volta das letras)."""
    res = p.voxel
    K = int(round(p.espessura / res))
    z = (np.arange(K) + 0.5) * res
    if p.estilo == "base":
        pad = int(np.ceil(p.borda / res)) + 3           # a borda em volta precisa de espaço ao redor da máscara
        m = np.pad(m, pad)
        yc = yc + pad * res
        if rot is not None:
            rot = np.pad(rot, pad, mode="edge")
    if p.dois_lados and p.produto != "chaveiro":
        # deixa a máscara simétrica em torno do eixo do furo, para o espelho (de cabeça para baixo) cair no lugar certo
        H = m.shape[0]
        rc = H - yc / res                                # linha do eixo, contada a partir do topo
        cima = int(round(max(0.0, H - 2 * rc)))
        baixo = int(round(max(0.0, 2 * rc - H)))
        m = np.pad(m, ((cima, baixo), (0, 0)))
        yc = m.shape[0] / 2 * res

    def corpo(mm):
        """Volume (linhas, colunas, z) de uma máscara no estilo escolhido."""
        if p.estilo == "vazada":
            parede = max(p.borda, 3 * res)
            dist = ndi.distance_transform_edt(mm) * res
            anel = _ligar(mm & (dist <= parede), p)      # liga laços soltos com pontes (como num estêncil)
            dist_a = ndi.distance_transform_edt(anel) * res
            g = _perfil(z, p.espessura, min(p.raio, parede / 2), p)
            o = (dist_a[:, :, None] >= np.maximum(g, res * 0.5)[None, None, :]) & anel[:, :, None]
            if p.fundo > 0:
                o |= mm[:, :, None] & (z[None, None, :] <= p.fundo)
            return o
        dist = ndi.distance_transform_edt(mm) * res
        g = _perfil(z, p.espessura, p.raio, p)
        o = (dist[:, :, None] >= np.maximum(g, res * 0.5)[None, None, :]) & mm[:, :, None]
        if p.estilo == "base":
            halo = ndi.distance_transform_edt(~mm) <= p.borda / res
            dist_h = ndi.distance_transform_edt(halo) * res
            hb = min(p.altura_borda, p.espessura)
            gb = _perfil(z, hb, min(p.raio, hb * 0.8, p.borda), p)
            o |= (dist_h[:, :, None] >= np.maximum(gb, res * 0.5)[None, None, :]) & halo[:, :, None] & (z[None, None, :] <= hb)
        return o

    occ = corpo(m)
    if p.dois_lados and p.produto != "chaveiro":
        occ_b = corpo(m[::-1])                           # metade de baixo: o mesmo nome virado de cabeça para baixo
        occ = np.where((z >= p.espessura / 2)[None, None, :], occ, occ_b)
    occ = np.flip(occ, 0).transpose(1, 0, 2)              # (x=colunas, y=linhas invertidas, z); linha 0 = topo -> y máximo
    nx, ny, nz = occ.shape
    y = (np.arange(ny) + 0.5) * res
    if p.produto == "chaveiro":                             # chaveiro: o furo é o da argola (já está na máscara)
        return (occ, rot) if rot is not None else occ
    zc = furo_centro_z(p)                                   # altura do eixo do furo
    ymin, ymax, zmin, zmax = furo_limites(p)
    H = ny * res
    folga_y = min(yc + ymin, H - (yc + ymax))
    folga_topo = p.espessura - (zc + zmax)
    if folga_y < 0.8 or folga_topo < 0.8:
        raise ValueError(
            f"O furo ({p.furo_formato} {p.furo + p.furo_folga:.1f} mm) não cabe com parede segura: "
            f"sobram {folga_y:.1f} mm nas laterais e {folga_topo:.1f} mm no topo (mínimo 0,8). "
            f"Aumente a altura da letra / a espessura ou diminua o furo.")
    fm = furo_mascara(p, (y - yc)[:, None], (z - zc)[None, :])   # (y, z)
    occ &= ~fm[None, :, :]                                  # furo passante (eixo X), aberto nas duas pontas
    return (occ, rot) if rot is not None else occ


def previa(texto, p, largura=760):
    """Imagem rápida (sem Blender): relevo iluminado + faixa do furo do lápis. Retorna (PIL.Image, (larg_mm, alt_mm))."""
    q = Params(**{**asdict(p), "voxel": max(p.voxel, 0.12)})
    m, yc = mascara(texto, q)
    res = q.voxel
    cor_letra = np.array([255, 150, 25])
    cor_base = np.array([255, 205, 130])
    cor_fundo = np.array([215, 120, 15])
    if q.estilo == "base":
        pad = int(np.ceil(q.borda / res)) + 3
        m = np.pad(m, pad)
        yc = yc + pad * res
        halo = ndi.distance_transform_edt(~m) <= q.borda / res
    dist = ndi.distance_transform_edt(m) * res
    topo = m
    if q.estilo == "vazada":
        topo = _ligar(m & (dist <= max(q.borda, 3 * res)), q)
        dist = ndi.distance_transform_edt(topo) * res
    t = np.minimum(dist, q.raio) / q.raio
    h = np.where(topo, p.espessura * np.sqrt(np.clip(1 - (1 - t) ** 2, 0, 1)), 0)
    gy, gx = np.gradient(ndi.gaussian_filter(h, 1.0))
    nrm = np.sqrt(gx ** 2 + gy ** 2 + 1.0)
    luz = np.array([-0.45, -0.55, 0.7])
    luz /= np.linalg.norm(luz)
    sh = 0.35 + 0.65 * np.clip((-gx * luz[0] - gy * luz[1] + luz[2]) / nrm, 0, 1)
    rgb = np.zeros(m.shape + (3,), np.uint8)
    rgb[:] = (245, 245, 245)
    if q.estilo == "base":
        rgb[halo] = cor_base
    if q.estilo == "vazada" and q.fundo > 0:
        rgb[m & ~topo] = cor_fundo
    rgb[topo] = (cor_letra[None, :] * sh[topo][:, None]).astype(np.uint8)
    # faixa do furo do lápis (vista de cima): linhas tracejadas em azul
    lin = m.shape[0] - int(round(yc / res))
    ymin_f, ymax_f, _, _ = furo_limites(q)
    for ylin in (() if q.produto == "chaveiro" else (lin - int(round(ymax_f / res)), lin - int(round(ymin_f / res)))):
        if 0 <= ylin < m.shape[0]:
            rgb[ylin, ::6] = (30, 90, 220)
            rgb[min(ylin + 1, m.shape[0] - 1), ::6] = (30, 90, 220)
    img = Image.fromarray(rgb)
    esc = largura / img.width
    img = img.resize((largura, max(1, int(img.height * esc))), Image.LANCZOS)
    return img, (m.shape[1] * res, m.shape[0] * res)


def previa_corte(p, altura_mm, tam=220):
    """Seção transversal da peça (visão de ponta): retângulo da letra com o furo em azul. Retorna PIL.Image."""
    esc = tam / max(altura_mm, p.espessura) * 0.8
    W, Hh = int(altura_mm * esc), int(p.espessura * esc)
    img = Image.new("RGB", (tam, tam), (250, 250, 250))
    dr = ImageDraw.Draw(img)
    ox, oy = (tam - W) // 2, (tam + Hh) // 2          # canto inferior esquerdo
    dr.rectangle((ox, oy - Hh, ox + W, oy), fill=(255, 190, 90), outline=(120, 80, 20))
    zc = furo_centro_z(p)
    yc = altura_mm / 2
    g = np.arange(0, tam)
    dy = ((g - ox) / esc - yc)[None, :]
    dz = ((oy - g) / esc - zc)[:, None]
    m = furo_mascara(p, dy, dz) & (g[None, :] >= ox) & (g[None, :] <= ox + W) & (g[:, None] <= oy) & (g[:, None] >= oy - Hh)
    arr = np.asarray(img).copy()
    arr[m] = (250, 250, 250)
    img = Image.fromarray(arr)
    dr = ImageDraw.Draw(img)
    dr.text((6, 4), f"{p.furo_formato}  {p.furo + p.furo_folga:.2f} mm", fill=(30, 60, 160))
    return img


def malha_skimage(occ, res, alvo=ALVO_TRIS):
    """Malha fechada e suave (marching cubes sobre o volume levemente suavizado) com ~alvo triângulos. Retorna (verts mm, faces)."""
    from skimage.measure import marching_cubes
    vol = ndi.gaussian_filter(np.pad(occ, 1).astype(np.float32), 0.9)
    verts, faces, _, _ = marching_cubes(vol, level=0.5, spacing=(res, res, res))
    del vol
    verts = verts - res + 0.5 * res                       # tira o preenchimento e alinha ao centro dos voxels
    faces = faces.astype(np.int32)
    if len(faces) > alvo:
        import fast_simplification
        verts, faces = fast_simplification.simplify(verts.astype(np.float32), faces, target_reduction=min(0.97, 1 - alvo / len(faces)))
    verts = np.asarray(verts, dtype=np.float32)
    tri = verts[faces]
    if np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() < 0:   # garante normais para fora
        faces = faces[:, ::-1]
    return verts, np.asarray(faces, dtype=np.int32)


def gravar_stl(path, v, f):
    """STL binário (mm) a partir de vértices e faces."""
    tri = np.asarray(v, np.float32)[f]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    arr = np.zeros(len(f), dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))
    arr["n"] = n
    arr["v"] = tri.reshape(len(f), 9)
    with open(path, "wb") as fh:
        fh.write(b"ponteiras".ljust(80, b"\0"))
        fh.write(struct.pack("<I", len(f)))
        fh.write(arr.tobytes())


def _faces(M, res):
    P = np.pad(M, 1)
    quads = []
    for ax in range(3):
        for sgn in (1, -1):
            nb = np.roll(P, -sgn, axis=ax)
            idx = np.argwhere(P & ~nb) - 1
            if len(idx) == 0:
                continue
            base = idx.astype(np.int64)
            if sgn == 1:
                base[:, ax] += 1
            a1, a2 = [i for i in range(3) if i != ax]
            c = []
            for (u, v) in [(0, 0), (1, 0), (1, 1), (0, 1)]:
                pp = base.copy()
                pp[:, a1] += u
                pp[:, a2] += v
                c.append(pp)
            q = np.stack(c, 1)
            if (sgn == 1) != ((a1 - ax) % 3 == 1):
                q = q[:, ::-1]
            quads.append(q)
    q = np.concatenate(quads)
    flat = q.reshape(-1, 3)
    key = flat[:, 0] * 10 ** 8 + flat[:, 1] * 10 ** 4 + flat[:, 2]
    u, inv = np.unique(key, return_inverse=True)
    first = np.zeros(len(u), np.int64)
    first[inv[::-1]] = np.arange(len(inv))[::-1]
    return (flat[first] * res).astype(np.float32), inv.reshape(-1, 4).astype(np.int32)


def ler_stl(path):
    b = open(path, "rb").read()
    n = struct.unpack("<I", b[80:84])[0]
    arr = np.frombuffer(b[84:], dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]), count=n)
    v = arr["v"].reshape(-1, 3).astype(np.float64)
    key = np.round(v * 1e4).astype(np.int64)
    _, idx, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return v[idx], inv.ravel().reshape(-1, 3)


def seguro(n):
    t = "".join(c for c in __import__("unicodedata").normalize("NFKD", n) if not __import__("unicodedata").combining(c))
    return re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").upper() or "NOME"


GEO_VERSAO = 5        # sobe quando a geometria muda (marcador: haste presa ao bloco do nome); invalida os STLs em cache


def chave(nome, p):
    h = hashlib.md5(repr((p.fonte, p.altura, p.espessura, p.raio, p.engrossar, p.espaco, p.base_arredondada, p.voxel, p.furo, p.furo_formato, p.furo_folga, p.furo_rot, p.furo_canto, p.parede_base, p.largura, p.ponte, p.estilo, p.borda, p.fundo, p.altura_borda, p.modo, p.zigzag, p.inclinacao, p.ondula, p.produto, p.elo_largo, p.elo_ancho, p.elo_alto, p.elo_espaco, p.ligar_letras, p.elo_forma, p.elo_canto, p.elo_borda, p.base_alt, p.emblema, p.emblema_d, p.marc_cores, p.livro_pos, p.emoji, p.emoji_d, p.marc_larg, p.marc_braco, p.marc_fenda, p.marc_cab, p.marc_cab_alt, p.marc_clip, p.marc_comp, p.elo_primeiro, p.elo_ultimo, p.relevo, p.argola_ext, p.argola_furo, p.argola_lado, nome, _assinatura_imagens(nome), 8, GEO_VERSAO)).encode()).hexdigest()[:6]
    return f"{seguro(nome)}_{h}"


# ----------------------------------------------------------------------------- pipeline
def gerar_stls(nomes_params, saida, log=print, refazer=False):
    """nomes_params: lista de (nome, Params) sem repetição. Cria saida/stl/<chave>.stl."""
    stl = os.path.join(saida, "stl")
    for velho in os.listdir(saida) if os.path.isdir(saida) else []:
        if velho.startswith("_tmp"):
            shutil.rmtree(os.path.join(saida, velho), ignore_errors=True)   # restos de execuções interrompidas
    tmp = os.path.join(saida, f"_tmp_{os.getpid()}")
    os.makedirs(tmp, exist_ok=True)
    os.makedirs(stl, exist_ok=True)
    pend = 0
    voxel = None
    for nome, p in nomes_params:
        k = chave(nome, p)
        if os.path.exists(os.path.join(stl, k + ".stl")) and not refazer:
            log(f"  {nome}: já gerado (cache)")
            continue
        log(f"  {nome}: desenhando letras...")
        if p.produto == "marcador":                 # marcador de páginas: base + letras/boca + rosto + capelo/óculos (4 filamentos)
            partes_m, res_c = marcador_occ(nome, p)
            fino = res_c <= 0.06                              # voxel fino (0,05 mm): peça pequena com texto miúdo, mais triângulos para não perder o contorno
            uni = np.logical_or.reduce(partes_m)
            v, fc = malha_skimage(uni, res_c, 260000 if fino else ALVO_TRIS)
            gravar_stl(os.path.join(stl, k + ".stl"), v, fc)
            for i, oc in enumerate(partes_m, 1):
                if oc.any():
                    v2, f2 = malha_skimage(oc, res_c, 160000 if fino else ALVO_TRIS // 2)
                    gravar_stl(os.path.join(stl, k + f"_P{i}.stl"), v2, f2)
            log(f"  OK {nome}: marcador de páginas, {len(fc)} triângulos")
            del partes_m, uni
            continue
        if p.produto == "tag":                      # chaveiro com base de contorno: base (cor A) + letras (cor B)
            base, letras, res_c = tag_occ(nome, p)
            v, fc = malha_skimage(base | letras, res_c)
            gravar_stl(os.path.join(stl, k + ".stl"), v, fc)
            for suf, oc in (("_A", base), ("_B", letras)):
                if oc.any():
                    v2, f2 = malha_skimage(oc, res_c, ALVO_TRIS // 2)
                    gravar_stl(os.path.join(stl, k + suf + ".stl"), v2, f2)
            log(f"  OK {nome}: chaveiro com base, {len(fc)} triângulos")
            del base, letras
            continue
        if p.produto == "corrente":                 # um elo por letra: base (cor A) + letras (cor B), imprime montada
            base, letras, res_c = corrente_occ(nome, p)
            nel = max(1, len(_elementos(nome, listar_imagens())))
            alvo = max(ALVO_TRIS, 40000 * nel)
            v, fc = malha_skimage(base | letras, res_c, alvo=alvo)
            gravar_stl(os.path.join(stl, k + ".stl"), v, fc)
            for suf, oc, al in (("_A", base, alvo), ("_B", letras, max(ALVO_TRIS, 12000 * nel))):
                if oc.any():
                    v2, f2 = malha_skimage(oc, res_c, alvo=al)
                    gravar_stl(os.path.join(stl, k + suf + ".stl"), v2, f2)
            log(f"  OK {nome}: corrente de {nel} elo(s), {len(fc)} triângulos")
            del base, letras
            continue
        if p.modo == "cores":                       # duas cores alternadas por letra: STL da união + parte A + parte B
            m, yc, rot = mascara_rotulada(nome, p)
            occ, rotf = ocupacao(m, yc, p, rot)
            v, fc = malha_skimage(occ, p.voxel)
            gravar_stl(os.path.join(stl, k + ".stl"), v, fc)
            par = (rotf % 2) == 0
            for suf, sel in (("_A", par), ("_B", ~par)):
                oc = occ & sel[:, None, None]
                if oc.any():
                    v2, f2 = malha_skimage(oc, p.voxel)
                    gravar_stl(os.path.join(stl, k + suf + ".stl"), v2, f2)
            log(f"  OK {nome}: 2 cores, {len(fc)} triângulos")
            del occ, m
            continue
        m, yc = mascara(nome, p)
        occ = ocupacao(m, yc, p)
        if MESHER == "skimage":
            v, fc = malha_skimage(occ, p.voxel)
            gravar_stl(os.path.join(stl, k + ".stl"), v, fc)
            log(f"  OK {nome}: {len(fc)} triângulos")
            del occ, m
            continue
        v, q = _faces(occ, p.voxel)
        np.savez(os.path.join(tmp, k + ".npz"), v=v, q=q)
        pend += 1
        voxel = p.voxel if voxel is None else min(voxel, p.voxel)
    if pend:
        arqs = sorted(f for f in os.listdir(tmp) if f.endswith(".npz"))
        nproc = max(1, min(len(arqs), (os.cpu_count() or 2) - 1, 6))
        log(f"  suavizando {pend} nome(s) no Blender ({nproc} em paralelo)...")
        lotes = [[] for _ in range(nproc)]
        for i, f in enumerate(sorted(arqs, key=lambda f: -os.path.getsize(os.path.join(tmp, f)))):
            lotes[i % nproc].append(f)           # balanceia: maiores primeiro, em rodízio
        procs = []
        for i, lote in enumerate(lotes):
            sub = os.path.join(tmp, f"w{i}")
            os.makedirs(sub)
            for f in lote:
                shutil.move(os.path.join(tmp, f), os.path.join(sub, f))
            procs.append(subprocess.Popen([BLENDER, "-b", "--python", os.path.join(HERE, "mesh_nomes.py"), "--", sub, stl, str(voxel)],
                                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
        for pr in procs:
            out = pr.communicate()[0]
            for ln in out.splitlines():
                if ln.startswith("OK") or "Error" in ln or "Traceback" in ln:
                    log("  " + ln)
    shutil.rmtree(tmp, ignore_errors=True)
    return stl


def empacotar(pecas, geo, prato=256.0, margem=12.0, folga=6.0):
    """pecas: lista de chaves; geo[chave]=(v,f,dim). Retorna lista de pratos [(chave,x,y)...] (prateleiras)."""
    pecas = sorted(pecas, key=lambda k: -geo[k][2][1])
    pratos = []

    def novo():
        return {"x": margem, "y": margem, "linha": 0.0, "itens": []}

    p = novo()
    pratos.append(p)
    for k in pecas:
        w, h = geo[k][2][0], geo[k][2][1]
        if w > prato - 2 * margem:
            raise ValueError(f"Peça maior que o prato ({w:.0f} mm)")
        if p["x"] + w > prato - margem:
            p["x"] = margem
            p["y"] += p["linha"] + folga
            p["linha"] = 0.0
        if p["y"] + h > prato - margem:
            p = novo()
            pratos.append(p)
        p["itens"].append((k, p["x"], p["y"]))
        p["x"] += w + folga
        p["linha"] = max(p["linha"], h)
    return [q["itens"] for q in pratos]


NS = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
      'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
      'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p"')


def escrever_3mf(arq, itens, geo, rotulo, partes=None, material="PLA", cores=None):
    """itens: [(chave,x,y)]; rotulo[chave]=nome de exibição. partes[chave] = [(v, f, extrusor)] para peças de várias cores
    (um objeto com várias partes, cada uma no seu filamento)."""
    partes = partes or {}
    zf = zipfile.ZipFile(arq, "w", zipfile.ZIP_DEFLATED)
    zf.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n <Default Extension="png" ContentType="image/png"/>\n <Default Extension="gcode" ContentType="text/x.gcode"/>\n</Types>')
    zf.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n</Relationships>')
    objs, rels, cont = {}, [], 0          # objs[n] = [(id_do_objeto, n_faces, extrusor)]; uma malha própria por peça (o Studio não abre malha repetida)
    for n, (k, _, _) in enumerate(itens):
        lista = partes[k] if k in partes else [(geo[k][0], geo[k][1], 1)]
        objs[n] = []
        for v, f, ext in lista:
            cont += 1
            x = ['<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" %s>\n <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n  <object id="%d" p:UUID="%08x-81cb-4c03-9d28-80fed5dfa1dc" type="model">\n   <mesh>\n    <vertices>' % (NS, cont, 0x10000 + cont)]
            x += ['     <vertex x="%.5g" y="%.5g" z="%.5g"/>' % tuple(r) for r in v] + ["    </vertices>\n    <triangles>"]
            x += ['     <triangle v1="%d" v2="%d" v3="%d"/>' % tuple(r) for r in f] + ["    </triangles>\n   </mesh>\n  </object>\n </resources>\n <build/>\n</model>"]
            zf.writestr("3D/Objects/object_%d.model" % cont, "\n".join(x))
            rels.append(' <Relationship Target="/3D/Objects/object_%d.model" Id="rel-%d" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>' % (cont, cont))
            objs[n].append((cont, len(f), ext))
    zf.writestr("3D/_rels/3dmodel.model.rels", '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n' + "\n".join(rels) + "\n</Relationships>")
    base = cont
    res, build, objcfg, inst = [], [], [], []
    for n, (k, x, y) in enumerate(itens):
        oid = base + 1 + n
        nm = escape(rotulo[k])
        comps = "\n".join(
            f'    <component p:path="/3D/Objects/object_{cid}.model" objectid="{cid}" p:UUID="{0x200 + n * 8 + j:08x}-b206-40ff-9872-83e8017abed1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>'
            for j, (cid, _, _) in enumerate(objs[n]))
        res.append(f'  <object id="{oid}" p:UUID="{0x100 + n:08x}-61cb-4c03-9d28-80fed5dfa1dc" type="model">\n   <components>\n{comps}\n   </components>\n  </object>')
        build.append(f'  <item objectid="{oid}" p:UUID="{0x300 + n:08x}-b1ec-4553-aec9-835e5b724bb4" transform="1 0 0 0 1 0 0 0 1 {x:.4f} {y:.4f} 0" printable="1"/>')
        pts = "\n".join(f'''    <part id="{cid}" subtype="normal_part">
      <metadata key="name" value="{nm}{'' if len(objs[n]) == 1 else ' - cor ' + str(j + 1)}"/>
      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>
      <metadata key="source_object_id" value="0"/>
      <metadata key="source_volume_id" value="{j}"/>
      <metadata key="source_offset_x" value="0"/>
      <metadata key="source_offset_y" value="0"/>
      <metadata key="source_offset_z" value="0"/>
      <metadata key="extruder" value="{ext}"/>
      <mesh_stat face_count="{nf}" edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>
    </part>''' for j, (cid, nf, ext) in enumerate(objs[n]))
        objcfg.append(f'''  <object id="{oid}">
    <metadata key="name" value="{nm}"/>
    <metadata key="extruder" value="1"/>
    <metadata face_count="{sum(nf for _, nf, _ in objs[n])}"/>
{pts}
  </object>''')
        inst.append(f'    <model_instance>\n      <metadata key="object_id" value="{oid}"/>\n      <metadata key="instance_id" value="0"/>\n      <metadata key="identify_id" value="{1000 + n}"/>\n    </model_instance>')
    main = f'''<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" {NS}>
 <metadata name="Application">BambuStudio-02.07.01.57</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <metadata name="Title">Ponteiras nomes</metadata>
 <resources>
{chr(10).join(res)}
 </resources>
 <build p:UUID="2c7c17d8-22b5-4d84-8835-1976022ea369">
{chr(10).join(build)}
 </build>
</model>'''
    zf.writestr("3D/3dmodel.model", main)
    zf.writestr("Metadata/model_settings.config",
                '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "\n".join(objcfg) +
                '\n  <plate>\n    <metadata key="plater_id" value="1"/>\n    <metadata key="plater_name" value="Plate 1"/>\n    <metadata key="locked" value="false"/>\n    <metadata key="filament_map_mode" value="Auto For Flush"/>\n' +
                "\n".join(inst) + "\n  </plate>\n  <assemble>\n  </assemble>\n</config>")
    if os.path.exists(BASE_CFG):
        zf.writestr("Metadata/project_settings.config", config_material(material, cores, max([e for v in objs.values() for _, _, e in v] or [1])))
    zf.close()


def opcoes_enfeite():
    """[(rótulo, token)]: '(nenhum)', símbolos prontos (coração, flor, estrela...) e as imagens importadas."""
    ops = [("(nenhum)", "")]
    ops += [(k.strip(":") + " (símbolo)", k) for k in ATALHOS]
    ops += [(nome + " (imagem)", f":{nome}:") for nome in listar_imagens()]
    return ops


def compor_nome(nome, antes="", depois=""):
    """Junta o nome com enfeites (símbolos/imagens) antes e depois. Ex.: compor_nome('Ana', ':coracao:', ':coracao:')."""
    return f"{antes}{nome.strip()}{depois}"


def gerar_tudo(itens, saida, log=print, refazer=False, pasta_pedido=None, detalhes=None, material="PLA", cores=None):
    """itens: [(nome, qtd, Params[, rotulo])]. O nome pode conter enfeites (ex.: ':coracao:ANA:coracao:').
    Gera STLs e pratos 3MF. Retorna a lista de arquivos 3MF. Se `detalhes` (dict) for passado, recebe: pratos, geo, rotulo, stl."""
    os.makedirs(saida, exist_ok=True)
    norm = []
    for it in itens:
        n, q, p = it[:3]
        rot = it[3] if len(it) > 3 and it[3] else None
        if n.strip() and int(q) > 0:
            norm.append((aplicar_caixa(n.strip(), p), int(q), p, rot))
    if not norm:
        raise ValueError("Nenhum nome informado")
    unicos, rotulos = {}, {}
    for n, q, p, rot in norm:
        unicos[chave(n, p)] = (n, p)
        rotulos[chave(n, p)] = rot or n
    itens = [(n, q, p) for n, q, p, _ in norm]
    log(f"{len(unicos)} nome(s) diferente(s), {sum(q for _, q, _ in itens)} peça(s) no total")
    stl = gerar_stls(list(unicos.values()), saida, log, refazer)
    geo, rotulo, partes = {}, {}, {}
    for k, (n, p) in unicos.items():
        v, f = ler_stl(os.path.join(stl, k + ".stl"))
        mn = v.min(0)
        v = v - mn
        geo[k] = (v, f, v.max(0))
        rotulo[k] = rotulos[k]
        if p.produto == "marcador":                 # partes 1..4 (filamentos) no mesmo referencial da peça inteira
            lst = []
            for i in range(1, 5):
                arq_p = os.path.join(stl, k + f"_P{i}.stl")
                if os.path.exists(arq_p):
                    vp, fp = ler_stl(arq_p)
                    lst.append((vp - mn, fp, i))
            if len(lst) >= 2:
                partes[k] = lst
            continue
        if p.modo == "cores" or p.produto in ("corrente", "tag"):   # partes A e B no mesmo referencial (mesma origem da peça inteira)
            lst = []
            for suf, ext in (("_A", 1), ("_B", 2)):
                arq_p = os.path.join(stl, k + suf + ".stl")
                if os.path.exists(arq_p):
                    vp, fp = ler_stl(arq_p)
                    lst.append((vp - mn, fp, ext))
            if len(lst) == 2:
                partes[k] = lst
    pecas = []
    for n, q, p in itens:
        pecas += [chave(n, p)] * q
    pratos = empacotar(pecas, geo)
    if detalhes is not None:
        detalhes.update({"pratos": pratos, "geo": geo, "rotulo": rotulo, "stl": stl, "partes": partes})
    arqs = []
    destino = pasta_pedido or saida
    os.makedirs(destino, exist_ok=True)
    for i, pr in enumerate(pratos, 1):
        arq = os.path.join(destino, f"Ponteiras_prato_{i}.3mf")
        escrever_3mf(arq, pr, geo, rotulo, partes, material, cores)
        arqs.append(arq)
        log(f"prato {i}: {len(pr)} peça(s) -> {arq}")
    return arqs


def gerar_gabarito(formato, medidas, saida, folga=0.0, rot=0.0, canto=1.2, espessura=5.0, voxel=0.1, log=print):
    """Peça de teste: uma barra com um furo VERTICAL de cada medida (da esquerda para a direita, em ordem crescente).
    Imprime em poucos minutos; o furo em que o lápis entra com leve atrito é o tamanho certo."""
    medidas = sorted(medidas)
    pitch = max(medidas) * 1.25 + 6
    nx, ny, nz = int(len(medidas) * pitch / voxel), int(pitch / voxel), int(espessura / voxel)
    x = (np.arange(nx) + 0.5) * voxel
    y = (np.arange(ny) + 0.5) * voxel
    occ = np.ones((nx, ny, nz), bool)
    # canto chanfrado no início da barra (marca o menor furo)
    cham = 6.0
    xx, yy = np.meshgrid(x, y, indexing="ij")
    occ &= ~((xx + yy) < cham)[:, :, None]
    for i, med in enumerate(medidas):
        q = Params(furo_formato=formato, furo=med, furo_folga=folga, furo_rot=rot, furo_canto=canto)
        fm = furo_mascara(q, (xx - (i + 0.5) * pitch), (yy - pitch / 2))
        occ &= ~fm[:, :, None]
    stl = os.path.join(saida, "stl_gabarito")
    os.makedirs(stl, exist_ok=True)
    nome = f"GABARITO_{formato.upper()}"
    if MESHER == "skimage":
        vv_, ff_ = malha_skimage(occ, voxel)
        gravar_stl(os.path.join(stl, nome + ".stl"), vv_, ff_)
        r = None
    else:
        v, qd = _faces(occ, voxel)
        tmp = os.path.join(saida, f"_tmp_gab_{os.getpid()}")
        os.makedirs(tmp, exist_ok=True)
        np.savez(os.path.join(tmp, nome + ".npz"), v=v, q=qd)
        log("  suavizando o gabarito no Blender...")
        r = subprocess.run([BLENDER, "-b", "--python", os.path.join(HERE, "mesh_nomes.py"), "--", tmp, stl, str(voxel)], capture_output=True, text=True)
        shutil.rmtree(tmp, ignore_errors=True)
    arq_stl = os.path.join(stl, nome + ".stl")
    if not os.path.exists(arq_stl):
        raise RuntimeError("Falha ao gerar o gabarito: " + (r.stdout[-400:] if r else ""))
    vv, ff = ler_stl(arq_stl)
    vv = vv - vv.min(0)
    geo = {nome: (vv, ff, vv.max(0))}
    arq = os.path.join(saida, f"Gabarito_{formato}_{'_'.join(f'{m:g}' for m in medidas)}.3mf")
    escrever_3mf(arq, [(nome, 20.0, 20.0)], geo, {nome: nome})
    log(f"gabarito ({formato}) com furos de {', '.join(f'{m:g}' for m in medidas)} mm (esquerda -> direita, o chanfro marca o menor): {arq}")
    return arq


def sugerir_ajustes(nome_fonte):
    """Sugestão de ajustes (engrossar, arredondado, largura, espaço) conforme o tipo de fonte. Retorna dict ou None."""
    n = nome_fonte.lower()
    if any(k in n for k in ("pixel", "silkscreen", "press start", "vt323", "jersey", "tiny5", "micro 5")):
        return {"engrossar": 0.35, "raio": 0.6, "largura": 1.0, "espaco": 0.4}          # estilo Minecraft: blocos
    if any(k in n for k in ("lobster", "pacifico", "cookie", "kaushan", "grand hotel", "yellowtail", "damion", "playball",
                            "courgette", "sacramento", "great vibes", "dancing", "lily script", "leckerli", "shrikhand", "berkshire")):
        return {"engrossar": 0.9, "raio": 2.0, "largura": 1.0, "espaco": -0.4}          # scripts: traço fino, precisa engrossar
    if any(k in n for k in ("pirata", "rye", "sancreek", "jolly", "new rocker", "ribeye")):
        return {"engrossar": 0.4, "raio": 1.6, "largura": 0.9, "espaco": -0.2}          # pirata / faroeste ("procurado")
    if "emoji" in n or "symbols" in n:
        return {"engrossar": 0.3, "raio": 1.2, "largura": 1.0, "espaco": 0.6}
    if any(k in n for k in ("modak", "chewy", "titan", "luckiest", "fredoka", "baloo", "bubblegum", "sniglet", "lilita", "paytone",
                            "sigmar", "margarine", "chelsea", "mouse memoirs", "bangers")):
        return {"engrossar": 0.3, "raio": 2.2, "largura": 0.8, "espaco": -0.4}          # cartoon grosso
    return None


GRUPOS_ESPECIAIS = [   # (título do grupo, palavras-chave da família da fonte)
    ("★ Script estilo Lobster / Disney", ("lobster", "pacifico", "cookie", "kaushan", "grand hotel", "yellowtail", "damion", "playball",
                                          "courgette", "sacramento", "great vibes", "dancing", "lily script", "leckerli", "shrikhand",
                                          "berkshire", "emilys", "fontdiner", "caveat", "gochi", "alex brush", "allura", "bad script",
                                          "knewave", "lovers quarrel", "marck script", "niconne", "norican", "oleo script", "parisienne",
                                          "pattaya", "sofia", "sriracha", "permanent marker", "kalam", "patrick hand", "handlee", "amatic")),
    ("★ Infantil / Cartoon", ("chewy", "modak", "titan one", "luckiest", "fredoka", "baloo", "bubblegum", "sniglet", "lilita", "paytone",
                              "sigmar", "chelsea", "mouse memoirs", "bangers", "comic neue", "pangolin", "sansita", "fascinate",
                              "rubik bubbles", "margarine", "bevan", "boogaloo", "carter one", "chicle", "coiny", "concert one",
                              "fugaz", "galindo", "gorditas", "jua", "kavoon", "lemon", "londrina", "mochiy", "mogra", "rammetto",
                              "righteous", "sonsie", "spicy rice", "varela round", "bungee")),
    ("★ Pixel (estilo Minecraft)", ("pixel", "silkscreen", "press start", "vt323", "jersey", "tiny5", "micro 5", "dotgothic",
                                    "jacquard", "handjet")),
    ("★ Pirata / Faroeste (estilo One Piece)", ("pirata", "jolly", "new rocker", "sancreek", "rye", "ribeye", "almendra", "creepster",
                                                "eater", "ewert", "holtwood", "metamorphous", "uncial", "vast shadow", "wellfleet")),
    ("★ Símbolos e emojis (flores, corações)", ("emoji", "symbols")),
]


def listar_fontes_agrupadas():
    """[(título do grupo, [nomes])]: Importadas (suas) · grupos Especiais por tema · Padrão (Windows)."""
    todas = listar_fontes()
    pasta = lambda path: os.path.dirname(os.path.abspath(path))
    importadas = {n for n, path in todas.items() if pasta(path) == os.path.abspath(FONTES_IMPORTADAS)}
    locais = {n for n, path in todas.items() if pasta(path) == os.path.abspath(FONTES_LOCAIS)}
    usados, grupos = set(), []
    if importadas:
        grupos.append(("★ Importadas (suas)", sorted(importadas)))
    for titulo, chaves in GRUPOS_ESPECIAIS:
        nomes = sorted(n for n in locais if any(k in INFO_FONTE[n][0].lower() for k in chaves) and n not in usados)
        usados.update(nomes)
        if nomes:
            grupos.append((titulo, nomes))
    resto = sorted(n for n in locais if n not in usados)
    if resto:
        grupos.append(("★ Outras especiais", resto))
    incluidas = {n for n, path in todas.items() if pasta(path) == os.path.abspath(FONTES_PADRAO)}
    if incluidas:
        grupos.append(("Padrão (incluídas no app)", sorted(incluidas)))
    resto_win = [n for n in todas if n not in locais and n not in importadas and n not in incluidas]
    if resto_win:
        grupos.append(("Padrão (Windows)", resto_win))
    return grupos


def fonte_e_especial(nome):
    p = listar_fontes().get(nome)
    return bool(p) and os.path.dirname(os.path.abspath(p)) in (os.path.abspath(FONTES_LOCAIS), os.path.abspath(FONTES_IMPORTADAS), os.path.abspath(FONTES_PADRAO))


_SPLIT_TOKEN = re.compile(r"(:[A-Za-z0-9_\-]+:)")


def letras_do_texto(texto):
    """Letras distintas (sem os símbolos :nome: e sem espaços) presentes no texto, em maiúsculas e na ordem em que aparecem."""
    vistos = []
    for i, parte in enumerate(_SPLIT_TOKEN.split(texto)):
        if i % 2 == 0:
            for c in parte:
                if c.isalnum() and c.upper() not in vistos:
                    vistos.append(c.upper())
    return vistos


def trocar_letra(texto, letra, token, qual="todas"):
    """Troca a letra (sem diferenciar maiúscula/minúscula) por um símbolo/imagem (token ':nome:').
    qual = 'todas' | 'primeira' | 'ultima'. Não mexe nos símbolos já existentes. Ex.: trocar_letra('LOVE','O',':coracao:') -> 'L:coracao:VE'."""
    partes = _SPLIT_TOKEN.split(texto)
    posicoes = [(i, j) for i, parte in enumerate(partes) if i % 2 == 0 for j, c in enumerate(parte) if c.upper() == letra.upper()]
    if qual == "primeira":
        posicoes = posicoes[:1]
    elif qual == "ultima":
        posicoes = posicoes[-1:]
    for i, j in sorted(posicoes, reverse=True):
        partes[i] = partes[i][:j] + token + partes[i][j + 1:]
    return "".join(partes)


def dados_visualizador(pecas, alvo_tris=9000, prato=None):
    """Dados compactos para o visualizador 3D (three.js). pecas = [(nome, vertices, faces, (x, y))] com vértices em mm com origem
    no canto mínimo da peça; (x, y) = posição no prato. Retorna dict serializável em JSON."""
    import base64
    objs = []
    for nome, v, f, (x, y) in pecas:
        v = np.asarray(v, np.float32)
        f = np.asarray(f, np.int32)
        if len(f) > alvo_tris:
            import fast_simplification
            v, f = fast_simplification.simplify(v, f, target_reduction=min(0.98, 1 - alvo_tris / len(f)))
            v = np.asarray(v, np.float32)
            f = np.asarray(f, np.int32)
        tri = v[f].reshape(-1, 3).astype(np.float32)
        objs.append({"nome": nome, "x": float(x), "y": float(y), "n": int(len(f)),
                     "pos": base64.b64encode(tri.tobytes()).decode("ascii")})
    return {"objs": objs, "prato": prato}


def malha_rapida(texto, p, voxel=0.2, alvo=15000):
    """Malha grosseira e rápida (segundos) só para a prévia 3D. Retorna (vértices mm com origem no canto mínimo, faces)."""
    q = replace(p, voxel=max(p.voxel, voxel))
    m, yc = mascara(texto, q)
    occ = ocupacao(m, yc, q)
    v, f = malha_skimage(occ, q.voxel, alvo)
    return v - v.min(0), f


def partes_rapidas(texto, p, voxel=0.2, alvo=15000):
    """Malha rápida para a prévia 3D, separada por cor quando o modo é 'cores'.
    Retorna [(vertices, faces, indice_da_cor)] no mesmo referencial (origem no canto mínimo da peça inteira)."""
    q = replace(p, voxel=max(p.voxel, voxel))
    if q.produto == "marcador":
        q2 = replace(q, voxel=max(q.voxel, 0.2))
        pm, rc = marcador_occ(texto, q2)
        vu, _ = malha_skimage(np.logical_or.reduce(pm), rc, alvo)
        mn = vu.min(0)
        out = []
        for i, oc in enumerate(pm):
            if oc.any():
                v2, f2 = malha_skimage(oc, rc, alvo if i == 0 else alvo // 3)
                out.append((v2 - mn, f2, i))
        return out
    if q.produto in ("corrente", "tag"):
        base, letras, rc = corrente_occ(texto, q, res=0.15) if q.produto == "corrente" else tag_occ(texto, q)
        vu, _ = malha_skimage(base | letras, rc, alvo)
        mn = vu.min(0)
        out = []
        for i, oc in enumerate((base, letras)):
            if oc.any():
                v2, f2 = malha_skimage(oc, rc, alvo if i == 0 else alvo // 2)
                out.append((v2 - mn, f2, i))
        return out
    if q.modo != "cores":
        v, f = malha_rapida(texto, q, voxel, alvo)
        return [(v, f, 0)]
    m, yc, rot = mascara_rotulada(texto, q)
    occ, rotf = ocupacao(m, yc, q, rot)
    vu, fu = malha_skimage(occ, q.voxel, alvo)
    mn = vu.min(0)
    par = (rotf % 2) == 0
    out = []
    for i, sel in enumerate((par, ~par)):
        oc = occ & sel[:, None, None]
        if oc.any():
            v2, f2 = malha_skimage(oc, q.voxel, alvo // 2)
            out.append((v2 - mn, f2, i))
    return out


def aplicar_caixa(texto, p):
    """Aplica a caixa das letras ao texto sem mexer nos símbolos ':nome:'. caixa: maiusculas | minusculas | digitado | capitalizar."""
    c = p.caixa
    if c == "auto":
        c = "maiusculas" if p.maiusculas else "digitado"
    if c == "digitado":
        return texto
    partes = _SPLIT_TOKEN.split(texto)
    for i in range(0, len(partes), 2):                    # índices pares = texto comum; ímpares = símbolos
        t = partes[i]
        if c == "maiusculas":
            t = t.upper()
        elif c == "minusculas":
            t = t.lower()
        elif c == "capitalizar":
            t = " ".join(w[:1].upper() + w[1:].lower() for w in t.split(" "))
        partes[i] = t
    return "".join(partes)


def ler_lista_nomes(conteudo, nome_arquivo, so_primeiro_nome=False):
    """Lê uma lista de nomes de .csv/.txt (NOME;QTD;FONTE;FURO por linha, '#' comenta) ou .xlsx (colunas na mesma ordem).
    Retorna [(nome, qtd, fonte_ou_None, furo_ou_None)]. so_primeiro_nome=True apaga o segundo nome de nomes compostos."""
    linhas = []
    if nome_arquivo.lower().endswith((".xlsx", ".xls")):
        import io
        import pandas as pd
        df = pd.read_excel(io.BytesIO(conteudo), header=None, dtype=str).fillna("")
        for _, r in df.iterrows():
            linhas.append([str(c).strip() for c in r.tolist()])
        if linhas and linhas[0] and linhas[0][0].strip().lower() in ("nome", "nomes", "name"):
            linhas = linhas[1:]                              # cabeçalho
    else:
        txt = conteudo.decode("utf-8-sig", errors="replace") if isinstance(conteudo, bytes) else conteudo
        for ln in txt.splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            sep = ";" if ";" in ln else ("	" if "	" in ln else ("," if "," in ln and ln.rsplit(",", 1)[1].strip().isdigit() else None))
            linhas.append([c.strip() for c in ln.split(sep)] if sep else [ln])
    out = []
    for c in linhas:
        if not c or not c[0].strip():
            continue
        nome = c[0].strip()
        if so_primeiro_nome and " " in nome and ":" not in nome:
            nome = nome.split()[0]
        qtd = int(float(c[1])) if len(c) > 1 and c[1].replace(".", "", 1).isdigit() else 1
        out.append((nome, max(1, qtd), c[2] if len(c) > 2 and c[2] else None, c[3] if len(c) > 3 and c[3] else None))
    return out


# ----------------------------------------------------------------------------- material do filamento
# Valores de partida (faixas usuais dos fabricantes) aplicados sobre o perfil P1S do seu projeto (PLA Bambu = base).
# chaves por material: temperatura do bico (normal/1ª camada), mesa (placa texturizada/1ª camada), ventoinha, vazão máxima (mm³/s), velocidades.
MATERIAIS = {
    "PLA": dict(tipo="PLA", nome="Bambu PLA Basic @BBL P1S 0.4 nozzle", fab="Bambu Lab", bico=220, bico1=220, mesa=55, mesa1=55, fan_min=100, fan_max=100, fan_off=1,
                vazao=21, dens=1.26, faixa=(190, 240), camada_lenta=4, nota="Perfil Bambu PLA Basic do seu projeto."),
    "PLA+": dict(tipo="PLA", nome="Generic PLA+ @BBL P1S 0.4 nozzle", fab="Generic", bico=225, bico1=225, mesa=55, mesa1=55, fan_min=100, fan_max=100, fan_off=1,
                 vazao=18, dens=1.24, faixa=(190, 245), camada_lenta=4, nota="PLA+ costuma pedir 5 °C a mais e fluxo um pouco menor."),
    "PETG": dict(tipo="PETG", nome="Generic PETG @BBL P1S 0.4 nozzle", fab="Generic", bico=250, bico1=255, mesa=70, mesa1=70, fan_min=30, fan_max=60, fan_off=3,
                 vazao=10, dens=1.27, faixa=(220, 270), camada_lenta=8, vel=(120, 180, 180), nota="PETG: ventoinha baixa, fluxo menor e mais lento; use cola na PEI."),
    "ABS": dict(tipo="ABS", nome="Generic ABS @BBL P1S 0.4 nozzle", fab="Generic", bico=270, bico1=270, mesa=90, mesa1=90, fan_min=10, fan_max=30, fan_off=3,
                vazao=16, dens=1.04, faixa=(240, 280), camada_lenta=6, nota="ABS: imprima com a tampa da P1S fechada; cola na PEI; cheira e empena."),
    "ASA": dict(tipo="ASA", nome="Generic ASA @BBL P1S 0.4 nozzle", fab="Generic", bico=265, bico1=265, mesa=90, mesa1=90, fan_min=10, fan_max=30, fan_off=3,
                vazao=16, dens=1.07, faixa=(240, 280), camada_lenta=6, nota="ASA: como o ABS, com tampa fechada."),
    "TPU": dict(tipo="TPU", nome="Generic TPU @BBL P1S 0.4 nozzle", fab="Generic", bico=230, bico1=230, mesa=45, mesa1=45, fan_min=60, fan_max=100, fan_off=1,
                vazao=3.6, dens=1.22, faixa=(200, 250), camada_lenta=10, vel=(40, 50, 50), nota="TPU: bem lento; não passe pelo AMS (use o carretel externo)."),
}


def expandir_filamentos(cfg, n):
    """Amplia o project_settings (1 filamento) para n filamentos, do mesmo jeito que o Bambu Studio salva um projeto com n cores."""
    import json
    if n <= 1:
        return cfg
    g = json.load(open(os.path.join(HERE, "base_bambu", "expansao_filamentos.json"), encoding="utf-8"))
    for chave in g.get("x1", []):
        if chave in cfg and len(cfg[chave]) == 1:
            cfg[chave] = list(cfg[chave]) * n
    for chave in g.get("x2", []):
        if chave in cfg and len(cfg[chave]) == 2:
            cfg[chave] = list(cfg[chave]) * n
    for chave in g.get("x4", []):
        if chave in cfg and len(cfg[chave]) == 4:
            cfg[chave] = list(cfg[chave]) * n
    for chave in g.get("n2", []):
        if chave in cfg and len(cfg[chave]) == 1:
            cfg[chave] = list(cfg[chave]) * (2 * n)
    for chave in g.get("q", []):
        cfg[chave] = ["0" if i // n == i % n else "200" for i in range(n * n)]
    if "vec" in g and g["vec"] in cfg:
        cfg[g["vec"]] = ["140"] * (2 * n)
    return cfg


COR_PADRAO = ["#FF9500", "#FFFFFF", "#FFD21F", "#2F6FE4", "#B58AE0", "#000000"]


def config_material(material="PLA", cores=None, n=None):
    """Devolve o project_settings.config (JSON) com a temperatura/ventoinha/vazão do material escolhido."""
    import json
    nfil = max(len(cores or []), n or 1)
    if material == "PLA" and not cores and nfil <= 1:
        return open(BASE_CFG, "rb").read()        # o perfil do seu projeto já é PLA: não mexe em nada
    cfg = json.load(open(BASE_CFG, encoding="utf-8"))
    cfg = expandir_filamentos(cfg, nfil)
    if nfil > 1 and not cores:
        cores = COR_PADRAO[:nfil]
    if cores:                                      # cores dos filamentos 1..N (aparecem no Bambu Studio)
        cc = [c.upper() + "FF" if len(c) == 7 else c.upper() for c in cores]
        for chave in ("filament_colour", "filament_multi_colour"):
            if chave in cfg:
                cfg[chave] = cc
        if "filament_colour_type" in cfg:
            cfg["filament_colour_type"] = ["0"] * len(cc)
    if material == "PLA":
        return json.dumps(cfg, ensure_ascii=False, indent=4).encode("utf-8")
    m = MATERIAIS.get(material) or MATERIAIS["PLA"]

    def pôr(chave, valor):
        if chave in cfg:
            cfg[chave] = [str(valor)] * len(cfg[chave]) if isinstance(cfg[chave], list) else str(valor)

    pôr("filament_type", m["tipo"])
    pôr("filament_settings_id", m["nome"])
    pôr("default_filament_profile", m["nome"])
    pôr("filament_vendor", m["fab"])
    pôr("nozzle_temperature", m["bico"])
    pôr("nozzle_temperature_initial_layer", m["bico1"])
    pôr("nozzle_temperature_range_low", m["faixa"][0])
    pôr("nozzle_temperature_range_high", m["faixa"][1])
    for chave in ("textured_plate_temp", "hot_plate_temp", "supertack_plate_temp"):
        pôr(chave, m["mesa"])
        pôr(chave + "_initial_layer", m["mesa1"])
    pôr("cool_plate_temp", 35 if m["tipo"] in ("PLA", "TPU") else 0)
    pôr("cool_plate_temp_initial_layer", 35 if m["tipo"] in ("PLA", "TPU") else 0)
    pôr("fan_min_speed", m["fan_min"])
    pôr("fan_max_speed", m["fan_max"])
    pôr("overhang_fan_speed", m["fan_max"])
    pôr("close_fan_the_first_x_layers", m["fan_off"])
    pôr("slow_down_layer_time", m["camada_lenta"])
    pôr("filament_density", m["dens"])
    if m["tipo"] != "PLA":
        pôr("filament_max_volumetric_speed", m["vazao"])
        pôr("additional_cooling_fan_speed", 0 if m["tipo"] in ("ABS", "ASA") else 40)
    else:
        pôr("filament_max_volumetric_speed", m["vazao"])
    if "vel" in m:
        ext, inte, enc = m["vel"]
        pôr("outer_wall_speed", ext)
        pôr("inner_wall_speed", inte)
        pôr("sparse_infill_speed", enc)
        pôr("initial_layer_speed", 25)
    return json.dumps(cfg, ensure_ascii=False, indent=4).encode("utf-8")


# chaveiro: valores de partida (nome grande e fino, argola colada na primeira letra)
CHAVEIRO = dict(altura=24.0, espessura=4.0, raio=1.2, engrossar=0.9, espaco=-1.2, largura=1.0, inclinacao=4.0, ondula=0.6)


# ----------------------------------------------------------------------------- corrente articulada (um elo por letra, imprime montada)
# Mesma ideia mecânica das correntes "llavero": cada elo tem, à esquerda, uma cavidade com um pino (eixo na largura) e, à direita,
# uma argola que abraça o pino do elo seguinte. Folga radial de 0,5 mm entre pino e argola. Geometria própria (calculada aqui).
CORRENTE = dict(altura=10.0, relevo=1.0, elo_largo=15.0, elo_ancho=12.0, elo_alto=6.0, elo_espaco=1.0)

_PINO_D, _ANEL_EXT, _ANEL_INT, _ANEL_ALT, _CAVIDADE_D, _CAVIDADE_P, _SEPARACAO, _SUPORTE_L, _SUPORTE_A, _CHAFLAN = 2.0, 6.0, 3.0, 4.0, 10.0, 5.5, 2.0, 2.0, 1.0, 1.0


def _glifo_corrente(el, p, res):
    """Máscara 2D (linhas de cima p/ baixo) da letra/símbolo/imagem `el` = (tipo, valor), já recortada no seu retângulo; letra de `p.altura` mm."""
    tipo, val = el
    cap_px = p.altura / res
    if tipo == "img":
        return _mascara_imagem(val, int(round(cap_px * 1.1)))
    ch = val
    if ch.isspace():
        return None
    f0 = ImageFont.truetype(p.fonte, 200)
    bb = f0.getbbox("H")
    size = max(8, int(round(200 * cap_px / (bb[3] - bb[1]))))
    f = ImageFont.truetype(p.fonte, size)
    if not _tem_glifo(f, ch):
        for r in (_fonte_reserva(c, 200) for c in _fontes_reserva()):
            if _tem_glifo(r, ch):
                l, t, rr, bt = r.getbbox(ch)
                f = _fonte_reserva(r.path, max(8, int(round(200 * cap_px * 1.05 / max(1, bt - t)))))
                break
    l, t, rr, bt = f.getbbox(ch)
    img = Image.new("L", (rr - l + 8, bt - t + 8), 0)
    ImageDraw.Draw(img).text((4 - l, 4 - t), ch, font=f, fill=255)
    m = np.asarray(img) > 127
    ys, xs = np.where(m)
    if len(ys) == 0:
        return None
    return m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def corrente_occ(nome, p, res=None):
    """Volumes (base, letras) da corrente: bool (x, y, z). Origem em 0 no primeiro elo."""
    res = res or min(p.voxel, 0.1)
    elementos = [e for e in _elementos(nome, listar_imagens())]
    n = len(elementos)
    L, W, H = p.elo_largo, p.elo_ancho, p.elo_alto
    if p.elo_forma == "hexagono":
        W = max(W, L * 2 / np.sqrt(3))                    # hexágono com lados planos virados para os vizinhos: largura = vértice a vértice
    larg = [L - 2 if (i == 0 and not p.elo_primeiro) else L for i in range(n)]
    pos = [0.0]
    for i in range(1, n):
        pos.append(pos[-1] + larg[i - 1] + p.elo_espaco)
    folga = _SEPARACAO + _ANEL_EXT / 2 + 1.0
    total = pos[-1] + larg[-1] + (folga if p.elo_ultimo else 0.5)
    xo = 1.0                                              # margem à esquerda
    NX, NY, NZ = int((total + xo + 1) / res), int(W / res) + 2, int((H + abs(p.relevo) + 1) / res) + 2
    X = ((np.arange(NX) + 0.5) * res - xo)[:, None, None]
    Y = ((np.arange(NY) + 0.5) * res - res)[None, :, None]
    Z = ((np.arange(NZ) + 0.5) * res)[None, None, :]
    base = np.zeros((NX, NY, NZ), bool)
    letras = np.zeros((NX, NY, NZ), bool)
    yc, zc = W / 2, H / 2
    for i, el in enumerate(elementos):
        ix0 = max(0, int((pos[i] - 2.0 + xo) / res))
        ix1 = min(NX, int((pos[i] + larg[i] + _SEPARACAO + _ANEL_EXT / 2 + 1.0 + xo) / res) + 2)
        x = X[ix0:ix1] - pos[i]
        la = larg[i]
        tem_cav = i > 0 or p.elo_primeiro
        tem_anel = i < n - 1 or p.elo_ultimo
        lim_pino = True
        if p.elo_forma == "hexagono":
            xr, yr = np.abs(x[:, :, 0] - la / 2), np.abs(Y[0, :, 0][None, :] - yc)           # (nx, ny)
            m2 = np.maximum(xr, 0.5 * xr + (np.sqrt(3) / 2) * yr) <= la / 2
            rc = max(0.2, min(p.elo_canto, la / 3, 1.5))                                       # cantos pequenos: a parede ao lado do pino precisa de material
            nuc = ndi.distance_transform_edt(m2) * res > rc                                    # abertura: arredonda os cantos do hexágono
            m2 = ndi.distance_transform_edt(~nuc) * res <= rc
            d2 = ndi.distance_transform_edt(m2) * res
            rv = max(0.2, min(p.elo_borda, H / 2 - 0.1))
            g = _perfil(Z[0, 0, :], H, rv, p)
            corpo = (d2[:, :, None] >= np.maximum(g, res * 0.5)[None, None, :]) & m2[:, :, None] & (Z <= H)
            lim_pino = m2[:, :, None]                                                       # o pino só existe onde há parede (não sai do hexágono)
        elif p.elo_forma == "quadrado":
            rv = max(0.2, min(p.elo_borda, H / 2 - 0.1))
            rc = max(rv, min(p.elo_canto, W / 2 - 0.1, la / 2 - 0.1))
            qx, qy, qz = np.abs(x - la / 2) - (la / 2 - rv), np.abs(Y - yc) - (W / 2 - rv), np.abs(Z - zc) - (H / 2 - rv)
            d3 = np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2 + np.maximum(qz, 0) ** 2) + np.minimum(np.maximum(np.maximum(qx, qy), qz), 0) - rv
            qx2, qy2 = np.abs(x - la / 2) - (la / 2 - rc), np.abs(Y - yc) - (W / 2 - rc)
            d2c = np.sqrt(np.maximum(qx2, 0) ** 2 + np.maximum(qy2, 0) ** 2) + np.minimum(np.maximum(qx2, qy2), 0) - rc
            corpo = (d3 <= 0) & (d2c <= 0)
        else:
            corpo = (x >= 0) & (x < la) & (Y >= 0) & (Y <= W) & (Z >= 0) & (Z <= H)
            corpo &= ~((x + Z) < _CHAFLAN) & ~((x + (H - Z)) < _CHAFLAN)         # chanfro da borda esquerda
        if tem_cav:
            cav = ((x ** 2 + (Z - zc) ** 2) <= (_CAVIDADE_D / 2) ** 2) & (np.abs(Y - yc) <= _CAVIDADE_P / 2)
            corpo &= ~cav
            corpo |= ((x - _PINO_D / 2) ** 2 + (Z - zc) ** 2 <= (_PINO_D / 2) ** 2) & (Y >= 0) & (Y <= W) & (x > -1) & lim_pino
        if tem_anel:
            cx = la + _SEPARACAO
            d2 = (x - cx) ** 2 + (Z - zc) ** 2
            anel = (d2 <= (_ANEL_EXT / 2) ** 2) & (d2 >= (_ANEL_INT / 2) ** 2) & (np.abs(Y - yc) <= _ANEL_ALT / 2)
            sup = (x >= la - 0.5) & (x <= la + _SUPORTE_L) & (np.abs(Y - yc) <= _ANEL_ALT / 2) &                   (((Z >= zc + _ANEL_EXT / 2 - _SUPORTE_A) & (Z <= zc + _ANEL_EXT / 2)) | ((Z <= zc - _ANEL_EXT / 2 + _SUPORTE_A) & (Z >= zc - _ANEL_EXT / 2)))
            corpo |= anel | sup
        base[ix0:ix1] |= corpo
        g = _glifo_corrente(el, p, res)
        if g is not None and abs(p.relevo) > 0:
            gh, gw = g.shape
            cxl = pos[i] + ((la / 2 + 0.6) if (i == 0 and not p.elo_primeiro) else (L / 2 + 2))   # centro livre do elo
            ix0 = int(round((cxl - gw * res / 2 + xo) / res))
            iy0 = int(round((yc - gh * res / 2 + res) / res))
            gm = np.flipud(g).T                                                  # (x, y) com y para cima
            iz0 = int(round(H / res))
            nz = int(round(abs(p.relevo) / res))
            sub = np.zeros((NX, NY), bool)
            xs0, xs1 = max(ix0, 0), min(ix0 + gm.shape[0], NX)
            ys0, ys1 = max(iy0, 0), min(iy0 + gm.shape[1], NY)
            if xs1 > xs0 and ys1 > ys0:
                sub[xs0:xs1, ys0:ys1] = gm[xs0 - ix0:xs1 - ix0, ys0 - iy0:ys1 - iy0]
            if p.relevo > 0:
                letras[:, :, iz0:iz0 + nz] |= sub[:, :, None]
            else:
                letras[:, :, iz0 - nz:iz0] |= sub[:, :, None]
    if p.relevo < 0:
        base &= ~letras
    return base, letras, res


# ----------------------------------------------------------------------------- chaveiro com base de contorno
# Base fina que segue o contorno do nome (a "borda" em volta das letras, com argola) + letras em relevo por cima, em outra cor.
TAG = dict(altura=16.0, engrossar=0.6, espaco=-0.8, largura=1.0, raio=1.0, borda=2.0, base_alt=2.0, relevo=1.6, inclinacao=3.0, ondula=0.4)


def tag_occ(nome, p):
    """Volumes (base, letras) do chaveiro com base de contorno: bool (x, y, z), mesmo referencial."""
    res = p.voxel
    q = replace(p, produto="ponteira", ligar_letras=False)
    m, yc = mascara(nome, q)                              # letras (sem argola e sem pontes entre palavras)
    pad = int((p.borda + 2.0) / res) + 4
    m = np.pad(m, pad)
    yc = yc + pad * res
    base = ndi.distance_transform_edt(~m) <= p.borda / res
    base = ndi.binary_fill_holes(base)                    # miolos de O, A, B... ficam cobertos pela base
    base = ndi.gaussian_filter(base.astype(float), 0.8 / res * 0.5) > 0.5
    base = _ligar(base, replace(q, ponte=max(q.ponte, 2 * p.borda)))
    cy = m.shape[0] - yc / res                            # linha do meio das maiúsculas
    base, off = _argola(base, p, cy)
    base = _ligar(base, replace(q, ponte=max(q.ponte, 0.5 * p.argola_ext)))
    dx = base.shape[1] - m.shape[1]
    m = np.pad(m, ((0, 0), (dx, 0) if p.argola_lado != "direita" else (0, dx)))
    zb = (np.arange(max(2, int(round(p.base_alt / res)))) + 0.5) * res
    rl = abs(p.relevo)
    zl = (np.arange(max(2, int(round(rl / res)))) + 0.5) * res
    db = ndi.distance_transform_edt(base) * res
    gb = _perfil(zb, p.base_alt, min(p.raio, p.base_alt * 0.45), p)
    ob = (db[:, :, None] >= np.maximum(gb, res * 0.5)[None, None, :]) & base[:, :, None]
    dl = ndi.distance_transform_edt(m) * res
    gl = _perfil(zl, rl, min(p.raio, rl * 0.6), p)
    ol = (dl[:, :, None] >= np.maximum(gl, res * 0.5)[None, None, :]) & m[:, :, None]
    nz = ob.shape[2] + ol.shape[2]
    A = np.zeros(ob.shape[:2] + (nz,), bool)
    B = np.zeros_like(A)
    A[:, :, :ob.shape[2]] = ob
    B[:, :, ob.shape[2]:] = ol
    fx = lambda v: np.flip(v, 0).transpose(1, 0, 2)
    return fx(A), fx(B), res


# ----------------------------------------------------------------------------- marcador de páginas (clip) com nome e emoji de professor
# Placa fina (1,4 mm) com a haste do clip (moldura em U + lingueta, como um clip de folha) e, no topo, o nome e o emoji em relevo,
# em até 4 filamentos: 1 base · 2 letras e boca (branco) · 3 rosto · 4 capelo e óculos.
MARCADOR = dict(altura=13.0, engrossar=0.6, espaco=-0.8, largura=1.0, raio=0.6, borda=2.4, base_alt=2.2, relevo=1.2, inclinacao=3.0, ondula=0.4)
PALETAS_MARCADOR_2 = {                                 # 2 filamentos: base, nome + emoji (mesmas cores dos chaveiros de 2 cores)
    "Menina": ["#B58AE0", "#FFD21F"],                    # base lilás, nome/emblema amarelo
    "Menino": ["#FFD21F", "#2F6FE4"],                    # base amarela, nome/emblema azul
}
PALETAS_MARCADOR = {                                   # filamentos 1..4: base, letras/boca, rosto, capelo/óculos
    "Menina": ["#B58AE0", "#FFFFFF", "#FFD21F", "#2F6FE4"],   # base lilás, capelo e óculos azuis
    "Menino": ["#2F6FE4", "#FFFFFF", "#FFD21F", "#B58AE0"],   # base azul, capelo e óculos lilás
}


def _emoji_professor(D, res):
    """Máscaras 2D (bool) do emoji de professor: rosto, capelo (sem pingente), óculos e boca, em um quadrado de 1,3·D. Retorna dict."""
    S = int(1.3 * D / res)
    c = S / 2
    d = D / res

    def novo():
        im = Image.new("L", (S, S), 0)
        return im, ImageDraw.Draw(im)

    face, f = novo()
    f.ellipse((c - d / 2, c - d / 2, c + d / 2, c + d / 2), fill=255)
    cap, k = novo()
    k.polygon([(c - 0.62 * d, c - 0.40 * d), (c, c - 0.58 * d), (c + 0.62 * d, c - 0.40 * d), (c, c - 0.22 * d)], fill=255)   # tábua do capelo
    k.rounded_rectangle((c - 0.34 * d, c - 0.36 * d, c + 0.34 * d, c - 0.21 * d), radius=0.07 * d, fill=255)                  # calota
    gl, g = novo()
    g.rounded_rectangle((c - 0.40 * d, c - 0.10 * d, c - 0.04 * d, c + 0.10 * d), radius=0.06 * d, fill=255)
    g.rounded_rectangle((c + 0.04 * d, c - 0.10 * d, c + 0.40 * d, c + 0.10 * d), radius=0.06 * d, fill=255)
    g.rectangle((c - 0.06 * d, c - 0.06 * d, c + 0.06 * d, c - 0.01 * d), fill=255)                                             # ponte
    mo, o = novo()
    o.pieslice((c - 0.28 * d, c + 0.17 * d, c + 0.28 * d, c + 0.47 * d), 0, 180, fill=255)                                      # sorriso aberto
    b = lambda im: np.asarray(im) > 127
    cap, gl, mo, face = b(cap), b(gl), b(mo), b(face)
    gl &= ~cap
    mo &= ~cap & ~gl
    solo = face & ~cap & ~gl & ~mo
    return dict(cap=cap, gl=gl, mo=mo, rosto=solo, todo=face | cap)


def _livro(D, res):
    """Máscaras 2D do livrinho aberto: capa (com as linhas de texto) e páginas, em uma tela de 1,25·D por 0,95·D."""
    Sw, Sh = int(1.25 * D / res), int(0.95 * D / res)
    def novo():
        im = Image.new("L", (Sw, Sh), 0)
        return im, ImageDraw.Draw(im)
    capa, c1 = novo()
    c1.rounded_rectangle((0, 0.05 * Sh, Sw - 1, Sh - 1), radius=0.10 * Sh, fill=255)
    pag, g = novo()
    g.rounded_rectangle((0.07 * Sw, 0.17 * Sh, 0.485 * Sw, 0.86 * Sh), radius=0.06 * Sh, fill=255)
    g.rounded_rectangle((0.515 * Sw, 0.17 * Sh, 0.93 * Sw, 0.86 * Sh), radius=0.06 * Sh, fill=255)
    lin, ln = novo()
    for y in (0.36, 0.52, 0.68):                                             # linhas de texto nas duas páginas
        ln.rectangle((0.13 * Sw, y * Sh, 0.42 * Sw, (y + 0.065) * Sh), fill=255)
        ln.rectangle((0.58 * Sw, y * Sh, 0.87 * Sw, (y + 0.065) * Sh), fill=255)
    b = lambda im: np.asarray(im) > 127
    capa, pag, lin = b(capa), b(pag), b(lin)
    pag &= ~lin
    capa &= ~pag
    return dict(capa=capa, pag=pag)


def _estadio(img, cx, y0, y1, w):
    """Desenha (em img PIL 'L') uma haste: retângulo de y0 até uma ponta semicircular que termina em y1."""
    r = w / 2
    d = ImageDraw.Draw(img)
    d.rectangle((cx - r, y0, cx + r, y1 - r), fill=255)
    d.ellipse((cx - r, y1 - 2 * r, cx + r, y1), fill=255)


def _emblema_cepi(D, res):
    """Releitura do emblema do C.E.P.I. Parque dos Buritis, com formas e texto limpos: (relevo, disco, yc_mm).
    Disco = base (cor 1). Relevo (cor 2): dois aros, nome da escola e lema escritos no anel entre eles, e no centro o escudo de cantos
    inferiores arredondados com 'C.E.P.I.', estrelas vazadas na metade esquerda e estrela grande + 1968 na metade direita."""
    N = int(round(D / res))
    k = N / D                                               # pixels por mm
    c = N / 2
    R = D / 2
    P = lambda x, y: (c + x * k, c + y * k)
    S = lambda L: [P(x, y) for x, y in L]
    fonte = listar_fontes()
    fpath = fonte.get("Archivo Black") or fonte.get("Arial Rounded MT Bold") or next(iter(fonte.values()))
    F = lambda mm: ImageFont.truetype(fpath, max(8, int(round(mm * k))))

    def tela():
        im = Image.new("L", (N, N), 0)
        return im, ImageDraw.Draw(im)

    disco_im, dd = tela()
    dd.ellipse((0, 0, N - 1, N - 1), fill=255)
    rel, dr = tela()
    ocos, do = tela()                                       # o que é vazado (mostra a base)

    def anel(r_ext, r_int):
        dr.ellipse((c - r_ext * k, c - r_ext * k, c + r_ext * k, c + r_ext * k), fill=255)
        dr.ellipse((c - r_int * k, c - r_int * k, c + r_int * k, c + r_int * k), fill=0)

    pequeno = D < 45                                        # emblema pequeno: anel mais estreito e só "PARQUE DOS BURITIS" (o lema não cabe legível)
    r_borda_ext, r_borda_int = (R - 0.9, R - 2.0) if pequeno else (R - 1.0, R - 2.3)             # aro de fora
    r_miolo = (R - 6.8) if pequeno else (R - 8.6)           # aro de dentro (o anel de texto fica entre os dois)
    anel(r_borda_ext, r_borda_int)
    anel(r_miolo + 1.2, r_miolo)
    r_txt = (r_borda_int + r_miolo + 1.2) / 2               # linha de centro do texto do anel
    h_txt = (r_borda_int - r_miolo - 1.2) * (0.80 if pequeno else 0.72)            # tamanho da letra dentro do anel
    _txt_topo, _txt_baixo = "PARQUE DOS BURITIS", ("" if pequeno else "EDUCAÇÃO · AMOR · CIDADANIA")
    _f4 = ImageFont.truetype(fpath, max(8, int(round(4.0 * k))))
    _larg4 = lambda t: (sum(_f4.getlength(ch) / k for ch in t) + 0.16 * 4.0 * (len(t) - 1)) if t else 0.0       # comprimento do texto com letra de 4 mm
    h_max = np.radians(200 if pequeno else 318) * r_txt / ((_larg4(_txt_topo) + _larg4(_txt_baixo)) / 4.0)           # os dois arcos somam no máximo ~318 graus
    h_txt = min(h_txt, h_max)

    def sobre_arco(texto, topo, h_mm):
        """Escreve o texto em arco no anel: topo=True (letras para fora, lendo da esquerda p/ direita) ou embaixo (letras de pé)."""
        f = F(h_mm)
        esp = 0.16 * h_mm
        larg = [f.getlength(ch) / k for ch in texto]
        total = sum(larg) + esp * (len(texto) - 1)
        ang0 = -total / r_txt / 2
        a = ang0
        for ch, w in zip(texto, larg):
            ac = a + w / r_txt / 2                          # ângulo do centro da letra (rad, 0 = topo ou fundo)
            a += (w + esp) / r_txt
            if ch == " ":
                continue
            tmp = Image.new("L", (int(h_mm * k * 3), int(h_mm * k * 3)), 0)
            ImageDraw.Draw(tmp).text((tmp.width / 2, tmp.height / 2), ch, font=f, fill=255, anchor="mm")
            graus = np.degrees(ac)
            tmp = tmp.rotate(-graus if topo else graus, resample=Image.BICUBIC)
            x = r_txt * np.sin(ac)
            y = (-r_txt * np.cos(ac)) if topo else (r_txt * np.cos(ac))
            cx, cy = P(x, y)
            dr.bitmap((cx - tmp.width / 2, cy - tmp.height / 2), tmp, fill=255)

    sobre_arco(_txt_topo, True, h_txt)
    if _txt_baixo:
        sobre_arco(_txt_baixo, False, h_txt)

    esc = 1.08 * min(1.0, r_miolo / 21.4)
    dy0 = 1.8 * esc                                      # escudo um pouco maior e mais baixo, para ocupar melhor o círculo de dentro
    Q = lambda x, y: P(x * esc, y * esc + dy0)
    T = lambda L: [Q(x, y) for x, y in L]
    # escudo: lados retos e cantos inferiores arredondados, terminando numa ponta suave
    W2, y_top, y_base = 12.4, -8.6, 1.4
    def bezier(p0, p1, p2, p3, n=40):
        t = np.linspace(0, 1, n)[:, None]
        return ((1 - t) ** 3 * np.array(p0) + 3 * (1 - t) ** 2 * t * np.array(p1) + 3 * (1 - t) * t ** 2 * np.array(p2) + t ** 3 * np.array(p3)).tolist()
    dir_ = bezier((W2, y_base), (W2, y_base + 7.2), (4.6, y_base + 10.4), (0, y_base + 12.4))
    esq_ = [(-x, y) for x, y in dir_][::-1]
    escudo = [(-W2, y_top), (W2, y_top)] + dir_ + esq_
    # faixa do nome da escola
    dr.rectangle((*Q(-W2, -16.2), *Q(W2, -9.4)), fill=255)
    do.text(Q(0, -12.8), "C.E.P.I.", font=F((5.2 if pequeno else 4.9) * esc), fill=255, anchor="mm")
    # metade esquerda cheia com estrelas vazadas
    esq_im, de = tela()
    de.polygon(T(escudo), fill=255)
    de.rectangle((*Q(-0.25, -30), *Q(40, 40)), fill=0)
    esq_mask = np.asarray(esq_im) > 127
    dr.bitmap((0, 0), esq_im, fill=255)
    for ex, ey in ((-9.2, -5.4), (-5.6, -5.4), (-2.4, -5.4), (-9.2, -1.9), (-5.6, -1.9), (-2.4, -1.9), (-9.2, 1.6), (-5.6, 1.6), (-2.4, 1.6),
                   (-7.4, 5.1), (-3.8, 5.1), (-3.2, 8.6)):
        pts = []
        for q in range(10):
            rr = 1.4 if q % 2 == 0 else 0.6
            ang = -np.pi / 2 + q * np.pi / 5
            pts.append((ex + rr * np.cos(ang), ey + rr * np.sin(ang)))
        box = Image.new("L", (N, N), 0)
        ImageDraw.Draw(box).polygon(T(pts), fill=255)
        bm = np.asarray(box) > 127
        if (bm & esq_mask).sum() >= 0.97 * bm.sum():         # só desenha a estrela que cabe inteira dentro do escudo
            do.polygon(T(pts), fill=255)
    # metade direita: contorno + estrela grande + 1968
    dr.line(T(escudo + [escudo[0]]), fill=255, width=int(0.9 * k), joint="curve")
    dr.line(T([(0.25, y_top), (0.25, y_base + 12.0)]), fill=255, width=int(0.8 * k))
    pts = []
    for q in range(10):
        rr = 5.4 if q % 2 == 0 else 2.2
        ang = -np.pi / 2 + q * np.pi / 5
        pts.append((6.7 + rr * np.cos(ang), -2.7 + rr * np.sin(ang)))
    dr.polygon(T(pts), fill=255)
    dr.text(Q(6.4, 5.4), "1968", font=F((4.3 if pequeno else 3.3) * esc), fill=255, anchor="mm")
    relf = (np.asarray(rel) > 127) & ~(np.asarray(ocos) > 127)
    disc = np.asarray(disco_im) > 127
    relf = ndi.binary_opening(relf, iterations=max(1, int(round(0.15 / res)))) & disc
    return relf, disc, N * res / 2


def _emblema_masks(caminho, D, res):
    """Emblema redondo a partir de uma imagem: (relevo, disco, yc_mm). O disco é a base (cor 1); o relevo são as partes claras (cor 2).
    Linhas mais finas que ~0,5 mm somem (não imprimem), então o emblema fica simplificado."""
    if caminho == "cepi":
        return _emblema_cepi(D, res)
    im = Image.open(caminho).convert("RGB")
    a = np.asarray(im).astype(float)
    lum = a.mean(2)
    lab, _ = ndi.label(~(a.min(2) > 235))
    disc = ndi.binary_fill_holes(lab == lab[a.shape[0] // 2, a.shape[1] // 2])
    ys, xs = np.where(disc)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    lado = max(y1 - y0, x1 - x0)
    cy, cx = (y0 + y1) // 2, (x0 + x1) // 2
    r0, c0 = max(0, cy - lado // 2), max(0, cx - lado // 2)
    sl = (slice(r0, r0 + lado), slice(c0, c0 + lado))
    N = int(round(D / res))
    redim = lambda arr: np.asarray(Image.fromarray((arr * 255).astype(np.uint8)).resize((N, N), Image.LANCZOS)) > 127
    disco = redim(disc[sl])
    rel = redim(((lum > 225) & disc)[sl]) & disco
    k = max(1, int(round(0.25 / res)))
    rel = ndi.binary_opening(rel, iterations=k)             # tira linhas finas demais
    rel = ndi.binary_closing(rel, iterations=k)             # fecha riscos finos dentro das áreas claras
    rel &= ndi.binary_erosion(disco, iterations=int(round(1.0 / res)))
    return rel, disco, N * res / 2


def _marcador_singelo(p):
    """Marcador singelo do C.E.P.I.: cabeça com a logo (largura p.marc_cab; a base acompanha o formato da logo) e, embaixo, o clip
    (largura p.marc_larg, comprimento p.marc_clip: moldura em U com lingueta). Comprimento total = p.marc_comp. 2 filamentos: [base, relevo]."""
    res = p.voxel
    k = 1.0 / res
    Wd, Wh, Ln = p.marc_larg, p.marc_cab, p.marc_comp
    pad = int(2.0 * k)
    Wpx, Hpx = int(max(Wd, Wh) * k) + 2 * pad, int(Ln * k) + 2 * pad
    cx = Wpx / 2
    P = lambda x, y: (cx + x * k, pad + y * k)
    S = lambda L: [P(x, y) for x, y in L]
    fonte = listar_fontes()
    fpath = fonte.get("Archivo Black") or fonte.get("Arial Rounded MT Bold") or next(iter(fonte.values()))

    def ajustar(txt, larg_mm, tam_max):
        f4 = ImageFont.truetype(fpath, int(4.0 * k))
        w4 = f4.getlength(txt) / k
        return ImageFont.truetype(fpath, max(8, int(round(min(tam_max, 4.0 * larg_mm / w4) * k))))

    def tela():
        im = Image.new("L", (Wpx, Hpx), 0)
        return im, ImageDraw.Draw(im)

    marg = 1.1                                               # borda de base em volta da logo
    hr = Wh / 2 - marg                                       # meia largura do conteúdo da logo
    rel, dr = tela()
    ocos, do = tela()
    y0 = marg
    # faixa C.E.P.I. (relevo com letras vazadas)
    h_band = 5.2
    dr.rectangle((*P(-hr, y0), *P(hr, y0 + h_band)), fill=255)
    f = ajustar("C.E.P.I.", 2 * hr - 3.6, 6.4)
    do.text(P(0, y0 + h_band / 2 + 0.1), "C.E.P.I.", font=f, fill=255, anchor="mm")
    # PQ BURITIS em relevo
    y_pq = y0 + h_band + 2.3
    f = ajustar("PQ BURITIS", 2 * hr - 0.8, 3.6)
    dr.text(P(0, y_pq), "PQ BURITIS", font=f, fill=255, anchor="mm")
    # escudo (cantos de baixo arredondados) com estrelas
    y_t = y_pq + 2.2
    y_b = p.marc_cab_alt - marg
    hh = y_b - y_t
    xs_ = hr
    fe = 1.4 if hh >= 0.9 * xs_ else 1.0                     # escudo alto (proporção da logo): estrelas maiores
    sc = min(xs_, 1.05 * hh) * fe                                 # escala das estrelas: o escudo é largo e baixo, elas acompanham a altura
    def bez(p0, p1, p2, p3, n=40):
        t = np.linspace(0, 1, n)[:, None]
        return ((1 - t) ** 3 * np.array(p0) + 3 * (1 - t) ** 2 * t * np.array(p1) + 3 * (1 - t) * t ** 2 * np.array(p2) + t ** 3 * np.array(p3)).tolist()
    dire = bez((xs_, y_t + 0.40 * hh), (xs_, y_t + 0.76 * hh), (0.40 * xs_, y_t + 0.92 * hh), (0, y_b))
    esq = [(-x, y) for x, y in dire][::-1]
    escudo = [(-xs_, y_t), (xs_, y_t)] + dire + esq
    esq_im, de = tela()
    de.polygon(S(escudo), fill=255)
    de.rectangle((*P(-0.2, -5), *P(60, 90)), fill=0)
    esq_mask = np.asarray(esq_im) > 127
    dr.bitmap((0, 0), esq_im, fill=255)
    for ex, ey in ((-0.69 * xs_, y_t + 0.24 * hh), (-0.31 * xs_, y_t + 0.24 * hh), (-0.69 * xs_, y_t + 0.52 * hh), (-0.31 * xs_, y_t + 0.52 * hh),
                   (-0.50 * xs_, y_t + 0.76 * hh)):
        pts = []
        for q in range(10):
            rr = 0.100 * sc if q % 2 == 0 else 0.042 * sc
            ang = -np.pi / 2 + q * np.pi / 5
            pts.append((ex + rr * np.cos(ang), ey + rr * np.sin(ang)))
        box = Image.new("L", (Wpx, Hpx), 0)
        ImageDraw.Draw(box).polygon(S(pts), fill=255)
        bm = np.asarray(box) > 127
        if (bm & esq_mask).sum() >= 0.97 * bm.sum():
            do.polygon(S(pts), fill=255)
    dr.line(S(escudo + [escudo[0]]), fill=255, width=int(0.7 * k), joint="curve")
    dr.line(S([(0.2, y_t), (0.2, y_b)]), fill=255, width=int(0.6 * k))
    pts = []
    for q in range(10):
        rr = 0.30 * sc if q % 2 == 0 else 0.125 * sc
        ang = -np.pi / 2 + q * np.pi / 5
        pts.append((0.50 * xs_ + rr * np.cos(ang), y_t + 0.50 * hh + rr * np.sin(ang)))
    dr.polygon(S(pts), fill=255)
    relf_pre = (np.asarray(rel) > 127) & ~(np.asarray(ocos) > 127)

    # base da cabeça: o formato da própria logo, com uma borda em volta
    logo = np.asarray(rel) > 127
    cab = ndi.distance_transform_edt(~logo) <= marg * k
    cab = ndi.binary_fill_holes(cab)
    cab = ndi.gaussian_filter(cab.astype(float), 0.3 * k) > 0.5

    # clip: tira de largura Wd, de baixo até um pouco dentro da cabeça; moldura em U com lingueta
    y_c = y_t + 0.55 * hh
    clip_im, dc = tela()
    r = Wd / 2
    dc.rectangle((*P(-r, y_c), *P(r, Ln - r)), fill=255)
    dc.ellipse((*P(-r, Ln - 2 * r), *P(r, Ln)), fill=255)

    def estadio(w, ytop, ybot):
        im, d = tela()
        rr = w / 2
        d.rectangle((*P(-rr, ytop), *P(rr, ybot - rr)), fill=255)
        d.ellipse((*P(-rr, ybot - 2 * rr), *P(rr, ybot)), fill=255)
        return np.asarray(im) > 127

    y_f = Ln - p.marc_clip + 1.5                             # a fenda começa logo abaixo da ponta do escudo
    Wi = Wd - 2 * p.marc_braco
    Wt = Wi - 2 * p.marc_fenda
    anel = estadio(Wi, y_f, Ln - p.marc_braco)
    ling = estadio(Wt, y_f, Ln - p.marc_braco - p.marc_fenda)
    base2d = (cab | (np.asarray(clip_im) > 127)) & ~(anel & ~ling)
    relf = relf_pre & base2d
    relf = ndi.binary_opening(relf, iterations=max(1, int(round(0.12 / res))))
    # volumes
    nzb = max(2, int(round(p.base_alt / res)))
    nzr = max(2, int(round(p.relevo / res)))
    zb = (np.arange(nzb) + 0.5) * res
    zr = (np.arange(nzr) + 0.5) * res
    db_ = ndi.distance_transform_edt(base2d) * res
    gb = _perfil(zb, p.base_alt, min(p.raio, p.base_alt * 0.45), p)
    obase = (db_[:, :, None] >= np.maximum(gb, res * 0.5)[None, None, :]) & base2d[:, :, None]
    di = ndi.distance_transform_edt(relf) * res
    gi = _perfil(zr, p.relevo, min(p.raio, p.relevo * 0.6), p)
    oin = (di[:, :, None] >= np.maximum(gi, res * 0.5)[None, None, :]) & relf[:, :, None]
    nz = nzb + nzr

    def vol(base=None, inlay=None):
        A = np.zeros(base2d.shape + (nz,), bool)
        if base is not None:
            A[:, :, :nzb] = base
        if inlay is not None:
            A[:, :, nzb:] = inlay
        return np.flip(A, 0).transpose(1, 0, 2)

    return [vol(base=obase), vol(inlay=oin)], res


def marcador_occ(nome, p):
    """Volumes do marcador de páginas: ([base, letras+boca, rosto, capelo+óculos], res), cada um bool (x, y, z) no mesmo referencial."""
    res = p.voxel
    if p.emblema == "cepi_slim":
        return _marcador_singelo(p)
    q = replace(p, produto="ponteira")
    disco = None
    if p.emblema:
        m, disco, yc = _emblema_masks(p.emblema, p.emblema_d, res)
    else:
        m, yc = mascara(nome, q)
    lh, lw = m.shape
    em = _emoji_professor(p.emoji_d, res) if (p.emoji and not p.emblema) else None
    lv = _livro(p.emoji_d, res) if (p.livro_pos != "nenhum" and not p.emblema) else None
    ctr_l = lh - yc / res                                  # linha do meio das maiúsculas
    gap = int(1.5 / res)
    esq, dir_ = [], []                                     # itens antes e depois do nome: (máscaras, largura, altura, chaves)
    if em:
        esq.append((em, em["todo"].shape[1], em["todo"].shape[0], ("cap", "gl", "mo", "rosto")))
    if lv and p.livro_pos in ("inicio", "ambos"):
        esq.append((lv, lv["capa"].shape[1], lv["capa"].shape[0], ("pag", "capa")))
    if lv and p.livro_pos in ("fim", "ambos"):
        dir_.append((lv, lv["capa"].shape[1], lv["capa"].shape[0], ("pag", "capa")))
    # posições (x relativo ao início da peça, linha de cima relativa à linha 0 do nome)
    pos, x = [], 0
    for it in esq:
        pos.append((it, x, int(round(ctr_l - it[2] / 2))))
        x += it[1] + gap
    x_nome = x
    x = x_nome + lw + (gap if dir_ else 0)
    for it in dir_:
        pos.append((it, x, int(round(ctr_l - it[2] / 2))))
        x += it[1] + gap
    W0 = x - (gap if dir_ else 0) if dir_ else x_nome + lw
    tops = [0] + [y for _, _, y in pos]
    base_y = -min(tops)
    H0 = max([lh + base_y] + [y + it[2] + base_y for it, _, y in pos])
    pad = int((p.borda + 2.0) / res) + 4

    def tela():
        return np.zeros((H0 + 2 * pad, W0 + 2 * pad), bool)

    L = tela()
    L[pad + base_y:pad + base_y + lh, pad + x_nome:pad + x_nome + lw] = m
    parts = {k: tela() for k in ("cap", "gl", "mo", "rosto", "pag", "capa")}
    for it, xx, yy in pos:
        mk, w, h, chaves = it
        for k in chaves:
            parts[k][pad + yy + base_y:pad + yy + base_y + h, pad + xx:pad + xx + w] |= mk[k]
    U = L.copy()
    for v in parts.values():
        U |= v
    blk = ndi.distance_transform_edt(~U) <= p.borda / res
    blk = ndi.binary_fill_holes(blk)
    blk = ndi.gaussian_filter(blk.astype(float), 0.4 / res) > 0.5
    if disco is not None:                                  # emblema: o bloco é o próprio disco
        blk = tela()
        blk[pad + base_y:pad + base_y + lh, pad + x_nome:pad + x_nome + lw] = disco
    ys, xs = np.where(blk)
    cxs = (xs.min() + xs.max()) / 2
    yb = ys.max()
    sobre = int(4.0 / res)
    ext = int((p.marc_comp + 2) / res)
    nrows = blk.shape[0] + ext

    def estende(a):
        return np.pad(a, ((0, nrows - a.shape[0]), (0, 0)))

    blk, L = estende(blk), estende(L)
    parts = {k: estende(v) for k, v in parts.items()}
    Wo = p.marc_larg / res
    # a haste começa por baixo da parte mais ALTA da borda do bloco dentro da largura da haste (o nome tem letras que sobem e descem;
    # se partisse do ponto mais baixo, só a letra que desce encostaria na haste e a peça ficaria solta)
    c0h, c1h = max(0, int(cxs - Wo / 2)), min(blk.shape[1], int(cxs + Wo / 2) + 1)
    fundo = [np.where(blk[:, c])[0].max() for c in range(c0h, c1h) if blk[:, c].any()]
    yb_h = min(fundo) if fundo else yb
    y0, y1 = yb_h - sobre, yb_h - sobre + int(p.marc_comp / res)
    Wi = Wo - 2 * p.marc_braco / res
    Wt = Wo - 2 * (p.marc_braco + p.marc_fenda) / res

    def haste(w, ytop, ybot):
        im = Image.new("L", (blk.shape[1], blk.shape[0]), 0)
        _estadio(im, cxs, ytop, ybot, w)
        return np.asarray(im) > 127

    outer = haste(Wo, y0, y1)
    ring = haste(Wi, y0, y1 - p.marc_braco / res)
    tong = haste(Wt, y0, y1 - (p.marc_braco + p.marc_fenda) / res)
    stem = outer & ~(ring & ~tong)
    base2d = blk | stem
    ys, xs = np.where(base2d)
    r0, r1, c0, c1 = ys.min() - 2, ys.max() + 3, xs.min() - 2, xs.max() + 3
    r0, c0 = max(r0, 0), max(c0, 0)
    cut = lambda a: a[r0:r1, c0:c1]
    base2d, L = cut(base2d), cut(L)
    parts = {k: cut(v) for k, v in parts.items()}
    nzb = max(2, int(round(p.base_alt / res)))
    nzr = max(2, int(round(p.relevo / res)))
    zb = (np.arange(nzb) + 0.5) * res
    zr = (np.arange(nzr) + 0.5) * res
    db = ndi.distance_transform_edt(base2d) * res
    gb = _perfil(zb, p.base_alt, min(p.raio, p.base_alt * 0.45), p)
    obase = (db[:, :, None] >= np.maximum(gb, res * 0.5)[None, None, :]) & base2d[:, :, None]
    inl = L.copy()
    for v in parts.values():
        inl |= v
    if p.marc_cores == 2:
        fio = ndi.distance_transform_edt(~parts["cap"]) <= 0.45 / res          # fio fino de base entre o capelo e o rosto
        tinta = L | parts["cap"] | parts["capa"] | parts["pag"] | (parts["rosto"] & ~fio)
        inl = tinta
    di = ndi.distance_transform_edt(inl) * res
    gi = _perfil(zr, p.relevo, min(p.raio, p.relevo * 0.6), p)
    oin = (di[:, :, None] >= np.maximum(gi, res * 0.5)[None, None, :]) & inl[:, :, None]
    nz = nzb + nzr

    def vol(base=None, inlay=None):
        A = np.zeros(base2d.shape + (nz,), bool)
        if base is not None:
            A[:, :, :nzb] = base
        if inlay is not None:
            A[:, :, nzb:] = inlay
        return np.flip(A, 0).transpose(1, 0, 2)

    p1 = vol(base=obase)
    if p.marc_cores == 2:
        return [p1, vol(inlay=oin)], res
    p2 = vol(inlay=oin & (L | parts["mo"] | parts["pag"])[:, :, None])
    p3 = vol(inlay=oin & parts["rosto"][:, :, None])
    p4 = vol(inlay=oin & (parts["cap"] | parts["gl"] | parts["capa"])[:, :, None])
    return [p1, p2, p3, p4], res


# marcador de páginas singelo com o emblema do C.E.P.I. (aprovado): cabeça 28 x 36 mm na proporção da logo + clip de 20 x 45 mm, base de 1 mm
MARCADOR_CEPI = dict(produto="marcador", emblema="cepi_slim", marc_larg=20.0, marc_cab=28.0, marc_cab_alt=36.0, marc_braco=3.4, marc_fenda=1.6,
                     marc_clip=45.0, voxel=0.05, marc_cores=2, emoji=False, livro_pos="nenhum", marc_comp=81.0,
                     **{**MARCADOR, "raio": 0.4, "base_alt": 1.0, "relevo": 0.6})
