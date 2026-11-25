import os
from flask_pymongo import PyMongo
from dotenv import load_dotenv

load_dotenv()

mongo = PyMongo()


def init_db(app):
    app.config["MONGO_URI"] = os.getenv("MONGO_URI")
    mongo.init_app(app)

    try:
        db = mongo.db
        if db is not None:
            _criar_indices(db)
    except Exception as e:
        print(f"Aviso ao criar índices no MongoDB: {e}")

    return mongo


def _criar_indices(db):
    # Usuários: e-mail único
    db.users.create_index("email", unique=True, sparse=True)

    # Condomínios: slug único
    db.condominios.create_index("slug", unique=True, sparse=True)

    # Imóveis: código único e filtros da vitrine
    db.imoveis.create_index("codigo", unique=True, sparse=True)
    db.imoveis.create_index([("status", 1), ("ativo", 1), ("destaque", 1)])
    db.imoveis.create_index("slug", sparse=True)

    # Endereços privados: 1 para 1 com imóvel
    db.imoveis_enderecos.create_index("imovel_id", unique=True, sparse=True)

    # OTPs: busca rápida por e-mail/tipo e expiração automática (TTL)
    db.otps.create_index([("email", 1), ("tipo", 1)])
    db.otps.create_index("expira_em", expireAfterSeconds=0)

    # Controle de tentativas de login
    db.login_tentativas.create_index("chave", unique=True, sparse=True)