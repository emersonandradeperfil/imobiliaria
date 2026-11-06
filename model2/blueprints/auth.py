import re
from datetime import datetime, timezone

from flask import (Blueprint, current_app, flash, make_response, redirect,
                   render_template, request, session, url_for)
from pymongo.errors import DuplicateKeyError
from werkzeug.security import generate_password_hash

import ratelimit
import seguranca
from extensions import get_db
from helpers import safe_next, senha_confere
from mail import send_email

bp = Blueprint("auth", __name__)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _iniciar_sessao(user_id, versao=0):
    session.clear()  # evita fixação de sessão
    session["user_id"] = str(user_id)
    session["sv"] = versao
    session.permanent = True


def _ip():
    return request.remote_addr or "?"


@bp.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if request.method == "POST":
        f = request.form
        nome = f.get("nome", "").strip()
        email = f.get("email", "").strip().lower()
        telefone = re.sub(r"\D", "", f.get("telefone", ""))
        documento = f.get("documento", "").strip()
        senha = f.get("senha", "")

        erros = []
        if len(nome) < 3:
            erros.append("Informe seu nome completo.")
        if not EMAIL_RE.match(email):
            erros.append("E-mail inválido.")
        if len(telefone) < 10:
            erros.append("Informe um telefone com DDD.")
        if current_app.config["EXIGIR_DOCUMENTO"] and not documento:
            erros.append("Informe seu documento (CPF).")
        if not 8 <= len(senha) <= 128:
            erros.append("A senha deve ter entre 8 e 128 caracteres.")
        if not f.get("aceite_lgpd"):
            erros.append("É necessário aceitar a Política de Privacidade.")

        if not erros:
            agora = datetime.now(timezone.utc)
            user = {
                "nome": nome, "email": email, "senha_hash": generate_password_hash(senha),
                "telefone": telefone, "documento": documento or None,
                "papel": "cliente",  # nunca vem do formulário
                "ativo": True, "favoritos": [], "sessao_versao": 0,
                "lgpd": {"aceite_em": agora, "versao_politica": current_app.config["VERSAO_POLITICA"]},
                "criado_em": agora, "ultimo_login": agora,
            }
            try:
                res = get_db().users.insert_one(user)
            except DuplicateKeyError:
                erros.append("Esse e-mail já está cadastrado.")
            else:
                _iniciar_sessao(res.inserted_id)
                flash("Cadastro realizado! Agora você pode ver os endereços e agendar visitas.", "ok")
                return redirect(safe_next(request.args.get("next")) or url_for("public.home"))

        for e in erros:
            flash(e, "erro")
        return render_template("cadastro.html", form=f), 400
    return render_template("cadastro.html", form={})


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()[:120]
        senha = request.form.get("senha", "")[:200]
        k_email, k_ip = f"login:email:{email}", f"login:ip:{_ip()}"
        if ratelimit.bloqueado(k_email, 5) or ratelimit.bloqueado(k_ip, 30):
            flash("Muitas tentativas de login. Aguarde 15 minutos e tente novamente.", "erro")
            return render_template("login.html"), 429

        db = get_db()
        user = db.users.find_one({"email": email, "ativo": True})
        if user and senha_confere(user.get("senha_hash"), senha):
            ratelimit.limpar(k_email)
            db.users.update_one({"_id": user["_id"]}, {"$set": {"ultimo_login": datetime.now(timezone.utc)}})
            _iniciar_sessao(user["_id"], user.get("sessao_versao", 0))
            return redirect(safe_next(request.args.get("next")) or url_for("public.home"))
        ratelimit.registrar(k_email)
        ratelimit.registrar(k_ip)
        flash("E-mail ou senha incorretos.", "erro")  # mensagem genérica de propósito
        return render_template("login.html"), 401
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("public.home"))


@bp.route("/esqueci-senha", methods=["GET", "POST"])
def esqueci_senha():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()[:120]
        k_ip, k_email = f"reset:ip:{_ip()}", f"reset:email:{email}"
        if not (ratelimit.bloqueado(k_ip, 10) or ratelimit.bloqueado(k_email, 3)):
            ratelimit.registrar(k_ip)
            ratelimit.registrar(k_email)
            user = get_db().users.find_one({"email": email, "ativo": True})
            if user:
                link = seguranca.criar_link_reset(user["_id"])
                send_email(
                    user["email"], "Redefinição de senha",
                    f"Olá, {user['nome']}.\n\nPara criar uma nova senha, acesse o link abaixo "
                    f"(válido por {current_app.config['RESET_TOKEN_MIN']} minutos):\n{link}\n\n"
                    "Se você não pediu isso, ignore este e-mail.",
                )
        # mesma resposta exista ou não a conta: não revela quem é cadastrado
        flash("Se o e-mail estiver cadastrado, enviamos um link para redefinir a senha.", "ok")
        return redirect(url_for("auth.login"))
    return render_template("esqueci_senha.html")


@bp.route("/redefinir-senha/<token>", methods=["GET", "POST"])
def redefinir_senha(token):
    doc = seguranca.token_valido(token)
    if not doc:
        flash("Link inválido ou expirado. Peça um novo.", "erro")
        return redirect(url_for("auth.esqueci_senha"))

    if request.method == "POST":
        senha, conf = request.form.get("senha", ""), request.form.get("confirmacao", "")
        if not 8 <= len(senha) <= 128:
            flash("A senha deve ter entre 8 e 128 caracteres.", "erro")
        elif senha != conf:
            flash("As senhas não conferem.", "erro")
        else:
            get_db().users.update_one(
                {"_id": doc["user_id"]},
                {"$set": {"senha_hash": generate_password_hash(senha)}, "$inc": {"sessao_versao": 1}},
            )
            seguranca.invalidar_tokens(doc["user_id"])
            session.clear()
            flash("Senha alterada! Faça login com a nova senha.", "ok")
            return redirect(url_for("auth.login"))

    resp = make_response(render_template("redefinir_senha.html"), 200)
    resp.headers["Referrer-Policy"] = "no-referrer"  # o token está na URL
    resp.headers["Cache-Control"] = "no-store"
    return resp
