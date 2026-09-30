"""Gerador de Ponteiras de Nomes - interface gráfica (Bambu Lab P1S).

Nomes e quantidades, fontes (especiais e padrão), estilo da letra (fechada / vazada / com borda), enfeites antes, no meio e
depois do nome (símbolos ou suas imagens), troca de letras por símbolos, furo do lápis (circular / hexagonal / triangular)
e prévia na hora.
Para abrir: duplo clique em Abrir_Gerador.bat  (ou: python ponteiras_gui.py)
"""
import json
import os
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk

import ponteiras_core as core
from fonte_picker import FontePicker

CFG = os.path.join(core.HERE, "config_gui.json")
SAIDA = os.path.join(core.HERE, "saida")
PADRAO = "(padrão)"
NENHUM = "(nenhum)"
ESTILOS = {"Fechada (sólida)": "fechada", "Vazada (só o contorno)": "vazada", "Com base / borda em degrau": "base"}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Gerador de Ponteiras de Nomes — P1S")
        self.geometry("1320x900")
        self.minsize(1150, 760)
        self.q = queue.Queue()
        self._job = None
        self._foto = self._foto2 = None
        self._icones = []
        self._recarregar_dados()
        self.itens = []            # [nome, qtd, fonte, furo, antes, depois]
        v = tk.DoubleVar
        self.var = {
            "fonte": tk.StringVar(), "altura": v(value=11.5), "espessura": v(value=10.9), "raio": v(value=2.2),
            "engrossar": v(value=0.45), "espaco": v(value=-0.6), "largura": v(value=0.72), "ponte": v(value=2.4),
            "estilo": tk.StringVar(value=list(ESTILOS)[0]), "borda": v(value=1.6), "fundo": v(value=1.0), "altura_borda": v(value=4.0),
            "maiusculas": tk.BooleanVar(value=True), "base_arredondada": tk.BooleanVar(value=False),
            "enf_antes": tk.StringVar(value=NENHUM), "enf_depois": tk.StringVar(value=NENHUM),
            "tipo_lapis": tk.StringVar(value=list(core.PRESETS_LAPIS)[0]), "furo_formato": tk.StringVar(value="Circular"),
            "furo": v(value=8.0), "furo_folga": v(value=0.0), "furo_rot": v(value=0.0), "furo_canto": v(value=1.2),
            "qualidade": tk.StringVar(value="Normal"),
        }
        padrao = next((k for k in self.fontes if k.lower().startswith("arial rounded")), next(iter(self.fontes)))
        self.var["fonte"].set(padrao)
        self._carregar()
        self._montar()
        for var in self.var.values():
            var.trace_add("write", lambda *_: self._agendar_previa())
        self._atualizar_estilo()
        self._atualizar_lista()
        self.after(100, self._poll)
        self.after(300, self._previa)

    # ------------------------------------------------------------------ dados
    def _recarregar_dados(self):
        self.fontes = core.listar_fontes()
        self.grupos = core.listar_fontes_agrupadas()
        self.enf = dict(core.opcoes_enfeite())            # rótulo -> token

    # ------------------------------------------------------------------ interface
    def _montar(self):
        pad = {"padx": 6, "pady": 3}
        esq = ttk.Frame(self)
        esq.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        # painel da direita com rolagem (muitos ajustes)
        cont = ttk.Frame(self)
        cont.pack(side="right", fill="y", padx=(0, 8), pady=8)
        self.cv = tk.Canvas(cont, width=400, highlightthickness=0)
        sbar = ttk.Scrollbar(cont, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=sbar.set)
        sbar.pack(side="right", fill="y")
        self.cv.pack(side="left", fill="y")
        dire = ttk.Frame(self.cv)
        self.cv.create_window((0, 0), window=dire, anchor="nw")
        dire.bind("<Configure>", lambda e: self.cv.configure(scrollregion=self.cv.bbox("all")))

        # --- lista de nomes
        ttk.Label(esq, text="Nomes e quantidades", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        cols = ("nome", "qtd", "fonte", "furo", "antes", "depois")
        self.tv = ttk.Treeview(esq, columns=cols, show="headings", height=7, selectmode="browse")
        for c, t, w in (("nome", "Nome", 170), ("qtd", "Qtd", 40), ("fonte", "Fonte", 170), ("furo", "Furo", 110),
                        ("antes", "Antes", 110), ("depois", "Depois", 110)):
            self.tv.heading(c, text=t)
            self.tv.column(c, width=w, anchor="w" if c != "qtd" else "center")
        self.tv.pack(fill="x", pady=4)
        self.tv.bind("<<TreeviewSelect>>", self._selecionou)

        f = ttk.LabelFrame(esq, text="Novo / editar")
        f.pack(fill="x", pady=4)
        ttk.Label(f, text="Nome (pode ter símbolos no meio, ex.: ANA :coracao: CLARA)").grid(row=0, column=0, columnspan=2, sticky="w", **pad)
        ttk.Label(f, text="Fonte (opcional)").grid(row=0, column=2, sticky="w", **pad)
        self.e_nome = ttk.Entry(f, width=34)
        self.e_qtd = ttk.Spinbox(f, from_=1, to=500, width=5)
        self.e_qtd.set(1)
        self.var_fonte_item = tk.StringVar(value=PADRAO)
        self.c_fonte = FontePicker(f, self.grupos, self.fontes, self.var_fonte_item, extra=[PADRAO], tamanho=11)
        self.e_nome.grid(row=1, column=0, **pad)
        self.e_qtd.grid(row=1, column=1, **pad)
        self.c_fonte.grid(row=1, column=2, columnspan=2, sticky="ew", **pad)
        f.columnconfigure(3, weight=1)
        self.e_nome.bind("<Return>", lambda e: self._adicionar())
        ttk.Label(f, text="Furo do lápis").grid(row=2, column=0, sticky="w", **pad)
        ttk.Label(f, text="Enfeite antes").grid(row=2, column=1, columnspan=2, sticky="w", **pad)
        ttk.Label(f, text="Enfeite depois").grid(row=2, column=3, sticky="w", **pad)
        self.c_furo = ttk.Combobox(f, values=[PADRAO] + list(core.FORMATOS_FURO), state="readonly", width=20)
        self.c_furo.set(PADRAO)
        self.c_antes = ttk.Combobox(f, state="readonly", width=24)
        self.c_depois = ttk.Combobox(f, state="readonly", width=24)
        self._atualizar_combos_enfeite()
        self.c_furo.grid(row=3, column=0, **pad)
        self.c_antes.grid(row=3, column=1, columnspan=2, sticky="w", **pad)
        self.c_depois.grid(row=3, column=3, sticky="w", **pad)
        bt = ttk.Frame(f)
        bt.grid(row=4, column=0, columnspan=4, sticky="w", **pad)
        for t, cmd in (("Adicionar", self._adicionar), ("Atualizar selecionado", self._atualizar), ("Remover", self._remover),
                       ("Símbolos e imagens...", self._paleta), ("Trocar letra por símbolo...", self._trocar_letra)):
            ttk.Button(bt, text=t, command=cmd).pack(side="left", padx=2)
        bt2 = ttk.Frame(f)
        bt2.grid(row=5, column=0, columnspan=4, sticky="w", padx=6, pady=(0, 4))
        for t, cmd in (("Adicionar vários...", self._varios), ("Importar lista...", self._importar), ("Limpar tudo", self._limpar)):
            ttk.Button(bt2, text=t, command=cmd).pack(side="left", padx=2)

        # --- prévia
        pv = ttk.LabelFrame(esq, text="Prévia (selecione um nome)")
        pv.pack(fill="both", expand=True, pady=4)
        topo = ttk.Frame(pv)
        topo.pack(fill="both", expand=True)
        self.lbl_prev = ttk.Label(topo, anchor="center")
        self.lbl_prev.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        cf = ttk.Frame(topo)
        cf.pack(side="right", padx=4)
        ttk.Label(cf, text="Corte (vista de ponta)", foreground="#555").pack()
        self.lbl_corte = ttk.Label(cf)
        self.lbl_corte.pack()
        self.lbl_dim = ttk.Label(pv, text="", foreground="#555", wraplength=760, justify="left")
        self.lbl_dim.pack(anchor="w", padx=6, pady=(0, 4))

        # --- ajustes (direita)
        ttk.Label(dire, text="Ajustes", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        pf = ttk.LabelFrame(dire, text="Fonte padrão")
        pf.pack(fill="x", pady=4)
        self.c_fonte_pad = FontePicker(pf, self.grupos, self.fontes, self.var["fonte"], tamanho=13)
        self.c_fonte_pad.pack(fill="x", padx=6, pady=(6, 3))
        rb = ttk.Frame(pf)
        rb.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(rb, text="Importar fonte...", command=self._importar_fonte).pack(side="left")
        ttk.Button(rb, text="Sugerir ajustes p/ esta fonte", command=self._sugerir).pack(side="left", padx=4)

        pe = ttk.LabelFrame(dire, text="Enfeites em todos os nomes (antes / depois)")
        pe.pack(fill="x", pady=4)
        rot = [r for r, _ in core.opcoes_enfeite()]
        self.g_antes = self._combo_linha(pe, "Antes do nome", "enf_antes", rot)
        self.g_depois = self._combo_linha(pe, "Depois do nome", "enf_depois", rot)
        rb2 = ttk.Frame(pe)
        rb2.pack(fill="x", padx=6, pady=(2, 4))
        ttk.Button(rb2, text="Importar imagem (PNG/JPG)...", command=self._importar_imagem).pack(side="left")
        ttk.Label(pe, text="Ex.: coração antes e depois. No meio do nome ou no lugar de uma letra: use 'Símbolos e imagens' / "
                           "'Trocar letra por símbolo' ou digite :coracao: / :nome_da_imagem:",
                  foreground="#666", wraplength=370, justify="left").pack(anchor="w", padx=6, pady=(0, 4))

        ps = ttk.LabelFrame(dire, text="Tamanho e formato (mm)")
        ps.pack(fill="x", pady=4)
        self._slider(ps, "Altura da letra", "altura", 6, 30, 0.5)
        self._slider(ps, "Espessura da peça", "espessura", 4, 20, 0.1)
        self._slider(ps, "Arredondado da borda", "raio", 0.4, 5, 0.1)
        self._slider(ps, "Engrossar traço", "engrossar", 0, 2, 0.05)
        self._slider(ps, "Largura das letras (×)", "largura", 0.4, 1.5, 0.02)
        self._slider(ps, "Espaço entre letras", "espaco", -3, 3, 0.1)
        self._slider(ps, "Largura das pontes", "ponte", 1, 5, 0.1)
        ttk.Checkbutton(ps, text="Converter o nome para MAIÚSCULAS (recomendado)", variable=self.var["maiusculas"]).pack(anchor="w", padx=6, pady=2)
        ttk.Checkbutton(ps, text="Arredondar também a base (evite)", variable=self.var["base_arredondada"]).pack(anchor="w", padx=6, pady=2)

        pst = ttk.LabelFrame(dire, text="Estilo da letra (corpo e borda)")
        pst.pack(fill="x", pady=4)
        fe = ttk.Frame(pst)
        fe.pack(fill="x", padx=6, pady=3)
        ttk.Label(fe, text="Estilo", width=20).pack(side="left")
        ce = ttk.Combobox(fe, textvariable=self.var["estilo"], values=list(ESTILOS), state="readonly", width=26)
        ce.pack(side="right")
        ce.bind("<<ComboboxSelected>>", lambda e: self._atualizar_estilo())
        self.lbl_estilo = ttk.Label(pst, text="", foreground="#666", wraplength=370, justify="left")
        self.lbl_estilo.pack(anchor="w", padx=6, pady=(0, 4))
        self.fr_borda = self._slider(pst, "Espessura da borda", "borda", 0.8, 6, 0.1)
        self.fr_fundo = self._slider(pst, "Fundo da letra vazada", "fundo", 0, 4, 0.1)
        self.fr_altb = self._slider(pst, "Altura da borda (degrau)", "altura_borda", 1, 10, 0.5)

        pl = ttk.LabelFrame(dire, text="Furo do lápis (atravessa o nome)")
        pl.pack(fill="x", pady=4)
        self._combo_linha(pl, "Tipo de lápis", "tipo_lapis", list(core.PRESETS_LAPIS), self._mudou_tipo, 28)
        self._combo_linha(pl, "Formato", "furo_formato", list(core.FORMATOS_FURO), self._mudou_formato, 26)
        self._slider(pl, "Medida do furo", "furo", 4, 12, 0.05)
        self._slider(pl, "Folga extra", "furo_folga", 0, 1, 0.05)
        self._slider(pl, "Girar furo (graus)", "furo_rot", -180, 180, 15)
        self._slider(pl, "Canto do triângulo", "furo_canto", 0.2, 3, 0.1)
        ttk.Label(pl, text="Circular: diâmetro · Hexagonal: entre faces · Triangular: altura", foreground="#666").pack(anchor="w", padx=6)

        pq = ttk.LabelFrame(dire, text="Qualidade (resolução da malha)")
        pq.pack(fill="x", pady=4)
        ttk.Combobox(pq, textvariable=self.var["qualidade"], values=list(core.QUALIDADE), state="readonly", width=30).pack(padx=6, pady=6)

        self.btn = ttk.Button(dire, text="GERAR PRATOS 3MF", command=self._gerar)
        self.btn.pack(fill="x", pady=(10, 4), ipady=8)
        ttk.Button(dire, text="Gerar gabarito de teste do furo", command=self._gabarito).pack(fill="x", pady=(0, 4))
        ttk.Button(dire, text="Abrir pasta de saída", command=lambda: os.startfile(SAIDA) if os.path.isdir(SAIDA) else None).pack(fill="x")
        self.log = tk.Text(dire, height=6, width=46, state="disabled", font=("Consolas", 9))
        self.log.pack(fill="x", pady=6)
        self.prog = ttk.Progressbar(dire, mode="indeterminate")
        self.prog.pack(fill="x", pady=(0, 10))

    def _combo_linha(self, parent, rotulo, chave, valores, ao_escolher=None, largura=32):
        fr = ttk.Frame(parent)
        fr.pack(fill="x", padx=6, pady=3)
        ttk.Label(fr, text=rotulo, width=16).pack(side="left")
        cb = ttk.Combobox(fr, textvariable=self.var[chave], values=valores, state="readonly", width=largura)
        cb.pack(side="right")
        if ao_escolher:
            cb.bind("<<ComboboxSelected>>", ao_escolher)
        return cb

    def _slider(self, parent, rotulo, chave, lo, hi, passo):
        fr = ttk.Frame(parent)
        fr.pack(fill="x", padx=6, pady=2)
        ttk.Label(fr, text=rotulo, width=22).pack(side="left")
        sp = ttk.Spinbox(fr, from_=lo, to=hi, increment=passo, textvariable=self.var[chave], width=7)
        sp.pack(side="right")
        ttk.Scale(fr, from_=lo, to=hi, variable=self.var[chave],
                  command=lambda v, k=chave, p=passo: self.var[k].set(round(round(float(v) / p) * p, 3))).pack(side="right", fill="x", expand=True, padx=6)
        return fr

    def _atualizar_estilo(self):
        est = ESTILOS[self.var["estilo"].get()]
        for fr in (self.fr_borda, self.fr_fundo, self.fr_altb):
            fr.pack_forget()
        dicas = {"fechada": "Letra sólida, arredondada no topo (como no original).",
                 "vazada": "Só o contorno de cada letra fica. 'Fundo' = 0 deixa a letra vazada de lado a lado; com fundo, vira uma bandeja. "
                           "Pontes ligam os anéis soltos (como num estêncil).",
                 "base": "Letras sólidas com uma borda mais baixa em volta (degrau), que também reforça a ligação entre as letras."}
        if est == "vazada":
            self.fr_borda.pack(fill="x", padx=6, pady=2)
            self.fr_fundo.pack(fill="x", padx=6, pady=2)
        elif est == "base":
            self.fr_borda.pack(fill="x", padx=6, pady=2)
            self.fr_altb.pack(fill="x", padx=6, pady=2)
        self.lbl_estilo.config(text=dicas[est])

    def _atualizar_combos_enfeite(self):
        ops = core.opcoes_enfeite()
        self.enf = dict(ops)
        rot = [r for r, _ in ops]
        self.c_antes["values"] = [PADRAO] + rot
        self.c_depois["values"] = [PADRAO] + rot
        if not self.c_antes.get():
            self.c_antes.set(PADRAO)
        if not self.c_depois.get():
            self.c_depois.set(PADRAO)
        if hasattr(self, "g_antes"):
            self.g_antes["values"] = rot
            self.g_depois["values"] = rot

    # ------------------------------------------------------------------ dados / params
    def _token(self, rotulo, global_var):
        """Enfeite efetivo de um item: (padrão) usa o global."""
        r = self.var[global_var].get() if rotulo in (PADRAO, "") else rotulo
        return self.enf.get(r, "")

    def _params(self, fonte_nome=None, furo_nome=None):
        v = self.var
        fn = fonte_nome if fonte_nome and fonte_nome != PADRAO else v["fonte"].get()
        path = self.fontes.get(fn) or core.resolver_fonte(fn)
        fmt_nome = furo_nome if furo_nome in core.FORMATOS_FURO else v["furo_formato"].get()
        return core.Params(
            fonte=path, altura=float(v["altura"].get()), espessura=float(v["espessura"].get()), raio=float(v["raio"].get()),
            engrossar=float(v["engrossar"].get()), espaco=float(v["espaco"].get()), largura=float(v["largura"].get()),
            ponte=float(v["ponte"].get()), base_arredondada=bool(v["base_arredondada"].get()), maiusculas=bool(v["maiusculas"].get()),
            estilo=ESTILOS[v["estilo"].get()], borda=float(v["borda"].get()), fundo=float(v["fundo"].get()),
            altura_borda=float(v["altura_borda"].get()),
            furo_formato=core.FORMATOS_FURO[fmt_nome][0],
            furo=(core.FORMATOS_FURO[furo_nome][1] if furo_nome in core.FORMATOS_FURO else float(v["furo"].get())),
            furo_folga=float(v["furo_folga"].get()), furo_rot=float(v["furo_rot"].get()), furo_canto=float(v["furo_canto"].get()),
            voxel=core.QUALIDADE[v["qualidade"].get()])

    def _texto(self, item):
        nome, _, _, _, antes, depois = item
        return core.compor_nome(nome.upper() if self.var["maiusculas"].get() else nome,
                                self._token(antes, "enf_antes"), self._token(depois, "enf_depois"))

    # ------------------------------------------------------------------ lista
    def _atualizar_lista(self):
        self.tv.delete(*self.tv.get_children())
        for i, it in enumerate(self.itens):
            self.tv.insert("", "end", iid=str(i), values=tuple(it))
        self._salvar()

    def _selecionado(self):
        s = self.tv.selection()
        return int(s[0]) if s else None

    def _selecionou(self, _=None):
        i = self._selecionado()
        if i is None:
            return
        n, q, f, fu, an, de = self.itens[i]
        self.e_nome.delete(0, "end")
        self.e_nome.insert(0, n)
        self.e_qtd.set(q)
        self.var_fonte_item.set(f)
        self.c_furo.set(fu)
        self.c_antes.set(an)
        self.c_depois.set(de)
        self._agendar_previa()

    def _ler_campos(self):
        nome = self.e_nome.get().strip()
        if not nome:
            return None
        try:
            q = max(1, int(self.e_qtd.get()))
        except ValueError:
            q = 1
        return [nome, q, self.var_fonte_item.get() or PADRAO, self.c_furo.get() or PADRAO,
                self.c_antes.get() or PADRAO, self.c_depois.get() or PADRAO]

    def _adicionar(self):
        it = self._ler_campos()
        if it:
            self.itens.append(it)
            self._atualizar_lista()
            self.tv.selection_set(str(len(self.itens) - 1))
            self.e_nome.delete(0, "end")
            self.e_nome.focus()

    def _atualizar(self):
        i, it = self._selecionado(), self._ler_campos()
        if i is not None and it:
            self.itens[i] = it
            self._atualizar_lista()
            self.tv.selection_set(str(i))

    def _remover(self):
        i = self._selecionado()
        if i is not None:
            del self.itens[i]
            self._atualizar_lista()

    def _limpar(self):
        if self.itens and messagebox.askyesno("Limpar", "Remover todos os nomes da lista?"):
            self.itens = []
            self._atualizar_lista()

    @staticmethod
    def _linha(c):
        """c = [nome, qtd, fonte, furo]; furo aceita circular/hexagonal/triangular."""
        fu = PADRAO
        if len(c) > 3 and c[3]:
            for nome, (fmt, _) in core.FORMATOS_FURO.items():
                if c[3].lower().startswith(fmt[:4]) or c[3].lower() == nome.lower():
                    fu = nome
        return [c[0], int(c[1]) if len(c) > 1 and c[1].isdigit() else 1, c[2] if len(c) > 2 and c[2] else PADRAO, fu, PADRAO, PADRAO]

    def _varios(self):
        w = tk.Toplevel(self)
        w.title("Adicionar vários nomes")
        ttk.Label(w, text="Um por linha. Opcional: Nome;Quantidade;Fonte;Furo (circular/hexagonal/triangular)").pack(padx=8, pady=6)
        t = tk.Text(w, width=56, height=16)
        t.pack(padx=8)

        def ok():
            for ln in t.get("1.0", "end").splitlines():
                ln = ln.strip()
                if ln:
                    self.itens.append(self._linha([x.strip() for x in re.split(r"[;\t]", ln)]))
            self._atualizar_lista()
            w.destroy()
        ttk.Button(w, text="Adicionar", command=ok).pack(pady=8)

    def _importar(self):
        p = filedialog.askopenfilename(filetypes=[("Lista", "*.csv *.txt"), ("Todos", "*.*")])
        if not p:
            return
        for ln in open(p, encoding="utf-8-sig"):
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                self.itens.append(self._linha([x.strip() for x in re.split(r"[;\t]", ln)]))
        self._atualizar_lista()

    # ------------------------------------------------------------------ fontes e imagens
    def _recarregar_pickers(self, selecionar=None):
        self._recarregar_dados()
        for pk in (self.c_fonte, self.c_fonte_pad):
            pk.recarregar(self.grupos, self.fontes)
        if selecionar:
            self.var["fonte"].set(selecionar)

    def _importar_fonte(self):
        arqs = filedialog.askopenfilenames(title="Importar fonte", filetypes=[("Fontes", "*.ttf *.otf"), ("Todos", "*.*")])
        nome = None
        for a in arqs:
            try:
                nome = core.importar_fonte(a)
            except ValueError as e:
                messagebox.showerror("Importar fonte", f"{os.path.basename(a)}: {e}")
        if nome:
            self._recarregar_pickers(selecionar=nome)
            self._escrever(f"Fonte importada: {nome} (grupo 'Importadas (suas)')")

    def _importar_imagem(self):
        arqs = filedialog.askopenfilenames(title="Importar imagem (desenho escuro em fundo claro, ou PNG com transparência)",
                                           filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("Todos", "*.*")])
        toks = []
        for a in arqs:
            try:
                toks.append(core.importar_imagem(a))
            except Exception as e:
                messagebox.showerror("Importar imagem", f"{os.path.basename(a)}: {e}")
        if toks:
            self._atualizar_combos_enfeite()
            rot = next((r for r, t in self.enf.items() if t == toks[-1]), NENHUM)
            self.var["enf_antes"].set(rot)
            self.var["enf_depois"].set(rot)
            self._escrever("Imagens importadas: " + ", ".join(toks) + " (aplicadas antes e depois dos nomes; mude em 'Enfeites').")

    def _sugerir(self):
        aj = core.sugerir_ajustes(self.var["fonte"].get())
        if not aj:
            self._escrever("Sem sugestão específica para essa fonte; ajuste pela prévia.")
            return
        for k, val in aj.items():
            self.var[k].set(val)
        self._escrever("Ajustes sugeridos aplicados: " + ", ".join(f"{k}={val}" for k, val in aj.items()))

    def _icone_simbolo(self, glifo, tam=34):
        """Ícone do símbolo desenhado com a fonte de reserva que o tiver."""
        im = Image.new("RGB", (tam, tam), "white")
        for c in core._fontes_reserva():
            ft = ImageFont.truetype(c, int(tam * 0.75))
            if core._tem_glifo(ft, glifo):
                bb = ft.getbbox(glifo)
                ImageDraw.Draw(im).text(((tam - (bb[2] - bb[0])) / 2 - bb[0], (tam - (bb[3] - bb[1])) / 2 - bb[1]),
                                        glifo, font=ft, fill=(30, 30, 30))
                break
        foto = ImageTk.PhotoImage(im)
        self._icones.append(foto)
        return foto

    def _paleta(self):
        """Janela com os símbolos prontos (coração, flor, estrela...) e as imagens importadas: um clique insere no nome."""
        w = tk.Toplevel(self)
        w.title("Símbolos e imagens")
        w.geometry("560x520")
        ttk.Label(w, text="Clique para inserir no campo Nome, no ponto do cursor (início, meio ou fim). "
                          "Também dá para digitar :nome:", wraplength=520).pack(padx=8, pady=6)
        cv = tk.Canvas(w, highlightthickness=0)
        sb = ttk.Scrollbar(w, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        corpo = ttk.Frame(cv)
        cv.create_window((0, 0), window=corpo, anchor="nw")
        corpo.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))

        def inserir(tok):
            self.e_nome.insert("insert", tok)
            self.e_nome.focus()
            self._agendar_previa()
        ttk.Label(corpo, text="Símbolos", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=6, sticky="w", padx=6, pady=4)
        for i, (tok, gl) in enumerate(core.ATALHOS.items()):
            ttk.Button(corpo, image=self._icone_simbolo(gl), text=tok.strip(":"), compound="top",
                       command=lambda t=tok: inserir(t)).grid(row=1 + i // 6, column=i % 6, padx=3, pady=3)
        r0 = 2 + (len(core.ATALHOS) + 5) // 6
        ttk.Label(corpo, text="Suas imagens", font=("Segoe UI", 10, "bold")).grid(row=r0, column=0, columnspan=6, sticky="w", padx=6, pady=4)
        imgs = core.listar_imagens()
        if not imgs:
            ttk.Label(corpo, text="(nenhuma ainda: use 'Importar imagem' em Enfeites)").grid(row=r0 + 1, column=0, columnspan=6, sticky="w", padx=6)
        for i, (nome, path) in enumerate(imgs.items()):
            try:
                im = Image.open(path).convert("RGBA")
                fundo = Image.new("RGBA", im.size, "white")
                fundo.alpha_composite(im)
                fundo = fundo.convert("RGB")
                fundo.thumbnail((40, 40))
                foto = ImageTk.PhotoImage(fundo)
                self._icones.append(foto)
                b = ttk.Button(corpo, image=foto, text=nome, compound="top", command=lambda t=f":{nome}:": inserir(t))
            except Exception:
                b = ttk.Button(corpo, text=nome, command=lambda t=f":{nome}:": inserir(t))
            b.grid(row=r0 + 1 + i // 6, column=i % 6, padx=3, pady=3)

    def _trocar_letra(self):
        """Troca uma letra do nome (todas as ocorrências, a primeira ou a última) por um símbolo ou imagem: L:coracao:VE."""
        nome = self.e_nome.get()
        letras = core.letras_do_texto(nome)
        if not letras:
            messagebox.showinfo("Trocar letra", "Digite o nome no campo Nome primeiro.")
            return
        ops = [r for r, t in core.opcoes_enfeite() if t]
        w = tk.Toplevel(self)
        w.title("Trocar letra por símbolo")
        ttk.Label(w, text=f"Nome: {nome}").grid(row=0, column=0, columnspan=2, padx=8, pady=6, sticky="w")
        ttk.Label(w, text="Letra a trocar").grid(row=1, column=0, padx=8, pady=3, sticky="w")
        vl = tk.StringVar(value=letras[0])
        ttk.Combobox(w, textvariable=vl, values=letras, state="readonly", width=8).grid(row=1, column=1, padx=8, sticky="w")
        ttk.Label(w, text="Qual ocorrência").grid(row=2, column=0, padx=8, pady=3, sticky="w")
        vq = tk.StringVar(value="Todas")
        ttk.Combobox(w, textvariable=vq, values=["Todas", "Primeira", "Última"], state="readonly", width=12).grid(row=2, column=1, padx=8, sticky="w")
        ttk.Label(w, text="Trocar por").grid(row=3, column=0, padx=8, pady=3, sticky="w")
        vp = tk.StringVar(value=ops[0])
        ttk.Combobox(w, textvariable=vp, values=ops, state="readonly", width=28).grid(row=3, column=1, padx=8, sticky="w")

        def ok():
            qual = {"Todas": "todas", "Primeira": "primeira", "Última": "ultima"}[vq.get()]
            novo = core.trocar_letra(self.e_nome.get(), vl.get(), self.enf[vp.get()], qual)
            self.e_nome.delete(0, "end")
            self.e_nome.insert(0, novo)
            self._agendar_previa()
            w.destroy()
        ttk.Button(w, text="Trocar", command=ok).grid(row=4, column=0, columnspan=2, pady=10)

    # ------------------------------------------------------------------ furo
    def _mudou_tipo(self, _=None):
        alt, esp = core.aplicar_preset(self.var["tipo_lapis"].get())
        self.var["altura"].set(alt)
        self.var["espessura"].set(esp)
        self._mudou_formato()

    def _mudou_formato(self, _=None):
        self.var["furo"].set(core.FORMATOS_FURO[self.var["furo_formato"].get()][1])

    def _gabarito(self):
        """Gera a peça de teste de encaixe (furos de medidas próximas à atual) e abre a pasta."""
        try:
            pp = self._params()
        except Exception as e:
            messagebox.showerror("Gabarito", str(e))
            return
        med = [round(pp.furo + d, 2) for d in (-0.6, -0.4, -0.2, 0.0, 0.2, 0.4, 0.6)]
        self.btn.state(["disabled"])
        self.prog.start(12)
        pasta = os.path.join(SAIDA, "gabarito_" + time.strftime("%Y-%m-%d_%H%M%S"))
        os.makedirs(pasta, exist_ok=True)
        self._escrever(f"Gabarito {pp.furo_formato}: furos de {med[0]:g} a {med[-1]:g} mm...")

        def tarefa():
            try:
                core.gerar_gabarito(pp.furo_formato, med, pasta, folga=pp.furo_folga, rot=pp.furo_rot, canto=pp.furo_canto,
                                    log=lambda m: self.q.put(("log", m)))
                self.q.put(("fim", pasta))
            except Exception as e:
                self.q.put(("erro", str(e)))
        threading.Thread(target=tarefa, daemon=True).start()

    # ------------------------------------------------------------------ prévia
    def _agendar_previa(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(350, self._previa)

    def _previa(self):
        self._job = None
        i = self._selecionado()
        if i is not None:
            item = self.itens[i]
        else:
            campos = self._ler_campos()
            item = campos or (self.itens[0] if self.itens else ["Helena", 1, PADRAO, PADRAO, PADRAO, PADRAO])
        try:
            pp = self._params(item[2], item[3])
            img, (w, h) = core.previa(self._texto(item), pp, largura=640)
        except Exception as e:
            self.lbl_dim.config(text=f"Prévia indisponível: {e}")
            return
        self._foto = ImageTk.PhotoImage(img)
        self.lbl_prev.config(image=self._foto)
        extra, aviso = "", ""
        try:
            self._foto2 = ImageTk.PhotoImage(core.previa_corte(pp, h))
            self.lbl_corte.config(image=self._foto2)
            yl = core.furo_limites(pp)
            extra = f" Furo {yl[1] - yl[0]:.1f} × {yl[3] - yl[2]:.1f} mm (larg. × alt.)."
            if (h - (yl[1] - yl[0])) / 2 < 0.8 or pp.espessura - (core.furo_centro_z(pp) + yl[3]) < 0.8:
                aviso = "  ⚠ o furo não cabe com parede segura: aumente a altura/espessura ou reduza o furo"
        except Exception:
            pass
        self.lbl_dim.config(text=f"{item[0]}: {w:.1f} × {h:.1f} mm, espessura {pp.espessura:.1f} mm. "
                                 f"Linhas azuis = furo do lápis.{extra}{aviso}")

    # ------------------------------------------------------------------ gerar
    def _escrever(self, msg):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _gerar(self):
        if not self.itens:
            messagebox.showinfo("Gerar", "Adicione pelo menos um nome.")
            return
        try:
            itens = [(self._texto(it), it[1], self._params(it[2], it[3]), it[0]) for it in self.itens]
        except Exception as e:
            messagebox.showerror("Erro", str(e))
            return
        self.btn.state(["disabled"])
        self.prog.start(12)
        pedido = os.path.join(SAIDA, "pedido_" + time.strftime("%Y-%m-%d_%H%M%S"))
        self._escrever("Iniciando...")

        def tarefa():
            try:
                core.gerar_tudo(itens, SAIDA, log=lambda m: self.q.put(("log", m)), pasta_pedido=pedido)
                self.q.put(("fim", pedido))
            except Exception as e:
                self.q.put(("erro", str(e)))
        threading.Thread(target=tarefa, daemon=True).start()

    def _poll(self):
        try:
            while True:
                k, m = self.q.get_nowait()
                if k == "log":
                    self._escrever(m)
                else:
                    self.prog.stop()
                    self.btn.state(["!disabled"])
                    if k == "fim":
                        self._escrever("Pronto! Pasta: " + m)
                        os.startfile(m)
                    else:
                        self._escrever("ERRO: " + m)
                        messagebox.showerror("Erro", m)
        except queue.Empty:
            pass
        self.after(150, self._poll)

    # ------------------------------------------------------------------ config
    def _salvar(self):
        try:
            d = {"itens": self.itens, "ajustes": {k: v.get() for k, v in self.var.items()}}
            json.dump(d, open(CFG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        except Exception:
            pass

    def _carregar(self):
        try:
            d = json.load(open(CFG, encoding="utf-8"))
            self.itens = [(list(it) + [PADRAO] * 6)[:6] for it in d.get("itens", [])]
            for k, v in d.get("ajustes", {}).items():
                if k in self.var:
                    self.var[k].set(v)
        except Exception:
            pass
        if self.var["fonte"].get() not in self.fontes:
            self.var["fonte"].set(next(iter(self.fontes)))
        if self.var["estilo"].get() not in ESTILOS:
            self.var["estilo"].set(list(ESTILOS)[0])

    def destroy(self):
        self._salvar()
        super().destroy()


if __name__ == "__main__":
    App().mainloop()
