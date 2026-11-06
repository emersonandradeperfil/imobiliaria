from datetime import datetime, timezone

from flask import abort, flash, redirect, render_template, request, url_for
from bson import ObjectId
from bson.errors import InvalidId

import condominio_form
from blueprints.admin import bp
from extensions import get_db
from helpers import role_required, slugify

SOMENTE_ADMIN = role_required("admin")


def _get(cid):
    try:
        c = get_db().condominios.find_one({"_id": ObjectId(cid)})
    except InvalidId:
        abort(404)
    if not c:
        abort(404)
    return c


def _slug_unico(nome):
    base, n, db = slugify(nome) or "condominio", 1, get_db()
    slug = base
    while db.condominios.find_one({"slug": slug}, {"_id": 1}):
        n += 1
        slug = f"{base}-{n}"
    return slug


@bp.route("/condominios")
@SOMENTE_ADMIN
def condominios():
    db = get_db()
    lista = list(db.condominios.find().sort("nome", 1))
    contagem = {r["_id"]: r["n"] for r in db.imoveis.aggregate([{"$group": {"_id": "$condominio_id", "n": {"$sum": 1}}}])}
    return render_template("admin/condominios.html", lista=lista, contagem=contagem)


@bp.route("/condominios/novo", methods=["GET", "POST"])
@SOMENTE_ADMIN
def condominio_novo():
    if request.method == "GET":
        return render_template("admin/condominio_form.html", v={"ativo": True, "estado": "SP", "cidade": "São Paulo"}, condo=None)
    campos, erros = condominio_form.parse(request.form)
    if erros:
        for e in erros:
            flash(e, "erro")
        return render_template("admin/condominio_form.html", v=request.form, condo=None), 400
    agora = datetime.now(timezone.utc)
    res = get_db().condominios.insert_one({**campos, "slug": _slug_unico(campos["nome"]), "criado_em": agora})
    flash("Condomínio cadastrado.", "ok")
    return redirect(url_for("admin.condominio_editar", cid=res.inserted_id))


@bp.route("/condominios/<cid>/editar", methods=["GET", "POST"])
@SOMENTE_ADMIN
def condominio_editar(cid):
    condo = _get(cid)
    if request.method == "GET":
        return render_template("admin/condominio_form.html", v=condominio_form.to_form(condo), condo=condo)
    campos, erros = condominio_form.parse(request.form)
    if erros:
        for e in erros:
            flash(e, "erro")
        return render_template("admin/condominio_form.html", v=request.form, condo=condo), 400
    get_db().condominios.update_one({"_id": condo["_id"]}, {"$set": campos})
    flash("Alterações salvas.", "ok")
    return redirect(url_for("admin.condominio_editar", cid=cid))


@bp.route("/condominios/<cid>/excluir", methods=["POST"])
@SOMENTE_ADMIN
def condominio_excluir(cid):
    condo = _get(cid)
    db = get_db()
    if db.imoveis.count_documents({"condominio_id": condo["_id"]}):
        flash("Há imóveis vinculados a este condomínio. Desative-o em vez de excluir (ou troque o condomínio dos imóveis).", "erro")
        return redirect(url_for("admin.condominios"))
    db.condominios.delete_one({"_id": condo["_id"]})
    flash("Condomínio excluído.", "ok")
    return redirect(url_for("admin.condominios"))
