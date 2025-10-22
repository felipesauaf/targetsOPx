# =================== Imports ===================
import os
import json
import threading
from functools import partial
from datetime import datetime, timedelta
import unicodedata
import re
import uuid  # para gerar iids temporários quando não houver _item_id
import pandas as pd
import customtkinter as ctk
from tkinter import ttk, messagebox

# PIL opcional (logo)
try:
    from PIL import Image, ImageTk
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
ctk.set_appearance_mode("Dark")
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
        try:
            s = str(s)
        except Exception:
            return ""
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def canonicalize_priority(val: str) -> str:
    """
    Normaliza a prioridade para rótulos canônicos: SEVERA / ALTA / MÉDIA / LEVE
    Aceita badges (🟥 etc), variações com acento, caixa, etc.
    """
    if not val:
        return ""
    s = _strip_accents(str(val)).upper().strip()
    s = s.replace("🟥", "").replace("🟧", "").replace("🟦", "").replace("🟩", "").strip()
    if "SEVER" in s:
        return "SEVERA"
    if "ALTA" in s:
        return "ALTA"
    if "MEDIA" in s or "MÉDIA" in s:
        return "MÉDIA"
    if "LEVE" in s:
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


# =================== Denan ===================
def denan(df: pd.DataFrame) -> pd.DataFrame:
    """Substitui NaN/NaT por string vazia, preserva DataFrame."""
    if df is None:
        return pd.DataFrame()
    return df.fillna("")


# =================== Monday JSON Update Hook ===================
class MondayDataUpdate:
    """
    Adapter mínimo para acionar o export do Monday para JSON no disco.
    Implemente 'mondayToJson' conforme seu ambiente.
    """
    def mondayToJson(self):
        # Placeholder: implemente aqui se quiser atualizar o JSON automaticamente
        # Ex.: baixar via API e salvar em 'monday_export_all.json'
        pass


# =================== Monday JSON → DataFrame (filtrado) ===================
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

    base_cols = ["Elemento", "Subelementos", "N° Proposta", "Cliente", "SN", "Prioridade", "Status", "Data de Submissão", "_item_id"]
    for c in base_cols:
        if c not in df.columns:
            df[c] = ""
    df = df[base_cols]
    return denan(df)


def read_lista_excel() -> pd.DataFrame | None:
    path = os.path.join(os.getcwd(), "ListaAtualizada.xlsx")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_excel(path, sheet_name="Reparos")
        for c in COLS_UI:
            if c not in df.columns:
                df[c] = ""
        if "_item_id" not in df.columns:
            df["_item_id"] = ""
        cols = ["_item_id"] + [c for c in COLS_UI if c != "_item_id"]
        df = df[cols]
        df = denan(df)
        return df
    except Exception:
        return None


# =================== Diff por _item_id ===================
def _keys_from_ids(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=str)
    if "_item_id" not in df.columns:
        return pd.Series(index=df.index, data="", dtype=str)
    return df["_item_id"].astype(str).str.strip()

def diff_new_items(df_monday_ptbr: pd.DataFrame, df_lista: pd.DataFrame) -> pd.DataFrame:
    cols = ["_item_id","Status", "Elemento", "N° Proposta", "Cliente", "SN", "Prioridade", "Data de Submissão"]
    if df_monday_ptbr is None or df_monday_ptbr.empty:
        return pd.DataFrame(columns=cols)
    if df_lista is None or df_lista.empty:
        return df_monday_ptbr[cols].copy()
    monday_ids = set(_keys_from_ids(df_monday_ptbr))
    lista_ids = set(_keys_from_ids(df_lista))
    novos_ids = monday_ids - lista_ids
    mask = df_monday_ptbr["_item_id"].astype(str).str.strip().isin(novos_ids) if "_item_id" in df_monday_ptbr.columns else pd.Series(False, index=df_monday_ptbr.index)
    out = df_monday_ptbr.loc[mask].copy()
    return out[cols]

def diff_finished_items(df_monday_ptbr: pd.DataFrame, df_lista: pd.DataFrame) -> pd.DataFrame:
    if df_lista is None or df_lista.empty:
        return pd.DataFrame(columns=COLS_UI)
    if df_monday_ptbr is None or df_monday_ptbr.empty:
        finished = df_lista.copy()
        for c in COLS_UI:
            if c not in finished.columns:
                finished[c] = ""
        return finished[COLS_UI]
    monday_ids = set(_keys_from_ids(df_monday_ptbr))
    lista_ids = set(_keys_from_ids(df_lista))
    remov_ids = lista_ids - monday_ids
    if "_item_id" not in df_lista.columns:
        return pd.DataFrame(columns=COLS_UI)
    mask = df_lista["_item_id"].astype(str).str.strip().isin(remov_ids)
    finished = df_lista.loc[mask].copy()
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
    if not label:
        return None
    m = re.search(r"Semana\s+(\d{1,2})\b", str(label))
    return int(m.group(1)) if m else None

def generate_targets(n, start_date_str="28/08/2025", default_per_week=5, week_overrides=None, start_from_next_week=True):
    week_overrides = week_overrides or {}
    start = datetime.strptime(start_date_str, "%d/%m/%Y")
    week_monday = monday_of_week(start)
    current_week_start = week_monday + timedelta(days=7 if start_from_next_week else 0)

    targets = []
    assigned = 0

    def iso_week_of(d: datetime) -> int:
        return int(d.isocalendar()[1])

    while assigned < n:
        week_num = iso_week_of(current_week_start)
        cap = week_overrides.get(week_num, default_per_week)
        if cap < 0:
            cap = 0
        for _ in range(cap):
            if assigned >= n:
                break
            label = f"Semana {week_num:02d} - {current_week_start.strftime('%d/%m/%Y')}"
            targets.append(label)
            assigned += 1
        current_week_start = current_week_start + timedelta(days=7)

    return targets


# =================== Modal de Carregamento ===================
class LoadingDialog(ctk.CTkToplevel):
    def __init__(self, parent, title="Carregando...", total=7):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.total = max(1, int(total))
        self.progress_val = 0.0

        # centralizar
        self.update_idletasks()
        w, h = 380, 140
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (w // 2)
        y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(18, 8))
        self.msg = ctk.CTkLabel(self, text="Iniciando...", wraplength=320)
        self.msg.pack(pady=(0, 8))

        self.pb = ctk.CTkProgressBar(self)
        self.pb.pack(fill="x", padx=20, pady=(0, 14))
        self.pb.set(0)

        self.cancelled = False
        self.btn_cancel = ctk.CTkButton(self, text="Cancelar", command=self._cancel, width=120)
        self.btn_cancel.pack(pady=(0, 10))

        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _cancel(self):
        # Apenas marca como cancelado; quem chama decide abortar de fato.
        self.cancelled = True

    def update_progress(self, step: int, text: str = ""):
        # step inicia em 0..total; clamp
        step = max(0, min(step, self.total))
        frac = step / float(self.total)
        self.pb.set(frac)
        if text:
            self.msg.configure(text=text)
        self.update_idletasks()

    def close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


# =================== App (UI) ===================
class SimpleTable(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Fila de Reparos · OPx")
        self.geometry("1320x860")
        self.minsize(1100, 650)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.start_date_str = ctk.StringVar(value="28/08/2025")
        self.max_per_week = ctk.StringVar(value="5")
        self.appearance = ctk.StringVar(value="Dark")

        self.week_overrides: dict[int, int] = {}
        self.week_override_week = ctk.StringVar(value="")
        self.week_override_qty = ctk.StringVar(value="")
        self._overrides_label = None

        self.mondayDataUpdate = MondayDataUpdate()

        self.colunas_exibidas = COLS_UI[:]
        self.df_final = pd.DataFrame(columns=["_item_id"] + self.colunas_exibidas)
        self.df_novos = pd.DataFrame()
        self.df_removed = pd.DataFrame()

        self._setup_theme()
        self._build_ui()
        self.load_data_initial()

    # ---------- Tema ----------
    def _setup_theme(self):
        theme = THEMES.get(self.appearance.get(), THEMES["Dark"])
        self.configure(fg_color=theme["bg"])

    def _setup_tree_style(self):
        theme = THEMES.get(self.appearance.get(), THEMES["Dark"])
        style = ttk.Style()
        # Base default, custom name
        style.configure(
            "OPX.Treeview",
            background=theme["row_even"],
            fieldbackground=theme["row_even"],
            foreground=theme["fg"],
            rowheight=28,
            bordercolor=theme["border"],
            font=("Segoe UI", 10),
        )
        style.map("OPX.Treeview", background=[("selected", theme["sel_bg"])], foreground=[("selected", theme["sel_fg"])])
        style.configure(
            "OPX.Treeview.Heading",
            background=theme["header_bg"],
            foreground=theme["header_fg"],
            font=("Segoe UI Semibold", 10),
            bordercolor=theme["border"],
        )
        style.map("OPX.Treeview.Heading", background=[("active", theme["header_bg"])])

    # ---------- UI ----------
    def _build_ui(self):
        theme = THEMES.get(self.appearance.get(), THEMES["Dark"])

        # Header
        self.header = ctk.CTkFrame(self, fg_color=theme["bg2"])
        self.header.pack(fill="x", padx=12, pady=12)

        brand = ctk.CTkLabel(self.header, text="Fila de Reparos · OPx", font=ctk.CTkFont(size=18, weight="bold"))
        brand.grid(row=0, column=0, padx=12, pady=(10, 2), sticky="w")

        theme_switch = ctk.CTkOptionMenu(self.header, values=["Dark", "Light"], variable=self.appearance,
                                         command=lambda _: self._on_theme_change())
        theme_switch.grid(row=0, column=1, padx=12, pady=(10, 2), sticky="e")

        # Controles (lado direito)
        controls = ctk.CTkFrame(self.header, fg_color="transparent")
        controls.grid(row=0, column=2, rowspan=2, sticky="e", padx=12, pady=10)

        ctk.CTkLabel(controls, text="Data inicial").grid(row=0, column=0, padx=(0, 8))
        self.entry_date = ctk.CTkEntry(
            controls, width=120, textvariable=self.start_date_str, placeholder_text="DD/MM/AAAA", justify="center"
        )
        self.entry_date.grid(row=0, column=1, padx=(0, 16))

        ctk.CTkLabel(controls, text="Máx/semana").grid(row=0, column=2, padx=(0, 8))
        self.opt_max = ctk.CTkOptionMenu(
            controls, variable=self.max_per_week, values=["3", "4", "5", "6", "7"],
            fg_color=OPX_YELLOW, button_color=OPX_YELLOW,
            button_hover_color=OPX_YELLOW
        )
        self.opt_max.grid(row=0, column=3, padx=(0, 10))

        # Semana custom
        week_frame = ctk.CTkFrame(self.header, fg_color="transparent")
        week_frame.grid(row=1, column=0, columnspan=3, sticky="we", padx=12, pady=(2, 10))

        ctk.CTkLabel(week_frame, text="Semana").grid(row=0, column=0, padx=(0, 8))
        self.entry_week_num = ctk.CTkEntry(week_frame, width=72, textvariable=self.week_override_week,
                                           placeholder_text="ex: 40", justify="center")
        self.entry_week_num.grid(row=0, column=1)

        ctk.CTkLabel(week_frame, text="Capacidade").grid(row=0, column=2, padx=(10, 6))
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
        self._overrides_label.grid(row=0, column=6, padx=(14, 0))

        # Corpo
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        # Barra de ações
        actions = ctk.CTkFrame(container, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=(12, 6))

        # Esquerda: ações principais
        left_actions = ctk.CTkFrame(actions, fg_color="transparent")
        left_actions.pack(side="left")

        self.btn_reload = ctk.CTkButton(
            left_actions,
            text="Atualizar dados",
            command=self.on_click_atualizar_async,  # <- agora com modal + progress bar
            width=300,
        )
        self._style_yellow_button(self.btn_reload)
        self.btn_reload.pack(side="left", padx=(0, 8))

        self.btn_transfer = ctk.CTkButton(
            left_actions, text="Transferir novos → Lista", command=self._transfer_all_novos, width=220
        )
        self._style_yellow_button(self.btn_transfer)
        self.btn_transfer.pack(side="left", padx=(0, 8))

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
            left_actions, text="Salvar", command=self.export_excel, width=140
        )
        self._style_yellow_button(self.btn_export)
        self.btn_export.pack(side="left", padx=(0, 8))

        # Árvore principal
        main_wrap = ctk.CTkFrame(container, fg_color="transparent")
        main_wrap.pack(fill="both", expand=True, padx=2, pady=(4, 10))

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
            selectmode="extended",
        )
        self.reported_tree.pack(fill="both", expand=True, padx=(0, 0), pady=(0, 0))
        self._enable_row_dnd()
        self.scroll_y.configure(command=self.reported_tree.yview)
        self.scroll_x.configure(command=self.reported_tree.xview)

        for col in self.colunas_exibidas:
            self.reported_tree.heading(col, text=col, anchor="center")
            self.reported_tree.column(col, anchor="center", width=140)

        # Painéis de "Novos" e "Removidos"
        self._novos_frame = ctk.CTkFrame(container, fg_color="transparent")
        self._novos_frame.pack(fill="x", padx=4, pady=(0, 8))
        self._removed_frame = ctk.CTkFrame(container, fg_color="transparent")
        self._removed_frame.pack(fill="x", padx=4, pady=(0, 8))

    def _style_yellow_button(self, btn: ctk.CTkButton):
        btn.configure(fg_color=OPX_YELLOW, hover_color="#ffcc33", text_color="#0F172A")

    def _on_theme_change(self):
        ctk.set_appearance_mode(self.appearance.get())
        self._setup_theme()
        self._setup_tree_style()
        self.render_main_table()

    # ---------- Carregamento inicial ----------
    def load_data_initial(self):
        # Carrega a ListaAtualizada, renderiza e calcula diffs se houver JSON
        df_lista = read_lista_excel()
        if df_lista is not None and not df_lista.empty:
            self.df_final = denan(df_lista.copy())
        else:
            self.df_final = pd.DataFrame(columns=["_item_id"] + COLS_UI)

        # tenta ler JSON (sem bloquear)
        try:
            if os.path.exists("monday_export_all.json"):
                df_monday_ptbr = map_monday_to_ptbr(get_monday_data_from_json())
                self.df_novos = diff_new_items(df_monday_ptbr, self.df_final)
                self.df_removed = diff_finished_items(df_monday_ptbr, self.df_final)
        except Exception:
            self.df_novos = pd.DataFrame()
            self.df_removed = pd.DataFrame()

        self.df_final = ensure_badges(self.df_final)
        self.render_main_table()
        self._render_novos_panel()
        self._render_removed_panel()

    # ---------- Atualizar dados (com modal/progress) ----------
    def on_click_atualizar_async(self):
        total_steps = 7  # manter sincronizado com a contagem dentro do worker
        dlg = LoadingDialog(self, title="Atualizando dados…", total=total_steps)
        # trava botão para evitar duplo-clique
        self.btn_reload.configure(state="disabled")

        def ui_progress(step, text=""):
            # safe-call no main-loop
            try:
                if dlg.cancelled:
                    return
                dlg.update_progress(step, text)
            except Exception:
                pass

        def ui_finish(n_novos, n_rem, error=None):
            # fecha modal
            try:
                dlg.close()
            except Exception:
                pass
            # reabilita botão
            self.btn_reload.configure(state="normal")

            if error:
                messagebox.showerror("Erro ao atualizar", f"Ocorreu um erro na atualização:\n{error}")
            else:
                messagebox.showinfo(
                    "Atualização concluída",
                    f"Novos: {n_novos}\nRemovidos: {n_rem}\n\nComparação feita por _item_id."
                )

        def worker():
            step = 0
            try:
                # 1) (opcional) atualizar JSON do Monday
                step += 1; self.after(0, ui_progress, step, "Preparando atualização…")
                if hasattr(self.mondayDataUpdate, "mondayToJson"):
                    if dlg.cancelled: return self.after(0, ui_finish, 0, 0, None)
                    self.mondayDataUpdate.mondayToJson()

                # 2) Ler JSON
                step += 1; self.after(0, ui_progress, step, "Lendo JSON do Monday…")
                if dlg.cancelled: return self.after(0, ui_finish, 0, 0, None)
                df_monday_raw = None
                if os.path.exists("monday_export_all.json"):
                    df_monday_raw = get_monday_data_from_json()
                else:
                    df_monday_raw = pd.DataFrame()

                # 3) Mapear p/ pt-BR
                step += 1; self.after(0, ui_progress, step, "Mapeando colunas…")
                if dlg.cancelled: return self.after(0, ui_finish, 0, 0, None)
                df_monday_ptbr = map_monday_to_ptbr(df_monday_raw) if df_monday_raw is not None else pd.DataFrame()

                # 4) Ler lista atual
                step += 1; self.after(0, ui_progress, step, "Carregando ListaAtualizada.xlsx…")
                if dlg.cancelled: return self.after(0, ui_finish, 0, 0, None)
                df_lista = read_lista_excel()
                if df_lista is not None and not df_lista.empty:
                    self.df_final = denan(df_lista.copy())
                else:
                    if getattr(self, "df_final", None) is None or self.df_final.empty:
                        self.df_final = pd.DataFrame(columns=["_item_id"] + COLS_UI)

                # 5) Diffs por _item_id
                step += 1; self.after(0, ui_progress, step, "Calculando diferenças…")
                if dlg.cancelled: return self.after(0, ui_finish, 0, 0, None)
                self.df_novos = diff_new_items(df_monday_ptbr, self.df_final) if df_monday_ptbr is not None else pd.DataFrame(columns=COLS_UI)
                self.df_removed = diff_finished_items(df_monday_ptbr, self.df_final) if df_monday_ptbr is not None else pd.DataFrame(columns=COLS_UI)

                # 6) Harmonizar lista com Monday atual (remover IDs que não existem mais)
                step += 1; self.after(0, ui_progress, step, "Harmonizando lista…")
                if dlg.cancelled: return self.after(0, ui_finish, 0, 0, None)
                if df_monday_ptbr is not None and not self.df_final.empty and "_item_id" in self.df_final.columns and "_item_id" in df_monday_ptbr.columns:
                    set_cur = set(df_monday_ptbr["_item_id"].astype(str).str.strip())
                    self.df_final = self.df_final[self.df_final["_item_id"].astype(str).str.strip().isin(set_cur) | (self.df_final["_item_id"].astype(str).str.strip() == "")]
                    self.df_final = self.df_final.reset_index(drop=True)

                # 7) Badges/NaN + render
                step += 1; self.after(0, ui_progress, step, "Renderizando…")
                if dlg.cancelled: return self.after(0, ui_finish, 0, 0, None)
                self.df_final = ensure_badges(self.df_final) if self.df_final is not None else pd.DataFrame(columns=["_item_id"] + COLS_UI)
                self.df_removed = ensure_badges(self.df_removed) if self.df_removed is not None else pd.DataFrame()
                self.df_final = denan(self.df_final)
                self.df_removed = denan(self.df_removed)

                # Render na UI
                self.after(0, self.render_main_table)
                self.after(0, self._render_novos_panel)
                self.after(0, self._render_removed_panel)

                n_novos = 0 if self.df_novos is None else len(self.df_novos.index)
                n_rem = 0 if self.df_removed is None else len(self.df_removed.index)

                # fim
                self.after(0, ui_finish, n_novos, n_rem, None)

            except Exception as e:
                self.after(0, ui_finish, 0, 0, str(e))

        threading.Thread(target=worker, daemon=True).start()

    # ---------- Renderização ----------
    def _clear_tree(self, tree: ttk.Treeview):
        for it in tree.get_children():
            tree.delete(it)

    def render_main_table(self):
        self._setup_tree_style()

        # limpa e zera o mapa de iids
        for it in self.reported_tree.get_children():
            self.reported_tree.delete(it)
        self._iid_index_map = {}  # mapeia iids temporários p/ índice original

        if self.df_final is None or self.df_final.empty:
            return

        # insere com iid = id-<_item_id> quando existir; senão, tmp-<idx>
        for idx, row in self.df_final.reset_index(drop=True).iterrows():
            rid = str(row.get("_item_id", "")).strip()
            iid = f"id-{rid}" if rid else f"tmp-{idx}"
            if iid.startswith("tmp-"):
                self._iid_index_map[iid] = idx  # para recuperar depois

            values = [row.get(c, "") for c in self.colunas_exibidas]
            try:
                self.reported_tree.insert("", "end", iid=iid, values=values)
            except Exception:
                # iid duplicado? gera único
                uid = f"{iid}-{uuid.uuid4().hex[:6]}"
                self.reported_tree.insert("", "end", iid=uid, values=values)

        # largura “inteligente”
        widths = {}
        df = self.df_final.copy()
        for col in self.colunas_exibidas:
            base = [len(str(col))]
            base += [len(str(v)) for v in df[col].astype(str).head(200)]
            widths[col] = min(max(max(base) + 4, 12), 60)
        for col in self.colunas_exibidas:
            self.reported_tree.column(col, width=int(widths.get(col, 140)))

    # ---------- Drag & Drop de linhas ----------
    def _enable_row_dnd(self):
        # estado interno de DnD
        self._dnd_active = False
        self._dnd_src_iid = None

        self.reported_tree.bind("<ButtonPress-1>", self._on_drag_start)
        self.reported_tree.bind("<B1-Motion>", self._on_drag_motion)
        self.reported_tree.bind("<ButtonRelease-1>", self._on_drag_release)

    def _on_drag_start(self, event):
        # pega a linha de origem no clique
        iid = self.reported_tree.identify_row(event.y)
        if not iid:
            self._dnd_active = False
            self._dnd_src_iid = None
            return
        self._dnd_active = True
        self._dnd_src_iid = iid

    def _on_drag_motion(self, event):
        if not self._dnd_active or not self._dnd_src_iid:
            return

        # autoscroll leve
        y = event.y
        bounds = self.reported_tree.bbox(self.reported_tree.get_children()[0]) if self.reported_tree.get_children() else None
        height = self.reported_tree.winfo_height()
        if y < 20:
            self.reported_tree.yview_scroll(-1, "units")
        elif y > height - 20:
            self.reported_tree.yview_scroll(1, "units")

        target_iid = self.reported_tree.identify_row(y)
        if not target_iid or target_iid == self._dnd_src_iid:
            return

        # move visualmente: coloca src ANTES do target
        parent = ""
        children = list(self.reported_tree.get_children(parent))
        try:
            target_index = children.index(target_iid)
        except ValueError:
            return
        try:
            self.reported_tree.move(self._dnd_src_iid, parent, target_index)
        except Exception:
            pass

    def _on_drag_release(self, event):
        if not self._dnd_active or not self._dnd_src_iid:
            return
        self._dnd_active = False

        # reconstrói df_final conforme a nova ordem visual
        try:
            self._rebuild_df_from_tree_order()
            # mantém capacidades já salvas por semana
            self.recalc_targets(keep_existing_week_caps=True)
            self.render_main_table()
        finally:
            self._dnd_src_iid = None

    def _rebuild_df_from_tree_order(self):
        """
        Recria self.df_final respeitando a ordem dos iids na árvore.
        Usa _item_id quando existir (iid com prefixo 'id-').
        Para iids temporários (prefixo 'tmp-'), usa o índice salvo em self._iid_index_map.
        """
        if self.df_final is None or self.df_final.empty:
            return

        ordered_iids = list(self.reported_tree.get_children(""))
        if not ordered_iids:
            return

        # índices na ordem nova
        idx_order = []
        used = set()

        # acesso rápido
        df = self.df_final.reset_index(drop=True).copy()

        # 1) itens com _item_id (iid = "id-<id>")
        if "_item_id" in df.columns:
            id_to_idx = {str(v).strip(): i for i, v in enumerate(df["_item_id"].tolist())}
        else:
            id_to_idx = {}

        for iid in ordered_iids:
            if iid.startswith("id-"):
                rid = iid[3:]
                i = id_to_idx.get(rid, None)
                if i is not None and i not in used:
                    idx_order.append(i)
                    used.add(i)
            elif iid.startswith("tmp-"):
                # recupera índice original salvo no render
                i = self._iid_index_map.get(iid, None)
                if i is not None and i not in used:
                    idx_order.append(i)
                    used.add(i)

        # acrescenta quaisquer linhas que, por algum motivo, não entraram (segurança)
        all_idx = list(range(len(df)))
        for i in all_idx:
            if i not in used:
                idx_order.append(i)

        self.df_final = df.iloc[idx_order].reset_index(drop=True)


    def _render_novos_panel(self):
        for w in self._novos_frame.winfo_children():
            w.destroy()

        lbl = ctk.CTkLabel(self._novos_frame, text=f"Novos: {0 if self.df_novos is None else len(self.df_novos.index)}")
        lbl.pack(anchor="w")

        if self.df_novos is None or self.df_novos.empty:
            return

        self.novos_tree = ttk.Treeview(
            self._novos_frame,
            columns=self.colunas_exibidas, show="headings", height=6, style="OPX.Treeview"
        )
        self.novos_tree.pack(fill="x", padx=0, pady=(6, 0))
        for col in self.colunas_exibidas[:-1]:
            self.novos_tree.heading(col, text=col, anchor="center")
            self.novos_tree.column(col, anchor="center", width=140)

        for _, r in self.df_novos.iterrows():
            self.novos_tree.insert("", "end", values=[r.get(c, "") for c in self.colunas_exibidas])

    def _render_removed_panel(self):
        for w in self._removed_frame.winfo_children():
            w.destroy()

        lbl = ctk.CTkLabel(self._removed_frame, text=f"Removidos: {0 if self.df_removed is None else len(self.df_removed.index)}")
        lbl.pack(anchor="w")

        if self.df_removed is None or self.df_removed.empty:
            return

        self.removed_tree = ttk.Treeview(
            self._removed_frame,
            columns=self.colunas_exibidas, show="headings", height=5, style="OPX.Treeview"
        )
        self.removed_tree.pack(fill="x", padx=0, pady=(6, 0))
        for col in self.colunas_exibidas:
            self.removed_tree.heading(col, text=col, anchor="center")
            self.removed_tree.column(col, anchor="center", width=140)

        for _, r in self.df_removed.iterrows():
            self.removed_tree.insert("", "end", values=[r.get(c, "") for c in self.colunas_exibidas])

    # ---------- Regras semanais ----------
    def _update_overrides_label(self):
        if not self.week_overrides:
            text = "Sem regras"
        else:
            parts = [f"S{w}:{q}" for w, q in sorted(self.week_overrides.items())]
            text = "Regras: " + ", ".join(parts)
        if self._overrides_label is not None:
            self._overrides_label.configure(text=text)

    def _indices_of_week(self, week_num: int) -> list[int]:
        if self.df_final is None or self.df_final.empty or "Targetts" not in self.df_final.columns:
            return []
        week_num = int(week_num)
        s1 = f"Semana {week_num:02d} - "
        s2 = f"Semana {week_num} - "
        idxs = []
        for i, v in enumerate(self.df_final["Targetts"].astype(str).tolist()):
            if v.startswith(s1) or v.startswith(s2):
                idxs.append(i)
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
            messagebox.showerror("Regra inválida", "Semana deve estar entre 0 e 53, e a capacidade deve ser ≥ 0.")
            return

        self.week_overrides[w] = q
        self._update_overrides_label()

        self.recalc_targets(keep_existing_week_caps=True)

        self._clear_changed_highlight()
        self._changed_indices = set(self._indices_of_week(w))

        self.render_main_table()
        try:
            self._highlight_job = self.after(900, self._clear_changed_highlight)
        except Exception:
            self._clear_changed_highlight()

        # Pop-up simples confirmando
        messagebox.showinfo("Regra aplicada", f"Semana {w} definida com capacidade {q}.")

    def _clear_week_overrides(self):
        self.week_overrides.clear()
        self._update_overrides_label()
        self._clear_changed_highlight()
        self.recalc_targets(keep_existing_week_caps=False)
        messagebox.showinfo("Regras limpas", "Todas as regras semanais foram removidas.")

    def _clear_week_overrides_ui_only(self):
        self.week_overrides.clear()
        self._update_overrides_label()

    def _infer_week_caps_from_current_df(self) -> dict[int, int]:
        caps: dict[int, int] = {}
        if self.df_final is None or self.df_final.empty:
            return caps
        for v in self.df_final["Targetts"].astype(str).tolist():
            wk = _parse_week_from_label(v)
            if wk is None:
                continue
            caps[wk] = caps.get(wk, 0) + 1
        return caps

    def recalc_targets(self, keep_existing_week_caps: bool = True):
        if self.df_final is None:
            return
        n = len(self.df_final.index)
        try:
            maxw = int(self.max_per_week.get())
        except Exception:
            maxw = 5
        start = self.start_date_str.get() or "28/08/2025"

        effective_overrides = {}
        if keep_existing_week_caps:
            effective_overrides.update(self._infer_week_caps_from_current_df())
        effective_overrides.update(self.week_overrides)

        self.df_final["Targetts"] = generate_targets(
            n,
            start_date_str=start,
            default_per_week=maxw,
            week_overrides=effective_overrides,
            start_from_next_week=True
        )
        self.render_main_table()

    # ---------- Transferência ----------
    def _transfer_all_novos(self):
        if self.df_novos is None or self.df_novos.empty:
            messagebox.showinfo("Transferir Novos", "Não há itens novos para transferir.")
            return

        if self.df_final is None or self.df_final.empty:
            self.df_final = pd.DataFrame(columns=["_item_id"] + self.colunas_exibidas)

        for c in self.colunas_exibidas:
            if c not in self.df_final.columns:
                self.df_final[c] = ""
        if "_item_id" not in self.df_final.columns:
            self.df_final["_item_id"] = ""

        prio_can = self.df_final["Prioridade"].map(canonicalize_priority) if not self.df_final.empty else pd.Series(dtype=str)

        added = 0
        existing_ids = set(self.df_final["_item_id"].astype(str).str.strip())

        for _, r in self.df_novos.iterrows():
            rid = str(r.get("_item_id", "")).strip()
            if rid and rid in existing_ids:
                continue

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
                prio_can = pd.Series([p_new])
                existing_ids.add(rid)
                added += 1
                continue

            same_idx = [i for i, v in enumerate(prio_can.tolist()) if v == p_new]
            if same_idx:
                insert_pos = max(same_idx) + 1
            else:
                lesser_idx = [i for i, v in enumerate(prio_can.tolist()) if PRIORITY_ORDER.get(v, 99) > PRIORITY_ORDER.get(p_new, 99)]
                if lesser_idx:
                    insert_pos = min(lesser_idx)
                else:
                    insert_pos = len(self.df_final)

            top = self.df_final.iloc[:insert_pos].copy()
            bot = self.df_final.iloc[insert_pos:].copy()
            self.df_final = pd.concat([top, pd.DataFrame([new_row]), bot], ignore_index=True)
            if "_item_id" in self.df_final.columns:
                self.df_final = self.df_final[["_item_id"] + self.colunas_exibidas]
            prio_can = self.df_final["Prioridade"].map(canonicalize_priority)
            existing_ids.add(rid)
            added += 1

        self.df_novos = pd.DataFrame()
        self._render_novos_panel()
        self.recalc_targets(keep_existing_week_caps=True)
        self.render_main_table()

        messagebox.showinfo("Transferência concluída", f"Foram adicionados {added} itens à lista.")

    # ---------- Ordenação ----------
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

    # ---------- Exportação ----------
    def export_excel(self):
        if self.df_final is None:
            return
        path = os.path.join(os.getcwd(), "ListaAtualizada.xlsx")
        df_out = self.df_final.copy()
        for c in COLS_UI:
            if c not in df_out.columns:
                df_out[c] = ""
        if "_item_id" not in df_out.columns:
            df_out["_item_id"] = ""
        cols_out = ["_item_id"] + COLS_UI
        df_out = denan(df_out[cols_out])
        with pd.ExcelWriter(path, engine="openpyxl") as w:
            df_out.to_excel(w, index=False, sheet_name="Reparos")
            ws = w.book["Reparos"]
            ws.freeze_panes = "A2"
            for j, col in enumerate(df_out.columns, start=1):
                sample = max([len(str(col))] + [len(str(v)) for v in df_out[col].astype(str).head(200)])
                ws.column_dimensions[ws.cell(row=1, column=j).column_letter].width = min(max(sample + 4, 12), 60)

        # Após salvar, some o chip "Regras" (UI only; não recalcula)
        self._clear_week_overrides_ui_only()
        messagebox.showinfo("Salvo", f"Planilha salva em:\n{path}")

    # ---------- Fechar ----------
    def _on_close(self):
        ans = messagebox.askyesnocancel(
            "Sair",
            "Deseja salvar as alterações antes de sair?\n\nSim: Salva e sai\nNão: Sai sem salvar\nCancelar: Volta ao app",
            default="yes",
            icon="question",
        )
        if ans is None:
            return  # cancelar
        if ans:
            try:
                self.export_excel()
            except Exception as e:
                messagebox.showerror("Erro ao salvar", f"Falha ao salvar antes de sair:\n{e}")
        self.destroy()


if __name__ == "__main__":
    app = SimpleTable()
    app.mainloop()