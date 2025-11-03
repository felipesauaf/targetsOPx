import os, json, threading, unicodedata, re, uuid, sys
from datetime import datetime, timedelta
import pandas as pd
import customtkinter as ctk
from tkinter import ttk

try:
    from jsonExport import dataMondaytoJson
    HAVE_MONDAY_EXPORT = True
except Exception:
    HAVE_MONDAY_EXPORT = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

OPX_YELLOW = "#ffbb00"
HEADER_BG   = "#000000"  # topo SEMPRE preto

THEMES = {
    "Dark": {
        "bg": "#000000","bg2": "#000000","fg": "#E5E7EB","muted": "#9AA4B2",
        "row_even": "#000000","row_odd": "#000000","sel_bg": "#111827","sel_fg": "#E5E7EB",
        "header_bg": "#000000","header_fg": "#FFFFFF","border": "#0A0A0A","chip_bg": "#111111",
        "ok": "#16a34a","warn": "#f59e0b","err": "#ef4444",
        "entry_bg": "#111111","entry_fg": "#FFFFFF","entry_border": "#242424","placeholder": "#9AA4B2",
    },
    "Light": {
        "bg": "#F1F5F9", "bg2": "#F8FAFC", "fg": "#0F172A", "muted": "#475569",
        "row_even": "#FFFFFF", "row_odd": "#F3F4F6",
        "sel_bg": "#D1E9FF", "sel_fg": "#0F172A",
        "header_bg": "#FFFFFF",
        "header_fg": "#0F172A",
        "border": "#CBD5E1", "chip_bg": "#EEF2FF",
        "ok": "#166534", "warn": "#b45309", "err": "#b91c1c",
        "entry_bg": "#FFFFFF", "entry_fg": "#0F172A",
        "entry_border": "#CBD5E1", "placeholder": "#6B7280",
    },
}

ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

COLS_UI = ["Status","Elemento","N° Proposta","Cliente","SN","Prioridade","Data de Submissão","Targetts"]

PRIO_ORDER = {"SEVERA":0,"ALTA":1,"MEDIA":2,"BAIXA":3}

def canonicalize_priority(v):
    """Normaliza texto (remove acentos, colchetes e não-letras) e retorna SEVERA/ALTA/MEDIA/BAIXA ou string original."""
    if v is None:
        return ""
    s = str(v)
    # Remove badge, HTML e normaliza
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"<[^>]*>", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Remove tudo que não é letra A-Z (isso tira [ ] etc.)
    s_letters = re.sub(r"[^A-Z]+", "", s)
    for k in PRIO_ORDER:
        if k in s_letters:
            return k
    return s_letters or s


def with_priority_badge(v):
    s=canonicalize_priority(v)
    if not s: return ""
    return f"[{s}]"

def ensure_badges(df):
    if "Prioridade" in df.columns:
        df=df.copy(); df["Prioridade"]=df["Prioridade"].map(with_priority_badge)
    return df

def denan(df):
    return pd.DataFrame() if df is None else df.fillna("")

class ThemedMessage(ctk.CTkToplevel):
    def __init__(self,parent,title,msg,level="info",buttons=("OK",),default_index=0):
        super().__init__(parent); self.withdraw(); self.title(title); self.resizable(False,False)
        self.transient(parent); self.grab_set()
        theme=THEMES[ctk.get_appearance_mode().capitalize()]
        self.configure(fg_color=theme["bg2"])
        w,h=420,180; self.update_idletasks()
        x=parent.winfo_rootx()+parent.winfo_width()//2-w//2; y=parent.winfo_rooty()+parent.winfo_height()//2-h//2
        self.geometry(f"{w}x{h}+{x}+{y}")
        color={"info":theme["ok"],"warn":theme["warn"],"error":theme["err"]}.get(level, theme["ok"])
        ctk.CTkFrame(self, fg_color=color, corner_radius=0, height=6).pack(fill="x", side="top")
        ctk.CTkLabel(self,text=title,font=ctk.CTkFont(size=16,weight="bold")).pack(pady=(14,6))
        ctk.CTkLabel(self,text=msg,wraplength=360,text_color=theme["fg"]).pack(padx=18,pady=(0,10))
        bf=ctk.CTkFrame(self,fg_color="transparent"); bf.pack(pady=(8,14)); self.choice=None; self._btns=[]
        for i,txt in enumerate(buttons):
            b=ctk.CTkButton(bf,text=txt,width=100,command=lambda t=txt:self._set_choice(t))
            b.configure(fg_color=OPX_YELLOW,hover_color="#ffcc33",text_color="#0F172A")
            self._btns.append(b); b.grid(row=0,column=i,padx=6)
        self.bind("<Return>", lambda e:self._set_choice(buttons[default_index] if 0<=default_index<len(buttons) else buttons[0]))
        self.deiconify(); self._btns[default_index].focus_set()
        self.protocol("WM_DELETE_WINDOW", lambda: self._set_choice(None))
        self.active_tree = None   # <- Treeview atualmente visível (normal ou filtrada)
    def _set_choice(self,v): self.choice=v; self.destroy()

def show_info(p,t,m):  d=ThemedMessage(p,t,m,"info",("OK",)); p.wait_window(d)
def show_error(p,t,m): d=ThemedMessage(p,t,m,"error",("OK",)); p.wait_window(d)
def ask_yes_no(p,t,m):
    d=ThemedMessage(p,t,m,"warn",("Sim","Não"),0); p.wait_window(d); return d.choice



def get_monday_data_from_json():
    with open("monday_export_all.json","r",encoding="utf-8") as f: data=json.load(f)
    items=data.get("items",[]); rows=[]
    for it in items:
        r={"Name":it.get("name",""),"_item_id":str(it.get("id",""))}
        for c in it.get("column_values",[]): r[c.get("id")]=c.get("text")
        r["text"]=r.get("text") or next((c.get("text") for c in it.get("column_values",[]) if c.get("id")=="text"), None)
        rows.append(r)
    df=pd.DataFrame(rows)
    for col in ("status","status_1","subelementos","proposta_n_","cliente"):
        if col not in df.columns: df[col]="" if col in ("subelementos","proposta_n_","cliente") else None
    df["due_date"]=pd.to_datetime(df.get("due_date"), errors="coerce")
    status_ok={"Reportado","Pausado","Em andamento"}
    df=df[df["status"].isin(status_ok)].copy()
    df=df[~df["status_1"].isin(["--","",None])].copy()
    return df

def map_monday_to_ptbr(df):
    df=df.copy()
    if "due_date" in df.columns and pd.api.types.is_datetime64_any_dtype(df["due_date"]):
        df["due_date"]=df["due_date"].dt.strftime("%d/%m/%Y")
    mapping={"Name":"Elemento","subelementos":"Subelementos","proposta_n_":"N° Proposta","cliente":"Cliente",
             "text":"SN","status_1":"Prioridade","status":"Status","due_date":"Data de Submissão","_item_id":"_item_id"}
    df.rename(columns=mapping,inplace=True)
    if "_item_id" not in df.columns: df["_item_id"]=df.get("id","").astype(str)
    base=["Elemento","Subelementos","N° Proposta","Cliente","SN","Prioridade","Status","Data de Submissão","_item_id"]
    for c in base:
        if c not in df.columns: df[c]=""
    return denan(df[base])

# =========================
#  Caminhos robustos ListaAtualizada.xlsx
# =========================
def _script_dir():
    return os.path.dirname(os.path.abspath(__file__))

def _parent_dir():
    return os.path.dirname(_script_dir())

def _lista_candidates():
    name = "ListaAtualizada.xlsx"
    return [
        os.path.join(_script_dir(), name),
        os.path.join(_parent_dir(), name),
        os.path.join(os.getcwd(), name),
    ]

def _latest_existing(path_list):
    existing = [(p, os.path.getmtime(p)) for p in path_list if os.path.exists(p)]
    if not existing:
        return None
    existing.sort(key=lambda t: t[1], reverse=True)
    return existing[0][0]  # caminho mais recente

def resolve_lista_path():
    """Escolhe o caminho mais recente/adequado para ListaAtualizada.xlsx (pai/script/cwd)."""
    return _latest_existing(_lista_candidates())

def read_lista_excel_at(path):
    """Lê a planilha do caminho informado; retorna DataFrame ou None."""
    if not path or not os.path.exists(path):
        return None
    try:
        df = pd.read_excel(path, sheet_name="Reparos")
        for c in COLS_UI:
            if c not in df.columns: df[c] = ""
        if "_item_id" not in df.columns: df["_item_id"] = ""
        return denan(df[["_item_id"] + COLS_UI])
    except Exception:
        return None

def write_lista_excel_at(df, path):
    """Escreve a planilha exatamente no caminho fornecido; se ausente, salva no dir do script."""
    if not path:
        path = os.path.join(_script_dir(), "ListaAtualizada.xlsx")
    df.to_excel(path, sheet_name="Reparos", index=False)
    return path

def compare_new_removed(df_lista, df_monday):
    if df_lista is None: df_lista=pd.DataFrame(columns=["_item_id"]+COLS_UI)
    if df_monday is None: df_monday=pd.DataFrame(columns=["_item_id"]+COLS_UI)
    cur=set(str(x).strip() for x in df_lista["_item_id"].tolist())
    new=set(str(x).strip() for x in df_monday["_item_id"].tolist())
    novos_ids = list(new-cur); rem_ids = list(cur-new)
    df_novos   = denan(df_monday[df_monday["_item_id"].astype(str).isin(novos_ids)]) if novos_ids else pd.DataFrame()
    df_removed = denan(df_lista [df_lista ["_item_id"].astype(str).isin(rem_ids)])   if rem_ids else pd.DataFrame()
    return df_novos, df_removed

def apply_updates_from_monday(df, mon, cols):
    if df is None or df.empty or mon is None or mon.empty: return 0,0
    mon=mon.copy(); mon["_item_id"]=mon["_item_id"].astype(str).str.strip()
    df =df .copy(); df ["_item_id"]=df ["_item_id"].astype(str).str.strip()
    t=mon.set_index("_item_id")
    changed_rows=0; changed_cells=0
    for i,r in df.iterrows():
        rid=str(r.get("_item_id","")).strip()
        if not rid or rid not in t.index: continue
        mon_row=t.loc[rid]
        cset=set(cols)
        cols=[c for c in cset if c in mon_row.index]
        row_changed=0
        for c in cols:
            nv=mon_row[c] if c in mon_row.index else ""
            if c=="Prioridade": nv=with_priority_badge(nv)
            ov=df.at[i,c] if c in df.columns else ""
            if str(ov)!=str(nv): df.at[i,c]=nv; changed_cells+=1; row_changed+=1
        if row_changed: changed_rows+=1
    return changed_rows, changed_cells

def monday_of_week(d): return d - timedelta(days=d.weekday()) if d.weekday()<5 else d + timedelta(days=(7-d.weekday()))
def _parse_week_from_label(lbl):
    if not lbl: return None
    m=re.search(r"Semana\s+(\d{1,2})\b", str(lbl)); return int(m.group(1)) if m else None

def _next_iso_week(wk):
    """Próxima semana ISO (1..53), com wrap."""
    if wk is None: 
        return 1
    return 1 if wk >= 53 else wk + 1

def _compute_week_calendar(start_date_str, horizon_weeks=180):
    """
    Mapa {iso_week -> monday_date} começando NA SEMANA SEGUINTE à data inicial,
    igual ao comportamento do app.
    """
    base = datetime.strptime(start_date_str, "%d/%m/%Y")
    week_monday = monday_of_week(base)
    cur = week_monday + timedelta(days=7)  # próxima semana após a base
    cal = {}
    for _ in range(int(horizon_weeks)):
        wk = int(cur.isocalendar()[1])
        cal.setdefault(wk, cur)  # guarda a primeira segunda dessa semana ISO
        cur += timedelta(days=7)
    cal.setdefault(0, base)  # “0” continua aceito como especial
    return cal



def generate_targets(n,start_date_str="28/08/2025",default_per_week=5,week_overrides=None,start_from_next_week=True):
    wo=week_overrides or {}
    start=datetime.strptime(start_date_str,"%d/%m/%Y")
    week_monday=monday_of_week(start)
    cur=week_monday + timedelta(days=7 if start_from_next_week else 0)
    t,ass=[],0
    def iso(d): return int(d.isocalendar()[1])
    while ass<n:
        wk=iso(cur); cap=wo.get(wk, default_per_week); cap=max(0,cap)
        for _ in range(cap):
            if ass>=n: break
            t.append(f"Semana {wk:02d} - {cur.strftime('%d/%m/%Y')}")
            ass+=1
        cur+=timedelta(days=7)
    return t

class LoadingDialog(ctk.CTkToplevel):
    def __init__(self, parent, title="Carregando…", total=8):
        super().__init__(parent)
        theme = THEMES[ctk.get_appearance_mode().capitalize()]
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.configure(fg_color=theme["bg2"])
        self.total = max(1, int(total))
        self.progress_val = 0.0

        self.update_idletasks()
        w, h = 460, 260
        x = parent.winfo_rootx() + parent.winfo_width() // 2 - w // 2
        y = parent.winfo_rooty() + parent.winfo_height() // 2 - h // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        ctk.CTkLabel(self,text=title,font=ctk.CTkFont(size=16,weight="bold")).pack(pady=(12,8))
        self.msg = ctk.CTkLabel(self, text="Iniciando…")
        self.msg.pack()

        self.pb = ctk.CTkProgressBar(self, width=360)
        self.pb.pack(pady=(8,12))
        self.pb.set(0.0)

        self.logbox = ctk.CTkTextbox(self, height=120, width=400)
        self.logbox.pack(fill="both", expand=False, padx=10, pady=(0,10))
        self.logbox.configure(state="disabled")

        self.btn_cancel = ctk.CTkButton(self, text="Cancelar", command=self.cancel,
                                        fg_color=OPX_YELLOW, hover_color="#ffcc33", text_color="#0F172A")
        self.btn_cancel.pack(pady=(0,10))

        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        try:
            self.btn_cancel.configure(state="disabled", text="Cancelando…")
        except:
            pass

    def update_progress(self, step, text=""):
        step = max(0, min(step, self.total))
        self.progress_val = step / float(self.total)
        self.pb.set(self.progress_val)
        if text:
            self.msg.configure(text=text)
        self.update_idletasks()

    def add_log(self, text: str):
        if not self.logbox:
            return
        from datetime import datetime as _dt
        line = f"[{_dt.now().strftime('%H:%M:%S')}] {text}\n"
        self.logbox.configure(state="normal")
        self.logbox.insert("end", line)
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

class SimpleTable(ctk.CTk):
    def __init__(self):
        super().__init__()
        self._base_title="Fila de Reparos"
        self.title(self._base_title); self.geometry("1320x860"); self.minsize(1100,650)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.start_date_str=ctk.StringVar(value="28/08/2025")
        self.max_per_week  =ctk.StringVar(value="5")
        self.appearance    =ctk.StringVar(value="Light")
        self._dirty=False

        self.week_overrides={}
        self.week_override_week=ctk.StringVar(value="")
        self.week_override_qty =ctk.StringVar(value="")
        self._overrides_label=None

        self.mondayDataUpdate = dataMondaytoJson() if HAVE_MONDAY_EXPORT else type("Noop",(),{"mondayToJson":lambda *_:None})()
        self.colunas_exibidas=COLS_UI[:]
        self.df_final=pd.DataFrame(columns=["_item_id"]+self.colunas_exibidas)
        self.df_novos=pd.DataFrame(); self.df_removed=pd.DataFrame()

        # Caminho de origem da ListaAtualizada.xlsx (para salvar no mesmo lugar)
        self._lista_path = None

        self._img_logo=self._img_sun=self._img_moon=None
        self._removed_count = 0
        self._removed_collapsed = False
        self.btn_removed_badge = None

        # Log de regras aplicadas por semana (para confirmar só quando mudar valor da MESMA semana)
        self._week_rule_log = {}

        self._setup_theme(); self._build_ui(); self.load_data_initial()

    # ====== Assets (imagens) ======
    def _asset_path(self, *parts):
        """
        Procura arquivo em locais comuns:
        - <dir_do_script>/assets/...
        - <dir_do_script>/...
        - <dir_do_script>/../assets/...
        - <dir_do_script>/../...
        - cwd/assets/...
        - cwd/...
        - PyInstaller (sys._MEIPASS)
        """
        base_script = os.path.dirname(os.path.abspath(__file__))
        parent_dir  = os.path.dirname(base_script)
        base_bundle = getattr(sys, "_MEIPASS", None)

        candidates = [
            os.path.join(base_script, "assets", *parts),
            os.path.join(base_script, *parts),
            os.path.join(parent_dir,  "assets", *parts),
            os.path.join(parent_dir,  *parts),
            os.path.join(os.getcwd(),  "assets", *parts),
            os.path.join(os.getcwd(),  *parts),
        ]
        if base_bundle:
            candidates += [
                os.path.join(base_bundle, "assets", *parts),
                os.path.join(base_bundle, *parts),
            ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return None

    def _load_images(self):
        """Carrega imagens (logo grande)"""
        self._img_logo = self._img_sun = self._img_moon = None
        if not PIL_AVAILABLE:
            return
        def _safe_load(fname, size):
            p = self._asset_path(fname)
            if not p: return None
            try:
                return ctk.CTkImage(light_image=Image.open(p), size=size)
            except Exception:
                return None
        # OPX MAIOR (96 x 96) + ícones de tema
        self._img_logo = _safe_load("opx.png",  (96, 96))
        self._img_sun  = _safe_load("sun.png",  (20, 20))
        self._img_moon = _safe_load("moon.png", (20, 20))

    def _get_active_tree(self):
        """Retorna a Treeview atualmente visível (filtrada ou principal)."""
        if getattr(self, "active_tree", None) is not None:
            return self.active_tree
        return getattr(self, "reported_tree", None)


    def _style_yellow_button(self, w):
        try:
            if isinstance(w, ctk.CTkButton):
                w.configure(fg_color=OPX_YELLOW,hover_color="#ffcc33",text_color="#0F172A",
                            corner_radius=12,height=max(32,int(w.cget("height") or 32)))
                return
            if isinstance(w, ctk.CTkOptionMenu):
                w.configure(fg_color=OPX_YELLOW,button_color=OPX_YELLOW,button_hover_color="#ffcc33",
                            text_color="#0F172A",corner_radius=12,height=36)
                return
            w.configure(fg_color=OPX_YELLOW,text_color="#0F172A")
        except: pass

    def _style_entry(self, entry):
        theme=THEMES[self.appearance.get()]
        try:
            entry.configure(fg_color=theme["entry_bg"], text_color=theme["entry_fg"],
                            border_color=theme["entry_border"], placeholder_text_color=theme["placeholder"],
                            corner_radius=12, height=36)
        except: pass

    def _restyle_inputs(self):
        for w in (getattr(self,"entry_week_num",None),
                  getattr(self,"entry_week_qty",None),
                  getattr(self,"entry_date",None),
                  getattr(self,"entry_search",None)):
            if w: self._style_entry(w)

    def _setup_theme(self):
        ctk.set_appearance_mode(self.appearance.get())
        theme=THEMES[self.appearance.get()]
        self.configure(fg_color=theme["bg"])

    def _setup_tree_style(self):
        theme=THEMES[self.appearance.get()]
        s=ttk.Style()
        try:s.theme_use("clam")
        except: pass
        for n in ("TFrame","TLabelframe","TLabelframe.Label"):
            s.configure(n, background=theme["bg2"], foreground=theme["fg"])
        s.layout("OPX.Treeview",[("Treeview.treearea",{"sticky":"nswe"})])
        s.configure("OPX.Treeview", background=theme["row_even"], fieldbackground=theme["row_even"],
                   foreground=theme["fg"], rowheight=28, relief="flat", borderwidth=0)
        s.map("OPX.Treeview", background=[("selected",theme["sel_bg"])], foreground=[("selected",theme["sel_fg"])])
        s.configure("OPX.Treeview.Heading", background=theme["header_bg"], foreground=theme["header_fg"],
                   relief="flat", bordercolor=theme["header_bg"])
        s.map("OPX.Treeview.Heading", background=[("active",theme["header_bg"])], foreground=[("!disabled",theme["header_fg"])])

    def _load_images_and_theme(self):
        self._load_images()
        self._setup_tree_style()

    def _restyle_action_buttons(self):
        for w in (getattr(self,"btn_reload",None), getattr(self,"btn_save",None),
                  getattr(self,"btn_transfer",None),
                  getattr(self,"btn_sort_asc",None), getattr(self,"btn_sort_desc",None),
                  getattr(self,"btn_apply_week",None), getattr(self,"btn_clear_weeks",None),
                  getattr(self,"btn_removed_badge",None),
                  getattr(self,"btn_clear_search",None),
                  getattr(self,"btn_apply_selected",None)):
            if w: self._style_yellow_button(w)

    def _style_theme_button(self):
        try:
            if self.appearance.get()=="Dark":
                self.btn_theme.configure(fg_color=OPX_YELLOW, hover_color="#ffcc33",
                                         text_color="#0F172A", corner_radius=20, width=40, height=40)
            else:
                self.btn_theme.configure(fg_color="transparent", hover_color="#222222",
                                         text_color="#FFFFFF", corner_radius=20, width=40, height=40)
        except: pass

    def _update_theme_icon(self):
        if not hasattr(self,"btn_theme"): return
        cur=self.appearance.get()
        try:
            if cur=="Light":
                self.btn_theme.configure(image=self._img_moon if self._img_moon else None, text="" if self._img_moon else "🌙")
            else:
                self.btn_theme.configure(image=self._img_sun if self._img_sun else None, text="" if self._img_sun else "☀")
            self._style_theme_button()
        except: pass

    def _toggle_theme(self):
        self.appearance.set("Dark" if self.appearance.get()=="Light" else "Light")
        self._on_theme_change()

    def _on_theme_change(self):
        self._setup_theme(); self._setup_tree_style(); self._update_theme_icon()
        self._restyle_inputs(); self._restyle_action_buttons()
        if hasattr(self,"header") and self.header is not None: self.header.configure(fg_color=HEADER_BG)
        if hasattr(self,"week_frame") and self.week_frame is not None: self.week_frame.configure(fg_color=HEADER_BG)

    def render_main_table(self):
        shell=self.table_shell
        for w in shell.winfo_children():
            if getattr(w,"_is_scroll",False): continue
            w.destroy()

        theme=THEMES[self.appearance.get()]
        self._setup_tree_style()
        self.reported_tree=ttk.Treeview(shell, columns=self.colunas_exibidas, show="headings", style="OPX.Treeview",
                                        yscrollcommand=self.scroll_y.set, xscrollcommand=self.scroll_x.set, selectmode="extended")
        self.reported_tree.pack(fill="both",expand=True,padx=0,pady=0)
        try:
            self.reported_tree.configure(borderwidth=0, highlightthickness=0)
            self.reported_tree.tk.call(self.reported_tree, "configure", "-highlightthickness", "0")
        except: pass

        self._enable_row_dnd()
        self.scroll_y.configure(command=self.reported_tree.yview)
        self.scroll_x.configure(command=self.reported_tree.xview)
        for c in self.colunas_exibidas:
            self.reported_tree.heading(c, text=c, anchor="center"); self.reported_tree.column(c, anchor="center", width=140)

        if self.df_final is not None and not self.df_final.empty:
            for _,r in self.df_final.iterrows():
                self.reported_tree.insert("", "end", values=[r.get(c,"") for c in self.colunas_exibidas])
        self.active_tree = self.reported_tree  # <- esta é a tabela ativa quando não está filtrado


    def _build_ui(self):
        theme=THEMES[self.appearance.get()]
        self._load_images()

        # ===== HEADER (preto) =====
        self.header=ctk.CTkFrame(self, fg_color=HEADER_BG); self.header.pack(fill="x", padx=12, pady=12)
        self.header.grid_columnconfigure(0,weight=0); self.header.grid_columnconfigure(1,weight=1); self.header.grid_columnconfigure(2,weight=0)
        self.header.grid_rowconfigure(0,weight=0); self.header.grid_rowconfigure(1,weight=0)
        # garante altura para a logo grande
        try:
            self.header.grid_rowconfigure(0, minsize=80)
        except Exception:
            pass

        if self._img_logo:
            ctk.CTkLabel(self.header, image=self._img_logo, text="").grid(row=0,column=0,padx=(12,8),pady=(6,2),sticky="w")
        else:
            badge=ctk.CTkFrame(self.header, fg_color=OPX_YELLOW, corner_radius=10, width=80, height=80)
            badge.grid(row=0,column=0,padx=(12,8),pady=(6,2),sticky="w"); badge.grid_propagate(False)
            ctk.CTkLabel(badge,text="OPX",text_color="#0F172A",font=ctk.CTkFont(size=20,weight="bold")).pack(expand=True)

        ctk.CTkLabel(self.header, text=self._base_title, text_color="#FFFFFF",
                     font=ctk.CTkFont(size=18, weight="bold")).grid(row=0,column=1,padx=(0,12),pady=(6,2),sticky="w")

        self.btn_theme=ctk.CTkButton(self.header,width=40,height=40,text="",command=self._toggle_theme,
                                     fg_color="transparent",hover=True,corner_radius=20)
        self.btn_theme.grid(row=0,column=2,padx=8,pady=(2,2),sticky="e"); self._update_theme_icon()

        # ===== BARRA DE CONTROLES (preta) =====
        self.week_frame=ctk.CTkFrame(self.header, fg_color=HEADER_BG)
        self.week_frame.grid(row=1,column=0,columnspan=3,sticky="we",padx=12,pady=(4,10))
        for i in range(12): self.week_frame.grid_columnconfigure(i,weight=0)
        self.week_frame.grid_columnconfigure(12,weight=1)

        ctk.CTkLabel(self.week_frame,text="Semana",text_color="#FFFFFF").grid(row=0,column=0,padx=(0,8))
        self.entry_week_num=ctk.CTkEntry(self.week_frame,width=72,height=36,textvariable=self.week_override_week,
                                         placeholder_text="45",justify="center")
        self.entry_week_num.grid(row=0,column=1); self._style_entry(self.entry_week_num)

        ctk.CTkLabel(self.week_frame,text="Capacidade",text_color="#FFFFFF").grid(row=0,column=2,padx=(10,6))
        self.entry_week_qty=ctk.CTkEntry(self.week_frame,width=72,height=36,textvariable=self.week_override_qty,
                                         placeholder_text="5",justify="center")
        self.entry_week_qty.grid(row=0,column=3); self._style_entry(self.entry_week_qty)

        self.btn_apply_week=ctk.CTkButton(self.week_frame,text="Aplicar semana",command=self._apply_week_override,width=150,height=36)
        self._style_yellow_button(self.btn_apply_week); self.btn_apply_week.grid(row=0,column=4,padx=(10,6))

        self.btn_clear_weeks=ctk.CTkButton(self.week_frame,text="Limpar regras",command=self._clear_week_overrides,width=130,height=36)
        self._style_yellow_button(self.btn_clear_weeks); self.btn_clear_weeks.grid(row=0,column=5,padx=(2,12))

        self.btn_apply_selected = ctk.CTkButton(
            self.week_frame, text="Aplicar aos selecionados",
            command=self._apply_week_to_selected, width=210, height=36
        )
        self._style_yellow_button(self.btn_apply_selected)
        self.btn_apply_selected.grid(row=0, column=6, padx=(2, 12))

        # ✅ único _overrides_label em col=7 (o duplicado causava sobreposição)
        self._overrides_label=ctk.CTkLabel(self.week_frame,text="Sem regras",text_color="#FFFFFF")
        self._overrides_label.grid(row=0,column=7,padx=(0,20), sticky="w")

        ctk.CTkLabel(self.week_frame,text="Data inicial",text_color="#FFFFFF").grid(row=0,column=8,padx=(0,8))
        self.entry_date=ctk.CTkEntry(self.week_frame,width=140,height=36,textvariable=self.start_date_str,
                                     placeholder_text="DD/MM/AAAA",justify="center")
        self.entry_date.grid(row=0,column=9,padx=(0,16)); self._style_entry(self.entry_date)

        ctk.CTkLabel(self.week_frame,text="Máx/semana",text_color="#FFFFFF").grid(row=0,column=10,padx=(0,8))
        self.opt_max=ctk.CTkOptionMenu(self.week_frame,variable=self.max_per_week,values=["3","4","5","6","7"],
                                       fg_color=OPX_YELLOW,button_color=OPX_YELLOW,button_hover_color="#ffcc33",
                                       text_color="#0F172A",corner_radius=12,height=36)
        self.opt_max.grid(row=0,column=11,padx=(0,10))

        # ===== CORPO =====
        container=ctk.CTkFrame(self, fg_color=theme["bg2"]); container.pack(fill="both",expand=True,padx=12,pady=(0,12))
        actions=ctk.CTkFrame(container, fg_color=theme["bg2"]); actions.pack(fill="x", padx=12, pady=(8,6))
        left=ctk.CTkFrame(actions, fg_color=theme["bg2"]); left.pack(side="left")

        self.btn_reload=ctk.CTkButton(left,text="Atualizar dados",command=self.on_click_atualizar_async,width=220)
        self._style_yellow_button(self.btn_reload); self.btn_reload.pack(side="left", padx=(0,8))

        self.btn_save=ctk.CTkButton(left,text="Salvar",command=self.export_excel,width=120)
        self._style_yellow_button(self.btn_save); self.btn_save.pack(side="left", padx=(0,8))

        self.btn_transfer=ctk.CTkButton(left,text="Transferir novos → Lista",command=self._transfer_all_novos,width=220)
        self._style_yellow_button(self.btn_transfer); self.btn_transfer.pack(side="left", padx=(0,8))

        self.btn_sort_asc=ctk.CTkButton(left,text="Prioridade ↑",command=self.sort_by_priority_asc,width=140)
        self._style_yellow_button(self.btn_sort_asc); self.btn_sort_asc.pack(side="left", padx=8)

        self.btn_sort_desc=ctk.CTkButton(left,text="Prioridade ↓",command=self.sort_by_priority_desc,width=140)
        self._style_yellow_button(self.btn_sort_desc); self.btn_sort_desc.pack(side="left", padx=8)

        self.btn_sort_week = ctk.CTkButton(left, text="Semanas ↑", command=self.sort_by_week, width=140)
        self._style_yellow_button(self.btn_sort_week)
        self.btn_sort_week.pack(side="left", padx=8)

        # 🔍 BUSCA (lado direito da barra de ações)
        search_frame = ctk.CTkFrame(actions, fg_color=theme["bg2"])
        search_frame.pack(side="right", padx=(8, 0))

        self.search_var = ctk.StringVar()
        self.entry_search = ctk.CTkEntry(
            search_frame, width=220, height=36,
            placeholder_text="🔍 Buscar...",
            textvariable=self.search_var, justify="left"
        )
        self._style_entry(self.entry_search)
        self.entry_search.pack(side="left", padx=(0, 6))
        self.entry_search.bind("<KeyRelease>", lambda e: self._apply_search())

        self.btn_clear_search = ctk.CTkButton(
            search_frame, text="❌", width=36, height=36,
            command=self._clear_search
        )
        self._style_yellow_button(self.btn_clear_search)
        self.btn_clear_search.pack(side="left")

        right=ctk.CTkFrame(actions, fg_color=theme["bg2"]); right.pack(side="right")
        self.btn_removed_badge = ctk.CTkButton(right, text="Removidos (0)", width=150,
                                               fg_color=OPX_YELLOW, hover_color="#ffcc33",
                                               text_color="#0F172A", corner_radius=12,
                                               command=self._show_removed_panel)
        self.btn_removed_badge.pack(side="right", padx=(8,0))

        shell=ctk.CTkFrame(container, fg_color=theme["bg2"]); shell.pack(fill="both",expand=True,padx=4,pady=(4,8))
        self.table_shell=shell
        self.scroll_y=ctk.CTkScrollbar(shell, orientation="vertical"); self.scroll_y.pack(side="right", fill="y"); self.scroll_y._is_scroll=True
        self.scroll_x=ctk.CTkScrollbar(shell, orientation="horizontal"); self.scroll_x.pack(side="bottom", fill="x"); self.scroll_x._is_scroll=True

        self._setup_tree_style()
        self.reported_tree=ttk.Treeview(shell, columns=self.colunas_exibidas, show="headings", style="OPX.Treeview",
                                        yscrollcommand=self.scroll_y.set, xscrollcommand=self.scroll_x.set, selectmode="extended")
        self.reported_tree.pack(fill="both",expand=True,padx=0,pady=0)
        try:
            self.reported_tree.configure(borderwidth=0, highlightthickness=0)
            self.reported_tree.tk.call(self.reported_tree, "configure", "-highlightthickness", "0")
        except: pass

        self._enable_row_dnd()
        self.scroll_y.configure(command=self.reported_tree.yview)
        self.scroll_x.configure(command=self.reported_tree.xview)
        for c in self.colunas_exibidas:
            self.reported_tree.heading(c, text=c, anchor="center"); self.reported_tree.column(c, anchor="center", width=140)

        # PAINÉIS NOVOS/REMOVIDOS
        self._novos_frame=ctk.CTkFrame(container, fg_color=("#000000" if self.appearance.get()=="Dark" else theme["bg2"]))
        self._removed_frame=ctk.CTkFrame(container, fg_color=("#000000" if self.appearance.get()=="Dark" else theme["bg2"]))
        self._novos_frame.pack(fill="x", padx=4, pady=(0,8)); self._removed_frame.pack(fill="x", padx=4, pady=(0,8))

    # ---------- resto do app ----------
    def _mark_dirty(self,v=True):
        if v and not self._dirty: self._dirty=True; self.title(self._base_title+" *")
        elif not v and self._dirty: self._dirty=False; self.title(self._base_title)

    def load_data_initial(self):
        # Sempre resolve a ListaAtualizada no início, pegando a mais recente
        self._lista_path = resolve_lista_path()

        df_lista = read_lista_excel_at(self._lista_path)
        if df_lista is not None and not df_lista.empty:
            self.df_final = denan(df_lista.copy())
        else:
            self.df_final = pd.DataFrame(columns=["_item_id"] + COLS_UI)

        try:
            mon_raw=get_monday_data_from_json() if os.path.exists("monday_export_all.json") else pd.DataFrame()
            mon=map_monday_to_ptbr(mon_raw) if mon_raw is not None else pd.DataFrame()
        except Exception:
            mon=pd.DataFrame()
        self.df_novos, self.df_removed = compare_new_removed(self.df_final, mon)
        self.df_final=ensure_badges(self.df_final)
        self.df_novos=ensure_badges(denan(self.df_novos))
        self.df_removed=ensure_badges(denan(self.df_removed))
        self.render_main_table(); self._render_novos_panel(); self._render_removed_panel(); self._mark_dirty(False)

    def _append_selected_to_week_end(self, week: int, stayed_indexes: list[int]):
        """
        Move, na ORDEM ATUAL, apenas as linhas cujos índices em df_final estão em stayed_indexes
        para logo após o último item da semana 'week'. Se a semana ainda não existe na tela,
        coloca no FINAL da lista.
        """
        if self.df_final is None or self.df_final.empty or not stayed_indexes:
            return

        df = self.df_final
        # mantém a ordem visual atual dos que ficaram
        stayed_in_order = [i for i in df.index if i in set(stayed_indexes)]

        # tira temporariamente os selecionados do dataframe para descobrir onde inserir
        df_excl = df.drop(index=stayed_in_order)

        # lista de índices na ordem visual restante
        idx_list = list(df_excl.index)

        # acha a última posição onde a semana 'week' aparece (sem os selecionados)
        last_pos = None
        for k, i in enumerate(idx_list):
            wk = _parse_week_from_label(str(df_excl.at[i, "Targetts"]).strip())
            if wk == week:
                last_pos = k

        # monta nova ordem
        if last_pos is None:
            # não existe ainda bloco da semana -> adiciona no fim
            new_order = idx_list + stayed_in_order
        else:
            new_order = idx_list[:last_pos + 1] + stayed_in_order + idx_list[last_pos + 1:]

        # aplica
        self.df_final = df.loc[new_order].reset_index(drop=True)
        self._mark_dirty(True)
        self.render_main_table()

    def on_click_atualizar_async(self):
        total=8
        dlg=LoadingDialog(self,title="Atualizando dados…",total=total)
        dlg.add_log("Iniciando sincronização…")
        self.btn_reload.configure(state="disabled")

        def ui_prog(s,t=""):
            try:
                if dlg.cancelled: return
                dlg.update_progress(s,t)
            except Exception: pass

        def ui_finish(novos, removidos):
            try:
                if dlg.cancelled:
                    dlg.close(); self.btn_reload.configure(state="normal"); return
                dlg.add_log(f"Novos: {novos} | Removidos: {removidos}")
                dlg.update_progress(total, "Concluído.")
                self.render_main_table(); self._render_novos_panel(); self._render_removed_panel()
            finally:
                dlg.close(); self.btn_reload.configure(state="normal")

        def run():
            try:
                s=0
                s+=1; self.after(0, ui_prog, s, "Obtendo dados…")
                self.after(0, lambda: dlg.add_log("Solicitando exportação do Monday (jsonExport)…"))
                try:
                    self.mondayDataUpdate.mondayToJson()
                    self.after(0, lambda: dlg.add_log("✔ Monday export OK."))
                except Exception as e:
                    if HAVE_MONDAY_EXPORT:
                        self.after(0, lambda: dlg.add_log(f"✖ Falha exportando Monday: {e}"))
                        raise e
                    else:
                        self.after(0, lambda: dlg.add_log("(!) Módulo de exportação ausente; seguindo com JSON local."))

                s+=1; self.after(0, ui_prog, s, "Lendo JSON…")
                self.after(0, lambda: dlg.add_log("Abrindo monday_export_all.json"))
                mon_raw = get_monday_data_from_json() if os.path.exists("monday_export_all.json") else pd.DataFrame()
                self.after(0, lambda: dlg.add_log(f"Itens no JSON bruto: {0 if mon_raw is None else len(mon_raw.index)}"))

                s+=1; self.after(0, ui_prog, s, "Mapeando colunas…")
                mon = map_monday_to_ptbr(mon_raw) if mon_raw is not None else pd.DataFrame()
                self.after(0, lambda: dlg.add_log(f"Itens após mapa pt-BR: {0 if mon is None else len(mon.index)}"))

                s+=1; self.after(0, ui_prog, s, "Carregando planilha…")
                self.after(0, lambda: dlg.add_log("Localizando ListaAtualizada.xlsx (pai/script/cwd)"))
                # sempre re-resolve o caminho para permitir substituição externa
                self._lista_path = resolve_lista_path()
                lista = read_lista_excel_at(self._lista_path)
                if lista is not None and not lista.empty:
                    self.df_final = denan(lista.copy())
                else:
                    self.df_final = pd.DataFrame(columns=["_item_id"] + COLS_UI)
                self.after(0, lambda: dlg.add_log(f"Planilha: {self._lista_path or 'NÃO ENCONTRADA'}"))

                s+=1; self.after(0, ui_prog, s, "Comparando itens…")
                self.df_novos, self.df_removed = compare_new_removed(self.df_final, mon)
                self.after(0, lambda: dlg.add_log(f"Novos: {0 if self.df_novos is None else len(self.df_novos.index)}; Removidos: {0 if self.df_removed is None else len(self.df_removed.index)}"))

                s+=1; self.after(0, ui_prog, s, "Atualizando campos…")
                cols = ["Elemento","N° Proposta","Cliente","SN","Prioridade","Data de Submissão"]
                upd, _ = apply_updates_from_monday(self.df_final, mon, cols)
                if upd>0:
                    self._mark_dirty(True)
                self.after(0, lambda: dlg.add_log(f"Células atualizadas: {upd}"))

                s+=1; self.after(0, ui_prog, s, "Harmonizando…")
                if not mon.empty and not self.df_final.empty and "_item_id" in self.df_final.columns and "_item_id" in mon.columns:
                    cur=set(mon["_item_id"].astype(str).str.strip()); before=len(self.df_final)
                    self.df_final=self.df_final[self.df_final["_item_id"].astype(str).str.strip().isin(cur) | (self.df_final["_item_id"].astype(str).str.strip()=="")].reset_index(drop=True)
                    after=len(self.df_final)
                    if after!=before:
                        self._mark_dirty(True)
                    self.after(0, lambda: dlg.add_log(f"Lista principal: {before} → {after} (após harmonização)"))

                s+=1; self.after(0, ui_prog, s, "Renderizando…")
                self.df_final=ensure_badges(denan(self.df_final)); self.df_removed=ensure_badges(denan(self.df_removed))
                self.after(0, self.render_main_table)
                self.after(0, self._render_novos_panel)
                self.after(0, self._render_removed_panel)
                self.after(0, lambda: dlg.add_log("Render concluído."))

                self.after(0, ui_finish,
                        0 if self.df_novos is None else len(self.df_novos.index),
                        0 if self.df_removed is None else len(self.df_removed.index),
                )
            except Exception as e:
                try:
                    self.after(0, lambda: show_error(self,"Erro",f"Falha na atualização:\n{e}"))
                finally:
                    self.after(0, dlg.close)
                    self.after(0, lambda: self.btn_reload.configure(state="normal"))

        threading.Thread(target=run, daemon=True).start()

    def _enable_row_dnd(self):
        self._dnd_active = False
        self._dnd_src_iid = None
        self._dnd_start_xy = None
        self._dnd_threshold = 6  # px
        self._dnd_snapshot_targets = []  # <- snapshot de Targetts por posição

        self.reported_tree.bind("<ButtonPress-1>", self._on_drag_start)
        self.reported_tree.bind("<B1-Motion>", self._on_drag_motion)
        self.reported_tree.bind("<ButtonRelease-1>", self._on_drag_release)

    def _on_drag_start(self, e):
        iid = self.reported_tree.identify_row(e.y)
        if not iid:
            self._dnd_active = False
            self._dnd_src_iid = None
            self._dnd_start_xy = None
            self._dnd_snapshot_targets = []
            return

        self._dnd_src_iid = iid
        self._dnd_start_xy = (e.x_root, e.y_root)
        self._dnd_active = False

        # Snapshot dos Targetts na ordem VISUAL atual (por posição)
        self._dnd_snapshot_targets = []
        order_iids = list(self.reported_tree.get_children(""))
        # pega os valores pela mesma ordem do Treeview
        for iid_row in order_iids:
            vals = self.reported_tree.item(iid_row, "values")
            try:
                col_idx = self.colunas_exibidas.index("Targetts")
                self._dnd_snapshot_targets.append(vals[col_idx] if col_idx < len(vals) else "")
            except ValueError:
                self._dnd_snapshot_targets.append("")

    def _on_drag_motion(self, e):
        if not self._dnd_start_xy or not self._dnd_src_iid:
            return
        dx = abs(e.x_root - self._dnd_start_xy[0])
        dy = abs(e.y_root - self._dnd_start_xy[1])
        if not self._dnd_active and (dx > self._dnd_threshold or dy > self._dnd_threshold):
            self._dnd_active = True
        if not self._dnd_active:
            return

        y = e.y
        h = self.reported_tree.winfo_height()
        if y < 20:
            self.reported_tree.yview_scroll(-1, "units")
        elif y > h - 20:
            self.reported_tree.yview_scroll(1, "units")

        tgt = self.reported_tree.identify_row(y)
        if not tgt or tgt == self._dnd_src_iid:
            return

        parent = ""
        ch = list(self.reported_tree.get_children(parent))
        try:
            idx = ch.index(tgt)
            self.reported_tree.move(self._dnd_src_iid, parent, idx)
        except Exception:
            pass

    def _on_drag_release(self, e):
        try:
            if self._dnd_active and self._dnd_src_iid:
                # 1) Reconstroi df_final obedecendo a ORDEM VISUAL atual
                self._rebuild_df_from_tree_order()

                # 2) Reaplica os Targetts da POSIÇÃO (snapshot) na nova ordem
                if self._dnd_snapshot_targets:
                    # ajusta tamanho (por segurança)
                    snap = list(self._dnd_snapshot_targets)
                    if len(snap) < len(self.df_final.index):
                        snap.extend([""] * (len(self.df_final.index) - len(snap)))
                    elif len(snap) > len(self.df_final.index):
                        snap = snap[:len(self.df_final.index)]

                    self.df_final["Targetts"] = snap

                    # preenche SOMENTE os vazios (se houver), respeitando regras/capacidade
                    # (não redistribui quem já tem)
                    if any(str(x).strip() == "" for x in self.df_final["Targetts"].tolist()):
                        self.recalc_targets(
                            keep_existing_week_caps=True,
                            user_initiated=True,
                            redistribute=False
                        )
                    else:
                        self._mark_dirty(True)
                        self.render_main_table()
        finally:
            self._dnd_active = False
            self._dnd_src_iid = None
            self._dnd_start_xy = None
            self._dnd_snapshot_targets = []

    def _rebuild_df_from_tree_order(self):
        """Reconstrói df_final obedecendo a ordem visual atual do Treeview,
        preservando os valores de cada linha (menos Targetts, que será reatribuído depois)."""
        if self.df_final is None:
            return
        rows = []
        for iid in self.reported_tree.get_children(""):
            vals = self.reported_tree.item(iid, "values")
            row = {c: (vals[i] if i < len(vals) else "") for i, c in enumerate(self.colunas_exibidas)}

            # tenta resgatar _item_id pelo par (Elemento, SN)
            rid = ""
            try:
                elem = row.get("Elemento", "")
                sn = row.get("SN", "")
                found = self.df_final[
                    (self.df_final["Elemento"] == elem) & (self.df_final["SN"] == sn)
                ]
                if not found.empty:
                    rid = found["_item_id"].iloc[0]
            except Exception:
                pass

            row["_item_id"] = rid
            rows.append(row)

        self.df_final = pd.DataFrame(rows, columns=["_item_id"] + self.colunas_exibidas)

    def sort_by_priority_asc(self):
        if self.df_final is None or self.df_final.empty: return
        key=self.df_final["Prioridade"].map(canonicalize_priority).map(lambda s: PRIO_ORDER.get(s, 9))
        self.df_final=self.df_final.iloc[key.argsort(kind="stable")].reset_index(drop=True); self.render_main_table()

    def sort_by_priority_desc(self):
        if self.df_final is None or self.df_final.empty: return
        key=self.df_final["Prioridade"].map(canonicalize_priority).map(lambda s: PRIO_ORDER.get(s, 9))
        self.df_final=self.df_final.iloc[key.argsort(kind="stable")[::-1]].reset_index(drop=True); self.render_main_table()

    def _render_novos_panel(self):
        for w in self._novos_frame.winfo_children(): w.destroy()
        title_color = "#FFFFFF" if self.appearance.get()=="Dark" else THEMES["Light"]["fg"]
        ctk.CTkLabel(self._novos_frame, text=f"Novos: {0 if self.df_novos is None else len(self.df_novos.index)}",
                     text_color=title_color).pack(anchor="w")
        if self.df_novos is None or self.df_novos.empty: return
        t=ttk.Treeview(self._novos_frame, columns=self.colunas_exibidas, show="headings", height=6, style="OPX.Treeview")
        t.pack(fill="x", pady=(6,0))
        for c in self.colunas_exibidas[:-1]:
            t.heading(c,text=c,anchor="center"); t.column(c,anchor="center",width=140)
        for _,r in self.df_novos.iterrows(): t.insert("", "end", values=[r.get(c,"") for c in self.colunas_exibidas])

    def _show_removed_panel(self):
        if self._removed_frame:
            try:
                self._removed_frame.pack(fill="x", padx=4, pady=(0,8))
            except Exception:
                pass
        self._removed_collapsed = False

    def _hide_removed_panel(self):
        if self._removed_frame:
            try:
                self._removed_frame.pack_forget()
            except Exception:
                pass
        self._removed_collapsed = True

    
    def _render_removed_panel(self):
        for w in self._removed_frame.winfo_children():
            w.destroy()
        count = 0 if self.df_removed is None else len(self.df_removed.index)
        self._removed_count = count
        if self.btn_removed_badge:
            try:
                self.btn_removed_badge.configure(text=f"Removidos ({count})")
            except Exception:
                pass
        title_color = "#FFFFFF" if self.appearance.get()=="Dark" else THEMES["Light"]["fg"]
        header = ctk.CTkFrame(self._removed_frame, fg_color="transparent"); header.pack(fill="x")
        ctk.CTkLabel(header, text=f"Removidos: {count}", text_color=title_color,
                     font=ctk.CTkFont(size=16, weight="bold")).pack(side="left", pady=(2,0))
        btn_close = ctk.CTkButton(header, text="×", width=28, height=28, corner_radius=8,
                                  fg_color=OPX_YELLOW, hover_color="#ffcc33", text_color="#0F172A",
                                  command=self._hide_removed_panel)
        btn_close.pack(side="right")
        if count == 0: return
        t=ttk.Treeview(self._removed_frame, columns=self.colunas_exibidas, show="headings", height=5, style="OPX.Treeview")
        t.pack(fill="x", pady=(6,0))
        for c in self.colunas_exibidas:
            t.heading(c, text=c, anchor="center"); t.column(c, anchor="center", width=140)
        for _, r in self.df_removed.iterrows():
            t.insert("", "end", values=[r.get(c, "") for c in self.colunas_exibidas])

    def _infer_week_caps_from_current_df(self):
        caps={}
        if self.df_final is None or self.df_final.empty: return caps
        for v in self.df_final["Targetts"].astype(str).tolist():
            wk=_parse_week_from_label(v)
            if wk is None: continue
            caps[wk]=caps.get(wk,0)+1
        return caps

    def _update_overrides_label(self):
        txt="Sem regras" if not self.week_overrides else "Regras: " + ", ".join(f"S{w}:{q}" for w,q in sorted(self.week_overrides.items()))
        if self._overrides_label: self._overrides_label.configure(text=txt)

    def recalc_targets(self, keep_existing_week_caps=True, user_initiated=False, redistribute=False):
        """
        - redistribute=False (default): NÃO redistribui quem já tem Targetts.
        Só normaliza rótulos e preenche vazios respeitando capacidades (regras > max_per_week).
        -> Use quando aplicar regra.
        - redistribute=True: empacota a lista de cima pra baixo em blocos por semana,
        começando na PRIMEIRA semana já existente na tela, respeitando capacidades.
        NÃO reordena linhas; só reatribui Targetts.
        -> Use após drag & drop.
        """
        if self.df_final is None or self.df_final.empty:
            return

        # capacidade padrão (mantém 5, como você pediu)
        try:
            maxw = int(self.max_per_week.get())
        except Exception:
            maxw = 5

        start = (self.start_date_str.get() or "28/08/2025").strip()
        cal = _compute_week_calendar(start, horizon_weeks=240)  # mapeia {wk -> monday_date}

        df = self.df_final.copy()
        if "Targetts" not in df.columns:
            df["Targetts"] = ""

        def label(wk, d): 
            return f"Semana {wk:02d} - {d.strftime('%d/%m/%Y')}"
        def capacity_of(wk: int) -> int:
            return max(0, self.week_overrides.get(wk, maxw))

        # ============= EMPACOTAMENTO (pós DnD) =============
        if redistribute:
            # 1) âncora = primeira semana já existente na ordem atual
            anchor_wk = None
            for i in range(len(df.index)):
                wk = _parse_week_from_label(str(df.at[i, "Targetts"]).strip())
                if wk is not None:
                    anchor_wk = wk
                    break

            if anchor_wk is None:
                weeks_in_cal = sorted([w for w in cal.keys() if w != 0])
                anchor_wk = weeks_in_cal[0] if weeks_in_cal else 1

            # mapa dinâmico semana->data (pode crescer)
            wk_date = dict(cal)
            counts = {}
            cur_wk = anchor_wk

            def next_week_with_slot():
                nonlocal cur_wk
                for _ in range(5000):  # guarda-chuva
                    used = counts.get(cur_wk, 0)
                    cap  = capacity_of(cur_wk)
                    if used < cap:
                        counts[cur_wk] = used + 1
                        if cur_wk not in wk_date:
                            # deriva data a partir da semana conhecida mais próxima
                            known = sorted([w for w in wk_date.keys() if w != 0])
                            if known:
                                base_w = known[-1]
                                wk_date[cur_wk] = wk_date[base_w] + timedelta(days=7)
                            else:
                                wk_date[cur_wk] = datetime.today()
                        return cur_wk, wk_date[cur_wk]
                    # sem vaga -> avança semana (1..53 com wrap)
                    nxt = _next_iso_week(cur_wk)
                    if nxt not in wk_date and cur_wk in wk_date:
                        wk_date[nxt] = wk_date[cur_wk] + timedelta(days=7)
                    cur_wk = nxt
                # fallback extremo
                return anchor_wk, wk_date.get(anchor_wk, datetime.today())

            # 2) atribui para TODOS na ordem atual (não reordena linhas)
            for i in range(len(df.index)):
                wk, d = next_week_with_slot()
                df.at[i, "Targetts"] = label(wk, d)

            self.df_final = df
            if user_initiated:
                self._mark_dirty(True)
            self.render_main_table()
            return

        # ============= MODO PADRÃO (aplicar regra) =============
        # 1) normaliza rótulos existentes e conta ocupação atual
        counts = {}
        for i in range(len(df.index)):
            cur_tt = str(df.at[i, "Targetts"]).strip()
            wk = _parse_week_from_label(cur_tt)
            if not cur_tt or wk is None:
                continue
            d = cal.get(wk, cal.get(0))
            df.at[i, "Targetts"] = label(wk, d)
            counts[wk] = counts.get(wk, 0) + 1

        # 2) preenche somente os vazios respeitando capacidades
        def next_week_with_slot_fill_only():
            for _ in range(2000):  # guarda-chuva
                for wk in [w for w in cal.keys() if w != 0]:
                    used = counts.get(wk, 0)
                    cap = capacity_of(wk)
                    if used < cap:
                        counts[wk] = used + 1
                        return wk, cal[wk]
                # estende calendário: cria nova semana após a maior conhecida
                last = max([w for w in cal.keys() if w != 0] or [1])
                nxt = 1 if last >= 53 else last + 1
                cal[nxt] = cal[last] + timedelta(days=7)

        changed = False
        for i in range(len(df.index)):
            if str(df.at[i, "Targetts"]).strip():
                continue  # NÃO mexe em quem já tem semana
            wk, d = next_week_with_slot_fill_only()
            df.at[i, "Targetts"] = label(wk, d)
            changed = True

        self.df_final = df
        if changed and user_initiated:
            self._mark_dirty(True)
        self.render_main_table()

        # --------- (bloco duplicado removido) ---------

    def _get_selected_df_indexes(self):
        """
        Converte seleção visual (na tabela ativa) em índices do df_final.
        Casa pelo trio (Elemento, SN, N° Proposta).
        """
        tree = self._get_active_tree()
        if tree is None or self.df_final is None or self.df_final.empty:
            return []

        iids = list(tree.selection())
        if not iids:
            return []

        # índice rápido por chave
        key_cols = ["Elemento", "SN", "N° Proposta"]
        for c in key_cols:
            if c not in self.df_final.columns:
                return []

        index_by_key = {}
        for i in self.df_final.index:
            k = (str(self.df_final.at[i, "Elemento"]),
                str(self.df_final.at[i, "SN"]),
                str(self.df_final.at[i, "N° Proposta"]))
            index_by_key.setdefault(k, i)  # primeiro que aparecer

        idxs = []
        for iid in iids:
            vals = tree.item(iid, "values")
            row = {c: (vals[j] if j < len(vals) else "") for j, c in enumerate(self.colunas_exibidas)}
            k = (str(row.get("Elemento", "")),
                str(row.get("SN", "")),
                str(row.get("N° Proposta", "")))
            i = index_by_key.get(k)
            if i is not None:
                idxs.append(i)

        return idxs


    def _indexes_with_week(self, df, wk):
        """Retorna índices do df cuja coluna Targetts aponta para a semana wk."""
        out = []
        for i in df.index:
            if _parse_week_from_label(str(df.at[i, "Targetts"]).strip()) == wk:
                out.append(i)
        return set(out)
    
    def _ask_week_number(self, default=""):
        """
        Abre um pop-up para o usuário digitar o número da semana (1–53).
        Tenta usar CTkInputDialog; se não existir, cai em tkinter.simpledialog.
        Retorna int ou None (se cancelar/fechar).
        """
        val = None
        # 1) CTkInputDialog (CustomTkinter >= 5)
        try:
            from customtkinter import CTkInputDialog
            dlg = CTkInputDialog(title="Aplicar semana aos selecionados",
                                text="Digite o número da semana (1–53):")
            val = dlg.get_input()
        except Exception:
            # 2) Fallback simples
            try:
                import tkinter.simpledialog as sd
                val = sd.askstring("Aplicar semana aos selecionados",
                                "Digite o número da semana (1–53):",
                                initialvalue=str(default) if default else "")
            except Exception:
                val = None

        if val is None:
            return None  # cancelado

        val = str(val).strip()
        if not val:
            return None

        try:
            wk = int(val)
        except Exception:
            show_error(self, "Semana inválida", "Informe um número inteiro entre 1 e 53.")
            return None

        if not (1 <= wk <= 53):
            show_error(self, "Semana inválida", "Semana deve estar entre 1 e 53.")
            return None

        return wk


    def _apply_week_to_selected(self):
        # --- pega seleção ---
        idxs = self._get_selected_df_indexes()
        if not idxs:
            show_error(self, "Nada selecionado", "Selecione ao menos um item na tabela.")
            return

        # --- pergunta a semana via pop-up ---
        wk_default = (self.week_override_week.get() or "").strip()  # usa como sugestão, se existir
        wk = self._ask_week_number(default=wk_default)
        if wk is None:
            return  # usuário cancelou/fechou

        # snapshot antes (quem já estava na semana)
        before_set = self._indexes_with_week(self.df_final, wk)

        # label da semana
        start = (self.start_date_str.get() or "28/08/2025").strip()
        cal = _compute_week_calendar(start, 240)
        d = cal.get(wk, cal.get(0)) or datetime.strptime(start, "%d/%m/%Y")
        lbl = f"Semana {wk:02d} - {d.strftime('%d/%m/%Y')}"

        # aplica label nos selecionados
        for i in idxs:
            self.df_final.at[i, "Targetts"] = lbl

        # capacidade alvo (regra da semana > máx/semana padrão)
        try:
            cap = int(self.week_overrides.get(wk, int(self.max_per_week.get())))
        except Exception:
            cap = self.week_overrides.get(wk, 5)

        self._mark_dirty(True)
        # faz cumprir capacidade e render
        self._enforce_week_capacity(week=wk, cap=cap)

        # pós-enforce: quem ficou na semana
        after_set = self._indexes_with_week(self.df_final, wk)
        selected_that_stayed = [i for i in idxs if i in after_set]
        stayed_count = len(selected_that_stayed)

        # lista “Você incluiu estes targetts”
        lines = []
        for i in selected_that_stayed:
            try:
                el = str(self.df_final.at[i, "Elemento"])
                sn = str(self.df_final.at[i, "SN"])
                pr = str(self.df_final.at[i, "N° Proposta"])
                lines.append(f"– {el} | {sn} | {pr}")
            except Exception:
                pass

            total_selected = len(idxs)
            now_in_week = len(after_set)

            msg = [
                f"Foi aplicada a semana {wk} para {total_selected} targetts.",
                f"Permaneceram em S{wk:02d}: {stayed_count}",
                f"Itens na S{wk:02d} agora: {now_in_week}",
                "",
                "Você incluiu mais estes targetts:" if lines else "Nenhum dos selecionados ficou na semana (sem vagas)."
            ]
            if lines:
                msg.extend(lines)

            show_info(self, "Aplicado aos selecionados", "\n".join(msg))

            # 🔽 NOVO: coloca os que ficaram no FIM do bloco da semana (sem reordenar o resto)
            stayed_keys = []
            for i in selected_that_stayed:
                try:
                    stayed_keys.append((
                        str(self.df_final.at[i, "Elemento"]),
                        str(self.df_final.at[i, "SN"]),
                        str(self.df_final.at[i, "N° Proposta"]),
                    ))
                except Exception:
                    pass

            # Reposiciona somente os que ficaram na semana escolhida
            self._append_selected_to_week_end(week=wk, stayed_indexes=selected_that_stayed)

            # Re-seleciona e rola até eles (usa o helper que já te passei)
            self._reselect_keys(stayed_keys)



    def sort_by_week(self, ascending=True):
        """Ordena por número da semana (estável, preserva ordem relativa dentro da semana)."""
        if self.df_final is None or self.df_final.empty:
            return
        def wk_key(lbl):
            wk = _parse_week_from_label(str(lbl))
            return wk if wk is not None else 999
        self.df_final = self.df_final.sort_values(
            by="Targetts",
            key=lambda s: s.map(wk_key),
            ascending=ascending,
            kind="stable"
        ).reset_index(drop=True)
        self.render_main_table()

    def _apply_week_override(self):
        try:
            w = int((self.week_override_week.get() or "").strip())
            q = int((self.week_override_qty.get()  or "").strip())
        except Exception:
            show_error(self, "Regra inválida", "Preencha 'Semana' e 'Capacidade' com números inteiros.")
            return

        if not (0 <= w <= 53) or q < 0:
            show_error(self, "Regra inválida", "Semana 0–53 e capacidade ≥ 0.")
            return

        prev = self._week_rule_log.get(w, None)
        if prev is not None and prev != q:
            c = ask_yes_no(self, "Alterar regra existente",
                        f"Semana {w} já tinha {prev} targetts.\nDeseja alterar para {q} targetts?")
            if c != "Sim":
                return

        # Atualiza regra (log + rótulo)
        self.week_overrides[w] = q
        self._week_rule_log[w] = q
        self._update_overrides_label()

        # 1) Faz cumprir imediatamente: mantém apenas os Q primeiros dessa semana e empurra excedentes
        self._enforce_week_capacity(week=w, cap=q)

        # 2) Preenche quem está sem Targetts (se houver), sem mexer nos já marcados
        self.recalc_targets(
            keep_existing_week_caps=True,
            user_initiated=True,
            redistribute=False
        )

        show_info(self, "Regra aplicada", f"Regra da semana {w} ajustada para {q} targetts.")

    def _enforce_week_capacity(self, week: int, cap: int):
        """
        Garante que a semana 'week' fique com EXATAMENTE 'cap' itens.
        1) Mantém os 'cap' primeiros (ordem visual).
        2) Excedentes: empurra para semanas posteriores respeitando capacidades.
        3) Se faltar: primeiro preenche com linhas SEM Targetts; se ainda faltar, puxa de semanas posteriores.
        """
        if self.df_final is None or self.df_final.empty:
            return

        def label(wk, d):
            return f"Semana {wk:02d} - {d.strftime('%d/%m/%Y')}"

        def capacity_of(wk: int) -> int:
            try:
                maxw = int(self.max_per_week.get())
            except Exception:
                maxw = 5
            return max(0, self.week_overrides.get(wk, maxw))

        def next_week(wk: int) -> int:
            return 1 if wk >= 53 else (1 if wk == 0 else wk + 1)

        start = (self.start_date_str.get() or "28/08/2025").strip()
        cal = _compute_week_calendar(start, horizon_weeks=240)

        df = self.df_final.copy()
        if "Targetts" not in df.columns:
            df["Targetts"] = ""

        # Normaliza rótulos e monta índices por semana
        counts, idx_by_week = {}, {}
        for i in range(len(df.index)):
            cur_tt = str(df.at[i, "Targetts"]).strip()
            wk = _parse_week_from_label(cur_tt)
            if cur_tt and wk is not None:
                d = cal.get(wk, cal.get(0))
                df.at[i, "Targetts"] = label(wk, d)
                counts[wk] = counts.get(wk, 0) + 1
                idx_by_week.setdefault(wk, []).append(i)

        # Coleta da semana-alvo
        idx_week = idx_by_week.get(week, []).copy()
        keep = idx_week[:cap] if cap >= 0 else []
        overflow_idx = idx_week[cap:] if cap < len(idx_week) else []
        counts[week] = len(keep)

        changed = False

        # 1) Empurra excedentes
        def find_next_week_with_slot(start_wk: int):
            wk_cursor = next_week(start_wk)
            for _ in range(600):
                used = counts.get(wk_cursor, 0)
                cap_w = capacity_of(wk_cursor)
                if used < cap_w:
                    if wk_cursor not in cal:
                        known = sorted([w for w in cal.keys() if w != 0])
                        cal[wk_cursor] = (cal[known[-1]] + timedelta(days=7)) if known else datetime.today()
                    return wk_cursor
                wk_cursor = next_week(wk_cursor)
            return start_wk

        for i in overflow_idx:
            wk_dest = find_next_week_with_slot(week)
            d_dest = cal.get(wk_dest, cal.get(0))
            df.at[i, "Targetts"] = label(wk_dest, d_dest)
            counts[wk_dest] = counts.get(wk_dest, 0) + 1
            counts[week] = counts.get(week, 0) - 1
            idx_by_week.setdefault(wk_dest, []).append(i)
            changed = True

        # 2) Se estiver faltando, preenche com VAZIOS primeiro
        deficit = cap - counts.get(week, 0)
        if deficit > 0:
            d_dest = cal.get(week, cal.get(0))
            for i in range(len(df.index)):
                if deficit <= 0:
                    break
                if not str(df.at[i, "Targetts"]).strip():  # vazio
                    df.at[i, "Targetts"] = label(week, d_dest)
                    counts[week] = counts.get(week, 0) + 1
                    deficit -= 1
                    changed = True

        # 3) Ainda faltou? puxa de semanas posteriores (ordem visual)
        if deficit > 0:
            def iter_forward_candidates(from_wk: int):
                seen = set()
                wk_cursor = next_week(from_wk)
                for _ in range(600):
                    for idx in idx_by_week.get(wk_cursor, []):
                        if idx not in seen:
                            seen.add(idx)
                            yield wk_cursor, idx
                    wk_cursor = next_week(wk_cursor)

            pulled = 0
            for wk_src, idx in iter_forward_candidates(week):
                if pulled >= deficit:
                    break
                d_dest = cal.get(week, cal.get(0))
                df.at[idx, "Targetts"] = label(week, d_dest)
                counts[wk_src] = counts.get(wk_src, 0) - 1
                counts[week] = counts.get(week, 0) + 1
                try:
                    idx_by_week[wk_src].remove(idx)
                except Exception:
                    pass
                idx_by_week.setdefault(week, []).append(idx)
                pulled += 1
                changed = True

        self.df_final = df

        # Complementa: preenche apenas os vazios restantes conforme capacidades (não redistribui quem já tem)
        self.recalc_targets(
            keep_existing_week_caps=True,
            user_initiated=False,
            redistribute=False
        )

        if changed:
            self._mark_dirty(True)
        self.render_main_table()

    def _clear_week_overrides(self):
        self.week_overrides.clear(); self._update_overrides_label()
        self.recalc_targets(keep_existing_week_caps=False, user_initiated=True)
        show_info(self,"Regras limpas","Todas as regras foram removidas."); self._mark_dirty(True)

    def _transfer_all_novos(self):
        if self.df_novos is None or self.df_novos.empty:
            show_info(self,"Transferir Novos","Não há itens novos.")
            return

        if self.df_final is None or self.df_final.empty:
            self.df_final = pd.DataFrame(columns=["_item_id"] + self.colunas_exibidas)

        # Garante colunas
        for c in self.colunas_exibidas:
            if c not in self.df_final.columns:
                self.df_final[c] = ""
        if "_item_id" not in self.df_final.columns:
            self.df_final["_item_id"] = ""

        # 1) Filtra somente realmente novos por _item_id
        existentes = set(self.df_final["_item_id"].astype(str).str.strip())
        novos_rows = []
        for _, r in self.df_novos.iterrows():
            rid = str(r.get("_item_id", "")).strip()
            if rid and rid in existentes:
                continue
            novos_rows.append({
                "_item_id": rid,
                "Status": r.get("Status", ""),
                "Elemento": r.get("Elemento", ""),
                "N° Proposta": r.get("N° Proposta", ""),
                "Cliente": r.get("Cliente", ""),
                "SN": r.get("SN", ""),
                # badge visual
                "Prioridade": with_priority_badge(r.get("Prioridade", "")),
                "Data de Submissão": r.get("Data de Submissão", ""),
                "Targetts": ""  # será preenchido via recalc_targets
            })
            existentes.add(rid)

        if not novos_rows:
            show_info(self,"Transferir Novos","Sem itens novos para adicionar.")
            return

        # 2) Mapa de prioridade -> novas linhas
        novos_por_prio = {}
        for row in novos_rows:
            p = canonicalize_priority(row.get("Prioridade", ""))
            novos_por_prio.setdefault(p, []).append(row)

        # 3) Descobre a sequência de prioridades já existente (na ordem em que aparecem),
        #    e a última posição (índice) de cada prioridade no df_final
        base_records = self.df_final.to_dict("records")
        ordem_existente = []          # prioridades na ordem em que aparecem
        last_index = {}               # prioridade -> último índice
        for i, row in enumerate(base_records):
            p = canonicalize_priority(row.get("Prioridade", ""))
            if p not in ordem_existente:
                ordem_existente.append(p)
            last_index[p] = i

        # 4) Monta a nova lista de registros preservando a ordem existente
        #    e inserindo os NOVOS imediatamente após o último item do mesmo bloco de prioridade.
        resultado = []
        inserido_prio = set()

        for i, row in enumerate(base_records):
            resultado.append(row)
            p = canonicalize_priority(row.get("Prioridade", ""))
            # Se este é o último item desse bloco, coloca os novos dessa prioridade agora
            if last_index.get(p, -1) == i and p in novos_por_prio and p not in inserido_prio:
                resultado.extend(novos_por_prio[p])
                inserido_prio.add(p)

        # 5) Se existem prioridades NOVAS que não existiam antes, precisamos decidir onde inserir:
        #    - após o bloco da prioridade mais alta que exista acima dela; se nenhuma, ao final.
        faltantes = [p for p in novos_por_prio.keys() if p not in inserido_prio]

        def prio_rank(p):
            return PRIO_ORDER.get(p, 999)

        if faltantes:
            for p in sorted(faltantes, key=prio_rank):
                resultado.extend(novos_por_prio[p])

        # 6) Atualiza df_final com o resultado e limpa painel de novos
        self.df_final = pd.DataFrame(resultado, columns=["_item_id"] + self.colunas_exibidas)
        self.df_novos = pd.DataFrame()

        # 7) Recalcula os Targetts para preencher os novos
        self.recalc_targets(keep_existing_week_caps=True, user_initiated=True)

        # 8) Re-render
        self.render_main_table()
        self._render_novos_panel()
        self._mark_dirty(True)
        show_info(self, "Transferência concluída", f"{len(novos_rows)} item(ns) adicionado(s) na sua prioridade.")

    def export_excel(self):
        if self.df_final is None: return
        df=denan(self.df_final.copy())
        df["Prioridade"]=df["Prioridade"].map(canonicalize_priority)
        saved_path = write_lista_excel_at(df, self._lista_path)
        self._lista_path = saved_path
        show_info(self,"Salvo",f"Alterações salvas em:\n{saved_path}")
        self._mark_dirty(False)

    # ===== 🔍 BUSCA =====
    def _apply_search(self):
        query = (self.search_var.get() or "").strip().lower()
        if not query:
            self.render_main_table()
            return
        if self.df_final is None or self.df_final.empty:
            return
        mask = self.df_final.apply(
            lambda row: any(query in str(val).lower() for val in row[self.colunas_exibidas].values),
            axis=1
        )
        filtered = self.df_final[mask]
        self._render_filtered_table(filtered)

    def _render_filtered_table(self, df_filtered):
        for w in self.table_shell.winfo_children():
            if getattr(w, "_is_scroll", False): continue
            w.destroy()
        self._setup_tree_style()
        t = ttk.Treeview(
            self.table_shell, columns=self.colunas_exibidas,
            show="headings", style="OPX.Treeview",
            yscrollcommand=self.scroll_y.set,
            xscrollcommand=self.scroll_x.set,
            selectmode="extended"
        )
        t.pack(fill="both", expand=True)
        self.scroll_y.configure(command=t.yview)
        self.scroll_x.configure(command=t.xview)
        for c in self.colunas_exibidas:
            t.heading(c, text=c, anchor="center")
            t.column(c, anchor="center", width=140)
        if df_filtered is not None and not df_filtered.empty:
            for _, r in df_filtered.iterrows():
                t.insert("", "end", values=[r.get(c, "") for c in self.colunas_exibidas])

        self.active_tree = t  # <- use esta tabela para pegar seleção quando filtrado


    def _clear_search(self):
        try:
            self.search_var.set("")
        except Exception:
            pass
        self.render_main_table()
        self.active_tree = getattr(self, "reported_tree", None)

    def _on_close(self):
        if not self._dirty: self.destroy(); return
        c=ask_yes_no(self,"Sair","Deseja salvar as alterações antes de sair?")
        if c == "Sim":
            try:self.export_excel()
            except Exception as e:
                show_error(self,"Erro ao salvar",f"Falha ao salvar:\n{e}"); return
        self.destroy()
   


if __name__=="__main__":
    app=SimpleTable(); app.mainloop()
