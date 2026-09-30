"""Ponteiras de Nomes — versão web (Streamlit) para a Bambu Lab P1S.

Rodar localmente:   streamlit run app_web.py
No Render:          veja README_WEB.md (render.yaml já está pronto)
"""
import io
import json
import os
import tempfile
import time
import uuid
import zipfile
from dataclasses import asdict

os.environ.setdefault("PONTEIRAS_MESHER", "skimage")          # o servidor não tem Blender: malha por marching cubes

import base64

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw, ImageFont

import ponteiras_core as core
from web_util import supabase_util as sb
from web_util import visualizador3d as viz

st.set_page_config(page_title="Ponteiras de Nomes", page_icon="✏️", layout="wide", initial_sidebar_state="expanded")

PADRAO = "(padrão)"
NENHUM = "(nenhum)"
ESTILOS = {"Fechada (sólida)": "fechada", "Vazada (só o contorno)": "vazada", "Com base / borda em degrau": "base"}
SAIDA = os.path.join(core.HERE, "saida")

# ----------------------------------------------------------------------------- visual moderno
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], .stMarkdown, button, input, textarea, select { font-family: 'Inter', 'Segoe UI', sans-serif !important; }
.block-container { padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1500px; }
header[data-testid="stHeader"] { background: transparent; }
.hero { background: linear-gradient(120deg, #6c4dff 0%, #8f6bff 45%, #ff8a1f 130%); border-radius: 22px; padding: 26px 32px; color: #fff;
        box-shadow: 0 10px 30px rgba(108,77,255,.25); margin-bottom: 18px; }
.hero h1 { margin: 0; font-size: 2.05rem; font-weight: 800; letter-spacing: -.02em; color: #fff; }
.hero p { margin: 6px 0 0; font-size: 1.02rem; opacity: .92; color: #fff; }
.hero .chips { margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap; }
.hero .chip { background: rgba(255,255,255,.18); border: 1px solid rgba(255,255,255,.3); padding: 4px 12px; border-radius: 999px; font-size: .8rem; font-weight: 600; }
.card { background: #fff; border-radius: 18px; padding: 16px 18px; box-shadow: 0 2px 14px rgba(40,50,90,.08); border: 1px solid #eceff8; }
div[data-testid="stTabs"] button[role="tab"] { border-radius: 12px 12px 0 0; font-weight: 600; padding: 10px 16px; }
div[data-testid="stTabs"] button[aria-selected="true"] { color: #6c4dff; }
.stButton > button, .stDownloadButton > button { border-radius: 12px; font-weight: 700; border: 1px solid #d9def0; transition: all .15s ease; }
.stButton > button:hover, .stDownloadButton > button:hover { border-color: #6c4dff; color: #6c4dff; transform: translateY(-1px); }
.stButton > button[kind="primary"] { background: linear-gradient(120deg, #6c4dff, #8f6bff); color: #fff; border: 0; box-shadow: 0 6px 16px rgba(108,77,255,.35); }
.stButton > button[kind="primary"]:hover { color: #fff; filter: brightness(1.06); }
div[data-testid="stMetric"] { background: #fff; border: 1px solid #eceff8; border-radius: 16px; padding: 12px 16px; box-shadow: 0 2px 10px rgba(40,50,90,.06); }
section[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #eceff8; }
section[data-testid="stSidebar"] div[data-testid="stExpander"] { border: 1px solid #eceff8; border-radius: 14px; background: #fafbff; }
div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] { border-radius: 14px; overflow: hidden; }
.dica { color: #6b7490; font-size: .86rem; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

st.markdown(
    """<div class="hero"><h1>✏️ Ponteiras de Nomes</h1>
    <p>Topos de lápis com o nome, letras fundidas numa peça só e furo sob medida. Pronto para imprimir na Bambu Lab P1S.</p>
    <div class="chips"><span class="chip">3MF para o Bambu Studio</span><span class="chip">Furo circular · hexagonal · triangular</span>
    <span class="chip">Símbolos e imagens no nome</span><span class="chip">Prévia 3D</span></div></div>""",
    unsafe_allow_html=True)

# ----------------------------------------------------------------------------- senha opcional
senha = os.environ.get("APP_PASSWORD", "")
if senha and not st.session_state.get("_ok"):
    st.markdown("<div class='card'>🔒 <b>Acesso restrito</b></div>", unsafe_allow_html=True)
    tent = st.text_input("Senha", type="password")
    if tent and tent == senha:
        st.session_state["_ok"] = True
        st.rerun()
    elif tent:
        st.error("Senha incorreta.")
    st.stop()

# ----------------------------------------------------------------------------- dados (fontes, enfeites)
if sb.configurado() and not st.session_state.get("_sync"):
    st.session_state["_sync"] = True
    try:
        sb.sincronizar_assets(core.FONTES_IMPORTADAS, core.IMAGENS_DIR)
    except Exception:
        pass


@st.cache_data(show_spinner=False)
def carregar_fontes(_v=0):
    fontes = core.listar_fontes()
    grupos = core.listar_fontes_agrupadas()
    return fontes, grupos, dict(core.INFO_FONTE)


def recarregar_tudo():
    st.cache_data.clear()


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
    "altura": 11.5, "espessura": 10.9, "raio": 2.2, "engrossar": 0.45, "largura": 0.72, "espaco": -0.6, "ponte": 2.4,
    "maiusculas": True, "base_arredondada": False, "estilo": list(ESTILOS)[0], "borda": 1.6, "fundo": 1.0, "altura_borda": 4.0,
    "tipo_lapis": list(core.PRESETS_LAPIS)[0], "furo_formato": "Circular", "furo": 8.0, "furo_folga": 0.0, "furo_rot": 0.0,
    "furo_canto": 1.2, "qualidade": "Normal", "enf_antes": NENHUM, "enf_depois": NENHUM,
    "fonte": next((k for k in FONTES if k.lower().startswith("arial rounded") or k.lower().startswith("poppins extra")), next(iter(FONTES))),
}
for k, v in DEF.items():
    st.session_state.setdefault(k, v)
if "sid" not in st.session_state:
    st.session_state.sid = uuid.uuid4().hex[:8]
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame([
        {"Nome": "Helena", "Qtd": 2, "Fonte": PADRAO, "Furo": PADRAO, "Antes": PADRAO, "Depois": PADRAO},
        {"Nome": "Ana :coracao: Clara", "Qtd": 1, "Fonte": PADRAO, "Furo": PADRAO, "Antes": PADRAO, "Depois": PADRAO},
    ])


# ----------------------------------------------------------------------------- funções
@st.cache_data(show_spinner=False)
def amostra_uri(caminho, nome, h=30):
    """Nome da fonte escrito com a própria fonte (imagem em data URI)."""
    try:
        ft = ImageFont.truetype(caminho, h)
        texto = nome if core._tem_glifo(ft, "A") else "❤ ✿ ★ ☺ ♪"
        bb = ft.getbbox(texto)
        im = Image.new("RGB", (max(40, bb[2] + 16), h + 16), "white")
        ImageDraw.Draw(im).text((6, 4 - min(0, bb[1])), texto, font=ft, fill=(25, 30, 50))
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
        base_arredondada=bool(s["base_arredondada"]), maiusculas=bool(s["maiusculas"]), estilo=ESTILOS[s["estilo"]],
        borda=float(s["borda"]), fundo=float(s["fundo"]), altura_borda=float(s["altura_borda"]),
        furo_formato=core.FORMATOS_FURO[fmt_nome][0],
        furo=(core.FORMATOS_FURO[furo_nome][1] if furo_nome in core.FORMATOS_FURO else float(s["furo"])),
        furo_folga=float(s["furo_folga"]), furo_rot=float(s["furo_rot"]), furo_canto=float(s["furo_canto"]),
        voxel=core.QUALIDADE[s["qualidade"]])


def token(rotulo, chave_global):
    r = st.session_state[chave_global] if rotulo in (PADRAO, "", None) else rotulo
    return ENF.get(r, "")


def texto_de(linha):
    nome = str(linha["Nome"]).strip()
    if st.session_state["maiusculas"]:
        nome = nome.upper()
    return core.compor_nome(nome, token(linha["Antes"], "enf_antes"), token(linha["Depois"], "enf_depois"))


def linhas_validas(df):
    out = []
    for _, r in df.iterrows():
        if isinstance(r["Nome"], str) and r["Nome"].strip():
            out.append({"Nome": r["Nome"].strip(), "Qtd": int(r["Qtd"]) if pd.notna(r["Qtd"]) else 1,
                        "Fonte": r["Fonte"] if pd.notna(r["Fonte"]) else PADRAO, "Furo": r["Furo"] if pd.notna(r["Furo"]) else PADRAO,
                        "Antes": r["Antes"] if pd.notna(r["Antes"]) else PADRAO, "Depois": r["Depois"] if pd.notna(r["Depois"]) else PADRAO})
    return out


AJUSTES_SALVAVEIS = list(DEF)


def ajustes_atuais():
    return {k: st.session_state[k] for k in AJUSTES_SALVAVEIS}


def aplicar_ajustes(aj):
    for k, v in aj.items():
        if k in DEF and (k != "fonte" or v in FONTES):
            st.session_state[k] = v


# callbacks
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
        st.session_state["_msg"] = "Ajustes sugeridos aplicados para essa fonte."
    else:
        st.session_state["_msg"] = "Sem sugestão específica para essa fonte; ajuste pela prévia."


def _cb_galeria():
    sel = st.session_state.get("galeria")
    if sel and sel.selection.rows:
        nomes = st.session_state.get("_galeria_nomes", [])
        i = sel.selection.rows[0]
        if i < len(nomes):
            st.session_state["fonte"] = nomes[i]


# ----------------------------------------------------------------------------- barra lateral (ajustes)
with st.sidebar:
    st.markdown("### ⚙️ Configurações")
    if st.session_state.get("_msg"):
        st.success(st.session_state.pop("_msg"))

    with st.expander("🔤 Fonte padrão", expanded=True):
        st.selectbox("Fonte", list(FONTES), key="fonte", format_func=lambda n: f"{ROTULO_GRUPO.get(n, 'Padrão')} · {n}",
                     help="Digite para buscar. Especiais (★) são as de tema; as demais são padrão.")
        uri = amostra_uri(FONTES[st.session_state["fonte"]], st.session_state["fonte"], 34)
        if uri:
            st.markdown(f"<div class='card' style='padding:8px 12px'><img src='{uri}' style='max-width:100%'></div>", unsafe_allow_html=True)
        st.button("✨ Sugerir ajustes p/ esta fonte", on_click=_cb_sugerir, width="stretch")

    with st.expander("📐 Tamanho e formato (mm)"):
        st.slider("Altura da letra", 6.0, 30.0, step=0.5, key="altura")
        st.slider("Espessura da peça", 4.0, 20.0, step=0.1, key="espessura")
        st.slider("Arredondado da borda", 0.4, 5.0, step=0.1, key="raio")
        st.slider("Engrossar traço", 0.0, 2.0, step=0.05, key="engrossar")
        st.slider("Largura das letras (×)", 0.4, 1.5, step=0.02, key="largura")
        st.slider("Espaço entre letras", -3.0, 3.0, step=0.1, key="espaco")
        st.slider("Largura das pontes", 1.0, 5.0, step=0.1, key="ponte")
        st.checkbox("Converter o nome para MAIÚSCULAS (recomendado)", key="maiusculas")
        st.checkbox("Arredondar também a base (evite)", key="base_arredondada")

    with st.expander("🎨 Estilo da letra"):
        st.selectbox("Estilo", list(ESTILOS), key="estilo")
        est = ESTILOS[st.session_state["estilo"]]
        if est == "vazada":
            st.slider("Espessura da borda", 0.8, 6.0, step=0.1, key="borda")
            st.slider("Fundo da letra vazada", 0.0, 4.0, step=0.1, key="fundo")
            st.caption("Só o contorno fica. Fundo 0 = vazada de lado a lado; com fundo vira bandeja. Pontes ligam os anéis soltos.")
        elif est == "base":
            st.slider("Largura da borda", 0.8, 6.0, step=0.1, key="borda")
            st.slider("Altura da borda (degrau)", 1.0, 10.0, step=0.5, key="altura_borda")
            st.caption("Borda mais baixa em volta das letras; também reforça a ligação entre elas.")
        else:
            st.caption("Letra sólida, arredondada no topo.")

    with st.expander("🔩 Furo do lápis"):
        st.selectbox("Tipo de lápis", list(core.PRESETS_LAPIS), key="tipo_lapis", on_change=_cb_tipo)
        st.selectbox("Formato", list(core.FORMATOS_FURO), key="furo_formato", on_change=_cb_formato)
        st.slider("Medida do furo (mm)", 4.0, 14.0, step=0.05, key="furo",
                  help="Circular: diâmetro · Hexagonal: entre faces · Triangular: altura")
        st.slider("Folga extra (mm)", 0.0, 1.0, step=0.05, key="furo_folga")
        st.slider("Girar furo (graus)", -180.0, 180.0, step=15.0, key="furo_rot")
        if core.FORMATOS_FURO[st.session_state["furo_formato"]][0] == "triangular":
            st.slider("Canto do triângulo (mm)", 0.2, 3.0, step=0.1, key="furo_canto")

    with st.expander("✨ Enfeites em todos os nomes"):
        st.selectbox("Antes do nome", ROTULOS_ENFEITE, key="enf_antes")
        st.selectbox("Depois do nome", ROTULOS_ENFEITE, key="enf_depois")
        st.caption("Ex.: coração antes e depois. No meio do nome, digite :coracao: (veja a aba Ferramentas).")

    with st.expander("⚡ Qualidade"):
        st.selectbox("Resolução da malha", list(core.QUALIDADE), key="qualidade")

    if sb.configurado():
        with st.expander("☁️ Predefinições (nuvem)"):
            nome_p = st.text_input("Nome da predefinição", key="nome_predef")
            if st.button("Salvar ajustes atuais", width="stretch") and nome_p.strip():
                try:
                    sb.salvar_predefinicao(nome_p.strip(), ajustes_atuais())
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
                if c1.button("Carregar", width="stretch"):
                    aplicar_ajustes(next(p["ajustes"] for p in preds if p["nome"] == esc))
                    st.rerun()
                if c2.button("Apagar", width="stretch"):
                    sb.apagar_predefinicao(esc)
                    st.rerun()

# ----------------------------------------------------------------------------- abas
aba_nomes, aba_3d, aba_gerar, aba_ferr, aba_hist = st.tabs(["✍️ Nomes", "🧊 Prévia 3D", "📦 Gerar pedido", "🧰 Ferramentas", "☁️ Histórico"])

# ============================== NOMES
with aba_nomes:
    st.markdown("**Nomes e quantidades** · edite direto na tabela (adicione linhas no fim)")
    cfg = {
        "Nome": st.column_config.TextColumn("Nome", required=True, help="Pode ter símbolos no meio: ANA :coracao: CLARA"),
        "Qtd": st.column_config.NumberColumn("Qtd", min_value=1, max_value=500, step=1, default=1, width="small"),
        "Fonte": st.column_config.SelectboxColumn("Fonte", options=[PADRAO] + list(FONTES), default=PADRAO),
        "Furo": st.column_config.SelectboxColumn("Furo do lápis", options=[PADRAO] + list(core.FORMATOS_FURO), default=PADRAO),
        "Antes": st.column_config.SelectboxColumn("Enfeite antes", options=[PADRAO] + ROTULOS_ENFEITE, default=PADRAO),
        "Depois": st.column_config.SelectboxColumn("Enfeite depois", options=[PADRAO] + ROTULOS_ENFEITE, default=PADRAO),
    }
    editado = st.data_editor(st.session_state.df, column_config=cfg, num_rows="dynamic", width="stretch", key="editor", hide_index=True)
    st.session_state.df = editado
    linhas = linhas_validas(editado)
    total = sum(l["Qtd"] for l in linhas)
    m1, m2, m3 = st.columns(3)
    m1.metric("Nomes", len(linhas))
    m2.metric("Peças no total", total)
    m3.metric("Fonte padrão", st.session_state["fonte"][:22])

    st.markdown("#### Prévia")
    if not linhas:
        st.info("Adicione um nome na tabela acima.")
    else:
        idx = st.selectbox("Nome", range(len(linhas)), format_func=lambda i: linhas[i]["Nome"], key="idx_prev", label_visibility="collapsed")
        linha = linhas[idx]
        try:
            pp = params_de(linha["Fonte"], linha["Furo"])
            img, (w, h) = core.previa(texto_de(linha), pp, largura=900)
            yl = core.furo_limites(pp)
            c_img, c_corte = st.columns([4, 1])
            with c_img:
                st.image(img, width="stretch")
            with c_corte:
                st.image(core.previa_corte(pp, h), caption="Corte (vista de ponta)", width="stretch")
            a1, a2, a3 = st.columns(3)
            a1.metric("Tamanho (mm)", f"{w:.1f} × {h:.1f}")
            a2.metric("Espessura (mm)", f"{pp.espessura:.1f}")
            a3.metric("Furo (larg. × alt., mm)", f"{yl[1] - yl[0]:.1f} × {yl[3] - yl[2]:.1f}")
            if (h - (yl[1] - yl[0])) / 2 < 0.8 or pp.espessura - (core.furo_centro_z(pp) + yl[3]) < 0.8:
                st.warning("O furo não cabe com parede segura: aumente a altura/espessura ou reduza o furo.")
            st.caption("Linhas azuis = furo do lápis. Laranja escuro = fundo (letra vazada); laranja claro = borda em degrau.")
        except Exception as e:
            st.error(f"Prévia indisponível: {e}")

# ============================== PRÉVIA 3D
with aba_3d:
    st.markdown("**Prévia 3D interativa** · arraste para girar, role para aproximar")
    if not linhas:
        st.info("Adicione um nome na aba Nomes.")
    else:
        c1, c2 = st.columns([3, 1])
        i3 = c1.selectbox("Nome", range(len(linhas)), format_func=lambda i: linhas[i]["Nome"], key="idx_3d")
        cor = c2.color_picker("Cor do filamento", "#ff8a1f", key="cor3d")
        linha = linhas[i3]

        @st.cache_data(show_spinner="Montando o modelo 3D...", max_entries=40)
        def prev3d(texto, pjson):
            p = core.Params(**json.loads(pjson))
            v, f = core.malha_rapida(texto, p)
            return viz.dados_malhas([(texto, v, f, (0, 0))], alvo_tris=12000)

        try:
            pp = params_de(linha["Fonte"], linha["Furo"])
            objs = prev3d(texto_de(linha), json.dumps(asdict(pp)))
            components.html(viz.html_visualizador(objs, None, cor, 560), height=580)
            st.caption("Prévia rápida (resolução reduzida). A malha final, com a resolução escolhida, sai na aba Gerar pedido.")
        except Exception as e:
            st.error(f"Não consegui montar o 3D: {e}")

# ============================== GERAR
with aba_gerar:
    st.markdown("**Gerar os arquivos para o Bambu Studio**")
    if not linhas:
        st.info("Adicione nomes na aba Nomes.")
    else:
        resumo = pd.DataFrame([{"Nome": l["Nome"], "Qtd": l["Qtd"], "Fonte": l["Fonte"], "Furo": l["Furo"]} for l in linhas])
        st.dataframe(resumo, width="stretch", hide_index=True)
        st.caption(f"Saída: 3MF com perfil P1S 0.4 + PLA + Textured PEI · pratos de 256 × 256 mm · qualidade **{st.session_state['qualidade']}**.")
        gerar = st.button("🚀 Gerar pratos 3MF", type="primary", width="stretch")
        if gerar:
            try:
                itens = [(texto_de(l), l["Qtd"], params_de(l["Fonte"], l["Furo"]), l["Nome"]) for l in linhas]
            except Exception as e:
                st.error(str(e))
                itens = None
            if itens:
                pasta = os.path.join(SAIDA, "web", st.session_state.sid, "pedido_" + time.strftime("%Y-%m-%d_%H%M%S"))
                det = {}
                with st.status("Gerando as peças...", expanded=True) as status:
                    try:
                        arqs = core.gerar_tudo(itens, SAIDA, log=lambda m: st.write(m), pasta_pedido=pasta, detalhes=det)
                        status.update(label="Pronto!", state="complete")
                        st.write("Montando a vista 3D dos pratos...")
                        viewer = []
                        for pr in det["pratos"]:
                            pecas = [(det["rotulo"][k], det["geo"][k][0], det["geo"][k][1], (x, y)) for k, x, y in pr]
                            viewer.append(viz.dados_malhas(pecas, alvo_tris=7000))
                        st.session_state["resultado"] = {"arqs": arqs, "det": det, "pasta": pasta, "viewer": viewer}
                    except Exception as e:
                        status.update(label="Erro", state="error")
                        st.error(str(e))

        res = st.session_state.get("resultado")
        if res:
            det, arqs = res["det"], res["arqs"]
            geo, rotulo, pratos = det["geo"], det["rotulo"], det["pratos"]
            vol = {k: float(np.einsum("ij,ij->i", g[0][g[1]][:, 0], np.cross(g[0][g[1]][:, 1], g[0][g[1]][:, 2])).sum() / 6) for k, g in geo.items()}
            total_mm3 = sum(vol[k] for pr in pratos for k, _, _ in pr)
            st.success("Arquivos gerados. Baixe abaixo e abra no Bambu Studio.")
            k1, k2, k3 = st.columns(3)
            k1.metric("Pratos", len(arqs))
            k2.metric("Peças", sum(len(pr) for pr in pratos))
            k3.metric("PLA se 100% sólido", f"{total_mm3 / 1000 * 1.24:.0f} g", help="Limite superior; com preenchimento normal gasta bem menos.")

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for a in arqs:
                    z.write(a, os.path.basename(a))
                for k in geo:
                    arq = os.path.join(det["stl"], k + ".stl")
                    if os.path.exists(arq):
                        z.write(arq, "stl/" + os.path.basename(arq))
            st.download_button("⬇️ Baixar tudo (.zip: 3MF + STL)", buf.getvalue(), "ponteiras.zip", "application/zip", width="stretch")

            tabs = st.tabs([f"Prato {i + 1}" for i in range(len(arqs))])
            for i, (tab, arq, pr) in enumerate(zip(tabs, arqs, pratos)):
                with tab:
                    cA, cB = st.columns([1, 3])
                    with cA:
                        st.download_button(f"⬇️ Prato {i + 1} (.3mf)", open(arq, "rb").read(), os.path.basename(arq), width="stretch", key=f"dl{i}")
                        st.caption(f"{len(pr)} peça(s)")
                        for nome_ in sorted({rotulo[k] for k, _, _ in pr}):
                            st.write("• " + nome_)
                    with cB:
                        components.html(viz.html_visualizador(res["viewer"][i], (256, 256), st.session_state.get("cor3d", "#ff8a1f"), 560), height=580)

            if sb.configurado():
                if st.button("☁️ Salvar este pedido na nuvem (Supabase)"):
                    try:
                        nome_pedido = "Pedido " + time.strftime("%d/%m/%Y %H:%M")
                        sb.enviar_arquivo(sb.BUCKET_ARQUIVOS, f"{st.session_state.sid}/{int(time.time())}.zip", buf.getvalue(), "application/zip")
                        sb.salvar_pedido(nome_pedido, linhas, ajustes_atuais())
                        st.success("Pedido salvo no histórico.")
                    except Exception as e:
                        st.error(str(e))

# ============================== FERRAMENTAS
with aba_ferr:
    f1, f2 = st.columns(2)
    with f1:
        st.markdown("#### 🔁 Trocar letra por símbolo")
        nome_t = st.text_input("Nome", "LOVE", key="tr_nome")
        letras = core.letras_do_texto(nome_t)
        if letras:
            l1, l2, l3 = st.columns(3)
            letra = l1.selectbox("Letra", letras, key="tr_letra")
            qual = l2.selectbox("Ocorrência", ["Todas", "Primeira", "Última"], key="tr_qual")
            por = l3.selectbox("Trocar por", [r for r in ROTULOS_ENFEITE if ENF[r]], key="tr_por")
            novo = core.trocar_letra(nome_t, letra, ENF[por], {"Todas": "todas", "Primeira": "primeira", "Última": "ultima"}[qual])
            st.code(novo)
            if st.button("Adicionar à tabela de nomes", key="tr_add"):
                st.session_state.df = pd.concat([st.session_state.df, pd.DataFrame([{"Nome": novo, "Qtd": 1, "Fonte": PADRAO, "Furo": PADRAO,
                                                                                     "Antes": PADRAO, "Depois": PADRAO}])], ignore_index=True)
                st.rerun()
        st.markdown("#### 📥 Importar fontes e imagens")
        ups = st.file_uploader("Fontes (.ttf / .otf)", type=["ttf", "otf"], accept_multiple_files=True, key="up_fontes")
        if ups and st.button("Importar fontes", key="bt_fontes"):
            for u in ups:
                tmp = os.path.join(tempfile.gettempdir(), u.name)
                open(tmp, "wb").write(u.getvalue())
                try:
                    nome = core.importar_fonte(tmp)
                    if sb.configurado():
                        sb.enviar_arquivo(sb.BUCKET_ASSETS, "fontes/" + u.name, u.getvalue())
                    st.success(f"Fonte importada: {nome}")
                except Exception as e:
                    st.error(f"{u.name}: {e}")
            recarregar_tudo()
            st.rerun()
        ups = st.file_uploader("Imagens (PNG/JPG) para usar no nome", type=["png", "jpg", "jpeg", "bmp", "gif", "webp"], accept_multiple_files=True, key="up_imgs")
        if ups and st.button("Importar imagens", key="bt_imgs"):
            toks = []
            for u in ups:
                tmp = os.path.join(tempfile.gettempdir(), u.name)
                open(tmp, "wb").write(u.getvalue())
                try:
                    t = core.importar_imagem(tmp)
                    toks.append(t)
                    if sb.configurado():
                        sb.enviar_arquivo(sb.BUCKET_ASSETS, "imagens/" + t.strip(":") + ".png", open(os.path.join(core.IMAGENS_DIR, t.strip(":") + ".png"), "rb").read())
                except Exception as e:
                    st.error(f"{u.name}: {e}")
            if toks:
                st.success("Imagens importadas: " + ", ".join(toks))
                recarregar_tudo()
                st.rerun()
    with f2:
        st.markdown("#### 🔩 Gabarito de teste do furo")
        st.caption("Barra de 5 mm com furos de medidas próximas à atual (−0,6 a +0,6 mm). O furo onde o seu lápis entra com leve atrito é a medida certa.")
        if st.button("Gerar gabarito", key="bt_gab"):
            try:
                pp = params_de()
                meds = [round(pp.furo + d, 2) for d in (-0.6, -0.4, -0.2, 0.0, 0.2, 0.4, 0.6)]
                pasta = os.path.join(SAIDA, "web", st.session_state.sid, "gabarito_" + time.strftime("%H%M%S"))
                os.makedirs(pasta, exist_ok=True)
                with st.spinner("Gerando o gabarito..."):
                    arq = core.gerar_gabarito(pp.furo_formato, meds, pasta, folga=pp.furo_folga, rot=pp.furo_rot, canto=pp.furo_canto)
                st.session_state["gabarito"] = (arq, meds, pp.furo_formato)
            except Exception as e:
                st.error(str(e))
        g = st.session_state.get("gabarito")
        if g:
            arq, meds, fmt = g
            st.success(f"Gabarito {fmt}: furos de {', '.join(f'{m:g}' for m in meds)} mm (esquerda → direita; o canto chanfrado marca o menor).")
            st.download_button("⬇️ Baixar gabarito (.3mf)", open(arq, "rb").read(), os.path.basename(arq))
        st.markdown("#### 🌸 Símbolos prontos")
        st.caption("Digite o código no nome, em qualquer ponto: início, meio, fim ou no lugar de uma letra.")
        cols = st.columns(6)
        for i, (tok, gl) in enumerate(core.ATALHOS.items()):
            with cols[i % 6]:
                im = Image.new("RGB", (48, 48), "white")
                for c in core._fontes_reserva():
                    ft = ImageFont.truetype(c, 36)
                    if core._tem_glifo(ft, gl):
                        bb = ft.getbbox(gl)
                        ImageDraw.Draw(im).text(((48 - (bb[2] - bb[0])) / 2 - bb[0], (48 - (bb[3] - bb[1])) / 2 - bb[1]), gl, font=ft, fill=(30, 30, 30))
                        break
                st.image(im, width=48)
                st.code(tok, language=None)
        imgs = core.listar_imagens()
        if imgs:
            st.markdown("#### 🖼️ Suas imagens")
            cols = st.columns(6)
            for i, (n, pth) in enumerate(imgs.items()):
                with cols[i % 6]:
                    im = Image.open(pth).convert("RGBA")
                    fundo = Image.new("RGBA", im.size, "white")
                    fundo.alpha_composite(im)
                    fundo.thumbnail((64, 64))
                    st.image(fundo.convert("RGB"), width=56)
                    st.code(f":{n}:", language=None)

    st.markdown("#### 🖼️ Galeria de fontes")
    filtro = st.text_input("Buscar fonte", key="filtro_galeria", placeholder="ex.: lobster, pixel, bold...")
    nomes_g = [n for n in FONTES if filtro.lower() in n.lower()][:120]
    st.session_state["_galeria_nomes"] = nomes_g
    df_g = pd.DataFrame({"Amostra": [amostra_uri(FONTES[n], n, 28) for n in nomes_g], "Fonte": nomes_g,
                         "Grupo": [ROTULO_GRUPO.get(n, "Padrão") for n in nomes_g]})
    st.dataframe(df_g, width="stretch", hide_index=True, height=380, key="galeria", on_select=_cb_galeria, selection_mode="single-row",
                 column_config={"Amostra": st.column_config.ImageColumn("Amostra", width="large")})
    st.caption("Clique em uma linha para usar a fonte como padrão (mostra até 120; use a busca).")

# ============================== HISTÓRICO
with aba_hist:
    if not sb.configurado():
        st.info("O histórico na nuvem usa o Supabase. Defina SUPABASE_URL e SUPABASE_KEY (veja README_WEB.md) para ativar: pedidos salvos, "
                "predefinições e fontes/imagens que não se perdem quando o servidor reinicia.")
    else:
        try:
            peds = sb.listar_pedidos()
        except Exception as e:
            peds = []
            st.error(str(e))
        if not peds:
            st.write("Nenhum pedido salvo ainda.")
        for p in peds:
            with st.expander(f"{p['nome']} · {len(p['itens'])} nome(s)"):
                st.dataframe(pd.DataFrame(p["itens"]), hide_index=True, width="stretch")
                c1, c2 = st.columns(2)
                if c1.button("Carregar este pedido", key="ld" + p["id"]):
                    st.session_state.df = pd.DataFrame(p["itens"])
                    aplicar_ajustes(p["ajustes"])
                    st.rerun()
                if c2.button("Apagar", key="rm" + p["id"]):
                    sb.apagar_pedido(p["id"])
                    st.rerun()
