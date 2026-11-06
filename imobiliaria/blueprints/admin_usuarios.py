import re
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from flask import abort, flash, redirect, render_template, request, url_for
from pymongo.errors import DuplicateKeyError
from werkzeug.security import generate_password_hash
import secrets

import seguranca
from blueprints.account import anonimizar_usuario
from blueprints.admin import bp
from extensions import get_db
from helpers import role_required, usuario_atual
from mail import email_configurado, send_email

SOMENTE_ADMIN = role_required("admin")
PAPEIS_ALL = [("cliente", "Cliente"), ("corretor", "Corretor"), ("admin", "Administrador")]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _get(uid):
    try:
        u = get_db().users.find_one({"_id": ObjectId(uid)})
    except InvalidId:
        abort(404)
    if not u:
        abort(404)
    return u


def _outro_admin_ativo(excluindo_id):
    return get_db().users.count_documents({"papel": "admin", "ativo": True, "_id": {"$ne": excluindo_id}}) > 0


def _enviar_convite(u, assunto, intro):
    link = seguranca.criar_link_reset(u["_id"])
    send_email(u["email"], assunto, f"Olá, {u['nome']}.\n\n{intro}\n{link}\n\nO link vale por 60 minutos.")
    return link


def _avisar_link(link):
    # Sem SMTP configurado o admin recebe o link na tela (fica visível só para ele)
    if not email_configurado():
        flash(f"E-mail não configurado: envie este link ao usuário manualmente: {link}", "info")


@bp.route("/usuarios")
@SOMENTE_ADMIN
def usuarios():
    q = {}
    papel = request.args.get("papel", "")
    if papel in dict(PAPEIS_ALL):
        q["papel"] = papel
    busca = request.args.get("q", "").strip()[:60]
    if busca:
        rx = {"$regex": re.escape(busca), "$options": "i"}
        q["$or"] = [{"nome": rx}, {"email": rx}]
    lista = list(get_db().users.find(q, {"senha_hash": 0}).sort("criado_em", -1).limit(100))
    return render_template("admin/usuarios.html", lista=lista, papeis=PAPEIS_ALL, papel=papel, busca=busca, eu=usuario_atual())


@bp.route("/usuarios/novo", methods=["GET", "POST"])
@SOMENTE_ADMIN
def usuario_novo():
    if request.method == "GET":
        return render_template("admin/usuario_form.html", v={"papel": "corretor"}, papeis=PAPEIS_ALL[1:])
    f = request.form
    nome, email = f.get("nome", "").strip()[:120], f.get("email", "").strip().lower()[:120]
    telefone, papel = re.sub(r"\D", "", f.get("telefone", ""))[:15], f.get("papel")
    erros = []
    if len(nome) < 3:
        erros.append("Informe o nome.")
    if not EMAIL_RE.match(email):
        erros.append("E-mail inválido.")
    if papel not in ("corretor", "admin"):
        erros.append("Escolha o papel (corretor ou administrador).")
    if erros:
        for e in erros:
            flash(e, "erro")
        return render_template("admin/usuario_form.html", v=f, papeis=PAPEIS_ALL[1:]), 400
    agora = datetime.now(timezone.utc)
    try:
        res = get_db().users.insert_one({
            "nome": nome, "email": email, "telefone": telefone, "documento": None, "papel": papel, "ativo": True,
            # senha aleatória que ninguém conhece: a pessoa define a dela pelo link do convite
            "senha_hash": generate_password_hash(secrets.token_urlsafe(24)), "sessao_versao": 0,
            "favoritos": [], "lgpd": {"aceite_em": agora, "versao_politica": "equipe"}, "criado_em": agora, "ultimo_login": None,
        })
    except DuplicateKeyError:
        flash("Já existe um usuário com esse e-mail.", "erro")
        return render_template("admin/usuario_form.html", v=f, papeis=PAPEIS_ALL[1:]), 400
    u = get_db().users.find_one({"_id": res.inserted_id})
    link = _enviar_convite(u, "Seu acesso ao painel", "Seu acesso foi criado. Defina sua senha neste link:")
    flash(f"Usuário {nome} criado. Enviamos o convite para {email}.", "ok")
    _avisar_link(link)
    return redirect(url_for("admin.usuarios"))


@bp.route("/usuarios/<uid>/ativo", methods=["POST"])
@SOMENTE_ADMIN
def usuario_ativo(uid):
    u, eu = _get(uid), usuario_atual()
    if u["_id"] == eu["_id"]:
        flash("Você não pode desativar a própria conta.", "erro")
    elif u["ativo"] and u["papel"] == "admin" and not _outro_admin_ativo(u["_id"]):
        flash("É preciso manter ao menos um administrador ativo.", "erro")
    else:
        get_db().users.update_one({"_id": u["_id"]}, {"$set": {"ativo": not u["ativo"]}, "$inc": {"sessao_versao": 1}})
        flash("Conta " + ("desativada." if u["ativo"] else "reativada."), "ok")
    return redirect(request.referrer or url_for("admin.usuarios"))


@bp.route("/usuarios/<uid>/papel", methods=["POST"])
@SOMENTE_ADMIN
def usuario_papel(uid):
    u, eu = _get(uid), usuario_atual()
    novo = request.form.get("papel")
    if novo not in dict(PAPEIS_ALL):
        abort(400)
    if u["_id"] == eu["_id"]:
        flash("Você não pode alterar o próprio papel.", "erro")
    elif u["papel"] == "admin" and novo != "admin" and not _outro_admin_ativo(u["_id"]):
        flash("É preciso manter ao menos um administrador ativo.", "erro")
    else:
        get_db().users.update_one({"_id": u["_id"]}, {"$set": {"papel": novo}, "$inc": {"sessao_versao": 1}})
        flash("Papel atualizado.", "ok")
    return redirect(url_for("admin.usuarios"))


@bp.route("/usuarios/<uid>/reset", methods=["POST"])
@SOMENTE_ADMIN
def usuario_reset(uid):
    u = _get(uid)
    link = _enviar_convite(u, "Redefinição de senha", "Um administrador gerou um link para você criar uma nova senha:")
    flash(f"Link de redefinição enviado para {u['email']}.", "ok")
    _avisar_link(link)
    return redirect(url_for("admin.usuarios"))


@bp.route("/usuarios/<uid>/excluir", methods=["POST"])
@SOMENTE_ADMIN
def usuario_excluir(uid):
    u, eu, db = _get(uid), usuario_atual(), get_db()
    if u["_id"] == eu["_id"]:
        flash("Você não pode excluir a própria conta por aqui.", "erro")
    elif u["papel"] == "admin" and not _outro_admin_ativo(u["_id"]):
        flash("É preciso manter ao menos um administrador ativo.", "erro")
    elif db.imoveis.count_documents({"corretor_id": u["_id"]}):
        flash("Este usuário é responsável por imóveis. Transfira-os para outro corretor antes de excluir (ou apenas desative a conta).", "erro")
    else:
        anonimizar_usuario(db, u["_id"])
        flash("Usuário e dados pessoais excluídos.", "ok")
    return redirect(url_for("admin.usuarios"))
