from pymongo import MongoClient
import os
from dotenv import load_dotenv
from datetime import datetime
import bcrypt

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))
db = client.imobiliaria

print("Populando banco de dados com dados de teste...")

# Limpa dados anteriores
db.condominios.delete_many({})
db.imoveis.delete_many({})
db.imoveis_enderecos.delete_many({})
db.users.delete_many({})

# 1. Inserir usuário Admin de teste
senha_hash = bcrypt.hashpw("123456".encode('utf-8'), bcrypt.gensalt())
admin_id = db.users.insert_one({
    "nome": "Corretor Admin",
    "email": "admin@imobiliaria.com",
    "senha_hash": senha_hash,
    "telefone": "+5511988887777",
    "papel": "admin",
    "ativo": True,
    "favoritos": [],
    "criado_em": datetime.utcnow()
}).inserted_id

# 2. Inserir Condomínio
condo_id = db.condominios.insert_one({
    "nome": "Edifício Grand View Vila Nova",
    "slug": "edificio-grand-view-vila-nova",
    "descricao": "Torre única de alto padrão com lazer completo e segurança blindada.",
    "bairro": "Vila Nova Conceição",
    "cidade": "São Paulo",
    "estado": "SP",
    "comodidades": ["piscina coberta", "academia technogym", "espaço gourmet", "segurança 24h"],
    "administrado_pela_imobiliaria": True,
    "criado_em": datetime.utcnow()
}).inserted_id

# 3. Inserir Imóvel Público
imovel_id = db.imoveis.insert_one({
    "codigo": "AP0001",
    "slug": "cobertura-linear-vila-nova-conceicao-ap0001",
    "titulo": "Cobertura Linear Exclusiva na Vila Nova Conceição",
    "descricao": "Espetacular cobertura com vista panorâmica definitiva para o Parque Ibirapuera.",
    "finalidade": ["venda"],
    "categoria": "residencial",
    "tipo": "cobertura",
    "status": "ativo",
    "destaque": True,
    "precos": {
        "venda": 12500000,
        "locacao": None,
        "condominio": 4800,
        "iptu": 2200
    },
    "ocultar_preco": False,
    "areas": { "util": 450, "total": 520, "terreno": None },
    "quartos": 4,
    "suites": 4,
    "banheiros": 6,
    "vagas": 5,
    "local_publico": {
        "bairro": "Vila Nova Conceição",
        "cidade": "São Paulo",
        "estado": "SP",
        "lat_aprox": -23.59,
        "lng_aprox": -46.67
    },
    "condominio_id": condo_id,
    "corretor_id": admin_id,
    "comodidades": ["piscina privada", "churrasqueira", "ar condicionado central", "closet master"],
    "midia": {
        "fotos": [
            { "arquivo": "ap0001/01-sala.webp", "legenda": "Living com pé-direito duplo", "ordem": 1, "capa": True }
        ],
        "video_url": None,
        "tour_url": None
    },
    "criado_em": datetime.utcnow(),
    "atualizado_em": datetime.utcnow()
}).inserted_id

# 4. Inserir Endereço Privado + Andar + Posição Solar (Protegido por login)
db.imoveis_enderecos.insert_one({
    "imovel_id": imovel_id,
    "logradouro": "Rua Domingos Leme",
    "numero": "500",
    "complemento": "Cobertura 121",
    "bloco": "Única",
    "andar": 12,
    "cep": "04558-000",
    "posicao_solar": "Face Norte (Sol da manhã e vista livre)",
    "lat": -23.5912345,
    "lng": -46.6712345
})

print("Banco populado com sucesso! 🚀")