import os, json, threading, unicodedata, re, uuid
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
        "header_bg": "#FFFFFF",     # cabeçalho branco no modo claro
        "header_fg": "#0F172A",     # texto escuro
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
    if v is None: return ""
    s=str(v)
    s=unicodedata.normalize("NFD", s).encode("ascii","ignore").decode().upper()
    s=s.replace("Ó","O").replace("Õ","O")
    s=re.sub(r"<[^>]*>","",s)  # remove html badge
    s=re.sub(r"\s+"," ",s).strip()
    for k in PRIO_ORDER:
        if k in s: return k
    return s

def with_priority_badge(v):
    s=canonicalize_priority(v)
    if not s: return ""
    color = {"SEVERA":"#ef4444","ALTA":"#f59e0b","MEDIA":"#3b82f6","BAIXA":"#16a34a"}.get(s,"#6b7280")
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
            # todos botões amarelos
            b.configure(fg_color=OPX_YELLOW,hover_color="#ffcc33",text_color="#0F172A")
            self._btns.append(b); b.grid(row=0,column=i,padx=6)
        self.bind("<Return>", lambda e:self._set_choice(buttons[default_index] if 0<=default_index<len(buttons) else buttons[0]))
        self.deiconify(); self._btns[default_index].focus_set()
        self.protocol("WM_DELETE_WINDOW", lambda: self._set_choice(None))

    def _set_choice(self,v): self.choice=v; self.destroy()

def show_info(p,t,m):  d=ThemedMessage(p,t,m,"info",("OK",)); p.wait_window(d)
def show_error(p,t,m): d=ThemedMessage(p,t,m,"error",("OK",)); p.wait_window(d)
def ask_yes_no_cancel(p,t,m):
    d=ThemedMessage(p,t,m,"warn",("Sim","Não","Cancelar"),0); p.wait_window(d); return d.choice

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

def read_lista_excel():
    p=os.path.join(os.getcwd(),"ListaAtualizada.xlsx")
    if not os.path.exists(p): return None
    try:
        df=pd.read_excel(p,sheet_name="Reparos")
        for c in COLS_UI:
            if c not in df.columns: df[c]=""
        if "_item_id" not in df.columns: df["_item_id"]=""
        return denan(df[["_item_id"]+COLS_UI])
    except Exception:
        return None

def write_lista_excel(df):
    p=os.path.join(os.getcwd(),"ListaAtualizada.xlsx")
    df.to_excel(p, sheet_name="Reparos", index=False)

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
            t.append(f"Semana {wk:02d} - {cur.strftime('%d/%m/%Y')}"); ass+=1
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

    # NOVO: método para adicionar linhas no log, com timestamp
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

        self._img_logo=self._img_sun=self._img_moon=None
        # --- Estado de painel Removidos / badge ---
        self._removed_count = 0
        self._removed_collapsed = False
        self.btn_removed_badge = None

        # --- Log de regras aplicadas por semana (para confirmações futuras) ---
        self._week_rule_log = {}

        self._setup_theme(); self._build_ui(); self.load_data_initial()

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
        for w in (getattr(self,"entry_week_num",None), getattr(self,"entry_week_qty",None), getattr(self,"entry_date",None)):
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

    def _load_images(self):
        self._img_logo=None; self._img_sun=None; self._img_moon=None
        if PIL_AVAILABLE:
            try:
                if os.path.exists("assets/opx.png"):
                    self._img_logo = ctk.CTkImage(light_image=Image.open("assets/opx.png"), size=(42,42))
            except Exception: self._img_logo=None
            try:
                if os.path.exists("assets/sun.png"):
                    self._img_sun  = ctk.CTkImage(light_image=Image.open("assets/sun.png"), size=(20,20))
            except Exception: self._img_sun=None
            try:
                if os.path.exists("assets/moon.png"):
                    self._img_moon = ctk.CTkImage(light_image=Image.open("assets/moon.png"), size=(20,20))
            except Exception: self._img_moon=None

    def _restyle_action_buttons(self):
        for w in (getattr(self,"btn_reload",None), getattr(self,"btn_transfer",None),
                  getattr(self,"btn_sort_asc",None), getattr(self,"btn_sort_desc",None),
                  getattr(self,"btn_apply_week",None), getattr(self,"btn_clear_weeks",None),
                  getattr(self,"btn_removed_badge",None)):
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
        # Faixas sempre pretas no topo
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

    def _build_ui(self):
        theme=THEMES[self.appearance.get()]
        self._load_images()

        # ===== HEADER (preto) =====
        self.header=ctk.CTkFrame(self, fg_color=HEADER_BG); self.header.pack(fill="x", padx=12, pady=12)
        self.header.grid_columnconfigure(0,weight=0); self.header.grid_columnconfigure(1,weight=1); self.header.grid_columnconfigure(2,weight=0)
        self.header.grid_rowconfigure(0,weight=0); self.header.grid_rowconfigure(1,weight=0)

        if self._img_logo:
            ctk.CTkLabel(self.header, image=self._img_logo, text="").grid(row=0,column=0,padx=(12,8),pady=(6,2),sticky="w")
        else:
            badge=ctk.CTkFrame(self.header, fg_color=OPX_YELLOW, corner_radius=10, width=40, height=40)
            badge.grid(row=0,column=0,padx=(12,8),pady=(6,2),sticky="w"); badge.grid_propagate(False)
            ctk.CTkLabel(badge,text="OPX",text_color="#0F172A",font=ctk.CTkFont(size=14,weight="bold")).pack(expand=True)

        ctk.CTkLabel(self.header, text=self._base_title, text_color="#FFFFFF",
                     font=ctk.CTkFont(size=18, weight="bold")).grid(row=0,column=1,padx=(0,12),pady=(6,2),sticky="w")

        self.btn_theme=ctk.CTkButton(self.header,width=40,height=40,text="",command=self._toggle_theme,
                                     fg_color="transparent",hover=True,corner_radius=20)
        self.btn_theme.grid(row=0,column=2,padx=8,pady=(2,2),sticky="e"); self._update_theme_icon()

        # ===== BARRA DE CONTROLES (também preta) =====
        self.week_frame=ctk.CTkFrame(self.header, fg_color=HEADER_BG)
        self.week_frame.grid(row=1,column=0,columnspan=3,sticky="we",padx=12,pady=(4,10))
        for i in range(12): self.week_frame.grid_columnconfigure(i,weight=0)
        self.week_frame.grid_columnconfigure(11,weight=1)

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

        self._overrides_label=ctk.CTkLabel(self.week_frame,text="Sem regras",text_color="#FFFFFF")
        self._overrides_label.grid(row=0,column=6,padx=(0,20))

        ctk.CTkLabel(self.week_frame,text="Data inicial",text_color="#FFFFFF").grid(row=0,column=7,padx=(0,8))
        self.entry_date=ctk.CTkEntry(self.week_frame,width=140,height=36,textvariable=self.start_date_str,
                                     placeholder_text="DD/MM/AAAA",justify="center")
        self.entry_date.grid(row=0,column=8,padx=(0,16)); self._style_entry(self.entry_date)

        ctk.CTkLabel(self.week_frame,text="Máx/semana",text_color="#FFFFFF").grid(row=0,column=9,padx=(0,8))
        self.opt_max=ctk.CTkOptionMenu(self.week_frame,variable=self.max_per_week,values=["3","4","5","6","7"],
                                       fg_color=OPX_YELLOW,button_color=OPX_YELLOW,button_hover_color="#ffcc33",
                                       text_color="#0F172A",corner_radius=12,height=36)
        self.opt_max.grid(row=0,column=10,padx=(0,10))

        # ===== CORPO =====
        container=ctk.CTkFrame(self, fg_color=theme["bg2"]); container.pack(fill="both",expand=True,padx=12,pady=(0,12))
        actions=ctk.CTkFrame(container, fg_color=theme["bg2"]); actions.pack(fill="x", padx=12, pady=(8,6))
        left=ctk.CTkFrame(actions, fg_color=theme["bg2"]); left.pack(side="left")

        self.btn_reload=ctk.CTkButton(left,text="Atualizar dados",command=self.on_click_atualizar_async,width=300)
        self._style_yellow_button(self.btn_reload); self.btn_reload.pack(side="left", padx=(0,8))
        self.btn_transfer=ctk.CTkButton(left,text="Transferir novos → Lista",command=self._transfer_all_novos,width=220)
        self._style_yellow_button(self.btn_transfer); self.btn_transfer.pack(side="left", padx=(0,8))
        self.btn_sort_asc=ctk.CTkButton(left,text="Prioridade ↑",command=self.sort_by_priority_asc,width=140)
        self._style_yellow_button(self.btn_sort_asc); self.btn_sort_asc.pack(side="left", padx=8)
        self.btn_sort_desc=ctk.CTkButton(left,text="Prioridade ↓",command=self.sort_by_priority_desc,width=140)
        self._style_yellow_button(self.btn_sort_desc); self.btn_sort_desc.pack(side="left", padx=8)
        right=ctk.CTkFrame(actions, fg_color=theme["bg2"]); right.pack(side="right")
        # Badge "Removidos (N)" fixo para reabrir painel quando fechado
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

        # PAINÉIS NOVOS/REMOVIDOS – em Dark ficam 100% pretos
        self._novos_frame=ctk.CTkFrame(container, fg_color=("#000000" if self.appearance.get()=="Dark" else theme["bg2"]))
        self._removed_frame=ctk.CTkFrame(container, fg_color=("#000000" if self.appearance.get()=="Dark" else theme["bg2"]))
        self._novos_frame.pack(fill="x", padx=4, pady=(0,8)); self._removed_frame.pack(fill="x", padx=4, pady=(0,8))

    # ---------- resto do app ----------
    def _mark_dirty(self,v=True):
        if v and not self._dirty: self._dirty=True; self.title(self._base_title+" *")
        elif not v and self._dirty: self._dirty=False; self.title(self._base_title)

    def load_data_initial(self):
        df_lista=read_lista_excel()
        self.df_final=denan(df_lista.copy()) if df_lista is not None and not df_lista.empty else pd.DataFrame(columns=["_item_id"]+COLS_UI)
        try:
            mon_raw=get_monday_data_from_json() if os.path.exists("monday_export_all.json") else pd.DataFrame()
            mon=map_monday_to_ptbr(mon_raw) if mon_raw is not None else pd.DataFrame()
        except Exception:
            mon=pd.DataFrame()
        self.df_novos, self.df_removed = compare_new_removed(self.df_final, mon)
        # Harmoniza prioridades e badges
        self.df_final=ensure_badges(self.df_final)
        self.df_novos=ensure_badges(denan(self.df_novos))
        self.df_removed=ensure_badges(denan(self.df_removed))
        self.render_main_table(); self._render_novos_panel(); self._render_removed_panel(); self._mark_dirty(False)

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
                # 1) Baixar do Monday
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

                # 2) Ler JSON
                s+=1; self.after(0, ui_prog, s, "Lendo JSON…")
                self.after(0, lambda: dlg.add_log("Abrindo monday_export_all.json"))
                mon_raw = get_monday_data_from_json() if os.path.exists("monday_export_all.json") else pd.DataFrame()
                self.after(0, lambda: dlg.add_log(f"Itens no JSON bruto: {0 if mon_raw is None else len(mon_raw.index)}"))

                # 3) Mapear colunas
                s+=1; self.after(0, ui_prog, s, "Mapeando colunas…")
                mon = map_monday_to_ptbr(mon_raw) if mon_raw is not None else pd.DataFrame()
                self.after(0, lambda: dlg.add_log(f"Itens após mapa pt-BR: {0 if mon is None else len(mon.index)}"))

                # 4) Planilha local
                s+=1; self.after(0, ui_prog, s, "Carregando planilha…")
                self.after(0, lambda: dlg.add_log("Lendo ListaAtualizada.xlsx (sheet 'Reparos')"))
                lista = read_lista_excel()
                if lista is not None and not lista.empty:
                    self.df_final = denan(lista.copy())
                else:
                    self.df_final = pd.DataFrame(columns=["_item_id"]+COLS_UI)

                # 5) Novos/Removidos
                s+=1; self.after(0, ui_prog, s, "Comparando itens…")
                self.df_novos, self.df_removed = compare_new_removed(self.df_final, mon)
                self.after(0, lambda: dlg.add_log(f"Novos: {0 if self.df_novos is None else len(self.df_novos.index)}; Removidos: {0 if self.df_removed is None else len(self.df_removed.index)}"))

                # 6) Atualizações de campos permitidos
                s+=1; self.after(0, ui_prog, s, "Atualizando campos…")
                cols = ["Elemento","N° Proposta","Cliente","SN","Prioridade","Data de Submissão"]
                upd, _ = apply_updates_from_monday(self.df_final, mon, cols)
                if upd>0:
                    self._mark_dirty(True)
                self.after(0, lambda: dlg.add_log(f"Células atualizadas: {upd}"))

                # 7) Harmonização
                s+=1; self.after(0, ui_prog, s, "Harmonizando…")
                if not mon.empty and not self.df_final.empty and "_item_id" in self.df_final.columns and "_item_id" in mon.columns:
                    cur=set(mon["_item_id"].astype(str).str.strip()); before=len(self.df_final)
                    self.df_final=self.df_final[self.df_final["_item_id"].astype(str).str.strip().isin(cur) | (self.df_final["_item_id"].astype(str).str.strip()=="")].reset_index(drop=True)
                    after=len(self.df_final)
                    if after!=before:
                        self._mark_dirty(True)
                    self.after(0, lambda: dlg.add_log(f"Lista principal: {before} → {after} (após harmonização)"))

                # 8) Render
                s+=1; self.after(0, ui_prog, s, "Renderizando…")
                self.df_final=ensure_badges(denan(self.df_final)); self.df_removed=ensure_badges(denan(self.df_removed))
                self.after(0, self.render_main_table)
                self.after(0, self._render_novos_panel)
                self.after(0, self._render_removed_panel)
                self.after(0, lambda: dlg.add_log("Render concluído."))

                # Fechar/Resumo
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
        # Estado do DnD com threshold
        self._dnd_active = False
        self._dnd_src_iid = None
        self._dnd_start_xy = None
        self._dnd_threshold = 6  # px

        self.reported_tree.bind("<ButtonPress-1>", self._on_drag_start)
        self.reported_tree.bind("<B1-Motion>", self._on_drag_motion)
        self.reported_tree.bind("<ButtonRelease-1>", self._on_drag_release)

    def _on_drag_start(self, e):
        iid = self.reported_tree.identify_row(e.y)
        if not iid:
            self._dnd_active = False
            self._dnd_src_iid = None
            self._dnd_start_xy = None
            return
        # Apenas marca o ponto inicial; não ativa ainda
        self._dnd_src_iid = iid
        self._dnd_start_xy = (e.x_root, e.y_root)
        self._dnd_active = False

    def _on_drag_motion(self, e):
        if not self._dnd_start_xy or not self._dnd_src_iid:
            return
        dx = abs(e.x_root - self._dnd_start_xy[0])
        dy = abs(e.y_root - self._dnd_start_xy[1])
        if not self._dnd_active and (dx > self._dnd_threshold or dy > self._dnd_threshold):
            self._dnd_active = True

        if not self._dnd_active:
            return  # clique simples, não reordena

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
        # Só reconstrói se houve arrasto real
        try:
            if self._dnd_active and self._dnd_src_iid:
                self._rebuild_df_from_tree_order()
                self.recalc_targets(keep_existing_week_caps=True, user_initiated=True)
                self.render_main_table()
                self._mark_dirty(True)
        finally:
            self._dnd_active = False
            self._dnd_src_iid = None
            self._dnd_start_xy = None

    def _rebuild_df_from_tree_order(self):
        if self.df_final is None: return
        rows=[]
        for iid in self.reported_tree.get_children(""):
            vals=self.reported_tree.item(iid,"values")
            row={c:vals[i] if i<len(vals) else "" for i,c in enumerate(self.colunas_exibidas)}
            # _item_id invisível no Treeview → preserve do df_final pela combinação (Elemento,SN,Cliente) quando possível
            found=self.df_final[(self.df_final["Elemento"]==row.get("Elemento",""))&(self.df_final["SN"]==row.get("SN",""))]
            rid = found["_item_id"].iloc[0] if not found.empty else ""
            row["_item_id"]=rid
            rows.append(row)
        self.df_final = pd.DataFrame(rows)

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
        # Treeview usa o mesmo estilo OPX (já preto no Dark)
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
        # Atualiza contador e badge
        count = 0 if self.df_removed is None else len(self.df_removed.index)
        self._removed_count = count
        if self.btn_removed_badge:
            try:
                self.btn_removed_badge.configure(text=f"Removidos ({count})")
            except Exception:
                pass

        title_color = "#FFFFFF" if self.appearance.get()=="Dark" else THEMES["Light"]["fg"]
        # Header com título e botão X (fecha/oculta o painel)
        header = ctk.CTkFrame(self._removed_frame, fg_color="transparent")
        header.pack(fill="x")
        ctk.CTkLabel(header, text=f"Removidos: {count}", text_color=title_color,
                     font=ctk.CTkFont(size=16, weight="bold")).pack(side="left", pady=(2,0))
        btn_close = ctk.CTkButton(header, text="×", width=28, height=28, corner_radius=8,
                                  fg_color=OPX_YELLOW, hover_color="#ffcc33", text_color="#0F172A",
                                  command=self._hide_removed_panel)
        btn_close.pack(side="right")

        if count == 0:
            return

        t=ttk.Treeview(self._removed_frame, columns=self.colunas_exibidas, show="headings", height=5, style="OPX.Treeview")
        t.pack(fill="x", pady=(6,0))
        for c in self.colunas_exibidas:
            t.heading(c, text=c, anchor="center")
            t.column(c, anchor="center", width=140)
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

    def recalc_targets(self, keep_existing_week_caps=True, user_initiated=False):
        if self.df_final is None: return
        n=len(self.df_final.index)
        try: maxw=int(self.max_per_week.get())
        except: maxw=5
        start=self.start_date_str.get() or "28/08/2025"
        eff={}
        if keep_existing_week_caps: eff.update(self._infer_week_caps_from_current_df())
        eff.update(self.week_overrides)
        new=generate_targets(n, start_date_str=start, default_per_week=maxw, week_overrides=eff, start_from_next_week=True)
        if "Targetts" not in self.df_final.columns or self.df_final["Targetts"].tolist()!=new:
            self.df_final["Targetts"]=new
            if user_initiated: self._mark_dirty(True)
        self.render_main_table()

    def _apply_week_override(self):
        try:
            w = int((self.week_override_week.get() or "").strip())
            q = int((self.week_override_qty.get()  or "").strip())
        except Exception:
            show_error(self, "Regra inválida", "Preencha 'Semana' e 'Capacidade' com números inteiros."); return
        if not (0 <= w <= 53) or q < 0:
            show_error(self, "Regra inválida", "Semana 0–53 e capacidade ≥ 0."); return

        # Confirmação 1: aplicar regra
        c = ask_yes_no_cancel(self, "Aplicar regra", f"Aplicar a regra:\n\nSemana {w} → {q} targetts?\n\nIsso irá recalcular a distribuição.")
        if c != "Sim":
            return

        # Confirmação 2: se já havia valor diferente para a MESMA semana
        prev = self._week_rule_log.get(w, None)
        if prev is not None and prev != q:
            c2 = ask_yes_no_cancel(self, "Alterar regra existente",
                                   f"Semana {w} já tinha {prev} targetts.\nAgora deseja alterar para {q} targetts?\n\nConfirmar alteração?")
            if c2 != "Sim":
                return

        # Aplica de fato
        self.week_overrides[w] = q
        self._week_rule_log[w] = q
        self._update_overrides_label()
        self.recalc_targets(keep_existing_week_caps=True, user_initiated=True)
        self.render_main_table()
        show_info(self, "Regra aplicada", f"Semana {w} = {q}.")
        self._mark_dirty(True)

    def _clear_week_overrides(self):
        self.week_overrides.clear(); self._update_overrides_label()
        self.recalc_targets(keep_existing_week_caps=False, user_initiated=True)
        show_info(self,"Regras limpas","Todas as regras foram removidas."); self._mark_dirty(True)

    def _transfer_all_novos(self):
        if self.df_novos is None or self.df_novos.empty:
            show_info(self,"Transferir Novos","Não há itens novos."); return
        if self.df_final is None or self.df_final.empty:
            self.df_final=pd.DataFrame(columns=["_item_id"]+self.colunas_exibidas)
        for c in self.colunas_exibidas:
            if c not in self.df_final.columns: self.df_final[c]=""
        if "_item_id" not in self.df_final.columns: self.df_final["_item_id"]=""
        added=0; existing=set(self.df_final["_item_id"].astype(str).str.strip())
        prio_can=self.df_final["Prioridade"].map(canonicalize_priority) if not self.df_final.empty else pd.Series(dtype=str)
        for _,r in self.df_novos.iterrows():
            rid=str(r.get("_item_id","")).strip()
            if rid and rid in existing: continue
            new={"_item_id":rid, "Status":r.get("Status",""),"Elemento":r.get("Elemento",""),
                 "N° Proposta":r.get("N° Proposta",""),"Cliente":r.get("Cliente",""),"SN":r.get("SN",""),
                 "Prioridade":with_priority_badge(r.get("Prioridade","")),"Data de Submissão":r.get("Data de Submissão",""),"Targetts":""}
            p_new=canonicalize_priority(new["Prioridade"])
            if self.df_final.empty:
                self.df_final=pd.concat([self.df_final,pd.DataFrame([new])],ignore_index=True)
                prio_can=pd.Series([p_new]); existing.add(rid); added+=1; continue
            # insere mantendo posição relativa por prioridade (não mexe nos já existentes)
            insert_idx=len(self.df_final.index)
            self.df_final=self.df_final.iloc[:insert_idx].append(new, ignore_index=True)
            existing.add(rid); added+=1
        self.df_novos=pd.DataFrame()
        self.render_main_table(); self._render_novos_panel(); self._mark_dirty(True)
        show_info(self,"Transferência concluída",f"{added} item(ns) adicionado(s) à lista.")

    def export_excel(self):
        if self.df_final is None: return
        df=denan(self.df_final.copy())
        # remove badge de prioridade ao exportar
        df["Prioridade"]=df["Prioridade"].map(canonicalize_priority)
        write_lista_excel(df)
        show_info(self,"Salvo","Alterações salvas em ListaAtualizada.xlsx")
        self._mark_dirty(False)

    def _on_close(self):
        if not self._dirty: self.destroy(); return
        c=ask_yes_no_cancel(self,"Sair","Deseja salvar as alterações antes de sair?\n\nSim: Salva e sai\nNão: Sai sem salvar\nCancelar: Volta ao app")
        if c is None or c=="Cancelar": return
        if c=="Sim":
            try:self.export_excel()
            except Exception as e:
                show_error(self,"Erro ao salvar",f"Falha ao salvar:\n{e}"); return
        self.destroy()

if __name__=="__main__":
    app=SimpleTable(); app.mainloop()
