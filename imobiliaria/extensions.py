from flask import current_app
from pymongo import MongoClient

_client = None


def get_db():
    """Cria o cliente uma única vez e devolve o banco configurado."""
    global _client
    if _client is None:
        _client = MongoClient(current_app.config["MONGO_URI"])
    return _client[current_app.config["MONGO_DB"]]


def ensure_indexes():
    db = get_db()
    db.users.create_index("email", unique=True)
    db.imoveis.create_index("codigo", unique=True)
    db.imoveis.create_index("slug", unique=True)
    db.imoveis.create_index([("status", 1), ("finalidade", 1), ("categoria", 1)])
    db.imoveis.create_index("local_publico.bairro")
    db.imoveis_enderecos.create_index("imovel_id", unique=True)
    db.condominios.create_index("slug", unique=True)
    db.agendamentos.create_index([("imovel_id", 1), ("data_hora", 1)])
    db.agendamentos.create_index("usuario_id")
    db.leads.create_index([("tipo", 1), ("status", 1)])
    db.reset_tokens.create_index("token_hash", unique=True)
    db.reset_tokens.create_index("expira_em", expireAfterSeconds=0)
    db.tentativas.create_index("chave")
    db.tentativas.create_index("em", expireAfterSeconds=3600)
