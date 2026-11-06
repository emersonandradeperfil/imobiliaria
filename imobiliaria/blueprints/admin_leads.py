from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from flask import abort, flash, redirect, render_template, request, url_for

from blueprints.admin import PAPEIS, bp
from blueprints.leads import LEADS
from extensions import get_db
from helpers import role_required, usuario_atual

STATUS_LEAD = [("novo", "Novo"), ("em_contato", "Em contato"), ("concluido", "Concluído")]
FILTROS = [("abertos", "Em aberto")] + STATUS_LEAD + [("todos", "Todos")]


def _get(lead_id):
    try:
        lead = get_db().leads.find_one({"_id": ObjectId(lead_id)})
    except InvalidId:
        abort(404)
    if not lead:
        abort(404)
    return lead


@bp.route("/leads")
@role_required(*PAPEIS)
def leads():
    q = {}
    filtro = request.args.get("filtro", "abertos")
    if filtro == "abertos":
        q["status"] = {"$in": ["novo", "em_contato"]}
    elif filtro in dict(STATUS_LEAD):
        q["status"] = filtro
    tipo = request.args.get("tipo", "")
    if tipo in LEADS:
        q["tipo"] = tipo
    lista = list(get_db().leads.find(q).sort("criado_em", -1).limit(100))
    return render_template("admin/leads.html", lista=lista, filtros=FILTROS, filtro=filtro, tipo=tipo, tipos=LEADS)


@bp.route("/leads/<lead_id>")
@role_required(*PAPEIS)
def lead(lead_id):
    l = _get(lead_id)
    rotulos = dict(LEADS[l["tipo"]]["extras"]) if l["tipo"] in LEADS else {}
    return render_template("admin/lead.html", l=l, tipos=LEADS, status_opts=STATUS_LEAD, rotulos=rotulos)


@bp.route("/leads/<lead_id>/status", methods=["POST"])
@role_required(*PAPEIS)
def lead_status(lead_id):
    l = _get(lead_id)
    novo = request.form.get("status")
    if novo not in dict(STATUS_LEAD):
        abort(400)
    get_db().leads.update_one({"_id": l["_id"]}, {"$set": {"status": novo}})
    flash("Status atualizado.", "ok")
    return redirect(url_for("admin.lead", lead_id=lead_id))


@bp.route("/leads/<lead_id>/nota", methods=["POST"])
@role_required(*PAPEIS)
def lead_nota(lead_id):
    l = _get(lead_id)
    texto = request.form.get("texto", "").strip()[:1000]
    if texto:
        get_db().leads.update_one({"_id": l["_id"]}, {"$push": {"notas": {"texto": texto, "por_nome": usuario_atual()["nome"], "em": datetime.now(timezone.utc)}}})
        flash("Nota adicionada.", "ok")
    return redirect(url_for("admin.lead", lead_id=lead_id))


@bp.route("/leads/<lead_id>/excluir", methods=["POST"])
@role_required("admin")
def lead_excluir(lead_id):
    l = _get(lead_id)
    get_db().leads.delete_one({"_id": l["_id"]})
    flash("Contato excluído (atende pedidos de exclusão da LGPD).", "ok")
    return redirect(url_for("admin.leads"))
