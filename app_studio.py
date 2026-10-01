"""Ponteiras de Nomes · Studio — interface no estilo do Parametric Model Maker (MakerLab).

Painel "Customize" à esquerda, visualização 3D grande com a mesa da P1S à direita, botão de gerar e baixar no topo.
Rodar:  streamlit run app_studio.py
"""
import base64
import io
import json
import os
import tempfile
import time
import uuid
import zipfile
from dataclasses import asdict

os.environ.setdefault("PONTEIRAS_MESHER", "skimage")          # sem Blender: malha por marching cubes

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw, ImageFont

import ponteiras_core as core
from web_util import supabase_util as sb
from web_util import visualizador3d as viz

st.set_page_config(page_title="Ponteiras de Nomes · Studio", page_icon="✏️", layout="wide", initial_sidebar_state="collapsed")

PADRAO = "(padrão)"
NENHUM = "(nenhum)"
ESTILOS = {"Fechada": "fechada", "Vazada (contorno)": "vazada", "Com borda em degrau": "base"}
MODOS = {"Uniforme": "uniforme", "Zig-zag": "zigzag", "Cores alternadas": "cores"}
CAIXAS = {"MAIÚSCULAS": "maiusculas", "minúsculas": "minusculas", "Primeira Maiúscula": "capitalizar", "Como digitado": "digitado"}
SAIDA = os.path.join(core.HERE, "saida")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"], button, input, textarea, select { font-family: 'Inter', 'Segoe UI', sans-serif !important; }
.block-container { padding: 0.6rem 1.2rem 1rem 1.2rem; max-width: 100%; }
header[data-testid="stHeader"] { display: none; }
#MainMenu, footer { visibility: hidden; }
.topo { display:flex; align-items:center; gap:12px; padding: 8px 4px 12px 4px; }
.topo .voltar { font-size: 1.3rem; opacity:.7; }
.topo h1 { margin:0; font-size:1.25rem; font-weight:700; letter-spacing:-.01em; }
.topo .sub { opacity:.6; font-size:.85rem; margin-left:6px; }
.card-modelo { background:#1c1f27; border:1px solid #2a2e39; border-radius:14px; padding:12px 14px; display:flex; gap:12px; margin-bottom:10px; }
.card-modelo .thumb { width:84px; height:84px; border-radius:10px; background: linear-gradient(135deg,#3b82f6,#22c55e);
   display:flex; align-items:center; justify-content:center; font-size:1.7rem; font-weight:800; color:#fff; letter-spacing:-.03em; }
.card-modelo .t { font-weight:700; font-size:1rem; line-height:1.2; }
.card-modelo .m { opacity:.65; font-size:.8rem; margin-top:4px; }
.card-modelo .chips span { display:inline-block; font-size:.7rem; background:#262a35; border-radius:999px; padding:2px 9px; margin:5px 4px 0 0; color:#b9c2d8; }
.tit-sec { font-weight:700; font-size:.95rem; display:flex; align-items:center; gap:8px; margin:2px 0 6px 0; }
div[data-testid="stExpander"] { border:1px solid #2a2e39; border-radius:12px; background:#181b22; }
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius:16px; }
.stButton > button, .stDownloadButton > button { border-radius:10px; font-weight:700; }
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] { background:#2f7bff; border:0; color:#fff; }
.stButton > button[kind="primary"]:hover { filter:brightness(1.1); }
div[data-testid="stMetric"] { background:#1c1f27; border:1px solid #2a2e39; border-radius:12px; padding:8px 12px; }
.dica { opacity:.6; font-size:.82rem; }
div[data-testid="stDataEditor"] { border-radius:10px; overflow:hidden; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ----------------------------------------------------------------------------- senha opcional
senha = os.environ.get("APP_PASSWORD", "")
if senha and not st.session_state.get("_ok"):
    st.markdown("<div class='topo'><span class='voltar'>✏️</span><h1>Ponteiras de Nomes</h1></div>", unsafe_allow_html=True)
    tent = st.text_input("Senha de acesso", type="password")
    if tent and tent == senha:
        st.session_state["_ok"] = True
        st.rerun()
    elif tent:
        st.error("Senha incorreta.")
    st.stop()

if sb.configurado() and not st.session_state.get("_sync"):
    st.session_state["_sync"] = True
    try:
        sb.sincronizar_assets(core.FONTES_IMPORTADAS, core.IMAGENS_DIR)
    except Exception:
        pass


@st.cache_data(show_spinner=False)
def carregar_fontes(_v=0):
    return core.listar_fontes(), core.listar_fontes_agrupadas(), dict(core.INFO_FONTE)


FONTES, GRUPOS, INFO = carregar_fontes()
core.INFO_FONTE.update(INFO)
ROTULO_GRUPO = {}
for titulo, nomes in GRUPOS:
    curto = titulo.replace("★ ", "").split(" (")[0].split(" estilo")[0].split(" /")[0]
    for n in nomes:
        ROTULO_GRUPO[n] = ("★ " if titulo.startswith("★") else "") + curto
OPCOES_ENFEITE = core.opcoes_enfeite()
ENF = dict(OPCOES_ENFEITE)
ROTULOS_ENFEITE = [r for r, _ in OPCOES_ENFEITE]

DEF = {
    "fonte": next((k for k in FONTES if k.lower().startswith(("lilita", "arial rounded", "poppins extra"))), next(iter(FONTES))),
    "altura": 11.5, "espessura": 10.9, "raio": 2.2, "engrossar": 0.45, "largura": 0.72, "espaco": -0.6, "ponte": 2.4,
    "caixa": "MAIÚSCULAS", "dois_lados": False, "modo": "Uniforme", "zigzag": 1.2, "estilo": "Fechada", "borda": 1.6, "fundo": 1.0, "altura_borda": 4.0,
    "tipo_lapis": list(core.PRESETS_LAPIS)[0], "furo_formato": "Circular", "furo": 8.0, "furo_folga": 0.0, "furo_rot": 0.0,
    "furo_canto": 1.2, "parede_base": 1.0, "qualidade": "Normal", "enf_antes": NENHUM, "enf_depois": NENHUM,
    "cor_a": "#2fd17b", "cor_b": "#ff8a1f", "opcoes_por_nome": False,
}
for k, v in DEF.items():
    st.session_state.setdefault(k, v)
if "sid" not in st.session_state:
    st.session_state.sid = uuid.uuid4().hex[:8]
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame([
        {"Nome": "Emma", "Qtd": 1, "Fonte": PADRAO, "Furo": PADRAO, "Antes": PADRAO, "Depois": PADRAO},
        {"Nome": "Helena", "Qtd": 1, "Fonte": PADRAO, "Furo": PADRAO, "Antes": PADRAO, "Depois": PADRAO},
    ])


# ----------------------------------------------------------------------------- funções
@st.cache_data(show_spinner=False)
def amostra_uri(caminho, nome, h=30):
    try:
        ft = ImageFont.truetype(caminho, h)
        texto = nome if core._tem_glifo(ft, "A") else "❤ ✿ ★ ☺ ♪"
        bb = ft.getbbox(texto)
        im = Image.new("RGB", (max(40, bb[2] + 16), h + 16), (28, 31, 39))
        ImageDraw.Draw(im).text((6, 4 - min(0, bb[1])), texto, font=ft, fill=(236, 240, 250))
        b = io.BytesIO()
        im.save(b, "PNG")
        return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()
    except Exception:
        return ""


def params_de(fonte_nome=None, furo_nome=None):
    s = st.session_state
    fn = fonte_nome if fonte_nome and fonte_nome != PADRAO else s["fonte"]
    fmt_nome = furo_nome if furo_nome in core.FORMATOS_FURO else s["furo_formato"]
    return core.Params(
        fonte=FONTES.get(fn) or core.resolver_fonte(fn), altura=float(s["altura"]), espessura=float(s["espessura"]), raio=float(s["raio"]),
        engrossar=float(s["engrossar"]), espaco=float(s["espaco"]), largura=float(s["largura"]), ponte=float(s["ponte"]),
        caixa=CAIXAS[s["caixa"]], dois_lados=bool(s["dois_lados"]), modo=MODOS[s["modo"]], zigzag=float(s["zigzag"]), estilo=ESTILOS[s["estilo"]],
        borda=float(s["borda"]), fundo=float(s["fundo"]), altura_borda=float(s["altura_borda"]), parede_base=float(s["parede_base"]),
        furo_formato=core.FORMATOS_FURO[fmt_nome][0],
        furo=(core.FORMATOS_FURO[furo_nome][1] if furo_nome in core.FORMATOS_FURO else float(s["furo"])),
        furo_folga=float(s["furo_folga"]), furo_rot=float(s["furo_rot"]), furo_canto=float(s["furo_canto"]),
        voxel=core.QUALIDADE[s["qualidade"]])


def token(rotulo, chave_global):
    r = st.session_state[chave_global] if rotulo in (PADRAO, "", None) else rotulo
    return ENF.get(r, "")


def texto_de(l):
    nome = core.aplicar_caixa(str(l["Nome"]).strip(), core.Params(caixa=CAIXAS[st.session_state["caixa"]]))
    return core.compor_nome(nome, token(l["Antes"], "enf_antes"), token(l["Depois"], "enf_depois"))


def linhas_validas(df):
    out = []
    for _, r in df.iterrows():
        if isinstance(r["Nome"], str) and r["Nome"].strip():
            g = lambda c, d=PADRAO: (r[c] if c in r and pd.notna(r[c]) else d)
            out.append({"Nome": r["Nome"].strip(), "Qtd": int(g("Qtd", 1)), "Fonte": g("Fonte"), "Furo": g("Furo"),
                        "Antes": g("Antes"), "Depois": g("Depois")})
    return out


def _cb_reset():
    for k, v in DEF.items():
        if k not in ("fonte",):
            st.session_state[k] = v


def _cb_tipo():
    alt, esp = core.aplicar_preset(st.session_state["tipo_lapis"])
    st.session_state["altura"], st.session_state["espessura"] = alt, esp
    st.session_state["furo"] = core.FORMATOS_FURO[st.session_state["furo_formato"]][1]


def _cb_formato():
    st.session_state["furo"] = core.FORMATOS_FURO[st.session_state["furo_formato"]][1]


def _cb_sugerir():
    aj = core.sugerir_ajustes(st.session_state["fonte"])
    if aj:
        for k, v in aj.items():
            st.session_state[k] = v


def _cb_gerar():
    st.session_state["_gerar_flag"] = True


@st.cache_data(show_spinner=False, max_entries=80)
def partes_prev(texto, pjson):
    """Malha rápida (por cor) + dados compactos do visualizador, em cache por nome/ajustes."""
    p = core.Params(**json.loads(pjson))
    partes = core.partes_rapidas(texto, p)
    dim = np.max([v.max(0) for v, _, _ in partes], axis=0)
    objs = []
    for v, f, idx in partes:
        o = viz.dados_malhas([(texto, v, f, (0, 0))], alvo_tris=6000)[0]
        o["idx"] = idx
        objs.append(o)
    return dim, objs



def icone_simbolo(glifo, tam=44):
    """Imagem do símbolo (coração, flor...) desenhada com a fonte de reserva que o tiver."""
    im = Image.new("RGB", (tam, tam), (28, 31, 39))
    for c in core._fontes_reserva():
        ft = core._fonte_reserva(c, int(tam * 0.75))
        if core._tem_glifo(ft, glifo):
            bb = ft.getbbox(glifo)
            ImageDraw.Draw(im).text(((tam - (bb[2] - bb[0])) / 2 - bb[0], (tam - (bb[3] - bb[1])) / 2 - bb[1]), glifo, font=ft, fill=(236, 240, 250))
            break
    return im


@st.dialog("Escolher fonte", width="large")
def dialogo_fonte():
    st.caption("Cada fonte aparece escrita no próprio estilo. Clique em uma linha para usar. "
               "No servidor não existem as fontes do Windows (Arial, Times...): há equivalentes abertos e você pode importar as suas (.ttf/.otf).")
    c1, c2 = st.columns([2, 1])
    busca = c1.text_input("Buscar", placeholder="ex.: lobster, pixel, bold, script...", key="f_busca")
    grupo = c2.selectbox("Grupo", ["Todos"] + [t for t, _ in GRUPOS], key="f_grupo")
    nomes = [n for t, ns in GRUPOS if grupo in ("Todos", t) for n in ns if busca.lower() in n.lower()]
    total = len(nomes)
    nomes = nomes[:150]
    df = pd.DataFrame({"Amostra": [amostra_uri(FONTES[n], n, 34) for n in nomes], "Fonte": nomes,
                       "Grupo": [ROTULO_GRUPO.get(n, "Padrão") for n in nomes]})
    ev = st.dataframe(df, hide_index=True, width="stretch", height=440, row_height=52, on_select="rerun", selection_mode="single-row",
                      key=f"f_tab_{st.session_state.get('f_n', 0)}", column_config={"Amostra": st.column_config.ImageColumn("Amostra", width="large")})
    st.caption(f"{total} fonte(s)" + (" (mostrando 150; refine a busca)" if total > 150 else ""))
    if ev.selection.rows:
        st.session_state["fonte"] = nomes[ev.selection.rows[0]]
        st.rerun()


def _cb_add_token(tok):
    st.session_state["mont_nome"] = st.session_state.get("mont_nome", "") + tok


def _cb_trocar():
    qual = {"Todas": "todas", "Primeira": "primeira", "Última": "ultima"}[st.session_state["tr_qual"]]
    st.session_state["mont_nome"] = core.trocar_letra(st.session_state["mont_nome"], st.session_state["tr_letra"],
                                                      ENF[st.session_state["tr_por"]], qual)


@st.dialog("Símbolos, imagens e troca de letras", width="large")
def dialogo_simbolos():
    st.session_state.setdefault("mont_nome", "LOVE")
    st.text_input("Monte o nome aqui (depois adicione à lista)", key="mont_nome")
    st.markdown("**Inserir no fim do nome** <span class='dica'>(início, meio ou fim: edite o texto acima)</span>", unsafe_allow_html=True)
    cols = st.columns(8)
    for i, (tok, gl) in enumerate(core.ATALHOS.items()):
        with cols[i % 8]:
            st.image(icone_simbolo(gl), width=44)
            st.button(tok.strip(":")[:9], key=f"sb{i}", on_click=_cb_add_token, args=(tok,), width="stretch")
    imgs = core.listar_imagens()
    if imgs:
        st.markdown("**Suas imagens**")
        cols = st.columns(8)
        for i, (n, pth) in enumerate(imgs.items()):
            with cols[i % 8]:
                im = Image.open(pth).convert("RGBA")
                fundo = Image.new("RGBA", im.size, (28, 31, 39, 255))
                fundo.alpha_composite(im)
                fundo.thumbnail((56, 56))
                st.image(fundo.convert("RGB"), width=44)
                st.button(n[:9], key=f"ib{i}", on_click=_cb_add_token, args=(f":{n}:",), width="stretch")
    st.markdown("**Trocar letra por símbolo**")
    letras = core.letras_do_texto(st.session_state["mont_nome"])
    if letras:
        t1, t2, t3 = st.columns(3)
        t1.selectbox("Letra", letras, key="tr_letra")
        t2.selectbox("Ocorrência", ["Todas", "Primeira", "Última"], key="tr_qual")
        t3.selectbox("Trocar por", [r for r in ROTULOS_ENFEITE if ENF[r]], key="tr_por")
        st.button("Aplicar troca", on_click=_cb_trocar)
    if st.button("➕ Adicionar à lista de nomes", type="primary", width="stretch"):
        nova = {"Nome": st.session_state["mont_nome"], "Qtd": 1, "Fonte": PADRAO, "Furo": PADRAO, "Antes": PADRAO, "Depois": PADRAO}
        st.session_state.df = pd.concat([st.session_state.df, pd.DataFrame([nova])], ignore_index=True)
        st.rerun()


@st.dialog("Gabarito de teste do furo", width="large")
def dialogo_gabarito():
    st.caption("Barra de 5 mm com furos de medidas próximas à atual (−0,6 a +0,6 mm), da esquerda (menor, canto chanfrado) para a direita. "
               "O furo onde o seu lápis entra com leve atrito é a medida certa.")
    if st.button("Gerar gabarito", type="primary"):
        try:
            pp = params_de()
            meds = [round(pp.furo + d, 2) for d in (-0.6, -0.4, -0.2, 0.0, 0.2, 0.4, 0.6)]
            pasta = os.path.join(SAIDA, "web", st.session_state.sid, "gabarito_" + time.strftime("%H%M%S"))
            os.makedirs(pasta, exist_ok=True)
            with st.spinner("Gerando o gabarito..."):
                arq = core.gerar_gabarito(pp.furo_formato, meds, pasta, folga=pp.furo_folga, rot=pp.furo_rot, canto=pp.furo_canto,
                                          log=lambda m: None)
            st.session_state["gabarito"] = (arq, meds, pp.furo_formato)
        except Exception as e:
            st.error(str(e))
    g = st.session_state.get("gabarito")
    if g:
        arq, meds, fmt = g
        st.success(f"Gabarito {fmt}: furos de {', '.join(f'{m:g}' for m in meds)} mm.")
        st.download_button("⬇️ Baixar gabarito (.3mf)", open(arq, "rb").read(), os.path.basename(arq), type="primary")
        try:
            stl = [os.path.join(os.path.dirname(arq), "stl_gabarito", f) for f in os.listdir(os.path.join(os.path.dirname(arq), "stl_gabarito"))][0]
            v, f = core.ler_stl(stl)
            objs = viz.dados_malhas([("gabarito", v - v.min(0), f, (0, 0), st.session_state["cor_a"])], alvo_tris=9000)
            components.html(viz.html_visualizador(objs, None, st.session_state["cor_a"], 360, "escuro"), height=380)
        except Exception:
            pass


@st.dialog("Predefinições e pedidos salvos (nuvem)", width="large")
def dialogo_salvos():
    t1, t2 = st.tabs(["Predefinições", "Pedidos"])
    with t1:
        nome_p = st.text_input("Nome da predefinição", key="nome_predef")
        if st.button("Salvar ajustes atuais") and nome_p.strip():
            try:
                sb.salvar_predefinicao(nome_p.strip(), {k: st.session_state[k] for k in DEF})
                st.success("Salvo.")
            except Exception as e:
                st.error(str(e))
        try:
            preds = sb.listar_predefinicoes()
        except Exception:
            preds = []
        if preds:
            esc = st.selectbox("Carregar", [p["nome"] for p in preds], key="sel_predef")
            c1, c2 = st.columns(2)
            if c1.button("Carregar predefinição", width="stretch"):
                for k, v in next(p["ajustes"] for p in preds if p["nome"] == esc).items():
                    if k in DEF and (k != "fonte" or v in FONTES):
                        st.session_state[k] = v
                st.rerun()
            if c2.button("Apagar predefinição", width="stretch"):
                sb.apagar_predefinicao(esc)
                st.rerun()
    with t2:
        res_ = st.session_state.get("resultado")
        if res_ and st.button("☁️ Salvar o pedido atual na nuvem"):
            try:
                sb.enviar_arquivo(sb.BUCKET_ARQUIVOS, f"{st.session_state.sid}/{int(time.time())}.zip", res_["zip"], "application/zip")
                sb.salvar_pedido("Pedido " + time.strftime("%d/%m/%Y %H:%M"), linhas_validas(st.session_state.df), {k: st.session_state[k] for k in DEF})
                st.success("Pedido salvo.")
            except Exception as e:
                st.error(str(e))
        try:
            peds = sb.listar_pedidos()
        except Exception:
            peds = []
        for p in peds:
            with st.expander(f"{p['nome']} · {len(p['itens'])} nome(s)"):
                st.dataframe(pd.DataFrame(p["itens"]), hide_index=True, width="stretch")
                c1, c2 = st.columns(2)
                if c1.button("Carregar este pedido", key="ld" + p["id"]):
                    st.session_state.df = pd.DataFrame(p["itens"])
                    for k, v in p["ajustes"].items():
                        if k in DEF and (k != "fonte" or v in FONTES):
                            st.session_state[k] = v
                    st.rerun()
                if c2.button("Apagar", key="rm" + p["id"]):
                    sb.apagar_pedido(p["id"])
                    st.rerun()


# ----------------------------------------------------------------------------- geração final (antes de desenhar a barra do topo)
linhas = linhas_validas(st.session_state.df)
if st.session_state.pop("_gerar_flag", False) and linhas:
    try:
        itens = [(texto_de(l), l["Qtd"], params_de(l["Fonte"], l["Furo"]), l["Nome"]) for l in linhas]
        pasta = os.path.join(SAIDA, "web", st.session_state.sid, "pedido_" + time.strftime("%Y-%m-%d_%H%M%S"))
        det = {}
        with st.spinner("Gerando as peças na resolução final..."):
            arqs = core.gerar_tudo(itens, SAIDA, log=lambda m: None, pasta_pedido=pasta, detalhes=det)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for a in arqs:
                z.write(a, os.path.basename(a))
            for k in det["geo"]:
                for suf in ("", "_A", "_B"):
                    arq = os.path.join(det["stl"], k + suf + ".stl")
                    if os.path.exists(arq):
                        z.write(arq, "stl/" + os.path.basename(arq))
        st.session_state["resultado"] = {"zip": buf.getvalue(), "arqs": arqs, "pratos": det["pratos"], "det": det}
        st.session_state["_msg_ok"] = f"{len(arqs)} prato(s) gerado(s)."
    except Exception as e:
        st.session_state["_msg_erro"] = str(e)

# ----------------------------------------------------------------------------- barra do topo
res = st.session_state.get("resultado")
tc1, tc2, tc3, tc4 = st.columns([5, 2, 2, 2])
with tc1:
    st.markdown("<div class='topo'><span class='voltar'>✏️</span><h1>Ponteiras de Nomes</h1>"
                "<span class='sub'>Modelo paramétrico · Bambu Lab P1S</span></div>", unsafe_allow_html=True)
with tc2:
    st.button("✨ Gerar arquivos", type="primary", width="stretch", on_click=_cb_gerar, disabled=not linhas)
with tc3:
    if res:
        st.download_button("⬇️ Baixar (.zip)", res["zip"], "ponteiras.zip", "application/zip", type="primary", width="stretch")
    else:
        st.button("⬇️ Baixar (.zip)", disabled=True, width="stretch", help="Clique em Gerar arquivos primeiro.")
with tc4:
    st.selectbox("Qualidade", list(core.QUALIDADE), key="qualidade", label_visibility="collapsed")

if st.session_state.get("_msg_erro"):
    st.error(st.session_state.pop("_msg_erro"))
if st.session_state.get("_msg_ok"):
    st.success(st.session_state.pop("_msg_ok"))

col_esq, col_dir = st.columns([1, 2.5], gap="medium")

# gancho de teste: STUDIO_ABRIR=simbolos|gabarito|fonte abre o diálogo ao carregar (usado só em testes)
_abrir_teste = os.environ.get("STUDIO_ABRIR", "")
if _abrir_teste == "simbolos":
    dialogo_simbolos()
elif _abrir_teste == "gabarito":
    dialogo_gabarito()

# ============================== PAINEL ESQUERDO (Customize)
with col_esq:
    primeira = linhas[0]["Nome"] if linhas else "Nome"
    st.markdown(
        f"""<div class='card-modelo'><div class='thumb'>{primeira[:1].upper()}</div><div>
        <div class='t'>Nomes de Lápis Encaixáveis</div><div class='m'>Topo de lápis com o nome · furo sob medida</div>
        <div class='chips'><span>3MF</span><span>PLA</span><span>Textured PEI</span><span>AMS</span></div></div></div>""",
        unsafe_allow_html=True)
    tb1, tb2, tb3 = st.columns(3)
    if tb1.button("🌸 Símbolos", width="stretch", help="Símbolos, imagens e troca de letras por símbolos"):
        dialogo_simbolos()
    if tb2.button("🔩 Gabarito", width="stretch", help="Peça de teste para achar a medida do furo"):
        dialogo_gabarito()
    if tb3.button("☁️ Salvos", width="stretch", disabled=not sb.configurado(), help="Predefinições e pedidos na nuvem (Supabase)"):
        dialogo_salvos()
    with st.container(height=700, border=True):
        hc1, hc2 = st.columns([4, 1])
        hc1.markdown("<div class='tit-sec'>🎛️ Personalizar</div>", unsafe_allow_html=True)
        hc2.button("↺", on_click=_cb_reset, help="Restaurar padrões", width="stretch")

        with st.expander("📥 Importar lista de nomes (.csv, .txt, .xlsx)"):
            st.caption("Uma linha por nome. Colunas: NOME;QUANTIDADE;FONTE;FURO (tudo depois do nome é opcional). "
                       "Também dá para colar linhas de uma planilha direto na tabela abaixo.")
            so1 = st.checkbox("Usar só o primeiro nome (apaga o segundo nome dos nomes compostos)", key="so_primeiro")
            subst = st.checkbox("Substituir a lista atual (em vez de acrescentar)", key="subst_lista")
            up = st.file_uploader("Arquivo da lista", type=["csv", "txt", "xlsx"], key="up_lista")
            if up is not None and st.button("Importar", type="primary", key="bt_imp"):
                try:
                    itens_imp = core.ler_lista_nomes(up.getvalue(), up.name, so_primeiro_nome=so1)
                    novas = pd.DataFrame([{"Nome": n, "Qtd": q, "Fonte": f if f in FONTES else PADRAO,
                                           "Furo": next((k for k in core.FORMATOS_FURO if fu and k.lower().startswith(fu.lower()[:4])), PADRAO),
                                           "Antes": PADRAO, "Depois": PADRAO} for n, q, f, fu in itens_imp])
                    if novas.empty:
                        st.warning("Não achei nomes nesse arquivo.")
                    else:
                        base_df = pd.DataFrame(columns=novas.columns) if subst else st.session_state.df
                        st.session_state.df = pd.concat([base_df, novas], ignore_index=True)
                        st.session_state["_msg_ok"] = f"{len(novas)} nome(s) importado(s)."
                        st.rerun()
                except Exception as e:
                    st.error(f"Não consegui ler o arquivo: {e}")

        st.markdown("**Nomes** <span class='dica'>(tabela: nome e quantidade)</span>", unsafe_allow_html=True)
        st.toggle("Opções por nome (fonte, furo, enfeites)", key="opcoes_por_nome")
        ordem = ["Nome", "Qtd", "Fonte", "Furo", "Antes", "Depois"] if st.session_state["opcoes_por_nome"] else ["Nome", "Qtd"]
        cfg = {
            "Nome": st.column_config.TextColumn("Nome", required=True, help="Símbolos: ANA :coracao: CLARA"),
            "Qtd": st.column_config.NumberColumn("Qtd", min_value=1, max_value=500, step=1, default=1, width="small"),
            "Fonte": st.column_config.SelectboxColumn("Fonte", options=[PADRAO] + list(FONTES), default=PADRAO),
            "Furo": st.column_config.SelectboxColumn("Furo", options=[PADRAO] + list(core.FORMATOS_FURO), default=PADRAO),
            "Antes": st.column_config.SelectboxColumn("Antes", options=[PADRAO] + ROTULOS_ENFEITE, default=PADRAO),
            "Depois": st.column_config.SelectboxColumn("Depois", options=[PADRAO] + ROTULOS_ENFEITE, default=PADRAO),
        }
        st.session_state.df = st.data_editor(st.session_state.df, column_config=cfg, column_order=ordem, num_rows="dynamic",
                                             width="stretch", key="editor", hide_index=True)
        linhas = linhas_validas(st.session_state.df)
        st.markdown("**Letras do nome**")
        st.radio("Caixa", list(CAIXAS), key="caixa", horizontal=True, label_visibility="collapsed")
        st.checkbox("Nome legível nos dois lados (frente e verso)", key="dois_lados",
                    help="Metade de cima com o nome e metade de baixo com o nome de cabeça para baixo: ao girar o lápis 180° o outro lado também lê de pé. Precisa de suporte na impressão.")
        if st.session_state["caixa"] in ("minúsculas", "Primeira Maiúscula", "Como digitado"):
            st.caption("Letras minúsculas são mais baixas que as maiúsculas: se o furo não couber ou a peça ficar fina, "
                       "aumente o tamanho da letra ou diminua o furo.")

        st.markdown("**Fonte**")
        uri = amostra_uri(FONTES[st.session_state["fonte"]], st.session_state["fonte"], 36)
        if uri:
            st.markdown(f"<img src='{uri}' style='max-width:100%;border-radius:8px'>", unsafe_allow_html=True)
        st.caption(f"{ROTULO_GRUPO.get(st.session_state['fonte'], 'Padrão')} · {st.session_state['fonte']} — {sum(len(n) for _, n in GRUPOS)} fontes disponíveis")
        fc1, fc2 = st.columns(2)
        if fc1.button("🔤 Escolher fonte...", width="stretch"):
            st.session_state["f_n"] = st.session_state.get("f_n", 0) + 1      # tabela nova a cada abertura (sem seleção antiga)
            dialogo_fonte()
        fc2.button("✨ Sugerir ajustes", on_click=_cb_sugerir, width="stretch")
        st.slider("Tamanho da letra (mm)", 6.0, 30.0, step=0.5, key="altura")
        st.slider("Espessura da peça (mm)", 4.0, 20.0, step=0.1, key="espessura")

        st.markdown("**Estilo das letras**")
        st.radio("Modo", list(MODOS), key="modo", horizontal=True, label_visibility="collapsed")
        if MODOS[st.session_state["modo"]] == "zigzag":
            st.slider("Zig-zag: quanto sobe/desce (mm)", 0.2, 3.0, step=0.1, key="zigzag")
        cc1, cc2 = st.columns(2)
        modo_cores = MODOS[st.session_state["modo"]] == "cores"
        cc1.color_picker("Cor A" if modo_cores else "Cor do filamento", key="cor_a")
        cc2.color_picker("Cor B", key="cor_b", disabled=not modo_cores)
        st.caption("Cada letra alterna A/B. No 3MF são duas partes (filamentos 1 e 2) para o AMS." if modo_cores
                   else "Cor usada na prévia 3D. Use o modo 'Cores alternadas' para duas cores.")
        st.selectbox("Corpo da letra", list(ESTILOS), key="estilo")
        if ESTILOS[st.session_state["estilo"]] == "vazada":
            st.slider("Espessura do contorno", 0.8, 6.0, step=0.1, key="borda")
            st.slider("Fundo (0 = vazada)", 0.0, 4.0, step=0.1, key="fundo")
        elif ESTILOS[st.session_state["estilo"]] == "base":
            st.slider("Largura da borda", 0.8, 6.0, step=0.1, key="borda")
            st.slider("Altura da borda", 1.0, 10.0, step=0.5, key="altura_borda")

        st.markdown("**Espaçamento e forma**")
        st.slider("Espaço entre letras (mm)", -3.0, 3.0, step=0.1, key="espaco")
        st.slider("Largura das letras (×)", 0.4, 1.5, step=0.02, key="largura")
        st.slider("Engrossar traço (mm)", 0.0, 2.0, step=0.05, key="engrossar")
        st.slider("Arredondado da borda (mm)", 0.4, 5.0, step=0.1, key="raio")

        st.markdown("**Furo do lápis**")
        st.selectbox("Tipo de lápis", list(core.PRESETS_LAPIS), key="tipo_lapis", on_change=_cb_tipo)
        st.radio("Formato", list(core.FORMATOS_FURO), key="furo_formato", horizontal=True, on_change=_cb_formato, label_visibility="collapsed")
        st.slider("Medida do furo (mm)", 4.0, 14.0, step=0.05, key="furo", help="Circular: diâmetro · Hexagonal: entre faces · Triangular: altura")
        st.slider("Folga extra (mm)", 0.0, 1.0, step=0.05, key="furo_folga")
        st.slider("Posição vertical do furo (parede da base, mm)", 0.4, 3.0, step=0.1, key="parede_base")
        st.slider("Girar furo (graus)", -180.0, 180.0, step=15.0, key="furo_rot")
        if core.FORMATOS_FURO[st.session_state["furo_formato"]][0] == "triangular":
            st.slider("Canto do triângulo (mm)", 0.2, 3.0, step=0.1, key="furo_canto")

        st.markdown("**Enfeites (todos os nomes)**")
        st.selectbox("Antes do nome", ROTULOS_ENFEITE, key="enf_antes")
        st.selectbox("Depois do nome", ROTULOS_ENFEITE, key="enf_depois")
        st.caption("No meio do nome ou no lugar de uma letra: use o botão 🌸 Símbolos (ou digite :coracao:, :flor:...).")

        with st.expander("Importar fonte ou imagem"):
            ups = st.file_uploader("Fontes (.ttf / .otf)", type=["ttf", "otf"], accept_multiple_files=True, key="up_f")
            if ups and st.button("Importar fontes"):
                for u in ups:
                    tmp = os.path.join(tempfile.gettempdir(), u.name)
                    open(tmp, "wb").write(u.getvalue())
                    try:
                        core.importar_fonte(tmp)
                        if sb.configurado():
                            sb.enviar_arquivo(sb.BUCKET_ASSETS, "fontes/" + u.name, u.getvalue())
                    except Exception as e:
                        st.error(f"{u.name}: {e}")
                st.cache_data.clear()
                st.rerun()
            ups = st.file_uploader("Imagens (PNG/JPG)", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True, key="up_i")
            if ups and st.button("Importar imagens"):
                for u in ups:
                    tmp = os.path.join(tempfile.gettempdir(), u.name)
                    open(tmp, "wb").write(u.getvalue())
                    try:
                        t = core.importar_imagem(tmp)
                        st.success(f"Use {t} no nome.")
                    except Exception as e:
                        st.error(f"{u.name}: {e}")
                st.cache_data.clear()

# ============================== VISUALIZAÇÃO 3D (direita)
with col_dir:
    if not linhas:
        st.info("Adicione um nome na tabela à esquerda.")
    else:
        try:
            pecas_geo, info_nomes, erros = {}, {}, []
            for l in linhas:
                texto = texto_de(l)
                pp = params_de(l["Fonte"], l["Furo"])
                k = core.chave(texto, pp)
                if k not in pecas_geo:
                    try:
                        dim, objs = partes_prev(texto, json.dumps(asdict(pp)))
                        pecas_geo[k] = (None, None, dim, objs)
                        info_nomes[k] = l["Nome"]
                    except Exception as e:
                        erros.append(f"{l['Nome']}: {e}")
            for e in erros:
                st.warning(e)
            if pecas_geo:
                fila = []
                for l in linhas:
                    k = core.chave(texto_de(l), params_de(l["Fonte"], l["Furo"]))
                    if k in pecas_geo:
                        fila += [k] * l["Qtd"]
                fila = fila[:60]
                prato = core.empacotar(fila, {k: g[:3] for k, g in pecas_geo.items()})[0]
                cores = [st.session_state["cor_a"], st.session_state["cor_b"]]
                objs_cena = []
                for k, x, y in prato:
                    for o in pecas_geo[k][3]:
                        c = dict(o)
                        c["x"], c["y"] = float(x), float(y)
                        c["cor"] = cores[o["idx"]] if MODOS[st.session_state["modo"]] == "cores" else cores[0]
                        objs_cena.append(c)
                components.html(viz.html_visualizador(objs_cena, (256, 256), cores[0], 760, "escuro"), height=780)
                a1, a2, a3, a4 = st.columns(4)
                nomes_unicos = sorted({info_nomes[k] for k in pecas_geo})
                a1.metric("Nomes", len(nomes_unicos))
                a2.metric("Peças no prato", len(prato))
                d0 = pecas_geo[prato[0][0]][2]
                a3.metric("1ª peça (mm)", f"{d0[0]:.0f} × {d0[1]:.0f} × {d0[2]:.0f}")
                a4.metric("Prévia", "rápida", help="Resolução reduzida; o arquivo final usa a qualidade escolhida.")
        except Exception as e:
            st.error(f"Não consegui montar a visualização: {e}")

    if res:
        with st.expander("Arquivos gerados", expanded=False):
            for i, a in enumerate(res["arqs"]):
                st.download_button(f"⬇️ Prato {i + 1} (.3mf)", open(a, "rb").read(), os.path.basename(a), key=f"dl{i}")
            st.caption("Modo 'Cores alternadas': no Bambu Studio, atribua os filamentos às partes 'cor A' e 'cor B'.")
