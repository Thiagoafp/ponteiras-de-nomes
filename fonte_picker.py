"""Seletor de fonte com grupos (Especiais por tema / Padrão) em que cada opção aparece escrita na própria fonte, com busca.
Fontes instaladas no Windows usam o rótulo nativo; fontes da pasta 'fontes' (não instaladas) são desenhadas como imagem.
API: get() / set() / recarregar(grupos, caminhos)."""
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk

import ponteiras_core as core


class FontePicker(ttk.Frame):
    def __init__(self, master, grupos, caminhos, variable, extra=(), largura=34, tamanho=12):
        super().__init__(master)
        self.var = variable
        self.extra = list(extra)
        self.tamanho = tamanho
        self._popup = None
        self._visivel = False
        self._pronto = False
        self._linhas = []          # [("f", nome, Label) | ("h", titulo, Label)]
        self._refs = []            # referências (Font / PhotoImage) para não serem coletadas
        self._cache_img = {}
        self.btn = tk.Label(self, relief="solid", borderwidth=1, anchor="w", bg="white", padx=6, pady=3, cursor="hand2")
        self.btn.pack(side="left", fill="x", expand=True)
        self.seta = tk.Label(self, text="▾", relief="solid", borderwidth=1, bg="#eee", padx=6, pady=3, cursor="hand2")
        self.seta.pack(side="left")
        for w in (self.btn, self.seta):
            w.bind("<Button-1>", self._abrir)
        self.recarregar(grupos, caminhos, atualizar=False)
        self.var.trace_add("write", lambda *_: self._atualizar_botao())
        self._atualizar_botao()

    # ------------------------------------------------------------------ dados
    def recarregar(self, grupos, caminhos, atualizar=True):
        """Atualiza a lista (ex.: depois de importar uma fonte). grupos = [(título, [nomes])]; caminhos = {nome: arquivo}."""
        self.grupos, self.caminhos = grupos, caminhos
        self._cache_img.clear()
        if self._popup is not None:
            try:
                self._popup.destroy()
            except tk.TclError:
                pass
            self._popup = None
            self._visivel = False
        self._pronto = False
        if atualizar:
            self._atualizar_botao()

    def get(self):
        return self.var.get()

    def set(self, v):
        self.var.set(v)

    # ------------------------------------------------------------------ aparência de cada linha
    def _familia_tk(self, nome):
        fam, sty = core.INFO_FONTE.get(nome, (nome, "Regular"))
        familias = tkfont.families()
        return (fam if fam in familias else (nome if nome in familias else None)), sty

    def _imagem_fonte(self, nome, altura=30):
        """Nome escrito com a própria fonte, desenhado como imagem (para fontes que não estão instaladas no Windows)."""
        if nome in self._cache_img:
            return self._cache_img[nome]
        foto = None
        try:
            ft = ImageFont.truetype(self.caminhos[nome], altura)
            tem_letras = core._tem_glifo(ft, "A")
            texto = nome if tem_letras else "❤ ✿ ★ ☺ ♪"
            if not tem_letras:
                ft = ImageFont.truetype(self.caminhos[nome], altura - 4)
            tam = ft.getbbox(texto)
            im = Image.new("RGB", (max(20, tam[2] + 12), altura + 14), "white")
            ImageDraw.Draw(im).text((4, 2), texto, font=ft, fill=(20, 20, 20))
            foto = ImageTk.PhotoImage(im)
            self._refs.append(foto)
        except Exception:
            foto = None
        self._cache_img[nome] = foto
        return foto

    def _config_rotulo(self, lbl, nome):
        """Escreve o nome no rótulo na própria fonte (nativa ou imagem)."""
        if nome in self.extra:
            f = tkfont.Font(size=self.tamanho - 2)
            self._refs.append(f)
            lbl.config(text=nome, font=f, image="")
            return
        fam, sty = self._familia_tk(nome)
        if fam:
            ls = sty.lower()
            peso = "bold" if any(k in ls for k in ("bold", "black", "heavy", "demi")) else "normal"
            slant = "italic" if any(k in ls for k in ("italic", "oblique")) else "roman"
            f = tkfont.Font(family=fam, size=self.tamanho, weight=peso, slant=slant)
            self._refs.append(f)
            lbl.config(text=nome, font=f, image="")
            return
        foto = self._imagem_fonte(nome)
        if foto is not None:
            lbl.config(image=foto, text="")
        else:
            lbl.config(text=nome)

    def _atualizar_botao(self):
        self._config_rotulo(self.btn, self.var.get())

    # ------------------------------------------------------------------ popup
    def _abrir(self, _=None):
        if self._visivel:
            self._fechar()
            return
        self.update_idletasks()
        x, y = self.winfo_rootx(), self.winfo_rooty() + self.winfo_height()
        w = max(self.winfo_width(), 400)
        if self._popup is None:
            self._criar_popup()
        pop = self._popup
        pop.geometry(f"{w}x380+{x}+{y}")
        pop.deiconify()
        pop.lift()
        self._visivel = True
        self.busca.delete(0, "end")
        self._filtrar()
        self._marcar()
        pop.focus_force()
        self.busca.focus_set()
        self.after(100, self._rolar_ate_selecionado)

    def _criar_popup(self):
        pop = tk.Toplevel(self.winfo_toplevel())
        pop.withdraw()
        pop.overrideredirect(True)
        pop.configure(bg="#888", padx=1, pady=1)
        self._popup = pop
        self.busca = ttk.Entry(pop)
        self.busca.pack(fill="x", padx=2, pady=2)
        self.busca.bind("<KeyRelease>", self._filtrar)
        corpo = ttk.Frame(pop)
        corpo.pack(fill="both", expand=True)
        self.cv = tk.Canvas(corpo, bg="white", highlightthickness=0)
        sb = ttk.Scrollbar(corpo, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.cv.pack(side="left", fill="both", expand=True)
        self.interno = tk.Frame(self.cv, bg="white")
        self._janela = self.cv.create_window((0, 0), window=self.interno, anchor="nw")
        self.interno.bind("<Configure>", lambda e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self.cv.bind("<Configure>", lambda e: self.cv.itemconfigure(self._janela, width=e.width))
        for w in (pop, self.cv, self.interno):
            w.bind("<MouseWheel>", self._roda)
        pop.bind("<Escape>", lambda e: self._fechar())
        pop.bind("<FocusOut>", lambda e: self.after(150, self._perdeu_foco))
        # sequência de linhas: extras (ex.: "(fonte padrão)"), depois cada grupo com seu cabeçalho
        self._seq = [("f", n) for n in self.extra]
        for titulo, nomes in self.grupos:
            if nomes:
                self._seq.append(("h", titulo))
                self._seq += [("f", n) for n in nomes]
        self._linhas = []
        self._construir(0)           # monta aos poucos: a lista abre na hora e vai se completando

    def _construir(self, i):
        if self._popup is None:
            return
        for tipo, val in self._seq[i:i + 20]:
            if tipo == "h":
                lbl = tk.Label(self.interno, text=val, anchor="w", bg="#e8e8e8", fg="#333", padx=8, pady=3,
                               font=tkfont.Font(size=9, weight="bold"))
            else:
                lbl = tk.Label(self.interno, anchor="w", bg="white", padx=8, pady=2)
                self._config_rotulo(lbl, val)
                lbl.bind("<Enter>", lambda e, l=lbl: l.config(bg="#dbe8ff"))
                lbl.bind("<Leave>", lambda e, l=lbl, n=val: l.config(bg="#c5d8ff" if n == self.var.get() else "white"))
                lbl.bind("<Button-1>", lambda e, n=val: self._escolher(n))
            lbl.bind("<MouseWheel>", self._roda)
            self._linhas.append((tipo, val, lbl))
            if self._cabe(tipo, val):
                lbl.pack(fill="x")
        self._marcar()
        if i + 20 < len(self._seq):
            self.after(1, lambda: self._construir(i + 20))
        else:
            self._pronto = True
            self._filtrar()
            self._rolar_ate_selecionado()

    def _termo(self):
        try:
            return self.busca.get().strip().lower()
        except Exception:
            return ""

    def _cabe(self, tipo, val):
        t = self._termo()
        return tipo == "h" or not t or t in val.lower()

    def _marcar(self):
        for tipo, val, l in self._linhas:
            if tipo == "f":
                l.config(bg="#c5d8ff" if val == self.var.get() else "white")

    def _rolar_ate_selecionado(self):
        if self._popup is None or not self._visivel:
            return
        self.update_idletasks()
        for tipo, val, l in self._linhas:
            if tipo == "f" and val == self.var.get() and l.winfo_ismapped():
                total = max(1, self.interno.winfo_height())
                self.cv.yview_moveto(max(0.0, (l.winfo_y() - 150) / total))
                break

    def _filtrar(self, _=None):
        """Mostra só as fontes que combinam com a busca; o cabeçalho de um grupo some se nenhuma fonte dele aparece."""
        for _, _, l in self._linhas:
            l.pack_forget()
        cab, pend = None, []
        for tipo, val, l in self._linhas:
            if tipo == "h":
                cab, pend = l, []
                continue
            if self._cabe(tipo, val):
                if cab is not None and cab not in pend:
                    cab.pack(fill="x")
                    pend.append(cab)
                l.pack(fill="x")
        self.cv.yview_moveto(0)

    def _roda(self, e):
        self.cv.yview_scroll(int(-e.delta / 120) * 3, "units")
        return "break"

    def _perdeu_foco(self):
        if self._popup is None or not self._visivel:
            return
        w = self.focus_get()
        if w is None or not str(w).startswith(str(self._popup)):
            self._fechar()

    def _escolher(self, nome):
        self.var.set(nome)
        self._fechar()

    def _fechar(self):
        if self._popup is not None and self._visivel:
            self._popup.withdraw()
        self._visivel = False
