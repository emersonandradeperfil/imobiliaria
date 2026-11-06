"""Tokens de redefinição de senha. O token em si nunca é guardado, só o hash."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app

from extensions import get_db
from helpers import link_externo


def _agora():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def criar_link_reset(user_id):
    token = secrets.token_urlsafe(32)
    get_db().reset_tokens.insert_one({
        "user_id": user_id, "token_hash": _hash(token), "usado": False,
        "expira_em": _agora() + timedelta(minutes=current_app.config["RESET_TOKEN_MIN"]),
    })
    return link_externo("auth.redefinir_senha", token=token)


def token_valido(token):
    return get_db().reset_tokens.find_one({"token_hash": _hash(token), "usado": False, "expira_em": {"$gt": _agora()}})


def invalidar_tokens(user_id):
    get_db().reset_tokens.update_many({"user_id": user_id}, {"$set": {"usado": True}})
