import pandas as pd
from datetime import datetime, timedelta

# Carregar dados corretamente
file_path = 'Laborat_rio_-_Bancada_1753210484.xlsx'
df = pd.read_excel(file_path, sheet_name='laboratório - bancada', header=4)

# Filtrar linhas pelos Status desejados
status_desejados = ['Reportado', 'Pausado', 'Em andamento']
df_filtrado = df[df['Status'].isin(status_desejados)].copy()

# Remover linhas sem prioridade válida
prioridades_validas = ['SEVERA', 'ALTA', 'MÉDIA', 'LEVE']
df_filtrado = df_filtrado[df_filtrado['Prioridade'].isin(prioridades_validas)]

# Ordenar prioridades fixas
ordem_prioridade = {'SEVERA': 0, 'ALTA': 1, 'MÉDIA': 2, 'LEVE': 3}
df_filtrado['ordem_prioridade'] = df_filtrado['Prioridade'].map(ordem_prioridade)
df_ordenado = df_filtrado.sort_values(by='ordem_prioridade').reset_index(drop=True)

# Selecionar colunas desejadas
colunas_desejadas = ['Name', 'Nº Proposta', 'SN', 'Prioridade', 'Status', 'Responsável', 'Cliente']
df_final = df_ordenado[colunas_desejadas].copy()

# Adicionar Deadline considerando 4 reparos por semana (2 semanas por reparo)
data_inicio = datetime(2025, 7, 21)
deadlines = []

for idx in df_final.index:
    semana_grupo = (idx // 4)  # Grupos de 4 reparos semanais
    prazo = data_inicio + timedelta(weeks=semana_grupo, days=14)
    deadlines.append(prazo.date())

df_final['Deadline'] = deadlines

# Exibir resultado
print("Fila de reparos com deadlines definidas:")
print(df_final.head(20))

# Salvar resultado
df_final.to_excel('fila_reparos_com_deadline.xlsx', index=False)
