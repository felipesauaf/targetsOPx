# dev.py — OPx Brand UI (dark/light) • botões amarelos
import os, json
import pandas as pd
from datetime import datetime, timedelta

import customtkinter as ctk
from tkinter import ttk

# (opcional) mostrar logo no header, se existir
try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

from jsonExport import dataMondaytoJson


# ==============================
# Aparência / Tema (OPx)
# ==============================
# Paleta OPx
OPX_YELLOW = "#FACC15"   # amarelo principal
OPX_YELLOW_HOVER = "#EAB308"
OPX_TEXT_DARK = "#0B1220"  # texto sobre amarelo (quase preto)

# Cores por modo
THEME = {
    "dark": {
        "bg": "#0B1220",
        "bg2": "#0F172A",
        "fg": "#E5E7EB",
        "muted": "#9CA3AF",
        "row_even": "#0F172A",
        "row_odd":  "#111827",
        "sel_bg": "#1F6AA5",
        "sel_fg": "#FFFFFF",
        "header_bg": "#0F172A",
        "header_fg": "#E5E7EB",
        "border": "#1F2937",
    },
    "light": {
        "bg": "#FFFFFF",
        "bg2": "#F8FAFC",
        "fg": "#0F172A",
        "muted": "#475569",
        "row_even": "#FFFFFF",
        "row_odd":  "#F3F4F6",
        "sel_bg": "#D1E9FF",
        "sel_fg": "#0F172A",
        "header_bg": "#E5E7EB",
        "header_fg": "#0F172A",
        "border": "#CBD5E1",
    },
}

ctk.set_appearance_mode("dark")       # inicial
ctk.set_default_color_theme("blue")   # base do CTk (vamos sobrescrever cores chave)


# ==============================
# Dados (Monday)
# ==============================
def get_monday_data():
    """Lê o monday_export_all.json e normaliza as colunas usadas."""
    with open("monday_export_all.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("items", [])
    records = []

    for item in items:
        record = {"Name": item.get("name", "")}
        for col in item.get("column_values", []):
            record[col.get("id")] = col.get("text")
        # garante SN explicitamente
        record["text"] = next(
            (col.get("text") for col in item.get("column_values", []) if col.get("id") == "text"),
            None
        )
        records.append(record)

    df = pd.DataFrame(records)

    # garante colunas críticas
    for col in ("status", "status_1", "subelementos", "proposta_n_", "cliente"):
        if col not in df.columns:
            df[col] = "" if col in ("subelementos", "proposta_n_", "cliente") else None

    # due_date como datetime
    if "due_date" in df.columns:
        df["due_date"] = pd.to_datetime(df["due_date"], errors="coerce")
    else:
        df["due_date"] = pd.NaT

    # Filtra status desejados
    status_desejados = {"Reportado", "Pausado", "Em andamento"}
    df = df[df["status"].isin(status_desejados)].copy()

    # remove casos antigos
    df = df[~df["status_1"].isin(["--", "", None])].copy()

    return df


# ==============================
# Lógica de Targets
# ==============================
def monday_of_week(d: datetime) -> datetime:
    """Retorna a segunda da semana que contém 'd'. Se for sábado/domingo, a próxima segunda."""
    if d.weekday() < 5:
        return d - timedelta(days=d.weekday())
    return d + timedelta(days=(7 - d.weekday()))

def generate_targets(n, start_date_str="28/08/2025", max_per_week=5):
    """
    Gera rótulos: 'Semana XX - dd/mm/aaaa'
    - Começa em 36; ao passar de 52, volta a 1.
    - Target sempre na segunda da semana seguinte.
    """
    start = datetime.strptime(start_date_str, "%d/%m/%Y")
    week_monday = monday_of_week(start)

    targets = []
    for i in range(n):
        block = i // max_per_week
        target_date = week_monday + timedelta(days=7 * (block + 1))
        semana_rotulo = (block + 36 - 1) % 52 + 1
        targets.append(f"Semana {semana_rotulo} - {target_date.strftime('%d/%m/%Y')}")
    return targets

def add_targets_to_reparos(df, start_date_str="28/08/2025", max_per_week=5):
    if df.empty:
        df["target"] = None
        return df
    prioridade = {"SEVERA": 0, "ALTA": 1, "MÉDIA": 2, "LEVE": 3}
    df = df.copy()
    df["__priority__"] = df["status_1"].map(prioridade).fillna(999).astype(int)
    df = df.sort_values(by=["__priority__", "due_date"], ascending=[True, True]).reset_index(drop=True)
    df["target"] = generate_targets(len(df), start_date_str=start_date_str, max_per_week=max_per_week)
    return df.drop(columns=["__priority__"])


# ==============================
# App
# ==============================
class SimpleTable(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Fila de Reparos · OPx")
        self.geometry("1280x820")
        self.minsize(1024, 600)

        # Estado
        self.start_date_str = ctk.StringVar(value="28/08/2025")
        self.max_per_week = ctk.StringVar(value="5")
        self.appearance = ctk.StringVar(value="dark")

        # Ordem pedida:
        self.colunas_exibidas = [
            "Status",
            "Elemento",
            "N° Proposta",
            "Cliente",   # entre proposta e SN
            "SN",
            "Prioridade",
            "Data de Submissão",
            "Targetts",
        ]
        self.df_final = pd.DataFrame()

        # Monday (atualizador)
        self.mondayDataUpdate = dataMondaytoJson()

        # Layout
        self._build_ui()
        self._apply_brand_colors()   # cores iniciais
        self.load_data()

    # ---------- UI ----------
    def _build_ui(self):
        # Header
        self.header = ctk.CTkFrame(self, corner_radius=16)
        self.header.pack(fill="x", padx=14, pady=12)

        # Logo (opcional)
        self.logo_label = None
        self._try_set_logo(self.header)

        self.title_label = ctk.CTkLabel(self.header, text="Fila de Reparos",
                                        font=ctk.CTkFont(size=24, weight="bold"))
        self.subtitle_label = ctk.CTkLabel(
            self.header,
            text="Arraste linhas para reordenar · targets saem na 2ª feira da semana seguinte",
            font=ctk.CTkFont(size=12)
        )
        self.title_label.grid(row=0, column=1, sticky="w", padx=12, pady=(10, 0))
        self.subtitle_label.grid(row=1, column=1, sticky="w", padx=12, pady=(0, 12))

        # Controles
        self.controls = ctk.CTkFrame(self.header, fg_color="transparent")
        self.controls.grid(row=0, column=2, rowspan=2, sticky="e", padx=12, pady=12)

        ctk.CTkLabel(self.controls, text="Data inicial").grid(row=0, column=0, padx=(0, 8))
        self.entry_date = ctk.CTkEntry(self.controls, width=120, textvariable=self.start_date_str,
                                       placeholder_text="DD/MM/AAAA")
        self.entry_date.grid(row=0, column=1, padx=(0, 16))

        ctk.CTkLabel(self.controls, text="Máx/semana").grid(row=0, column=2, padx=(0, 8))
        self.opt_max = ctk.CTkOptionMenu(self.controls, variable=self.max_per_week,
                                         values=["3", "4", "5", "6", "7"])
        self.opt_max.grid(row=0, column=3, padx=(0, 16))

        self.btn_recalc = ctk.CTkButton(self.controls, text="Recalcular", command=self.recalc_targets, width=120)
        self.btn_recalc.grid(row=0, column=4, padx=(0, 10))

        self.btn_auto = ctk.CTkButton(self.controls, text="Auto ajustar", command=self.auto_resize_columns, width=120)
        self.btn_auto.grid(row=0, column=5, padx=(0, 10))

        self.appearance_btn = ctk.CTkSegmentedButton(
            self.controls, values=["dark", "light", "system"],
            variable=self.appearance, command=self.change_appearance
        )
        self.appearance_btn.grid(row=0, column=6)

        # Container
        container = ctk.CTkFrame(self, corner_radius=16)
        container.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        # Ações
        actions = ctk.CTkFrame(container, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=(12, 6))

        self.btn_reload = ctk.CTkButton(actions, text="Atualizar dados",
                                        command=lambda: self.load_data(1), width=150)
        self.btn_reload.pack(side="left")

        self.btn_sort_asc = ctk.CTkButton(actions, text="Prioridade ↑",
                                          command=self.sort_by_priority_asc, width=140)
        self.btn_sort_asc.pack(side="left", padx=8)

        self.btn_sort_desc = ctk.CTkButton(actions, text="Prioridade ↓",
                                           command=self.sort_by_priority_desc, width=140)
        self.btn_sort_desc.pack(side="left")

        # Treeview
        tree_wrap = ctk.CTkFrame(container)
        tree_wrap.pack(fill="both", expand=True, padx=12, pady=(8, 12))

        self.scroll_y = ttk.Scrollbar(tree_wrap, orient="vertical")
        self.scroll_y.pack(side="right", fill="y")

        self.scroll_x = ttk.Scrollbar(tree_wrap, orient="horizontal")
        self.scroll_x.pack(side="bottom", fill="x")

        self._setup_tree_style()  # cria estilo ttk baseado no modo atual

        self.reported_tree = ttk.Treeview(
            tree_wrap,
            columns=self.colunas_exibidas,
            show="headings",
            style="OPX.Treeview",
            yscrollcommand=self.scroll_y.set,
            xscrollcommand=self.scroll_x.set,
            selectmode="browse",
        )
        self.reported_tree.pack(fill="both", expand=True)
        self.scroll_y.config(command=self.reported_tree.yview)
        self.scroll_x.config(command=self.reported_tree.xview)

        for col in self.colunas_exibidas:
            self.reported_tree.heading(col, text=col, command=lambda c=col: self.sort_by_column(c))
            self.reported_tree.column(col, minwidth=90, width=160, anchor="center")

        # zebra
        self.reported_tree.tag_configure("oddrow", background=THEME["dark"]["row_odd"])
        self.reported_tree.tag_configure("evenrow", background=THEME["dark"]["row_even"])

        # DnD
        self.reported_tree.bind("<ButtonPress-1>", self._on_tree_press)
        self.reported_tree.bind("<B1-Motion>", self._on_tree_motion)
        self.reported_tree.bind("<ButtonRelease-1>", self._on_tree_release)

        # Status bar
        self.status = ctk.CTkLabel(self, text="Pronto", anchor="w")
        self.status.pack(fill="x", padx=14, pady=(0, 10))

    def _try_set_logo(self, parent):
        """Se existir a logo no mesmo diretório, exibe no header."""
        logo_path_candidates = [
            "opx_logo.png",
            "logo.png",
            os.path.join(os.getcwd(), "opx_logo.png"),
            os.path.join(os.getcwd(), "logo.png"),
            # imagem enviada nesta conversa (ajuste se quiser fixar caminho)
            "/mnt/data/5082b2bb-77a4-4dca-a578-62b0dfd196c5.png",
        ]
        if not PIL_AVAILABLE:
            return
        for p in logo_path_candidates:
            if os.path.exists(p):
                img = Image.open(p)
                # reduz e mantém transparência
                longest = 140
                ratio = longest / max(img.size)
                img = img.resize((int(img.size[0]*ratio), int(img.size[1]*ratio)))
                cimg = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
                self.logo_label = ctk.CTkLabel(parent, image=cimg, text="")
                self.logo_label.grid(row=0, column=0, rowspan=2, padx=(12, 6), pady=6)
                break

    # ---------- Estilos ----------
    def _current_mode(self) -> str:
        mode = self.appearance.get()
        if mode == "system":
            # pega do CTk
            return ctk.get_appearance_mode().lower()
        return mode

    def _setup_tree_style(self):
        """Cria/atualiza o estilo ttk Treeview conforme o modo atual."""
        mode = self._current_mode()
        pal = THEME[mode]

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(
            "OPX.Treeview",
            background=pal["bg"],
            foreground=pal["fg"],
            fieldbackground=pal["bg"],
            rowheight=30,
            borderwidth=0,
            relief="flat",
            font=("Segoe UI", 11),
        )
        style.map(
            "OPX.Treeview",
            background=[("selected", pal["sel_bg"])],
            foreground=[("selected", pal["sel_fg"])],
        )

        style.configure(
            "OPX.Treeview.Heading",
            background=pal["header_bg"],
            foreground=pal["header_fg"],
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            borderwidth=0,
        )

        # zebra tags (atualiza as cores)
        self.reported_tree_tag_even = pal["row_even"]
        self.reported_tree_tag_odd = pal["row_odd"]
        if hasattr(self, "reported_tree"):
            self.reported_tree.tag_configure("evenrow", background=self.reported_tree_tag_even)
            self.reported_tree.tag_configure("oddrow", background=self.reported_tree_tag_odd)

        # fundo da janela/header
        if hasattr(self, "header"):
            self.header.configure(fg_color=pal["bg2"])
        self.configure(fg_color=pal["bg"])

    def _apply_brand_colors(self):
        """Aplica amarelo OPx nos botões e ajusta textos conforme modo."""
        mode = self._current_mode()
        pal = THEME[mode]

        # labels
        self.title_label.configure(text_color=pal["fg"])
        self.subtitle_label.configure(text_color=pal["muted"])
        if self.logo_label:
            self.logo_label.configure(fg_color="transparent")

        # botões principais: amarelo OPx
        yellow_kwargs = dict(fg_color=OPX_YELLOW, hover_color=OPX_YELLOW_HOVER, text_color=OPX_TEXT_DARK)
        self.btn_recalc.configure(**yellow_kwargs)
        self.btn_auto.configure(**yellow_kwargs)
        self.btn_reload.configure(**yellow_kwargs)
        self.btn_sort_asc.configure(**yellow_kwargs)
        self.btn_sort_desc.configure(**yellow_kwargs)

        # --- AQUI O AJUSTE ---
        # OptionMenu (Máx/semana) também amarelo
        self.opt_max.configure(fg_color=OPX_YELLOW,
                            button_color=OPX_YELLOW,
                            button_hover_color=OPX_YELLOW_HOVER,
                            text_color=OPX_TEXT_DARK)

        # SegmentedButton (dark/light/system) em cinza discreto
        self.appearance_btn.configure(
            fg_color=pal["bg2"],
            selected_color=pal["fg"],
            selected_hover_color=pal["fg"],
            unselected_color=pal["border"],
            unselected_hover_color=pal["muted"],
            text_color=pal["bg"],  # texto claro/escuro conforme fundo
        )
        # ---------------------

        # status bar
        self.status.configure(text_color=pal["fg"])

        # header/bg (reforço)
        if hasattr(self, "header"):
            self.header.configure(fg_color=pal["bg2"])
        self.configure(fg_color=pal["bg"])


    # ---------- Data Ops ----------
    def populate(self, tree, df):
        tree.delete(*tree.get_children())
        cols = [c for c in self.colunas_exibidas if c in df.columns]
        for i, (_, row) in enumerate(df.iterrows()):
            iid = str(row["__iid"]) if "__iid" in row.index else str(i)
            values = [row.get(c, "") for c in cols]
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            tree.insert("", "end", iid=iid, values=values, tags=(tag,))

    def load_data(self, flag_reload=0):
        try:
            if flag_reload:
                self.mondayDataUpdate.mondayToJson()

            df = get_monday_data()
            df = add_targets_to_reparos(
                df,
                start_date_str=self.start_date_str.get(),
                max_per_week=int(self.max_per_week.get())
            )

            df = df.copy()
            if pd.api.types.is_datetime64_any_dtype(df["due_date"]):
                df["due_date"] = df["due_date"].dt.strftime("%d/%m/%Y")

            # ícones prioridade
            icon = {"SEVERA": "🟥 ", "ALTA": "🟧 ", "MÉDIA": "🟦 ", "LEVE": "🟩 "}
            df["status_1"] = df["status_1"].map(lambda s: f"{icon.get(s,'')} {s}" if s else s)

            # mapeia rótulos
            column_mapping = {
                "Name": "Elemento",
                "subelementos": "Subelementos",
                "proposta_n_": "N° Proposta",
                "cliente": "Cliente",
                "text": "SN",
                "status_1": "Prioridade",
                "status": "Status",
                "due_date": "Data de Submissão",
                "target": "Targetts",
            }
            df.rename(columns=column_mapping, inplace=True)
            df.drop(columns=["Subelementos"], errors="ignore", inplace=True)

            cols = [c for c in self.colunas_exibidas if c in df.columns]
            df["__iid"] = range(1, len(df) + 1)
            self.df_final = df[["__iid"] + cols].copy()

            self.populate(self.reported_tree, self.df_final)
            self.auto_resize_columns(sample=120)

            self.status.configure(
                text=f"Carregado: {len(self.df_final)} itens · Atualizado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
            )
        except Exception as e:
            self.status.configure(text=f"Erro ao carregar dados: {e}")
            self.df_final = pd.DataFrame(columns=["__iid"] + self.colunas_exibidas)
            self.populate(self.reported_tree, self.df_final)

    # ---------- UX helpers ----------
    def recalc_targets(self):
        try:
            datetime.strptime(self.start_date_str.get(), "%d/%m/%Y")
        except ValueError:
            self.status.configure(text="Data inválida. Use DD/MM/AAAA.")
            return
        self._recalc_targets_inplace()
        self.populate(self.reported_tree, self.df_final)

    def _priority_rank(self, cell_value: str) -> int:
        if not isinstance(cell_value, str):
            return 999
        base = cell_value.replace("🟥", "").replace("🟧", "").replace("🟦", "").replace("🟩", "").strip()
        mapping = {"SEVERA": 0, "ALTA": 1, "MÉDIA": 2, "LEVE": 3}
        return mapping.get(base, 999)

    def sort_by_priority_asc(self):
        if "Prioridade" in self.df_final.columns and not self.df_final.empty:
            self.df_final = self.df_final.sort_values(
                by="Prioridade",
                key=lambda s: s.map(self._priority_rank),
                ascending=True
            ).reset_index(drop=True)
            self.populate(self.reported_tree, self.df_final)

    def sort_by_priority_desc(self):
        if "Prioridade" in self.df_final.columns and not self.df_final.empty:
            self.df_final = self.df_final.sort_values(
                by="Prioridade",
                key=lambda s: s.map(self._priority_rank),
                ascending=False
            ).reset_index(drop=True)
            self.populate(self.reported_tree, self.df_final)

    def sort_by_column(self, col_name: str):
        if col_name not in self.df_final.columns or self.df_final.empty:
            return
        if not hasattr(self, "_sort_state"):
            self._sort_state = {}
        last = self._sort_state.get(col_name, "desc")
        ascending = True if last == "desc" else False
        self._sort_state[col_name] = "asc" if ascending else "desc"

        if col_name == "Prioridade":
            self.df_final = self.df_final.sort_values(
                by="Prioridade",
                key=lambda s: s.map(self._priority_rank),
                ascending=ascending
            ).reset_index(drop=True)
        else:
            self.df_final = self.df_final.sort_values(
                by=col_name, ascending=ascending, na_position="last"
            ).reset_index(drop=True)
        self.populate(self.reported_tree, self.df_final)

    def auto_resize_columns(self, sample=100, min_w=100, max_w=360):
        if self.df_final.empty:
            return
        cols = [c for c in self.colunas_exibidas if c in self.df_final.columns]
        for col in cols:
            header_w = len(str(col)) * 9 + 30
            serie = self.df_final[col].astype(str).head(sample)
            cell_w = max((len(v) for v in serie), default=10) * 8 + 28
            width = max(min_w, min(max(header_w, cell_w), max_w))
            self.reported_tree.column(col, width=width)

    # ---------- Drag & Drop ----------
    def _on_tree_press(self, event):
        row_iid = self.reported_tree.identify_row(event.y)
        if row_iid:
            self._dragging_iid = row_iid
            self.reported_tree.selection_set(row_iid)
        else:
            self._dragging_iid = None

    def _on_tree_motion(self, event):
        if not hasattr(self, "_dragging_iid") or not self._dragging_iid:
            return
        y = event.y
        height = self.reported_tree.winfo_height()
        if y < 20:
            self.reported_tree.yview_scroll(-1, "units")
        elif y > height - 20:
            self.reported_tree.yview_scroll(1, "units")
        target_iid = self.reported_tree.identify_row(event.y)
        if target_iid and target_iid != self._dragging_iid:
            idx = self.reported_tree.index(target_iid)
            self.reported_tree.move(self._dragging_iid, "", idx)

    def _on_tree_release(self, event):
        if not hasattr(self, "_dragging_iid") or not self._dragging_iid:
            return
        order = list(self.reported_tree.get_children(""))
        try:
            idx_order = [int(i) for i in order]
        except ValueError:
            idx_order = order
        if "__iid" in self.df_final.columns and len(idx_order) == len(self.df_final):
            self.df_final = (
                self.df_final.set_index("__iid")
                            .loc[idx_order]
                            .reset_index()
            )
        self._recalc_targets_inplace()
        self.populate(self.reported_tree, self.df_final)
        self._dragging_iid = None
        self.status.configure(text=f"Reordenado: {len(self.df_final)} itens · Targets atualizados")

    def _recalc_targets_inplace(self):
        n = len(self.df_final)
        if n == 0:
            return
        targets = generate_targets(
            n,
            start_date_str=self.start_date_str.get(),
            max_per_week=int(self.max_per_week.get())
        )
        if "Targetts" not in self.df_final.columns:
            self.df_final["Targetts"] = ""
        self.df_final.loc[:, "Targetts"] = targets

    # ---------- Aparência ----------
    def change_appearance(self, mode):
        # Atualiza modo do CTk
        ctk.set_appearance_mode(mode)
        # Atualiza estilos ttk e cores de componentes
        self._setup_tree_style()
        self._apply_brand_colors()
        # força repintura das linhas (zebra com cores do modo)
        self.populate(self.reported_tree, self.df_final)


if __name__ == "__main__":
    app = SimpleTable()
    app.mainloop()
