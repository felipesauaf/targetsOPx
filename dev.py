import json
import pandas as pd
from datetime import datetime, timedelta
import customtkinter as ctk
from tkinter import ttk
from jsonExport import dataMondaytoJson

# ---------------- Aparência / Tema ----------------
ctk.set_appearance_mode("dark")          # dark / light / system
ctk.set_default_color_theme("blue")      # base azul clean


# ---------------- Dados (Monday) ----------------
def get_monday_data():
    # Abre o arquivo JSON exportado do Monday.com no modo leitura
    with open('monday_export_all.json', 'r', encoding='utf-8') as f:
        data = json.load(f)  # Carrega o conteúdo do arquivo em um dicionário Python

    # Extrai a lista de itens (tarefas/entradas) do JSON, ou retorna lista vazia se não existir
    items = data.get('items', [])
    records = []  # Lista para armazenar os registros tratados

    # Percorre cada item do JSON
    for item in items:
        # Cria um dicionário com o campo "Name" (nome do item), ou vazio se não existir
        record = {"Name": item.get("name", "")}

        # Percorre todas as colunas do item e pega o campo "text"
        for col in item.get("column_values", []):
            record[col.get("id")] = col.get("text")

        # Garante SN explicitamente (id "text" no Monday)
        record["text"] = next(
            (col.get("text") for col in item.get("column_values", []) if col.get("id") == "text"),
            None  # Se não existir, retorna None
        )

        # Adiciona o registro completo à lista de registros
        records.append(record)

    # Converte a lista de registros em um DataFrame do pandas
    df = pd.DataFrame(records)

    # Garante que colunas críticas existam
    for col in ("status", "status_1", "subelementos", "proposta_n_", "cliente"):
        if col not in df.columns:
            df[col] = "" if col in ("subelementos", "proposta_n_", "cliente") else None

    # Converte a coluna "due_date" para datetime, se existir
    if "due_date" in df.columns:
        df["due_date"] = pd.to_datetime(df["due_date"], errors="coerce")
    else:
        df["due_date"] = pd.NaT

    # Filtra apenas os registros com status desejados
    status_desejados = {"Reportado", "Pausado", "Em andamento"}
    df = df[df["status"].isin(status_desejados)].copy()

    # Remove registros antigos, onde "status_1" está "--", vazio ou None
    df = df[~df["status_1"].isin(["--", "", None])].copy()

    # Retorna o DataFrame tratado
    return df


# ---------------- Lógica de targets ----------------
def monday_of_week(d: datetime) -> datetime:
    """
    Retorna a data da segunda-feira da semana da data 'd'.
    Caso a data informada seja sábado ou domingo,
    retorna a próxima segunda-feira.
    """
    if d.weekday() < 5:
        return d - timedelta(days=d.weekday())
    return d + timedelta(days=(7 - d.weekday()))

def generate_targets(n, start_date_str="28/08/2025", max_per_week=5):
    """
    Targets semanais com ANO:
      - Até 'max_per_week' itens por semana;
      - Target sempre na segunda-feira da semana seguinte;
      - Semana inicial começa em 36 e reseta em 52.
    """
    # Converte a data inicial (string) para objeto datetime
    start = datetime.strptime(start_date_str, "%d/%m/%Y")

    # Obtém a segunda-feira da semana da data inicial
    week_monday = monday_of_week(start)

    targets = []
    week_idx = 0

    for i in range(n):
        block = i // max_per_week
        if block != week_idx:
            week_idx = block

        target_date = week_monday + timedelta(days=7 * (week_idx + 1))

        # começa em 36 e quando passa de 52 volta para 1
        semana_rotulo = (week_idx + 36 - 1) % 52 + 1
        targets.append(f"Semana {semana_rotulo} - {target_date.strftime('%d/%m/%Y')}")

    return targets

def add_targets_to_reparos(df, start_date_str="28/08/2025", max_per_week=5):
    """
    Adiciona uma coluna 'target' ao DataFrame de reparos,
    atribuindo semanas conforme prioridade e data limite (due_date).
    """
    if df.empty:
        df["target"] = None
        return df

    prioridade = {"SEVERA": 0, "ALTA": 1, "MÉDIA": 2, "LEVE": 3}
    df = df.copy()
    df["__priority__"] = df["status_1"].map(prioridade).fillna(999).astype(int)

    df = df.sort_values(by=["__priority__", "due_date"], ascending=[True, True]).reset_index(drop=True)
    df["target"] = generate_targets(len(df), start_date_str=start_date_str, max_per_week=max_per_week)

    return df.drop(columns=["__priority__"])


# ---------------- App ----------------
class SimpleTable(ctk.CTk):
    def __init__(self):
        super().__init__()  # Inicializa a janela principal
        self.title("Fila de Reparos · OPX")
        self.geometry("1280x820")
        self.minsize(1024, 600)

        # ---------- Estado ----------
        self.start_date_str = ctk.StringVar(value="28/08/2025")  # Data inicial
        self.max_per_week = ctk.StringVar(value="5")             # Máx. reparos por semana
        self.appearance = ctk.StringVar(value="dark")            # Tema

        # NOVA ORDEM DE EXIBIÇÃO:
        # Status, Elemento, N° Proposta, Cliente, SN, Prioridade, Data de Submissão, Targetts
        self.colunas_exibidas = [
            "Status",
            "Elemento",
            "N° Proposta",
            "Cliente",     # <— novo campo entre N° Proposta e SN
            "SN",
            "Prioridade",
            "Data de Submissão",
            "Targetts",
        ]
        self.df_final = pd.DataFrame()

        # Controle para Drag & Drop (DnD)
        self._dragging_iid = None
        self._auto_scroll_job = None

        # ---------- Header ----------
        header = ctk.CTkFrame(self, corner_radius=16)
        header.pack(fill="x", padx=14, pady=12)

        title = ctk.CTkLabel(header, text="Fila de Reparos",
                             font=ctk.CTkFont(size=24, weight="bold"))
        subtitle = ctk.CTkLabel(header,
                                text="Arraste linhas para reordenar · targets saem na 2ª feira da semana seguinte",
                                font=ctk.CTkFont(size=12))
        title.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 0))
        subtitle.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 12))

        controls = ctk.CTkFrame(header, fg_color="transparent")
        controls.grid(row=0, column=1, rowspan=2, sticky="e", padx=12, pady=12)

        ctk.CTkLabel(controls, text="Data inicial").grid(row=0, column=0, padx=(0, 8))
        self.entry_date = ctk.CTkEntry(controls, width=120, textvariable=self.start_date_str,
                                       placeholder_text="DD/MM/AAAA")
        self.entry_date.grid(row=0, column=1, padx=(0, 16))

        ctk.CTkLabel(controls, text="Máx/semana").grid(row=0, column=2, padx=(0, 8))
        self.opt_max = ctk.CTkOptionMenu(controls, variable=self.max_per_week,
                                         values=["3", "4", "5", "6", "7"])
        self.opt_max.grid(row=0, column=3, padx=(0, 16))

        self.btn_recalc = ctk.CTkButton(controls, text="Recalcular", command=self.recalc_targets, width=120)
        self.btn_recalc.grid(row=0, column=4, padx=(0, 16))

        self.btn_auto = ctk.CTkButton(controls, text="Auto ajustar", command=self.auto_resize_columns, width=120)
        self.btn_auto.grid(row=0, column=5, padx=(0, 16))

        self.appearance_btn = ctk.CTkSegmentedButton(controls, values=["dark", "light", "system"],
                                                     variable=self.appearance, command=self.change_appearance)
        self.appearance_btn.grid(row=0, column=6)

        # ---------- Container ----------
        container = ctk.CTkFrame(self, corner_radius=16)
        container.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        # Barra de ações
        actions = ctk.CTkFrame(container, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=(12, 6))

        self.btn_reload = ctk.CTkButton(actions, text="Atualizar dados", command=lambda: self.load_data(1), width=150)
        self.btn_reload.pack(side="left")

        self.btn_sort_asc = ctk.CTkButton(actions, text="Prioridade ↑", command=self.sort_by_priority_asc, width=140)
        self.btn_sort_asc.pack(side="left", padx=8)

        self.btn_sort_desc = ctk.CTkButton(actions, text="Prioridade ↓", command=self.sort_by_priority_desc, width=140)
        self.btn_sort_desc.pack(side="left")

        # ---------- Treeview + Scroll ----------
        tree_wrap = ctk.CTkFrame(container)
        tree_wrap.pack(fill="both", expand=True, padx=12, pady=(8, 12))

        self.scroll_y = ttk.Scrollbar(tree_wrap, orient="vertical")
        self.scroll_y.pack(side="right", fill="y")

        self.scroll_x = ttk.Scrollbar(tree_wrap, orient="horizontal")
        self.scroll_x.pack(side="bottom", fill="x")

        # Estilo bonitão para o Treeview (dark + zebra + seleção)
        self._setup_tree_style()

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

        # Cabeçalhos e larguras iniciais
        for col in self.colunas_exibidas:
            self.reported_tree.heading(col, text=col, command=lambda c=col: self.sort_by_column(c))
            self.reported_tree.column(col, minwidth=90, width=160, anchor="center")

        # Zebra
        self.reported_tree.tag_configure("oddrow", background="#0f172a")
        self.reported_tree.tag_configure("evenrow", background="#111827")

        # --- DnD bindings ---
        self.reported_tree.bind("<ButtonPress-1>", self._on_tree_press)
        self.reported_tree.bind("<B1-Motion>", self._on_tree_motion)
        self.reported_tree.bind("<ButtonRelease-1>", self._on_tree_release)

        # Rodapé (status bar)
        self.status = ctk.CTkLabel(self, text="Pronto", anchor="w")
        self.status.pack(fill="x", padx=14, pady=(0, 10))

        self.mondayDataUpdate = dataMondaytoJson()

        self.load_data()

    # ---------- Estilo ttk ----------
    def _setup_tree_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        # Cores base (dark)
        bg = "#0b1220"
        fg = "#e5e7eb"
        sel_bg = "#1f6aa5"
        sel_fg = "#ffffff"
        hdr_bg = "#0f172a"
        hdr_fg = "#e5e7eb"

        style.configure(
            "OPX.Treeview",
            background=bg,
            foreground=fg,
            fieldbackground=bg,
            rowheight=30,
            borderwidth=0,
            relief="flat",
            font=("Segoe UI", 11),
        )
        style.map(
            "OPX.Treeview",
            background=[("selected", sel_bg)],
            foreground=[("selected", sel_fg)],
        )

        style.configure(
            "OPX.Treeview.Heading",
            background=hdr_bg,
            foreground=hdr_fg,
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            borderwidth=0,
        )

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

            # Exibição com due_date formatada (dd/mm/aaaa)
            df = df.copy()
            if pd.api.types.is_datetime64_any_dtype(df["due_date"]):
                df["due_date"] = df["due_date"].dt.strftime("%d/%m/%Y")

            # Ícones de prioridade
            icon = {"SEVERA": "🟥 ", "ALTA": "🟧 ", "MÉDIA": "🟦 ", "LEVE": "🟩 "}
            df["status_1"] = df["status_1"].map(lambda s: f"{icon.get(s,'')} {s}" if s else s)

            # Mapeamento de nomes de colunas -> rótulos bonitos
            column_mapping = {
                "Name": "Elemento",
                "subelementos": "Subelementos",
                "proposta_n_": "N° Proposta",
                "cliente": "Cliente",         # <— mapeia o campo do JSON para o rótulo
                "text": "SN",
                "status_1": "Prioridade",
                "status": "Status",
                "due_date": "Data de Submissão",
                "target": "Targetts",
            }
            df.rename(columns=column_mapping, inplace=True)

            # Remove totalmente "Subelementos" do DF (opcional, mantém mais limpo)
            df.drop(columns=["Subelementos"], errors="ignore", inplace=True)

            # Ordem final da tabela (só colunas exibidas) + ID invisível para DnD
            cols = [c for c in self.colunas_exibidas if c in df.columns]
            df["__iid"] = range(1, len(df) + 1)  # ID estável por sessão
            self.df_final = df[["__iid"] + cols].copy()

            # Desenha
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
        # Validação leve da data
        try:
            datetime.strptime(self.start_date_str.get(), "%d/%m/%Y")
        except ValueError:
            self.status.configure(text="Data inválida. Use o formato DD/MM/AAAA.")
            return
        # mantém a ordem atual (inclusive DnD) e apenas recalcula targets
        self._recalc_targets_inplace()
        self.populate(self.reported_tree, self.df_final)

    def _priority_rank(self, cell_value: str) -> int:
        if not isinstance(cell_value, str):
            return 999
        base = cell_value.replace("🟥", "").replace("🟧", "").replace("🟦", "").replace("🟩", "").strip()
        mapping = {"SEVERA": 0, "ALTA": 1, "MÉDIA": 2, "LEVE": 3}
        return mapping.get(base, 999)

    def sort_by_priority_asc(self):
        if "Prioridade" in self.df_final.columns:
            self.df_final = self.df_final.sort_values(
                by="Prioridade",
                key=lambda s: s.map(self._priority_rank),
                ascending=True
            ).reset_index(drop=True)
            self.populate(self.reported_tree, self.df_final)

    def sort_by_priority_desc(self):
        if "Prioridade" in self.df_final.columns:
            self.df_final = self.df_final.sort_values(
                by="Prioridade",
                key=lambda s: s.map(self._priority_rank),
                ascending=False
            ).reset_index(drop=True)
            self.populate(self.reported_tree, self.df_final)

    def sort_by_column(self, col_name: str):
        """Ordenação genérica ao clicar no cabeçalho (toggle asc/desc)."""
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
        """Ajusta largura pelas amostras de células + cabeçalho."""
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
        if not self._dragging_iid:
            return
        # autoscroll quando perto das bordas
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
        if not self._dragging_iid:
            return
        # Reconstroi a ordem no DataFrame pela sequência de iids
        order = list(self.reported_tree.get_children(""))
        try:
            idx_order = [int(i) for i in order]
        except ValueError:
            idx_order = order

        if "__iid" in self.df_final.columns:
            self.df_final = (
                self.df_final.set_index("__iid")
                            .loc[idx_order]
                            .reset_index()
            )
        # Recalcula targets conforme nova ordem
        self._recalc_targets_inplace()

        # Redesenha (mantém zebra correta)
        self.populate(self.reported_tree, self.df_final)
        self._dragging_iid = None
        self.status.configure(text=f"Reordenado: {len(self.df_final)} itens · Targets atualizados")

    def _recalc_targets_inplace(self):
        """Recalcula a coluna 'Targetts' conforme a ordem atual na tabela."""
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

    def on_treeview_click(self, event):
        # reservado para futuras ações (ex: abrir detalhe)
        pass

    def change_appearance(self, mode):
        ctk.set_appearance_mode(mode)


if __name__ == "__main__":
    app = SimpleTable()
    app.mainloop()
