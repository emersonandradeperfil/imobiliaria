import os
import json
from pymongo import MongoClient
from datetime import datetime
from bson import ObjectId

# Conexão com o Banco de Dados (ajuste se usar Atlas)
client = MongoClient("mongodb+srv://ecoponto:emerson@ecoponto.qozypnw.mongodb.net/imobiliaria?retryWrites=true&w=majority")
db = client.imobiliaria  # nome do seu banco

# Carrega o arquivo JSON
with open("imoveis_lote.json", "r", encoding="utf-8") as f:
    imoveis_data = json.load(f)

print(f"Lendo {len(imoveis_data)} imóveis do arquivo JSON...")

for item in imoveis_data:
    codigo = item["codigo"]
    
    # 1. Cria a pasta física para receber as imagens futuras
    pasta_imovel = os.path.join("static", "upload", codigo)
    os.makedirs(pasta_imovel, exist_ok=True)
    
    # Extrai o endereço privado do dicionário principal
    endereco_privado = item.pop("endereco_privado")
    
    # Adiciona a data de criação padrão
    item["criado_em"] = datetime.utcnow()
    
    # 2. Insere na coleção principal 'imoveis'
    resultado = db.imoveis.insert_one(item)
    imovel_id = resultado.inserted_id
    
    # 3. Insere os dados privados na coleção 'imoveis_enderecos' vinculando pelo ID
    endereco_privado["imovel_id"] = imovel_id
    db.imoveis_enderecos.insert_one(endereco_privado)
    
    print(f"[{codigo}] Importado com sucesso e pasta criada!")

print("🚀 Importação via JSON concluída com sucesso total!")