import os
import re
from datetime import timezone
from functools import wraps
from zoneinfo import ZoneInfo

from bson import ObjectId
from bson.errors import InvalidId
from flask import abort, current_app, flash, g, redirect, request, session, url_for

from extensions import get_db

TZ = ZoneInfo("America/Sao_Paulo")


# ---------- sessão / permissões ----------
def usuario_atual():
    """Usuário logado (dict) ou None. Consulta o banco 1x por requisição."""
    if not hasattr(g, "_usuario"):
        user = None
        uid = session.get("user_id")
        if uid:
            try:
                user = get_db().users.find_one({"_id": ObjectId(uid), "ativo": True})
            except InvalidId:
                user = None
            # troca de senha invalida as outras sessões abertas
            if user and session.get("sv", 0) != user.get("sessao_versao", 0):
                user = None
        g._usuario = user
    return g._usuario


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not usuario_atual():
            flash("Faça login para continuar.", "info")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def role_required(*papeis):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = usuario_atual()
            if not user:
                return redirect(url_for("auth.login", next=request.path))
            if user["papel"] not in papeis:
                abort(403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def safe_next(url):
    """Só aceita redirecionamento para caminho interno (evita open redirect)."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return None


# ---------- filtros / globals de template ----------
def brl(valor):
    if valor is None:
        return "—"
    return "R$ " + f"{valor:,.0f}".replace(",", ".")


def data_br(dt):
    if not dt:
        return ""
    return dt.replace(tzinfo=timezone.utc).astimezone(TZ).strftime("%d/%m/%Y às %H:%M")


def capa(imovel):
    fotos = (imovel.get("midia") or {}).get("fotos") or []
    for f in fotos:
        if f.get("capa"):
            return f["arquivo"]
    return fotos[0]["arquivo"] if fotos else None


def foto_url(arquivo, pasta="imoveis"):
    """URL da foto em static/img/<pasta>; se o arquivo não existir, usa placeholder."""
    if arquivo:
        caminho = os.path.join(current_app.static_folder, "img", pasta, arquivo)
        if os.path.exists(caminho):
            return url_for("static", filename=f"img/{pasta}/{arquivo}")
    return url_for("static", filename="img/placeholder.svg")


def youtube_embed(url):
    if not url:
        return None
    m = re.search(r"(?:youtu\.be/|v=|embed/)([\w-]{11})", url)
    return f"https://www.youtube.com/embed/{m.group(1)}" if m else None


def slugify(txt):
    import unicodedata

    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", txt.lower()).strip("-")


def whatsapp(telefone):
    """Link wa.me a partir de um telefone brasileiro (só dígitos, com ou sem 55)."""
    d = re.sub(r"\D", "", telefone or "")
    if not d:
        return ""
    if len(d) in (10, 11):
        d = "55" + d
    return f"https://wa.me/{d}"


def link_externo(endpoint, **values):
    """URL completa para e-mails. Prefere BASE_URL (evita depender do cabeçalho Host)."""
    base = current_app.config.get("BASE_URL")
    if base:
        return base.rstrip("/") + url_for(endpoint, **values)
    return url_for(endpoint, _external=True, **values)


def senha_confere(senha_hash, senha):
    """Confere a senha sem nunca estourar erro, mesmo com hash em formato estranho.

    Aceita hash salvo como texto ou como bytes (acontece quando o usuário é criado
    à mão no Atlas). Hash de outra biblioteca (ex.: bcrypt) simplesmente não confere.
    """
    from werkzeug.security import check_password_hash

    if isinstance(senha_hash, (bytes, bytearray)):
        try:
            senha_hash = bytes(senha_hash).decode("utf-8")
        except UnicodeDecodeError:
            return False
    if not isinstance(senha_hash, str):
        return False
    try:
        return check_password_hash(senha_hash, senha)
    except (ValueError, TypeError):
        return False
