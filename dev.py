# =================== Imports ===================
import os
import json
import threading
from datetime import datetime, timedelta
import unicodedata
import re
import uuid
import pandas as pd
import customtkinter as ctk
from tkinter import ttk, messagebox

# Monday export (jsonExport.py)
try:
    from jsonExport import dataMondaytoJson
    HAVE_MONDAY_EXPORT = True
except Exception:
    HAVE_MONDAY_EXPORT = False

# PIL (imagens) opcional
try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# =================== Tema / Paleta ===================
OPX_YELLOW = "#ffbb00"

THEMES = {
    "Dark": {
        "bg": "#0B1221",
        "bg2": "#111827",
        "fg": "#E5E7EB",
        "muted": "#94A3B8",
        "row_even": "#0F172A",
        "row_odd":  "#0B1221",
        "sel_bg": "#1F2937",
        "sel_fg": "#E5E7EB",
        "header_bg": "#0F172A",
        "header_fg": "#E5E7EB",
        "border": "#1F2937",
        "chip_bg": "#1E293B",
    },
    "Light": {
        "bg": "#F1F5F9",
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

# >>> Iniciar CLARO <<<
ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

# =================== Colunas / Chaves ===================
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
KEY_COLS = ["Elemento", "Cliente", "SN"]

PRIORITY_BADGE_MAP = {
    "SEVERA": "🟥 SEVERA",
    "ALTA":   "🟧 ALTA",
    "MÉDIA":  "🟦 MÉDIA",
    "LEVE":   "🟩 LEVE",
}
PRIORITY_ORDER = {"SEVERA": 0, "ALTA": 1, "MÉDIA": 2, "LEVE": 3}

# =================== Helpers ===================
def _strip_accents(s: str) -> str:
    if not isinstance(s, str):
        try: s = str(s)
        except Exception: return ""
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def canonicalize_priority(val: str) -> str:
    if not val: return ""
    s = _strip_accents(str(val)).upper().strip()
    s = s.replace("🟥","").replace("🟧","").replace("🟦","").replace("🟩","").strip()
    if "SEVER" in s: return "SEVERA"
    if "ALTA"  in s: return "ALTA"
    if "MEDIA" in s or "MÉDIA" in s: return "MÉDIA"
    if "LEVE"  in s: return "LEVE"
    return ""

def with_priority_badge(val: str) -> str:
    base = canonicalize_priority(val)
    return PRIORITY_BADGE_MAP.get(base, val if val is not None else "")

def ensure_badges(df: pd.DataFrame) -> pd.DataFrame:
    if "Prioridade" in df.columns:
        df = df.copy()
        df["Prioridade"] = df["Prioridade"].map(with_priority_badge)
    return df

def denan(df: pd.DataFrame) -> pd.DataFrame:
    if df is None: return pd.DataFrame()
    return df.fillna("")

# =================== Monday JSON → DataFrame ===================
def get_monday_data_from_json():
    with open("monday_export_all.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", [])
    records = []
    for item in items:
        r = {"Name": item.get("name", "")}
        r["_item_id"] = str(item.get("id", ""))
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
    if "due_date" in df.columns and pd.api.types.is_datetime64_any_dtype(df["due_date"]):
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
        "_item_id": "_item_id",
    }
    df.rename(columns=mapping, inplace=True)
    if "_item_id" not in df.columns:
        df["_item_id"] = df.get("id", "").astype(str)
    base_cols = ["Elemento","Subelementos","N° Proposta","Cliente","SN","Prioridade","Status","Data de Submissão","_item_id"]
    for c in base_cols:
        if c not in df.columns: df[c] = ""
    df = df[base_cols]
    return denan(df)

def read_lista_excel() -> pd.DataFrame | None:
    path = os.path.join(os.getcwd(), "ListaAtualizada.xlsx")
    if not os.path.exists(path): return None
    try:
        df = pd.read_excel(path, sheet_name="Reparos")
        for c in COLS_UI:
            if c not in df.columns: df[c] = ""
        if "_item_id" not in df.columns: df["_item_id"] = ""
        cols = ["_item_id"] + [c for c in COLS_UI if c != "_item_id"]
        df = df[cols]
        return denan(df)
    except Exception:
        return None

# =================== Diff por _item_id ===================
def _keys_from_ids(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty: return pd.Series(dtype=str)
    if "_item_id" not in df.columns: return pd.Series(index=df.index, data="", dtype=str)
    return df["_item_id"].astype(str).str.strip()

def diff_new_items(df_monday_ptbr: pd.DataFrame, df_lista: pd.DataFrame) -> pd.DataFrame:
    cols = ["_item_id","Status","Elemento","N° Proposta","Cliente","SN","Prioridade","Data de Submissão"]
    if df_monday_ptbr is None or df_monday_ptbr.empty:
        return pd.DataFrame(columns=cols)
    if df_lista is None or df_lista.empty:
        return df_monday_ptbr[cols].copy()
    novos_ids = set(_keys_from_ids(df_monday_ptbr)) - set(_keys_from_ids(df_lista))
    mask = df_monday_ptbr["_item_id"].astype(str).str.strip().isin(novos_ids)
    return df_monday_ptbr.loc[mask, cols].copy()

def diff_finished_items(df_monday_ptbr: pd.DataFrame, df_lista: pd.DataFrame) -> pd.DataFrame:
    if df_lista is None or df_lista.empty:
        return pd.DataFrame(columns=COLS_UI)
    if df_monday_ptbr is None or df_monday_ptbr.empty:
        finished = df_lista.copy()
        for c in COLS_UI:
            if c not in finished.columns: finished[c] = ""
        return finished[COLS_UI]
    remov_ids = set(_keys_from_ids(df_lista)) - set(_keys_from_ids(df_monday_ptbr))
    if "_item_id" not in df_lista.columns:
        return pd.DataFrame(columns=COLS_UI)
    mask = df_lista["_item_id"].astype(str).str.strip().isin(remov_ids)
    finished = df_lista.loc[mask].copy()
    for c in COLS_UI:
        if c not in finished.columns: finished[c] = ""
    return finished[COLS_UI]

# =================== Sync de campos por _item_id ===================
def apply_updates_from_monday(df_final: pd.DataFrame,
                              df_monday_ptbr: pd.DataFrame,
                              update_cols: list[str]) -> tuple[int, int]:
    """
    Atualiza df_final *in-place* para os _item_id existentes,
    copiando os valores de update_cols que vieram do Monday.
    Retorna (linhas_atualizadas, celulas_alteradas).
    """
    if df_final is None or df_final.empty:
        return 0, 0
    if df_monday_ptbr is None or df_monday_ptbr.empty:
        return 0, 0
    if "_item_id" not in df_final.columns or "_item_id" not in df_monday_ptbr.columns:
        return 0, 0

    mon = df_monday_ptbr.set_index("_item_id")
    changed_rows = 0
    changed_cells = 0

    ids = df_final["_item_id"].astype(str).str.strip()
    for i, rid in enumerate(ids):
        if not rid or rid not in mon.index:
            continue

        row_changed = 0
        for col in update_cols:
            new_val = mon.at[rid, col] if col in mon.columns else ""
            if col == "Prioridade":
                new_val = with_priority_badge(new_val)  # preserva o badge
            old_val = df_final.at[i, col] if col in df_final.columns else ""
            if str(old_val) != str(new_val):
                df_final.at[i, col] = new_val
                changed_cells += 1
                row_changed += 1

        if row_changed:
            changed_rows += 1

    return changed_rows, changed_cells

# =================== Targets ===================
def monday_of_week(d: datetime) -> datetime:
    return d - timedelta(days=d.weekday()) if d.weekday() < 5 else d + timedelta(days=(7 - d.weekday()))

def _parse_week_from_label(label: str) -> int | None:
    if not label: return None
    m = re.search(r"Semana\s+(\d{1,2})\b", str(label))
    return int(m.group(1)) if m else None

def generate_targets(n, start_date_str="28/08/2025", default_per_week=5, week_overrides=None, start_from_next_week=True):
    week_overrides = week_overrides or {}
    start = datetime.strptime(start_date_str, "%d/%m/%Y")
    week_monday = monday_of_week(start)
    current_week_start = week_monday + timedelta(days=7 if start_from_next_week else 0)
    targets, assigned = [], 0
    def iso_week_of(d: datetime) -> int: return int(d.isocalendar()[1])
    while assigned < n:
        week_num = iso_week_of(current_week_start)
        cap = week_overrides.get(week_num, default_per_week)
        if cap < 0: cap = 0
        for _ in range(cap):
            if assigned >= n: break
            label = f"Semana {week_num:02d} - {current_week_start.strftime('%d/%m/%Y')}"
            targets.append(label); assigned += 1
        current_week_start += timedelta(days=7)
    return targets

# =================== Modal de Carregamento ===================
class LoadingDialog(ctk.CTkToplevel):
    def __init__(self, parent, title="Carregando...", total=8):
        super().__init__(parent)
        self.title(title); self.resizable(False, False); self.transient(parent); self.grab_set()
        self.total = max(1, int(total)); self.progress_val = 0.0
        self.update_idletasks()
        w, h = 380, 140
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (w // 2)
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")
        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(18, 8))
        self.msg = ctk.CTkLabel(self, text="Iniciando...", wraplength=320); self.msg.pack(pady=(0, 8))
        self.pb = ctk.CTkProgressBar(self); self.pb.pack(fill="x", padx=20, pady=(0, 14)); self.pb.set(0)
        self.cancelled = False
        self.btn_cancel = ctk.CTkButton(self, text="Cancelar", command=self._cancel, width=120)
        self.btn_cancel.pack(pady=(0, 10))
        self.protocol("WM_DELETE_WINDOW", self._cancel)
    def _cancel(self): self.cancelled = True
    def update_progress(self, step: int, text: str = ""):
        step = max(0, min(step, self.total)); self.pb.set(step / float(self.total))
        if text: self.msg.configure(text=text)
        self.update_idletasks()
    def close(self):
        try: self.grab_release()
        except Exception: pass
        self.destroy()

# =================== App (UI) ===================
class SimpleTable(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Fila de Reparos · OPx")
        self.geometry("1320x860")
        self.minsize(1100, 650)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Estado
        self.start_date_str = ctk.StringVar(value="28/08/2025")
        self.max_per_week   = ctk.StringVar(value="5")
        self.appearance     = ctk.StringVar(value="Light")  # começa CLARO

        self.week_overrides: dict[int, int] = {}
        self.week_override_week = ctk.StringVar(value="")
        self.week_override_qty  = ctk.StringVar(value="")
        self._overrides_label = None

        # Exportador Monday
        self.mondayDataUpdate = dataMondaytoJson() if HAVE_MONDAY_EXPORT else type("Noop", (), {"mondayToJson": lambda *_: None})()

        self.colunas_exibidas = COLS_UI[:]
        self.df_final   = pd.DataFrame(columns=["_item_id"] + self.colunas_exibidas)
        self.df_novos   = pd.DataFrame()
        self.df_removed = pd.DataFrame()

        # Assets
        self._img_logo = None
        self._img_sun  = None
        self._img_moon = None

        self._setup_theme()
        self._build_ui()
        self.load_data_initial()

    # ---------- Tema ----------
    def _setup_theme(self):
        ctk.set_appearance_mode(self.appearance.get())
        theme = THEMES.get(self.appearance.get(), THEMES["Light"])
        self.configure(fg_color=theme["bg"])

    def _setup_tree_style(self):
        theme = THEMES.get(self.appearance.get(), THEMES["Light"])
        style = ttk.Style()
        style.configure(
            "OPX.Treeview",
            background=theme["row_even"],
            fieldbackground=theme["row_even"],
            foreground=theme["fg"],
            rowheight=28,
            bordercolor=theme["border"],
            font=("Segoe UI", 10),
        )
        style.map("OPX.Treeview",
                  background=[("selected", theme["sel_bg"])],
                  foreground=[("selected", theme["sel_fg"])])
        style.configure(
            "OPX.Treeview.Heading",
            background=theme["header_bg"],
            foreground=theme["header_fg"],
            font=("Segoe UI Semibold", 10),
            bordercolor=theme["border"],
        )
        style.map("OPX.Treeview.Heading", background=[("active", theme["header_bg"])])

    def _update_theme_icon(self):
        if not hasattr(self, "btn_theme"): return
        current = self.appearance.get()
        try:
            # Em Light mostra LUA (clicar → Dark). Em Dark mostra SOL (clicar → Light).
            if current == "Light" and self._img_moon:
                self.btn_theme.configure(image=self._img_moon)
            elif current == "Dark" and self._img_sun:
                self.btn_theme.configure(image=self._img_sun)
        except Exception:
            pass

    def _toggle_theme(self):
        self.appearance.set("Dark" if self.appearance.get() == "Light" else "Light")
        self._on_theme_change()

    def _on_theme_change(self):
        self._setup_theme()
        self._setup_tree_style()
        self._update_theme_icon()
        self.render_main_table()

    def _load_images(self):
        # Logo
        if PIL_AVAILABLE and os.path.exists("opx.jpeg"):
            try:
                self._img_logo = ctk.CTkImage(
                    dark_image=Image.open("opx.jpeg"),
                    light_image=Image.open("opx.jpeg"),
                    size=(28, 28)
                )
            except Exception:
                self._img_logo = None
        # Ícones tema
        if PIL_AVAILABLE:
            try:
                if os.path.exists("sun.png"):
                    self._img_sun = ctk.CTkImage(
                        dark_image=Image.open("sun.png"),
                        light_image=Image.open("sun.png"),
                        size=(20, 20)
                    )
                if os.path.exists("moon.png"):
                    self._img_moon = ctk.CTkImage(
                        dark_image=Image.open("moon.png"),
                        light_image=Image.open("moon.png"),
                        size=(20, 20)
                    )
            except Exception:
                self._img_sun = self._img_moon = None

    # ---------- UI ----------
    def _build_ui(self):
        theme = THEMES.get(self.appearance.get(), THEMES["Light"])
        self._load_images()

        # Header
        self.header = ctk.CTkFrame(self, fg_color=theme["bg2"])
        self.header.pack(fill="x", padx=12, pady=12)

        # grade do cabeçalho
        self.header.grid_columnconfigure(0, weight=0)  # logo
        self.header.grid_columnconfigure(1, weight=1)  # título
        self.header.grid_columnconfigure(2, weight=0)  # botão tema
        self.header.grid_columnconfigure(3, weight=0)  # controles
        self.header.grid_rowconfigure(0, weight=0)
        self.header.grid_rowconfigure(1, weight=0)

        # Logo
        if self._img_logo:
            ctk.CTkLabel(self.header, image=self._img_logo, text="").grid(row=0, column=0, padx=(12, 6), pady=(10, 2), sticky="w")

        # Título
        brand = ctk.CTkLabel(self.header, text="Fila de Reparos · OPx", font=ctk.CTkFont(size=18, weight="bold"))
        brand.grid(row=0, column=1, padx=(6, 12), pady=(10, 2), sticky="w")

        # Botão Tema
        self.btn_theme = ctk.CTkButton(
            self.header, width=36, height=36, text="",
            command=self._toggle_theme, fg_color="transparent", hover=True
        )
        self.btn_theme.grid(row=0, column=2, padx=8, pady=(6, 2), sticky="e")
        self._update_theme_icon()

        # Controles (lado direito)
        controls = ctk.CTkFrame(self.header, fg_color="transparent")
        controls.grid(row=0, column=3, rowspan=2, sticky="e", padx=12, pady=10)

        ctk.CTkLabel(controls, text="Data inicial").grid(row=0, column=0, padx=(0, 8))
        self.entry_date = ctk.CTkEntry(controls, width=120, textvariable=self.start_date_str, placeholder_text="DD/MM/AAAA", justify="center")
        self.entry_date.grid(row=0, column=1, padx=(0, 16))

        ctk.CTkLabel(controls, text="Máx/semana").grid(row=0, column=2, padx=(0, 8))
        self.opt_max = ctk.CTkOptionMenu(
            controls, variable=self.max_per_week, values=["3","4","5","6","7"],
            fg_color=OPX_YELLOW, button_color=OPX_YELLOW, button_hover_color=OPX_YELLOW, text_color="#0F172A"
        )
        self.opt_max.grid(row=0, column=3, padx=(0, 10))

        # Semana custom
        week_frame = ctk.CTkFrame(self.header, fg_color="transparent")
        week_frame.grid(row=1, column=0, columnspan=4, sticky="we", padx=12, pady=(2, 10))

        ctk.CTkLabel(week_frame, text="Semana").grid(row=0, column=0, padx=(0, 8))
        self.entry_week_num = ctk.CTkEntry(week_frame, width=72, textvariable=self.week_override_week, placeholder_text="ex: 40", justify="center")
        self.entry_week_num.grid(row=0, column=1)

        ctk.CTkLabel(week_frame, text="Capacidade").grid(row=0, column=2, padx=(10, 6))
        self.entry_week_qty = ctk.CTkEntry(week_frame, width=72, textvariable=self.week_override_qty, placeholder_text="5", justify="center")
        self.entry_week_qty.grid(row=0, column=3)

        self.btn_apply_week = ctk.CTkButton(week_frame, text="Aplicar semana", command=self._apply_week_override, width=150)
        self._style_yellow_button(self.btn_apply_week)
        self.btn_apply_week.grid(row=0, column=4, padx=(10, 6))

        self.btn_clear_weeks = ctk.CTkButton(week_frame, text="Limpar regras", command=self._clear_week_overrides, width=130)
        self._style_yellow_button(self.btn_clear_weeks)
        self.btn_clear_weeks.grid(row=0, column=5, padx=(2, 10))

        self._overrides_label = ctk.CTkLabel(week_frame, text="Sem regras")
        self._overrides_label.grid(row=0, column=6, padx=(14, 0))

        # Corpo
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Barra de ações
        actions = ctk.CTkFrame(container, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=(12, 6))
        left_actions = ctk.CTkFrame(actions, fg_color="transparent")
        left_actions.pack(side="left")

        self.btn_reload = ctk.CTkButton(left_actions, text="Atualizar dados", command=self.on_click_atualizar_async, width=300)
        self._style_yellow_button(self.btn_reload); self.btn_reload.pack(side="left", padx=(0, 8))

        self.btn_transfer = ctk.CTkButton(left_actions, text="Transferir novos → Lista", command=self._transfer_all_novos, width=220)
        self._style_yellow_button(self.btn_transfer); self.btn_transfer.pack(side="left", padx=(0, 8))

        self.btn_sort_asc = ctk.CTkButton(left_actions, text="Prioridade ↑", command=self.sort_by_priority_asc, width=140)
        self._style_yellow_button(self.btn_sort_asc); self.btn_sort_asc.pack(side="left", padx=8)

        self.btn_sort_desc = ctk.CTkButton(left_actions, text="Prioridade ↓", command=self.sort_by_priority_desc, width=140)
        self._style_yellow_button(self.btn_sort_desc); self.btn_sort_desc.pack(side="left", padx=(0, 8))

        self.btn_export = ctk.CTkButton(left_actions, text="Salvar", command=self.export_excel, width=140)
        self._style_yellow_button(self.btn_export); self.btn_export.pack(side="left", padx=(0, 8))

        # Árvore principal
        main_wrap = ctk.CTkFrame(container, fg_color="transparent")
        main_wrap.pack(fill="both", expand=True, padx=2, pady=(4, 10))

        self.scroll_y = ttk.Scrollbar(main_wrap, orient="vertical"); self.scroll_y.pack(side="right", fill="y")
        self.scroll_x = ttk.Scrollbar(main_wrap, orient="horizontal"); self.scroll_x.pack(side="bottom", fill="x")

        self._setup_tree_style()
        self.reported_tree = ttk.Treeview(
            main_wrap, columns=self.colunas_exibidas, show="headings", style="OPX.Treeview",
            yscrollcommand=self.scroll_y.set, xscrollcommand=self.scroll_x.set, selectmode="extended",
        )
        self.reported_tree.pack(fill="both", expand=True, padx=0, pady=0)
        self._enable_row_dnd()
        self.scroll_y.configure(command=self.reported_tree.yview)
        self.scroll_x.configure(command=self.reported_tree.xview)

        for col in self.colunas_exibidas:
            self.reported_tree.heading(col, text=col, anchor="center")
            self.reported_tree.column(col, anchor="center", width=140)

        # Painéis “Novos/Removidos”
        self._novos_frame = ctk.CTkFrame(container, fg_color="transparent");   self._novos_frame.pack(fill="x", padx=4, pady=(0, 8))
        self._removed_frame = ctk.CTkFrame(container, fg_color="transparent"); self._removed_frame.pack(fill="x", padx=4, pady=(0, 8))

    def _style_yellow_button(self, btn: ctk.CTkButton):
        btn.configure(fg_color=OPX_YELLOW, hover_color="#ffcc33", text_color="#0F172A")

    # ---------- Carregamento inicial ----------
    def load_data_initial(self):
        df_lista = read_lista_excel()
        if df_lista is not None and not df_lista.empty:
            self.df_final = denan(df_lista.copy())
        else:
            self.df_final = pd.DataFrame(columns=["_item_id"] + COLS_UI)

        try:
            if os.path.exists("monday_export_all.json"):
                df_monday_ptbr = map_monday_to_ptbr(get_monday_data_from_json())
                self.df_novos = diff_new_items(df_monday_ptbr, self.df_final)
                self.df_removed = diff_finished_items(df_monday_ptbr, self.df_final)
        except Exception:
            self.df_novos = pd.DataFrame(); self.df_removed = pd.DataFrame()

        self.df_final = ensure_badges(self.df_final)
        self.render_main_table()
        self._render_novos_panel()
        self._render_removed_panel()

    # ---------- Atualizar dados ----------
    def on_click_atualizar_async(self):
        total_steps = 8
        dlg = LoadingDialog(self, title="Atualizando dados…", total=total_steps)
        self.btn_reload.configure(state="disabled")

        def ui_progress(step, text=""):
            try:
                if dlg.cancelled: return
                dlg.update_progress(step, text)
            except Exception: pass

        def ui_finish(n_novos, n_rem, n_upd, error=None):
            try: dlg.close()
            except Exception: pass
            self.btn_reload.configure(state="normal")
            if error:
                messagebox.showerror("Erro ao atualizar", f"Ocorreu um erro na atualização:\n{error}")
            else:
                messagebox.showinfo(
                    "Atualização concluída",
                    f"Novos: {n_novos}\nRemovidos: {n_rem}\nAtualizados: {n_upd}\n\nComparação por _item_id."
                )

        def worker():
            step = 0
            updated_rows = 0
            try:
                # 1) Baixar do Monday
                step += 1; self.after(0, ui_progress, step, "Conectando ao Monday…")
                if dlg.cancelled: return self.after(0, ui_finish, 0, 0, 0, None)
                try:
                    self.mondayDataUpdate.mondayToJson()  # grava monday_export_all.json
                except Exception as e:
                    if HAVE_MONDAY_EXPORT: raise e

                # 2) Ler JSON
                step += 1; self.after(0, ui_progress, step, "Lendo JSON do Monday…")
                if dlg.cancelled: return self.after(0, ui_finish, 0, 0, 0, None)
                df_monday_raw = get_monday_data_from_json() if os.path.exists("monday_export_all.json") else pd.DataFrame()

                # 3) Mapear PT-BR
                step += 1; self.after(0, ui_progress, step, "Mapeando colunas…")
                if dlg.cancelled: return self.after(0, ui_finish, 0, 0, 0, None)
                df_monday_ptbr = map_monday_to_ptbr(df_monday_raw) if df_monday_raw is not None else pd.DataFrame()

                # 4) Ler lista atual
                step += 1; self.after(0, ui_progress, step, "Carregando ListaAtualizada.xlsx…")
                if dlg.cancelled: return self.after(0, ui_finish, 0, 0, 0, None)
                df_lista = read_lista_excel()
                if df_lista is not None and not df_lista.empty:
                    self.df_final = denan(df_lista.copy())
                else:
                    if getattr(self, "df_final", None) is None or self.df_final.empty:
                        self.df_final = pd.DataFrame(columns=["_item_id"] + COLS_UI)

                # 5) Diffs por _item_id
                step += 1; self.after(0, ui_progress, step, "Calculando diferenças…")
                if dlg.cancelled: return self.after(0, ui_finish, 0, 0, 0, None)
                self.df_novos   = diff_new_items(df_monday_ptbr, self.df_final) if df_monday_ptbr is not None else pd.DataFrame(columns=COLS_UI)
                self.df_removed = diff_finished_items(df_monday_ptbr, self.df_final) if df_monday_ptbr is not None else pd.DataFrame(columns=COLS_UI)

                # 6) Aplicar atualizações de campos para IDs que permaneceram
                step += 1; self.after(0, ui_progress, step, "Aplicando atualizações em itens existentes…")
                if dlg.cancelled: return self.after(0, ui_finish, 0, 0, 0, None)
                cols_to_update = ["Elemento", "N° Proposta", "Cliente", "SN", "Prioridade", "Data de Submissão"]
                # Se quiser incluir "Status", descomente:
                # cols_to_update.append("Status")
                updated_rows, _updated_cells = apply_updates_from_monday(self.df_final, df_monday_ptbr, cols_to_update)

                # 7) Harmonizar lista (com trava se Monday vier vazio)
                step += 1; self.after(0, ui_progress, step, "Harmonizando lista…")
                if dlg.cancelled: return self.after(0, ui_finish, 0, 0, 0, None)
                if (
                    df_monday_ptbr is not None
                    and not df_monday_ptbr.empty
                    and not self.df_final.empty
                    and "_item_id" in self.df_final.columns
                    and "_item_id" in df_monday_ptbr.columns
                ):
                    set_cur = set(df_monday_ptbr["_item_id"].astype(str).str.strip())
                    self.df_final = self.df_final[
                        self.df_final["_item_id"].astype(str).str.strip().isin(set_cur) |
                        (self.df_final["_item_id"].astype(str).str.strip() == "")
                    ].reset_index(drop=True)

                # 8) Badges/NaN + render
                step += 1; self.after(0, ui_progress, step, "Renderizando…")
                if dlg.cancelled: return self.after(0, ui_finish, 0, 0, 0, None)
                self.df_final   = ensure_badges(self.df_final)  if self.df_final   is not None else pd.DataFrame(columns=["_item_id"] + COLS_UI)
                self.df_removed = ensure_badges(self.df_removed) if self.df_removed is not None else pd.DataFrame()
                self.df_final   = denan(self.df_final)
                self.df_removed = denan(self.df_removed)

                self.after(0, self.render_main_table)
                self.after(0, self._render_novos_panel)
                self.after(0, self._render_removed_panel)

                n_novos = 0 if self.df_novos is None else len(self.df_novos.index)
                n_rem   = 0 if self.df_removed is None else len(self.df_removed.index)
                self.after(0, ui_finish, n_novos, n_rem, updated_rows, None)
            except Exception as e:
                self.after(0, ui_finish, 0, 0, 0, str(e))

        threading.Thread(target=worker, daemon=True).start()

    # ---------- Renderização ----------
    def _clear_tree(self, tree: ttk.Treeview):
        for it in tree.get_children(): tree.delete(it)

    def render_main_table(self):
        self._setup_tree_style()
        for it in self.reported_tree.get_children():
            self.reported_tree.delete(it)
        self._iid_index_map = {}
        if self.df_final is None or self.df_final.empty: return

        for idx, row in self.df_final.reset_index(drop=True).iterrows():
            rid = str(row.get("_item_id", "")).strip()
            iid = f"id-{rid}" if rid else f"tmp-{idx}"
            if iid.startswith("tmp-"): self._iid_index_map[iid] = idx
            values = [row.get(c, "") for c in self.colunas_exibidas]
            try:
                self.reported_tree.insert("", "end", iid=iid, values=values)
            except Exception:
                uid = f"{iid}-{uuid.uuid4().hex[:6]}"
                self.reported_tree.insert("", "end", iid=uid, values=values)

        widths = {}
        df = self.df_final.copy()
        for col in self.colunas_exibidas:
            base = [len(str(col))] + [len(str(v)) for v in df[col].astype(str).head(200)]
            widths[col] = min(max(max(base) + 4, 12), 60)
        for col in self.colunas_exibidas:
            self.reported_tree.column(col, width=int(widths.get(col, 140)))

    # ---------- Drag & Drop ----------
    def _enable_row_dnd(self):
        self._dnd_active = False; self._dnd_src_iid = None
        self.reported_tree.bind("<ButtonPress-1>", self._on_drag_start)
        self.reported_tree.bind("<B1-Motion>", self._on_drag_motion)
        self.reported_tree.bind("<ButtonRelease-1>", self._on_drag_release)

    def _on_drag_start(self, event):
        iid = self.reported_tree.identify_row(event.y)
        if not iid:
            self._dnd_active = False; self._dnd_src_iid = None; return
        self._dnd_active = True; self._dnd_src_iid = iid

    def _on_drag_motion(self, event):
        if not self._dnd_active or not self._dnd_src_iid: return
        y = event.y; height = self.reported_tree.winfo_height()
        if y < 20: self.reported_tree.yview_scroll(-1, "units")
        elif y > height - 20: self.reported_tree.yview_scroll(1, "units")
        target_iid = self.reported_tree.identify_row(y)
        if not target_iid or target_iid == self._dnd_src_iid: return
        parent = ""; children = list(self.reported_tree.get_children(parent))
        try:
            target_index = children.index(target_iid)
            self.reported_tree.move(self._dnd_src_iid, parent, target_index)
        except Exception:
            pass

    def _on_drag_release(self, event):
        if not self._dnd_active or not self._dnd_src_iid: return
        self._dnd_active = False
        try:
            self._rebuild_df_from_tree_order()
            self.recalc_targets(keep_existing_week_caps=True)
            self.render_main_table()
        finally:
            self._dnd_src_iid = None

    def _rebuild_df_from_tree_order(self):
        if self.df_final is None or self.df_final.empty: return
        ordered_iids = list(self.reported_tree.get_children(""))
        if not ordered_iids: return
        idx_order, used = [], set()
        df = self.df_final.reset_index(drop=True).copy()
        id_to_idx = {str(v).strip(): i for i, v in enumerate(df["_item_id"].tolist())} if "_item_id" in df.columns else {}
        for iid in ordered_iids:
            if iid.startswith("id-"):
                rid = iid[3:]; i = id_to_idx.get(rid, None)
                if i is not None and i not in used: idx_order.append(i); used.add(i)
            elif iid.startswith("tmp-"):
                i = getattr(self, "_iid_index_map", {}).get(iid, None)
                if i is not None and i not in used: idx_order.append(i); used.add(i)
        for i in range(len(df)):
            if i not in used: idx_order.append(i)
        self.df_final = df.iloc[idx_order].reset_index(drop=True)

    def _render_novos_panel(self):
        for w in self._novos_frame.winfo_children(): w.destroy()
        lbl = ctk.CTkLabel(self._novos_frame, text=f"Novos: {0 if self.df_novos is None else len(self.df_novos.index)}")
        lbl.pack(anchor="w")
        if self.df_novos is None or self.df_novos.empty: return
        self.novos_tree = ttk.Treeview(self._novos_frame, columns=self.colunas_exibidas, show="headings", height=6, style="OPX.Treeview")
        self.novos_tree.pack(fill="x", padx=0, pady=(6, 0))
        for col in self.colunas_exibidas[:-1]:
            self.novos_tree.heading(col, text=col, anchor="center")
            self.novos_tree.column(col, anchor="center", width=140)
        for _, r in self.df_novos.iterrows():
            self.novos_tree.insert("", "end", values=[r.get(c, "") for c in self.colunas_exibidas])

    def _render_removed_panel(self):
        for w in self._removed_frame.winfo_children(): w.destroy()
        lbl = ctk.CTkLabel(self._removed_frame, text=f"Removidos: {0 if self.df_removed is None else len(self.df_removed.index)}")
        lbl.pack(anchor="w")
        if self.df_removed is None or self.df_removed.empty: return
        self.removed_tree = ttk.Treeview(self._removed_frame, columns=self.colunas_exibidas, show="headings", height=5, style="OPX.Treeview")
        self.removed_tree.pack(fill="x", padx=0, pady=(6, 0))
        for col in self.colunas_exibidas:
            self.removed_tree.heading(col, text=col, anchor="center")
            self.removed_tree.column(col, anchor="center", width=140)
        for _, r in self.df_removed.iterrows():
            self.removed_tree.insert("", "end", values=[r.get(c, "") for c in self.colunas_exibidas])

    # ---------- Regras semanais ----------
    def _update_overrides_label(self):
        text = "Sem regras" if not self.week_overrides else "Regras: " + ", ".join(f"S{w}:{q}" for w,q in sorted(self.week_overrides.items()))
        if self._overrides_label is not None: self._overrides_label.configure(text=text)

    def _indices_of_week(self, week_num: int) -> list[int]:
        if self.df_final is None or self.df_final.empty or "Targetts" not in self.df_final.columns: return []
        week_num = int(week_num); s1 = f"Semana {week_num:02d} - "; s2 = f"Semana {week_num} - "
        idxs = []
        for i, v in enumerate(self.df_final["Targetts"].astype(str).tolist()):
            if v.startswith(s1) or v.startswith(s2): idxs.append(i)
        return idxs

    def _clear_changed_highlight(self):
        try:
            for iid in self.reported_tree.get_children():
                self.reported_tree.item(iid, tags=())
        except Exception:
            pass

    def _apply_week_override(self):
        try:
            w = int((self.week_override_week.get() or "").strip())
            q = int((self.week_override_qty.get() or "").strip())
        except Exception:
            messagebox.showerror("Regra inválida", "Preencha 'Semana' e 'Capacidade' com números inteiros.")
            return
        if not (0 <= w <= 53) or q < 0:
            messagebox.showerror("Regra inválida", "Semana deve estar entre 0 e 53, e a capacidade deve be ≥ 0.")
            return
        self.week_overrides[w] = q
        self._update_overrides_label()
        self.recalc_targets(keep_existing_week_caps=True)
        self._clear_changed_highlight()
        self.render_main_table()
        messagebox.showinfo("Regra aplicada", f"Semana {w} definida com capacidade {q}.")

    def _clear_week_overrides(self):
        self.week_overrides.clear()
        self._update_overrides_label()
        self.recalc_targets(keep_existing_week_caps=False)
        messagebox.showinfo("Regras limpas", "Todas as regras semanais foram removidas.")

    def _infer_week_caps_from_current_df(self) -> dict[int, int]:
        caps: dict[int, int] = {}
        if self.df_final is None or self.df_final.empty: return caps
        for v in self.df_final["Targetts"].astype(str).tolist():
            wk = _parse_week_from_label(v)
            if wk is None: continue
            caps[wk] = caps.get(wk, 0) + 1
        return caps

    def recalc_targets(self, keep_existing_week_caps: bool = True):
        if self.df_final is None: return
        n = len(self.df_final.index)
        try: maxw = int(self.max_per_week.get())
        except Exception: maxw = 5
        start = self.start_date_str.get() or "28/08/2025"
        effective_overrides = {}
        if keep_existing_week_caps: effective_overrides.update(self._infer_week_caps_from_current_df())
        effective_overrides.update(self.week_overrides)
        self.df_final["Targetts"] = generate_targets(
            n, start_date_str=start, default_per_week=maxw,
            week_overrides=effective_overrides, start_from_next_week=True
        )
        self.render_main_table()

    # ---------- Transferência ----------
    def _transfer_all_novos(self):
        if self.df_novos is None or self.df_novos.empty:
            messagebox.showinfo("Transferir Novos", "Não há itens novos para transferir."); return
        if self.df_final is None or self.df_final.empty:
            self.df_final = pd.DataFrame(columns=["_item_id"] + self.colunas_exibidas)
        for c in self.colunas_exibidas:
            if c not in self.df_final.columns: self.df_final[c] = ""
        if "_item_id" not in self.df_final.columns: self.df_final["_item_id"] = ""

        prio_can = self.df_final["Prioridade"].map(canonicalize_priority) if not self.df_final.empty else pd.Series(dtype=str)
        added = 0; existing_ids = set(self.df_final["_item_id"].astype(str).str.strip())

        for _, r in self.df_novos.iterrows():
            rid = str(r.get("_item_id", "")).strip()
            if rid and rid in existing_ids: continue
            new_row = {
                "_item_id": rid,
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
                prio_can = pd.Series([p_new]); existing_ids.add(rid); added += 1; continue
            same_idx = [i for i, v in enumerate(prio_can.tolist()) if v == p_new]
            if same_idx: insert_pos = max(same_idx) + 1
            else:
                lesser_idx = [i for i, v in enumerate(prio_can.tolist())
                              if PRIORITY_ORDER.get(v, 99) > PRIORITY_ORDER.get(p_new, 99)]
                insert_pos = min(lesser_idx) if lesser_idx else len(self.df_final)
            top = self.df_final.iloc[:insert_pos].copy(); bot = self.df_final.iloc[insert_pos:].copy()
            self.df_final = pd.concat([top, pd.DataFrame([new_row]), bot], ignore_index=True)
            if "_item_id" in self.df_final.columns:
                self.df_final = self.df_final[["_item_id"] + self.colunas_exibidas]
            prio_can = self.df_final["Prioridade"].map(canonicalize_priority)
            existing_ids.add(rid); added += 1

        self.df_novos = pd.DataFrame()
        self._render_novos_panel()
        self.recalc_targets(keep_existing_week_caps=True)
        self.render_main_table()
        messagebox.showinfo("Transferência concluída", f"Foram adicionados {added} itens à lista.")

    # ---------- Ordenação ----------
    def sort_by_priority_asc(self):
        if self.df_final is None or self.df_final.empty: return
        self.df_final["_pri"] = self.df_final["Prioridade"].map(lambda v: PRIORITY_ORDER.get(canonicalize_priority(v), 999))
        self.df_final = self.df_final.sort_values(by=["_pri"], kind="stable").drop(columns=["_pri"]).reset_index(drop=True)
        self.render_main_table()

    def sort_by_priority_desc(self):
        if self.df_final is None or self.df_final.empty: return
        self.df_final["_pri"] = self.df_final["Prioridade"].map(lambda v: PRIORITY_ORDER.get(canonicalize_priority(v), -1))
        self.df_final = self.df_final.sort_values(by=["_pri"], ascending=False, kind="stable").drop(columns=["_pri"]).reset_index(drop=True)
        self.render_main_table()

    # ---------- Exportação ----------
    def export_excel(self):
        if self.df_final is None: return
        path = os.path.join(os.getcwd(), "ListaAtualizada.xlsx")
        df_out = self.df_final.copy()
        for c in COLS_UI:
            if c not in df_out.columns: df_out[c] = ""
        if "_item_id" not in df_out.columns: df_out["_item_id"] = ""
        cols_out = ["_item_id"] + COLS_UI
        df_out = denan(df_out[cols_out])
        with pd.ExcelWriter(path, engine="openpyxl") as w:
            df_out.to_excel(w, index=False, sheet_name="Reparos")
            ws = w.book["Reparos"]; ws.freeze_panes = "A2"
            for j, col in enumerate(df_out.columns, start=1):
                sample = max([len(str(col))] + [len(str(v)) for v in df_out[col].astype(str).head(200)])
                ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = min(max(sample + 4, 12), 60)
        self.week_overrides.clear(); self._update_overrides_label()
        messagebox.showinfo("Salvo", f"Planilha salva em:\n{path}")

    # ---------- Fechar ----------
    def _on_close(self):
        ans = messagebox.askyesnocancel(
            "Sair",
            "Deseja salvar as alterações antes de sair?\n\nSim: Salva e sai\nNão: Sai sem salvar\nCancelar: Volta ao app",
            default="yes", icon="question",
        )
        if ans is None: return
        if ans:
            try: self.export_excel()
            except Exception as e: messagebox.showerror("Erro ao salvar", f"Falha ao salvar antes de sair:\n{e}")
        self.destroy()

if __name__ == "__main__":
    app = SimpleTable()
    app.mainloop()
