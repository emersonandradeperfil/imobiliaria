from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
import re

from bson import json_util
from flask import (Blueprint, Response, abort, flash, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import generate_password_hash

from extensions import get_db
from helpers import TZ, link_externo, login_required, safe_next, senha_confere, usuario_atual
from mail import send_email

bp = Blueprint("account", __name__)


@bp.route("/imovel/<slug>/agendar", methods=["POST"])
@login_required
def agendar(slug):
    db = get_db()
    user = usuario_atual()
    imovel = db.imoveis.find_one({"slug": slug, "status": "ativo"})
    if not imovel:
        abort(404)
    destino = redirect(url_for("public.detalhe", slug=slug) + "#agendar")

    try:
        local = datetime.strptime(request.form.get("data_hora", ""), "%Y-%m-%dT%H:%M").replace(tzinfo=TZ)
    except ValueError:
        flash("Escolha uma data e horário válidos.", "erro")
        return destino
    dt_utc = local.astimezone(timezone.utc)
    if dt_utc <= datetime.now(timezone.utc):
        flash("Escolha uma data futura.", "erro")
        return destino

    ocupado = db.agendamentos.find_one(
        {"imovel_id": imovel["_id"], "data_hora": dt_utc.replace(tzinfo=None), "status": {"$in": ["pendente", "confirmado"]}}
    )
    if ocupado:
        flash("Esse horário já está reservado. Escolha outro.", "erro")
        return destino

    res = db.agendamentos.insert_one(
        {
            "imovel_id": imovel["_id"],
            "usuario_id": user["_id"],
            "corretor_id": imovel.get("corretor_id"),
            "data_hora": dt_utc,
            "status": "pendente",
            "historico": [{"status": "pendente", "por": user["_id"], "por_nome": user["nome"], "em": datetime.now(timezone.utc), "motivo": None}],
            "observacoes": request.form.get("observacoes", "").strip()[:500],
            # cópia dos dados no momento do agendamento (registro para o corretor)
            "visitante_snapshot": {
                "nome": user["nome"],
                "telefone": user.get("telefone"),
                "documento": user.get("documento"),
            },
            "criado_em": datetime.now(timezone.utc),
        }
    )
    corretor = db.users.find_one({"_id": imovel.get("corretor_id")}, {"email": 1, "nome": 1}) if imovel.get("corretor_id") else None
    if corretor:
        send_email(
            corretor["email"], f"Nova solicitação de visita · {imovel['codigo']}",
            f"Olá, {corretor['nome']}.\n\n{user['nome']} solicitou uma visita ao imóvel {imovel['codigo']} "
            f"({imovel['titulo']}) em {local.strftime('%d/%m/%Y às %H:%M')}.\n\n"
            f"Veja os detalhes e confirme: {link_externo('admin.agendamento', ag_id=res.inserted_id)}",
        )
    flash("Visita solicitada! O corretor confirmará o horário.", "ok")
    return redirect(url_for("account.meus_agendamentos"))


@bp.route("/meus-agendamentos")
@login_required
def meus_agendamentos():
    db = get_db()
    ags = list(db.agendamentos.find({"usuario_id": usuario_atual()["_id"]}).sort("data_hora", -1))
    imoveis = {i["_id"]: i for i in db.imoveis.find({"_id": {"$in": [a["imovel_id"] for a in ags]}})}
    return render_template("meus_agendamentos.html", ags=ags, imoveis=imoveis)


@bp.route("/agendamentos/<ag_id>/cancelar", methods=["POST"])
@login_required
def cancelar(ag_id):
    try:
        oid = ObjectId(ag_id)
    except InvalidId:
        abort(404)
    # filtra também por usuario_id: ninguém cancela agendamento de outra pessoa
    res = get_db().agendamentos.update_one(
        {"_id": oid, "usuario_id": usuario_atual()["_id"], "status": {"$in": ["pendente", "confirmado"]}},
        {
            "$set": {"status": "cancelado", "cancelado_por": "cliente"},
            "$push": {"historico": {"status": "cancelado", "por": usuario_atual()["_id"], "por_nome": usuario_atual()["nome"], "em": datetime.now(timezone.utc), "motivo": None}},
        },
    )
    if res.matched_count:
        flash("Agendamento cancelado.", "ok")
    return redirect(url_for("account.meus_agendamentos"))


@bp.route("/favoritos")
@login_required
def favoritos():
    ids = usuario_atual().get("favoritos", [])
    imoveis = list(get_db().imoveis.find({"_id": {"$in": ids}, "status": {"$in": ["ativo", "reservado"]}}))
    return render_template("favoritos.html", imoveis=imoveis)


@bp.route("/favoritos/<slug>", methods=["POST"])
@login_required
def favoritar(slug):
    db = get_db()
    user = usuario_atual()
    imovel = db.imoveis.find_one({"slug": slug}, {"_id": 1})
    if not imovel:
        abort(404)
    op = "$pull" if imovel["_id"] in user.get("favoritos", []) else "$addToSet"
    db.users.update_one({"_id": user["_id"]}, {op: {"favoritos": imovel["_id"]}})
    return redirect(safe_next(request.form.get("next")) or url_for("public.detalhe", slug=slug))


# ------------------------------------------------------------ minha conta (LGPD)
@bp.route("/conta")
@login_required
def conta():
    return render_template("conta.html")


@bp.route("/conta/dados", methods=["POST"])
@login_required
def conta_dados():
    f = request.form
    nome = f.get("nome", "").strip()[:120]
    telefone = re.sub(r"\D", "", f.get("telefone", ""))[:15]
    documento = f.get("documento", "").strip()[:20] or None
    if len(nome) < 3 or len(telefone) < 10:
        flash("Informe nome completo e telefone com DDD.", "erro")
    else:
        get_db().users.update_one({"_id": usuario_atual()["_id"]}, {"$set": {"nome": nome, "telefone": telefone, "documento": documento}})
        flash("Dados atualizados.", "ok")
    return redirect(url_for("account.conta"))


@bp.route("/conta/senha", methods=["POST"])
@login_required
def conta_senha():
    user = usuario_atual()
    atual, nova = request.form.get("senha_atual", ""), request.form.get("nova_senha", "")
    if not senha_confere(user.get("senha_hash"), atual):
        flash("Senha atual incorreta.", "erro")
    elif not 8 <= len(nova) <= 128:
        flash("A nova senha deve ter entre 8 e 128 caracteres.", "erro")
    else:
        versao = user.get("sessao_versao", 0) + 1
        get_db().users.update_one({"_id": user["_id"]}, {"$set": {"senha_hash": generate_password_hash(nova), "sessao_versao": versao}})
        session["sv"] = versao  # esta sessão continua; as demais são encerradas
        flash("Senha alterada.", "ok")
    return redirect(url_for("account.conta"))


@bp.route("/conta/exportar")
@login_required
def conta_exportar():
    """Cópia dos dados pessoais guardados (direito de acesso, LGPD)."""
    db = get_db()
    user = dict(usuario_atual())
    user.pop("senha_hash", None)
    dados = {
        "usuario": user,
        "agendamentos": list(db.agendamentos.find({"usuario_id": user["_id"]})),
        "contatos_enviados": list(db.leads.find({"email": user["email"]})),
    }
    return Response(
        json_util.dumps(dados, ensure_ascii=False, indent=2), mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=meus-dados.json"},
    )


def anonimizar_usuario(db, user_id):
    """Remove dados pessoais ligados ao usuário e apaga a conta (direito de exclusão, LGPD)."""
    anon = {"nome": "Removido (LGPD)", "telefone": None, "documento": None}
    for ag in db.agendamentos.find({"usuario_id": user_id}):
        hist = [dict(h, por=None, por_nome="Removido (LGPD)") if h.get("por") == user_id else h for h in ag.get("historico", [])]
        sets = {"visitante_snapshot": anon, "usuario_id": None, "historico": hist, "observacoes": ""}
        if ag["status"] in ("pendente", "confirmado"):
            sets.update(status="cancelado", cancelado_por="cliente")
        db.agendamentos.update_one({"_id": ag["_id"]}, {"$set": sets})
    email = db.users.find_one({"_id": user_id}, {"email": 1}).get("email")
    db.leads.delete_many({"email": email})
    db.users.delete_one({"_id": user_id})


@bp.route("/conta/excluir", methods=["POST"])
@login_required
def conta_excluir():
    user = usuario_atual()
    if user["papel"] != "cliente":
        flash("Contas da equipe são removidas por um administrador.", "erro")
        return redirect(url_for("account.conta"))
    if not senha_confere(user.get("senha_hash"), request.form.get("senha", "")):
        flash("Senha incorreta. A conta não foi excluída.", "erro")
        return redirect(url_for("account.conta"))
    anonimizar_usuario(get_db(), user["_id"])
    session.clear()
    flash("Sua conta e seus dados pessoais foram excluídos.", "ok")
    return redirect(url_for("public.home"))
