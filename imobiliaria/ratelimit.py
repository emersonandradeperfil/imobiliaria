"""Limite de tentativas guardado no MongoDB (funciona com vários processos do gunicorn)."""
from datetime import datetime, timedelta, timezone

from extensions import get_db


def _agora():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def bloqueado(chave, limite, janela_min=15):
    desde = _agora() - timedelta(minutes=janela_min)
    return get_db().tentativas.count_documents({"chave": chave, "em": {"$gt": desde}}) >= limite


def registrar(chave):
    get_db().tentativas.insert_one({"chave": chave, "em": _agora()})


def limpar(chave):
    get_db().tentativas.delete_many({"chave": chave})
