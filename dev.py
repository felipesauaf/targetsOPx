# =================== Imports ===================
import os
import json
import pandas as pd
from datetime import datetime, timedelta
import unicodedata  # <- para normalizar acentos/case em 'Prioridade'
import re

import customtkinter as ctk
from tkinter import ttk

# PIL opcional (logo)
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# =================== Integração Monday (JSON) ===================
# Espera-se um objeto com método mondayToJson() que gera "monday_export_all.json"
try:
    from jsonExport import dataMondaytoJson
except Exception:
    # Fallback para não quebrar durante testes sem o módulo
    class dataMondaytoJson:
        def mondayToJson(self):  # no-op
            pass


# =================== Constantes / Tema ===================
OPX_YELLOW = "#FACC15"
OPX_YELLOW_HOVER = "#EAB308"
OPX_TEXT_DARK = "#0B1220"   # usado para texto sobre amarelo
OPX_BLACK = "#0B1220"       # preto/azul bem escuro para o header e fundo
TITLE_FONT_SIZE = 38        # tamanho do título do cabeçalho

# Logo grande no header
LOGO_MAX_W = 360   # largura máx da logo no header
LOGO_MAX_H = 80    # altura máx da logo no header

THEME = {
    "Dark": {
        "bg": "#0B1220",
        "bg2": "#0F172A",
        "fg": "#E5E7EB",
        "muted": "#9CA3AF",
        "row_even": "#0F172A",
        "row_odd":  "#111827",
        "sel_bg": "#FFD900",
        "sel_fg": "#111827",
        "header_bg": "#0F172A",
        "header_fg": "#E5E7EB",
        "border": "#1F2937",
        "chip_bg": "#111827",
    },
    "Light": {
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
        "chip_bg": "#EEF2FF",
    },
}
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Colunas padrão em PT-BR (como aparecem na interface/Excel principal)
COLS_UI = [
    "Status",
    "Elemento",
    "N° Proposta",
    "Cliente",
    "SN",
    "Prioridade",
    "Data de Submissão",
    "Targetts",
]

# <<< CHAVE DE COMPARAÇÃO >>>: somente Elemento + Cliente + SN
KEY_COLS = ["Elemento", "Cliente", "SN"]

# Badges coloridos para Prioridade
PRIORITY_BADGE_MAP = {
    "SEVERA": "🟥 SEVERA",
    "ALTA":   "🟧 ALTA",
    "MÉDIA":  "🟦 MÉDIA",
    "LEVE":   "🟩 LEVE",
}
PRIORITY_ORDER = {"SEVERA": 0, "ALTA": 1, "MÉDIA": 2, "LEVE": 3}


# =================== Helpers de Prioridade ===================
def _strip_accents(s: str) -> str:
    if not isinstance(s, str):
        s = "" if s is None else str(s)
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def canonicalize_priority(val: str) -> str:
    """
    Normaliza/Padroniza a string de prioridade para uma destas: SEVERA, ALTA, MÉDIA, LEVE.
    Aceita com/sem emoji, acentos e diferentes cases (ex.: 'media', 'Média', '🟦 MÉDIA').
    Caso não reconheça, retorna string vazia.
    """
    if val is None:
        return ""
    v = str(val)
    for sq in ("🟥", "🟧", "🟦", "🟩"):
        v = v.replace(sq, "")
    v = v.strip()
    v_upper = _strip_accents(v).upper()

    if "SEVERA" in v_upper:
        return "SEVERA"
    if "ALTA" in v_upper:
        return "ALTA"
    if "MEDIA" in v_upper:
        return "MÉDIA"
    if "LEVE" in v_upper:
        return "LEVE"
    return ""


def with_priority_badge(val: str) -> str:
    """Retorna a prioridade com a 'caixinha' correspondente. Caso desconhecida, devolve o original."""
    base = canonicalize_priority(val)
    return PRIORITY_BADGE_MAP.get(base, val if val is not None else "")


def ensure_badges(df: pd.DataFrame) -> pd.DataFrame:
    """Garante que a coluna Prioridade do DF esteja com o badge (🟥🟧🟦🟩)."""
    if "Prioridade" in df.columns:
        df = df.copy()
        df["Prioridade"] = df["Prioridade"].map(with_priority_badge)
    return df

# =================== Anti-NaN helper ===================  # [ANTI-NAN]
def denan(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None:
        return None
    out = df.copy()
    return out.where(pd.notna(out), "")


# =================== Monday JSON → DataFrame (filtrado) ===================
def get_monday_data_from_json():
    with open("monday_export_all.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("items", [])
    records = []
    for item in items:
        r = {"Name": item.get("name", "")}
        for col in item.get("column_values", []):
            r[col.get("id")] = col.get("text")
        r["text"] = r.get("text") or next(
            (c.get("text") for c in item.get("column_values", []) if c.get("id") == "text"), None
        )
        records.append(r)

    df = pd.DataFrame(records)

    for col in ("status", "status_1", "subelementos", "proposta_n_", "cliente"):
        if col not in df.columns:
            df[col] = "" if col in ("subelementos", "proposta_n_", "cliente") else None

    if "due_date" in df.columns:
        df["due_date"] = pd.to_datetime(df["due_date"], errors="coerce")
    else:
        df["due_date"] = pd.NaT

    status_ok = {"Reportado", "Pausado", "Em andamento"}
    df = df[df["status"].isin(status_ok)].copy()
    df = df[~df["status_1"].isin(["--", "", None])].copy()

    return df


def map_monday_to_ptbr(df_monday: pd.DataFrame) -> pd.DataFrame:
    df = df_monday.copy()
    if pd.api.types.is_datetime64_any_dtype(df["due_date"]):
        df["due_date"] = df["due_date"].dt.strftime("%d/%m/%Y")

    mapping = {
        "Name": "Elemento",
        "subelementos": "Subelementos",
        "proposta_n_": "N° Proposta",
        "cliente": "Cliente",
        "text": "SN",
        "status_1": "Prioridade",
        "status": "Status",
        "due_date": "Data de Submissão",
    }
    df.rename(columns=mapping, inplace=True)
    for c in ["Elemento", "Subelementos", "N° Proposta", "Cliente", "SN", "Prioridade", "Status", "Data de Submissão"]:
        if c not in df.columns:
            df[c] = ""
    df = df[["Elemento", "Subelementos", "N° Proposta", "Cliente", "SN", "Prioridade", "Status", "Data de Submissão"]]
    return denan(df)


def write_monday_dados_excel(df_monday_ptbr: pd.DataFrame):
    if df_monday_ptbr.empty:
        return
    path = os.path.join(os.getcwd(), "monday_dados.xlsx")
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df_monday_ptbr.to_excel(w, index=False, sheet_name="Dados")
        ws = w.book["Dados"]
        ws.freeze_panes = "A2"
        for j, col in enumerate(df_monday_ptbr.columns, start=1):
            sample = max([len(str(col))] + [len(str(v)) for v in df_monday_ptbr[col].astype(str).head(200)])
            ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = min(max(sample + 4, 12), 50)


# =================== Leitura das planilhas para comparação ===================
def read_monday_excel() -> pd.DataFrame | None:
    path = os.path.join(os.getcwd(), "monday_dados.xlsx")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_excel(path, sheet_name="Dados")
        cols = ["Elemento", "Subelementos", "N° Proposta", "Cliente", "SN", "Prioridade", "Status", "Data de Submissão"]
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        df = df[cols]
        df = denan(df)
        return df
    except Exception:
        return None


def read_lista_excel() -> pd.DataFrame | None:
    path = os.path.join(os.getcwd(), "ListaAtualizada.xlsx")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_excel(path, sheet_name="Reparos")
        for c in COLS_UI:
            if c not in df.columns:
                df[c] = ""
        df = df[COLS_UI]
        df = denan(df)
        return df
    except Exception:
        return None


# =================== Diff (Novos e Finalizados) ===================
def _normalize_keys(df: pd.DataFrame, key_cols=KEY_COLS) -> pd.Series:
    base = df.copy()
    for c in key_cols:
        if c not in base.columns:
            base[c] = ""
    base = base[key_cols].fillna("").astype(str)
    return base.apply(lambda r: "||".join([s.strip() for s in r.tolist()]), axis=1)


def diff_new_items(df_monday_ptbr_excel: pd.DataFrame, df_lista_reparos: pd.DataFrame) -> pd.DataFrame:
    if df_monday_ptbr_excel is None or df_monday_ptbr_excel.empty:
        return pd.DataFrame(columns=["Status", "Elemento", "N° Proposta", "Cliente", "SN", "Prioridade", "Data de Submissão"])

    if df_lista_reparos is None or df_lista_reparos.empty:
        out = df_monday_ptbr_excel.copy()
        return out[["Status", "Elemento", "N° Proposta", "Cliente", "SN", "Prioridade", "Data de Submissão"]]

    monday_keys = _normalize_keys(df_monday_ptbr_excel)
    lista_keys = _normalize_keys(df_lista_reparos.rename(columns={"Targetts": "_Targetts_"}).copy())

    mask_new = ~monday_keys.isin(set(lista_keys))
    novos = df_monday_ptbr_excel.loc[mask_new].copy()

    return novos[["Status", "Elemento", "N° Proposta", "Cliente", "SN", "Prioridade", "Data de Submissão"]]


def diff_finished_items(df_monday_ptbr_excel: pd.DataFrame, df_lista_reparos: pd.DataFrame) -> pd.DataFrame:
    if df_lista_reparos is None or df_lista_reparos.empty:
        return pd.DataFrame(columns=COLS_UI)
    if df_monday_ptbr_excel is None or df_monday_ptbr_excel.empty:
        return pd.DataFrame(columns=COLS_UI)

    monday_keys = _normalize_keys(df_monday_ptbr_excel)
    lista_keys = _normalize_keys(df_lista_reparos.rename(columns={"Targetts": "_Targetts_"}).copy())
    finished_mask = ~lista_keys.isin(set(monday_keys))
    finished = df_lista_reparos.loc[finished_mask].copy()
    for c in COLS_UI:
        if c not in finished.columns:
            finished[c] = ""
    return finished[COLS_UI]


# =================== Targets ===================
def monday_of_week(d: datetime) -> datetime:
    if d.weekday() < 5:
        return d - timedelta(days=d.weekday())
    return d + timedelta(days=(7 - d.weekday()))

def _parse_week_from_label(label: str) -> int | None:
    """
    Extrai 'Semana NN' do rótulo 'Semana NN - DD/MM/AAAA' e retorna o inteiro NN.
    """
    if not label:
        return None
    m = re.search(r"Semana\s+(\d{1,2})\b", str(label))
    return int(m.group(1)) if m else None

# >>> SEMANA CUSTOM: geração com capacidades por semana (overrides) e semana ISO
def generate_targets(n, start_date_str="28/08/2025", default_per_week=5, week_overrides=None, start_from_next_week=True):
    """
    Gera a lista de Targetts para n itens.
    - default_per_week: capacidade padrão (Máx/semana)
    - week_overrides: dict {semana_iso:int -> capacidade} para semanas específicas
    - start_from_next_week: se True, começa na semana seguinte à 'start_date_str'
    Label: 'Semana NN - DD/MM/AAAA' (NN = semana ISO da data-base daquela semana)
    """
    week_overrides = week_overrides or {}
    start = datetime.strptime(start_date_str, "%d/%m/%Y")
    week_monday = monday_of_week(start)
    current_week_start = week_monday + timedelta(days=7 if start_from_next_week else 0)

    targets = []
    assigned = 0

    while assigned < n:
        iso_week = current_week_start.isocalendar()[1]
        capacity = week_overrides.get(int(iso_week), default_per_week)
        slots = min(capacity, n - assigned)
        for _ in range(slots):
            targets.append(f"Semana {iso_week:02d} - {current_week_start.strftime('%d/%m/%Y')}")
            assigned += 1
            if assigned >= n:
                break
        current_week_start += timedelta(days=7)

    return targets


# =================== App (UI) ===================
class SimpleTable(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Fila de Reparos · OPx")
        self.geometry("1320x860")
        self.minsize(1100, 650)

        self.start_date_str = ctk.StringVar(value="28/08/2025")
        self.max_per_week = ctk.StringVar(value="5")
        self.appearance = ctk.StringVar(value="Dark")

        # >>> SEMANA CUSTOM: estados e inputs
        self.week_overrides: dict[int, int] = {}  # {semana_iso: capacidade}
        self.week_override_week = ctk.StringVar(value="")
        self.week_override_qty = ctk.StringVar(value="")
        self._overrides_label = None

        self.colunas_exibidas = COLS_UI[:]  # cópia
        self.df_final = pd.DataFrame(columns=self.colunas_exibidas)   # principal (Reparos)
        self.df_novos = pd.DataFrame()                                # aba "Novos"
        self.df_removed = pd.DataFrame()                              # itens removidos (finalizados)

        self.mondayDataUpdate = dataMondaytoJson()

        self.logo_label = None
        self.pane_novos = None
        self.novos_tree = None
        self.btn_atualizar_novos = None

        self.pane_removed = None
        self.removed_tree = None
        self.btn_hide_removed = None

        # estado do drag-and-drop
        self._dragging = False
        self._dragging_iid = None
        self._drag_start_index = None
        self._last_drop_index = None

        # destaque de alterações (piscar amarelo)
        self._changed_indices = set()
        self._highlight_job = None  # id do after agendado

        self._build_ui()
        self._apply_brand_colors()

        # >>> ATUALIZA monday_dados AO INICIAR e já cria "Novos" + aplica remoção dos finalizados <<<
        self.load_data(flag_reload=1)

    # Pequeno helper de paleta atual
    def _pal(self):
        mode = self.appearance.get()
        if mode not in ("Dark", "Light"):
            mode = "Dark"
        return THEME[mode]

    # ---------- UI ----------
    def _build_ui(self):
        # =====================  HEADER (hero)  =====================
        self.header = ctk.CTkFrame(self, corner_radius=0, fg_color=OPX_BLACK)
        self.header.pack(fill="x", padx=0, pady=0)

        self.header.grid_columnconfigure(0, weight=0)  # logo
        self.header.grid_columnconfigure(1, weight=1)  # título/subtítulo
        self.header.grid_columnconfigure(2, weight=0)  # controles

        self._try_set_logo(self.header, max_w=LOGO_MAX_W, max_h=LOGO_MAX_H)

        self.title_label = ctk.CTkLabel(
            self.header,
            text="FILA DE REPAROS",
            font=ctk.CTkFont(size=TITLE_FONT_SIZE, weight="bold"),
            text_color="#FFFFFF",
        )
        self.title_label.grid(row=0, column=1, sticky="w", padx=(8, 12), pady=(10, 0))

        self.subtitle_label = ctk.CTkLabel(
            self.header,
            text="Arraste as linhas para reordenar · 'Novos' vão para o fim do bloco da mesma Prioridade",
            font=ctk.CTkFont(size=12),
            text_color="#FFFFFF",
        )
        self.subtitle_label.grid(row=1, column=1, sticky="w", padx=(8, 12), pady=(0, 10))

        # Controles (lado direito)
        controls = ctk.CTkFrame(self.header, fg_color="transparent")
        controls.grid(row=0, column=2, rowspan=2, sticky="e", padx=12, pady=10)

        ctk.CTkLabel(controls, text="Data inicial", text_color="#FFFFFF").grid(row=0, column=0, padx=(0, 8))
        self.entry_date = ctk.CTkEntry(
            controls, width=120, textvariable=self.start_date_str, placeholder_text="DD/MM/AAAA", justify="center"
        )
        self.entry_date.grid(row=0, column=1, padx=(0, 16))

        ctk.CTkLabel(controls, text="Máx/semana", text_color="#FFFFFF").grid(row=0, column=2, padx=(0, 8))
        self.opt_max = ctk.CTkOptionMenu(
            controls, variable=self.max_per_week, values=["3", "4", "5", "6", "7"],
            fg_color=OPX_YELLOW, button_color=OPX_YELLOW,
            button_hover_color=OPX_YELLOW_HOVER, text_color=OPX_TEXT_DARK
        )
        self.opt_max.grid(row=0, column=3, padx=(0, 16))

        self.btn_recalc = ctk.CTkButton(
            controls, text="Recalcular targets", command=self.recalc_targets, width=160
        )
        self.btn_recalc.grid(row=0, column=4, padx=(0, 10))

        self.btn_auto = ctk.CTkButton(
            controls, text="Auto ajustar colunas", command=self.auto_resize_columns, width=180
        )
        self.btn_auto.grid(row=0, column=5, padx=(0, 10))

        self.appearance_btn = ctk.CTkSegmentedButton(
            controls,
            values=["Dark", "Light"],
            variable=self.appearance,
            command=self.change_appearance,
            corner_radius=12
        )
        self.appearance_btn.grid(row=0, column=6)

        self._style_yellow_button(self.btn_recalc)
        self._style_yellow_button(self.btn_auto)

        # =====================  CONTAINER PRINCIPAL  =====================
        container = ctk.CTkFrame(self, corner_radius=16)
        container.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        # Barra de ações
        actions = ctk.CTkFrame(container, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=(12, 6))

        # Esquerda: ações principais
        left_actions = ctk.CTkFrame(actions, fg_color="transparent")
        left_actions.pack(side="left")

        self.btn_reload = ctk.CTkButton(
            left_actions,
            text="Atualizar dados",
            command=lambda: self.load_data(1),
            width=300,
        )
        self._style_yellow_button(self.btn_reload)
        self.btn_reload.pack(side="left")

        self.btn_sort_asc = ctk.CTkButton(
            left_actions, text="Prioridade ↑", command=self.sort_by_priority_asc, width=140
        )
        self._style_yellow_button(self.btn_sort_asc)
        self.btn_sort_asc.pack(side="left", padx=8)

        self.btn_sort_desc = ctk.CTkButton(
            left_actions, text="Prioridade ↓", command=self.sort_by_priority_desc, width=140
        )
        self._style_yellow_button(self.btn_sort_desc)
        self.btn_sort_desc.pack(side="left", padx=(0, 8))

        self.btn_export = ctk.CTkButton(
            left_actions, text="Salvar", command=self.export_excel, width=200
        )
        self._style_yellow_button(self.btn_export)
        self.btn_export.pack(side="left")

        # >>> UI SEMANA (à direita)
        week_frame = ctk.CTkFrame(actions, fg_color="transparent")
        week_frame.pack(side="right")

        ctk.CTkLabel(week_frame, text="Semana").grid(row=0, column=0, padx=(0, 6))
        self.entry_week = ctk.CTkEntry(week_frame, width=72, textvariable=self.week_override_week,
                                       placeholder_text="36", justify="center")
        self.entry_week.grid(row=0, column=1)

        ctk.CTkLabel(week_frame, text="Qtd").grid(row=0, column=2, padx=(10, 6))
        self.entry_week_qty = ctk.CTkEntry(week_frame, width=72, textvariable=self.week_override_qty,
                                           placeholder_text="5", justify="center")
        self.entry_week_qty.grid(row=0, column=3)

        self.btn_apply_week = ctk.CTkButton(week_frame, text="Aplicar semana",
                                            command=self._apply_week_override, width=150)
        self._style_yellow_button(self.btn_apply_week)
        self.btn_apply_week.grid(row=0, column=4, padx=(10, 6))

        self.btn_clear_weeks = ctk.CTkButton(week_frame, text="Limpar regras",
                                             command=self._clear_week_overrides, width=130)
        self._style_yellow_button(self.btn_clear_weeks)
        self.btn_clear_weeks.grid(row=0, column=5, padx=(2, 10))

        self._overrides_label = ctk.CTkLabel(week_frame, text="Sem regras")
        self._overrides_label.grid(row=0, column=6, padx=(8, 0))

        # Painel: Tabela principal (Reparos)
        pane_main = ctk.CTkFrame(container, corner_radius=12)
        pane_main.pack(fill="both", expand=True, padx=12, pady=(8, 8))

        lbl_main = ctk.CTkLabel(
            pane_main, text="Reparos (ListaAtualizada)", font=ctk.CTkFont(size=14, weight="bold")
        )
        lbl_main.pack(anchor="w", padx=8, pady=(8, 0))

        main_wrap = ctk.CTkFrame(pane_main)
        main_wrap.pack(fill="both", expand=True, padx=8, pady=8)

        self.scroll_y = ttk.Scrollbar(main_wrap, orient="vertical")
        self.scroll_y.pack(side="right", fill="y")
        self.scroll_x = ttk.Scrollbar(main_wrap, orient="horizontal")
        self.scroll_x.pack(side="bottom", fill="x")

        self._setup_tree_style()

        self.reported_tree = ttk.Treeview(
            main_wrap,
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
            self.reported_tree.heading(col, text=col, anchor="w")
            self.reported_tree.column(col, anchor="w", width=140, stretch=True)

        # --- Drag & Drop na tabela principal ---
        self.reported_tree.bind("<ButtonPress-1>", self._on_tree_btn_press)
        self.reported_tree.bind("<B1-Motion>", self._on_tree_motion)
        self.reported_tree.bind("<ButtonRelease-1>", self._on_tree_btn_release)

    # ---------- Estilos e temas ----------
    def _setup_tree_style(self):
        mode = self.appearance.get() if self.appearance.get() in ("Dark", "Light") else "Dark"
        pal = THEME[mode]

        style = ttk.Style(self)
        style.theme_use("default")

        style.configure(
            "OPX.Treeview",
            background=pal["bg2"],
            fieldbackground=pal["bg2"],
            foreground=pal["fg"],
            bordercolor=pal["border"],
            borderwidth=0,
            rowheight=26,
            font=("Inter", 11)
        )
        style.configure(
            "OPX.Treeview.Heading",
            background=pal["header_bg"],
            foreground=pal["header_fg"],
            relief="flat",
            font=("Inter", 11, "bold")
        )
        style.map(
            "OPX.Treeview",
            background=[("selected", pal["sel_bg"])],
            foreground=[("selected", pal["sel_fg"])],
            highlight=[("selected", pal["sel_bg"])],
        )

    def _apply_brand_colors(self):
        mode = self.appearance.get() if self.appearance.get() in ("Dark", "Light") else "Dark"
        pal = THEME[mode]
        self.configure(fg_color=pal["bg"])
        self.header.configure(fg_color=OPX_BLACK)
        if self.title_label is not None:
            self.title_label.configure(text_color="#FFFFFF")
        if self.subtitle_label is not None:
            self.subtitle_label.configure(text_color="#FFFFFF")
        self._style_yellow_button(self.btn_recalc)
        self._style_yellow_button(self.btn_auto)
        if self._overrides_label is not None:
            self._overrides_label.configure(text_color=pal["muted"], fg_color=pal["chip_bg"], corner_radius=10, padx=10, pady=6)

    def _style_yellow_button(self, btn: ctk.CTkButton):
        btn.configure(fg_color=OPX_YELLOW, hover_color=OPX_YELLOW_HOVER, text_color=OPX_TEXT_DARK)

    # --- Logo grande no header ---
    def _try_set_logo(self, parent, max_w=LOGO_MAX_W, max_h=LOGO_MAX_H):
        if not PIL_AVAILABLE:
            return
        candidates = ["logo_header.png", "logo_header.jpg", "logo_header.jpeg", "logo_opx.png", "logo.png"]
        logo_path = None
        for p in candidates:
            pfull = os.path.join(os.getcwd(), p)
            if os.path.exists(pfull):
                logo_path = pfull
                break
        if not logo_path:
            return
        try:
            img = Image.open(logo_path).convert("RGBA")
            w, h = img.size
            scale = min(max_w / float(w), max_h / float(h))
            new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
            img = img.resize(new_size, Image.LANCZOS)
            self._logo_imgtk = ImageTk.PhotoImage(img)
            self.logo_label = ctk.CTkLabel(parent, text="", image=self._logo_imgtk)
            self.logo_label.grid(row=0, column=0, rowspan=2, sticky="w", padx=12, pady=8)
        except Exception:
            pass

    # ---------- Destaque temporário ----------
    def _clear_changed_highlight(self):
        """Limpa o destaque e cancela o job pendente (se existir)."""
        try:
            if self._highlight_job is not None:
                self.after_cancel(self._highlight_job)
        except Exception:
            pass
        self._highlight_job = None
        if self._changed_indices:
            self._changed_indices.clear()
            self.render_main_table()

    def _indices_of_week(self, week_num: int) -> list[int]:
        """Retorna todos os índices da lista principal cujo Targetts é 'Semana week_num - ...'."""
        if self.df_final is None or self.df_final.empty or "Targetts" not in self.df_final.columns:
            return []
        week_num = int(week_num)
        s1 = f"Semana {week_num:02d}"
        s2 = f"Semana {week_num}"
        vals = self.df_final["Targetts"].astype(str).tolist()
        return [i for i, v in enumerate(vals) if v.startswith(s1) or v.startswith(s2)]

    # ---------- Inferência de capacidades atuais ----------
    def _infer_week_caps_from_current_df(self) -> dict[int, int]:
        """
        Lê a coluna Targetts atual e infere quantos slots cada semana já possui,
        p.ex.: {'40': 2}, preservando a distribuição já salva.
        """
        caps: dict[int, int] = {}
        if self.df_final is None or self.df_final.empty or "Targetts" not in self.df_final.columns:
            return caps
        for v in self.df_final["Targetts"].astype(str).tolist():
            w = _parse_week_from_label(v)
            if w is not None:
                caps[w] = caps.get(w, 0) + 1
        return caps

    def change_appearance(self, *_):
        mode = self.appearance.get()
        ctk.set_appearance_mode(mode)
        self._setup_tree_style()
        self._apply_brand_colors()
        self.render_main_table()
        self._render_novos_panel()
        self._render_removed_panel()

    # ---------- Dados / Ações ----------
    def load_data(self, flag_reload=0):
        if flag_reload:
            try:
                self.mondayDataUpdate.mondayToJson()
            except Exception:
                pass
            json_path = os.path.join(os.getcwd(), "monday_export_all.json")
            if os.path.exists(json_path):
                try:
                    df_monday_raw = get_monday_data_from_json()
                    df_monday_ptbr = map_monday_to_ptbr(df_monday_raw)
                    write_monday_dados_excel(df_monday_ptbr)
                except Exception:
                    pass

        df_monday_excel = read_monday_excel()
        df_lista = read_lista_excel()

        if df_lista is None:
            self.df_final = pd.DataFrame(columns=self.colunas_exibidas)
        else:
            self.df_final = df_lista.copy()

        self.df_removed = diff_finished_items(df_monday_excel, self.df_final)
        if self.df_removed is not None and not self.df_removed.empty:
            if df_monday_excel is not None and not df_monday_excel.empty:
                keys_monday = set(_normalize_keys(df_monday_excel))
                keys_lista = _normalize_keys(self.df_final.rename(columns={"Targetts": "_Targetts_"}).copy())
                keep_mask = keys_lista.isin(keys_monday)
                self.df_final = self.df_final.loc[keep_mask].reset_index(drop=True)

        self.df_final = ensure_badges(self.df_final)
        self.df_removed = ensure_badges(self.df_removed) if self.df_removed is not None else pd.DataFrame()

        self.df_final = denan(self.df_final)
        self.df_removed = denan(self.df_removed) if self.df_removed is not None else pd.DataFrame()

        base_cmp = self.df_final[self.colunas_exibidas[:-1]] if not self.df_final.empty else df_final_like()
        self.df_novos = diff_new_items(df_monday_excel, base_cmp).copy()
        self.df_novos = ensure_badges(self.df_novos)
        self.df_novos = denan(self.df_novos)

        self.render_main_table()
        self._render_novos_panel()
        self._render_removed_panel()

    def recalc_targets(self, keep_existing_week_caps: bool = True):
        """
        Recalcula a coluna Targetts para a lista atual.
        - keep_existing_week_caps=True: preserva capacidades já salvas por semana a partir da coluna atual.
        """
        if self.df_final is None or self.df_final.empty:
            return
        n = len(self.df_final)
        try:
            maxw = int(self.max_per_week.get())
        except Exception:
            maxw = 5
        start = self.start_date_str.get() or "28/08/2025"

        # >>> mescla "capacidades inferidas" + "overrides" recém-aplicados
        effective_overrides = {}
        if keep_existing_week_caps:
            effective_overrides.update(self._infer_week_caps_from_current_df())
        # overrides digitados pelo usuário têm precedência
        effective_overrides.update(self.week_overrides)

        self.df_final["Targetts"] = generate_targets(
            n,
            start_date_str=start,
            default_per_week=maxw,
            week_overrides=effective_overrides,
            start_from_next_week=True
        )
        self.render_main_table()

    # >>> SEMANA CUSTOM: aplicar/limpar regras
    def _apply_week_override(self):
        try:
            w = int((self.week_override_week.get() or "").strip())
            q = int((self.week_override_qty.get() or "").strip())
        except Exception:
            return
        if not (1 <= w <= 53) or q <= 0:
            return

        # atualiza regra da semana
        self.week_overrides[w] = q
        self._update_overrides_label()

        # recalc preservando capacidades já salvas
        self.recalc_targets(keep_existing_week_caps=True)

        # cancela highlight anterior e calcula novo (pack da semana w)
        self._clear_changed_highlight()
        self._changed_indices = set(self._indices_of_week(w))

        # renderiza com destaque e agenda limpar (~0,9s)
        self.render_main_table()
        try:
            self._highlight_job = self.after(900, self._clear_changed_highlight)
        except Exception:
            self._clear_changed_highlight()

    def _clear_week_overrides(self):
        # limpa regras + recalcula (volta a usar só máx/semana) + remove destaque
        self.week_overrides.clear()
        self._update_overrides_label()
        self._clear_changed_highlight()
        self.recalc_targets(keep_existing_week_caps=False)

    def _clear_week_overrides_ui_only(self):
        """
        Limpa SOMENTE a UI (chip 'Regras'), preservando os Targetts atuais.
        Usado após 'Salvar'.
        """
        self.week_overrides.clear()
        self._update_overrides_label()
        # nada de recalc aqui!

    def _update_overrides_label(self):
        if not self.week_overrides:
            text = "Sem regras"
        else:
            parts = [f"{wk}→{qty}" for wk, qty in sorted(self.week_overrides.items())]
            text = "Regras: " + ", ".join(parts)
        if self._overrides_label is not None:
            self._overrides_label.configure(text=text)

    def auto_resize_columns(self):
        df = self.df_final if self.df_final is not None else pd.DataFrame(columns=self.colunas_exibidas)
        widths = {}
        for col in self.colunas_exibidas:
            base = [len(col)]
            if col in df.columns:
                base += [len(str(v)) for v in df[col].astype(str).head(200)]
            widths[col] = min(max(max(base) + 4, 12), 60)

        for col in self.colunas_exibidas:
            self.reported_tree.column(col, width=int(widths.get(col, 140)))

        if self.novos_tree is not None and self.df_novos is not None and not self.df_novos.empty:
            for col in self.colunas_exibidas[:-1]:
                self.novos_tree.column(col, width=int(widths.get(col, 140)))

        if self.removed_tree is not None and self.df_removed is not None and not self.df_removed.empty:
            for col in self.colunas_exibidas:
                self.removed_tree.column(col, width=int(widths.get(col, 140)))

    def sort_by_priority_asc(self):
        if self.df_final is None or self.df_final.empty:
            return
        self.df_final["_pri"] = self.df_final["Prioridade"].map(lambda v: PRIORITY_ORDER.get(canonicalize_priority(v), 999))
        self.df_final = self.df_final.sort_values(by=["_pri"], kind="stable").drop(columns=["_pri"]).reset_index(drop=True)
        self.render_main_table()

    def sort_by_priority_desc(self):
        if self.df_final is None or self.df_final.empty:
            return
        self.df_final["_pri"] = self.df_final["Prioridade"].map(lambda v: PRIORITY_ORDER.get(canonicalize_priority(v), -1))
        self.df_final = self.df_final.sort_values(by=["_pri"], ascending=False, kind="stable").drop(columns=["_pri"]).reset_index(drop=True)
        self.render_main_table()

    def export_excel(self):
        """Salva ListaAtualizada.xlsx (sheet 'Reparos') com as colunas da UI e limpa o chip de regras."""
        if self.df_final is None:
            return
        path = os.path.join(os.getcwd(), "ListaAtualizada.xlsx")
        df_out = self.df_final.copy()
        for c in COLS_UI:
            if c not in df_out.columns:
                df_out[c] = ""
        df_out = df_out[COLS_UI]
        df_out = denan(df_out)
        with pd.ExcelWriter(path, engine="openpyxl") as w:
            df_out.to_excel(w, index=False, sheet_name="Reparos")
            ws = w.book["Reparos"]
            ws.freeze_panes = "A2"
            for j, col in enumerate(df_out.columns, start=1):
                sample = max([len(str(col))] + [len(str(v)) for v in df_out[col].astype(str).head(200)])
                ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = min(max(sample + 4, 12), 60)

        # >>> após salvar, some o chip "Regras" (UI only; não recalcula)
        self._clear_week_overrides_ui_only()

    # ---------- Renderização ----------
    def _clear_tree(self, tree: ttk.Treeview):
        for it in tree.get_children():
            tree.delete(it)

    def _insert_zebra(self, tree, values, extra_tags=()):
        idx = len(tree.get_children())
        base_tag = "even" if idx % 2 == 0 else "odd"
        tree.insert("", "end", values=values, tags=(base_tag, *extra_tags))

    def render_main_table(self):
        pal = self._pal()
        self.reported_tree.tag_configure("even", background=pal["row_even"])
        self.reported_tree.tag_configure("odd", background=pal["row_odd"])
        self.reported_tree.tag_configure("changed", background=OPX_YELLOW, foreground=OPX_TEXT_DARK)

        self._clear_tree(self.reported_tree)
        if self.df_final is None or self.df_final.empty:
            return

        self.df_final = ensure_badges(self.df_final)
        self.df_final = denan(self.df_final)

        changed = getattr(self, "_changed_indices", set())
        for i, (_, row) in enumerate(self.df_final.iterrows()):
            vals = [row.get(c, "") for c in self.colunas_exibidas]
            extras = ("changed",) if i in changed else ()
            self._insert_zebra(self.reported_tree, vals, extra_tags=extras)

    def _render_novos_panel(self):
        if hasattr(self, "pane_novos") and self.pane_novos is not None:
            try:
                self.pane_novos.destroy()
            except Exception:
                pass
            self.pane_novos = None
            self.novos_tree = None
            self.btn_atualizar_novos = None

        if self.df_novos is None or self.df_novos.empty:
            return

        self.pane_novos = ctk.CTkFrame(self, corner_radius=12)
        self.pane_novos.pack(fill="both", expand=False, padx=14, pady=(0, 12))

        header = ctk.CTkFrame(self.pane_novos, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=(10, 0))

        lbl = ctk.CTkLabel(header, text=f"Novos ({len(self.df_novos)})", font=ctk.CTkFont(size=14, weight="bold"))
        lbl.pack(side="left", padx=(6, 8))

        self.btn_atualizar_novos = ctk.CTkButton(header, text="Atualizar",
                                                 command=self._transfer_all_novos, width=140)
        self._style_yellow_button(self.btn_atualizar_novos)
        self.btn_atualizar_novos.pack(side="left", padx=6)

        wrap = ctk.CTkFrame(self.pane_novos)
        wrap.pack(fill="both", expand=True, padx=8, pady=8)

        sy = ttk.Scrollbar(wrap, orient="vertical")
        sy.pack(side="right", fill="y")
        sx = ttk.Scrollbar(wrap, orient="horizontal")
        sx.pack(side="bottom", fill="x")

        cols_novos = self.colunas_exibidas[:-1]
        self.novos_tree = ttk.Treeview(
            wrap,
            columns=cols_novos,
            show="headings",
            style="OPX.Treeview",
            yscrollcommand=sy.set,
            xscrollcommand=sx.set,
            selectmode="extended",
        )
        self.novos_tree.pack(fill="both", expand=True)
        sy.config(command=self.novos_tree.yview)
        sx.config(command=self.novos_tree.xview)

        for col in cols_novos:
            self.novos_tree.heading(col, text=col, anchor="w")
            self.novos_tree.column(col, anchor="w", width=140, stretch=True)

        pal = self._pal()
        self.novos_tree.tag_configure("even", background=pal["row_even"])
        self.novos_tree.tag_configure("odd", background=pal["row_odd"])

        dfn = ensure_badges(self.df_novos)
        dfn = denan(dfn)
        for _, row in dfn.iterrows():
            vals = [row.get(c, "") for c in cols_novos]
            self._insert_zebra(self.novos_tree, vals)

        self.auto_resize_columns()

    def _render_removed_panel(self):
        if hasattr(self, "pane_removed") and self.pane_removed is not None:
            try:
                self.pane_removed.destroy()
            except Exception:
                pass
            self.pane_removed = None
            self.removed_tree = None
            self.btn_hide_removed = None

        if self.df_removed is None or self.df_removed.empty:
            return

        self.pane_removed = ctk.CTkFrame(self, corner_radius=12)
        self.pane_removed.pack(fill="both", expand=False, padx=14, pady=(0, 12))

        header = ctk.CTkFrame(self.pane_removed, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=(10, 0))

        lbl = ctk.CTkLabel(header, text=f"Removidos (finalizados no Monday) ({len(self.df_removed)})",
                           font=ctk.CTkFont(size=14, weight="bold"))
        lbl.pack(side="left", padx=(6, 8))

        self.btn_hide_removed = ctk.CTkButton(header, text="Ocultar",
                                              command=self._hide_removed_panel, width=120)
        self._style_yellow_button(self.btn_hide_removed)
        self.btn_hide_removed.pack(side="left", padx=6)

        wrap = ctk.CTkFrame(self.pane_removed)
        wrap.pack(fill="both", expand=True, padx=8, pady=8)

        sy = ttk.Scrollbar(wrap, orient="vertical")
        sy.pack(side="right", fill="y")
        sx = ttk.Scrollbar(wrap, orient="horizontal")
        sx.pack(side="bottom", fill="x")

        cols_removed = self.colunas_exibidas
        self.removed_tree = ttk.Treeview(
            wrap,
            columns=cols_removed,
            show="headings",
            style="OPX.Treeview",
            yscrollcommand=sy.set,
            xscrollcommand=sx.set,
            selectmode="browse",
        )
        self.removed_tree.pack(fill="both", expand=True)
        sy.config(command=self.removed_tree.yview)
        sx.config(command=self.removed_tree.xview)

        for col in cols_removed:
            self.removed_tree.heading(col, text=col, anchor="w")
            self.removed_tree.column(col, anchor="w", width=140, stretch=True)

        pal = self._pal()
        self.removed_tree.tag_configure("even", background=pal["row_even"])
        self.removed_tree.tag_configure("odd", background=pal["row_odd"])

        dfr = ensure_badges(self.df_removed)
        dfr = denan(dfr)
        for _, row in dfr.iterrows():
            vals = [row.get(c, "") for c in cols_removed]
            self._insert_zebra(self.removed_tree, vals)

        self.auto_resize_columns()

    def _hide_removed_panel(self):
        if self.pane_removed is not None:
            try:
                self.pane_removed.destroy()
            except Exception:
                pass
            self.pane_removed = None
            self.removed_tree = None
            self.btn_hide_removed = None

    # ---------- Transferência dos NOVOS ----------
    def _transfer_all_novos(self):
        if self.df_novos is None or self.df_novos.empty:
            return

        if self.df_final is None or self.df_final.empty:
            self.df_final = pd.DataFrame(columns=self.colunas_exibidas)

        for c in self.colunas_exibidas:
            if c not in self.df_final.columns:
                self.df_final[c] = ""

        prio_can = self.df_final["Prioridade"].map(canonicalize_priority) if not self.df_final.empty else pd.Series(dtype=str)

        for _, r in self.df_novos.iterrows():
            new_row = {
                "Status": r.get("Status", ""),
                "Elemento": r.get("Elemento", ""),
                "N° Proposta": r.get("N° Proposta", ""),
                "Cliente": r.get("Cliente", ""),
                "SN": r.get("SN", ""),
                "Prioridade": with_priority_badge(r.get("Prioridade", "")),
                "Data de Submissão": r.get("Data de Submissão", ""),
                "Targetts": "",
            }

            p_new = canonicalize_priority(new_row["Prioridade"])
            if self.df_final.empty:
                self.df_final = pd.concat([self.df_final, pd.DataFrame([new_row])], ignore_index=True)
                prio_can = pd.Series([p_new])
                continue

            same_idx = [i for i, v in enumerate(prio_can.tolist()) if v == p_new]
            if same_idx:
                insert_pos = max(same_idx) + 1
            else:
                insert_pos = len(self.df_final)

            top = self.df_final.iloc[:insert_pos].copy()
            bot = self.df_final.iloc[insert_pos:].copy()
            self.df_final = pd.concat([top, pd.DataFrame([new_row]), bot], ignore_index=True)
            prio_can = self.df_final["Prioridade"].map(canonicalize_priority)

        self.df_novos = pd.DataFrame()
        self._render_novos_panel()
        self.recalc_targets(keep_existing_week_caps=True)
        self.render_main_table()

    # ---------- Drag & Drop ----------
    def _on_tree_btn_press(self, event):
        region = self.reported_tree.identify("region", event.x, event.y)
        if region not in ("cell", "tree"):
            self._dragging = False
            return
        iid = self.reported_tree.identify_row(event.y)
        if not iid:
            self._dragging = False
            return
        self._dragging = True
        self._dragging_iid = iid
        self._drag_start_index = self.reported_tree.index(iid)
        self._last_drop_index = None
        self.reported_tree.selection_set(iid)
        self.reported_tree.focus(iid)

    def _autoscroll(self, y_local):
        border = 24
        h = self.reported_tree.winfo_height()
        if y_local < border:
            self.reported_tree.yview_scroll(-1, "units")
        elif y_local > h - border:
            self.reported_tree.yview_scroll(1, "units")

    def _on_tree_motion(self, event):
        if not self._dragging or not self._dragging_iid:
            return

        self._autoscroll(event.y)
        children = self.reported_tree.get_children()
        if not children:
            return

        dest_iid = self.reported_tree.identify_row(event.y)
        if not dest_iid:
            if event.y < 0:
                dest_index = 0
            else:
                dest_index = "end"
        else:
            dest_index = self.reported_tree.index(dest_iid)
            try:
                first_col = self.colunas_exibidas[0]
                _, yrow, _, h = self.reported_tree.bbox(dest_iid, first_col)
                if event.y > yrow + h / 2:
                    dest_index += 1
            except Exception:
                pass

        cur_index = self.reported_tree.index(self._dragging_iid)

        if dest_index == "end":
            if cur_index != len(children) - 1:
                self.reported_tree.move(self._dragging_iid, "", "end")
                self._last_drop_index = len(children) - 1
        else:
            dest_index = max(0, min(dest_index, len(children) - 1))
            if dest_index != cur_index:
                self.reported_tree.move(self._dragging_iid, "", dest_index)
                self._last_drop_index = dest_index

    def _on_tree_btn_release(self, event):
        if not self._dragging:
            return
        self._dragging = False

        rows = []
        for iid in self.reported_tree.get_children():
            vals = self.reported_tree.item(iid, "values")
            rows.append(dict(zip(self.colunas_exibidas, vals)))
        self.df_final = pd.DataFrame(rows, columns=self.colunas_exibidas)

        # Recalcula mantendo capacidades já salvas por semana
        self.recalc_targets(keep_existing_week_caps=True)

        if self._last_drop_index is not None:
            self._select_row_by_index(self._last_drop_index)

    # ---------- Utilidades ----------
    def _select_row_by_index(self, idx: int):
        kids = self.reported_tree.get_children()
        if not kids:
            return
        idx = max(0, min(idx, len(kids) - 1))
        iid = kids[idx]
        self.reported_tree.selection_set(iid)
        self.reported_tree.focus(iid)
        self.reported_tree.see(iid)

    def get_current_df_from_tree(self, tree: ttk.Treeview, cols: list[str]) -> pd.DataFrame:
        rows = []
        for iid in tree.get_children():
            vals = tree.item(iid, "values")
            rows.append(dict(zip(cols, vals)))
        return pd.DataFrame(rows, columns=cols)

# Helper para criar um DF vazio com as colunas da lista principal (sem Targetts)
def df_final_like():
    return pd.DataFrame(columns=["Status", "Elemento", "N° Proposta", "Cliente", "SN", "Prioridade", "Data de Submissão"])


if __name__ == "__main__":
    app = SimpleTable()
    app.mainloop()
