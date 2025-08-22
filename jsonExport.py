import requests
import json
from datetime import datetime

class dataMondaytoJson:
  def __init__(self):
      pass
      
  def mondayToJson(self):
    # Configuração
    API_URL = "https://api.monday.com/v2"
    API_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJ0aWQiOjUzMjIwNzUwNywiYWFpIjoxMSwidWlkIjo4NjA1NjM1LCJpYWQiOiIyMDI1LTA2LTI3VDIxOjA2OjI3LjAwMFoiLCJwZXIiOiJtZTp3cml0ZSIsImFjdGlkIjozOTI2MzAzLCJyZ24iOiJ1c2UxIn0.EDQ9gomjxu2Uli4-4HLx5zirJ7HAB8XpT-CkVe782zk"  # Substitua aqui seu token
    BOARD_ID = 1264540922

    # Cabeçalhos HTTP
    headers = {
        "Authorization": API_TOKEN,
        "Content-Type": "application/json"
    }

    all_items = []
    cursor = None
    page = 1

    while True:
        # Monta query com ou sem cursor
        if cursor:
            query = """
            {
              boards(ids: [%d]) {
                items_page(limit: 100, cursor: "%s") {
                  cursor
                  items {
                    id
                    name
                    column_values {
                      id
                      text
                      value
                      type
                    }
                  }
                }
              }
            }
            """ % (BOARD_ID, cursor)
        else:
            query = """
            {
              boards(ids: [%d]) {
                items_page(limit: 100) {
                  cursor
                  items {
                    id
                    name
                    column_values {
                      id
                      text
                      value
                      type
                    }
                  }
                }
              }
            }
            """ % BOARD_ID

        # Faz a requisição
        response = requests.post(API_URL, json={"query": query}, headers=headers)
        if response.status_code != 200:
            print(f"❌ Erro ao consultar API Monday: {response.status_code}")
            print(response.text)
            break

        data = response.json()

        # Extrai itens
        page_items = data["data"]["boards"][0]["items_page"]["items"]
        all_items.extend(page_items)
        print(f"✅ Página {page} baixada: {len(page_items)} itens")

        # Verifica se tem mais páginas
        cursor = data["data"]["boards"][0]["items_page"]["cursor"]
        if not cursor:
            print("✅ Todas as páginas foram baixadas.")
            break
        page += 1

    # Salvar JSON final
    final_data = {
        "items": all_items
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"monday_export_all.json"

    with open(file_name, "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=4)

    print(f"✅ Exportação concluída. Arquivo salvo como: {file_name}")
