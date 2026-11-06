import os
import re
from datetime import datetime, timedelta, timezone

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)
from pymongo.errors import DuplicateKeyError

import imovel_form
from extensions import get_db
from helpers import TZ, link_externo, role_required, slugify, usuario_atual
from mail import send_email
from bson import ObjectId
from bson.errors import InvalidId

bp = Blueprint("admin", __name__, url_prefix="/admin")
PAPEIS = ("admin", "corretor")


@bp.route("/")
@role_required(*PAPEIS)
def dashboard():
    db = get_db()
    user = usuario_atual()
    filtro_ag = {"status": "pendente"}
    if user["papel"] == "corretor":  # corretor só vê as próprias visitas
        filtro_ag["corretor_id"] = user["_id"]

    ags = list(db.agendamentos.find(filtro_ag).sort("data_hora", 1).limit(20))
    imoveis = {i["_id"]: i for i in db.imoveis.find({"_id": {"$in": [a["imovel_id"] for a in ags]}})}
    resumo = {
        "imoveis_ativos": db.imoveis.count_documents({"status": "ativo"}),
        "leads_novos": db.leads.count_documents({"status": "novo"}),
        "ag_pendentes": db.agendamentos.count_documents(filtro_ag),
        "usuarios": db.users.count_documents({"papel": "cliente"}),
        "condominios": db.condominios.count_documents({}),
    }
    return render_template("admin/dashboard.html", resumo=resumo, ags=ags, imoveis=imoveis)


# ---------------------------------------------------------------- imóveis
def _imovel_ou_403(codigo):
    """Busca por código; corretor só acessa os próprios imóveis."""
    imovel = get_db().imoveis.find_one({"codigo": codigo})
    if not imovel:
        abort(404)
    user = usuario_atual()
    if user["papel"] == "corretor" and imovel.get("corretor_id") != user["_id"]:
        abort(403)
    return imovel


def _corretores():
    return list(get_db().users.find({"papel": {"$in": list(PAPEIS)}, "ativo": True}, {"nome": 1}).sort("nome", 1))


def _proximo_codigo(categoria):
    prefixo = "AP" if categoria == "residencial" else "CM"
    usados = get_db().imoveis.find({"codigo": {"$regex": f"^{prefixo}\\d+$"}}, {"codigo": 1})
    maior = max([int(c["codigo"][2:]) for c in usados] or [0])
    return f"{prefixo}{maior + 1:04d}"


def _render_form(form, imovel=None):
    db = get_db()
    arquivos = []
    if imovel:
        pasta = os.path.join(current_app.static_folder, "img", "imoveis", imovel["codigo"].lower())
        if os.path.isdir(pasta):
            arquivos = sorted(f"{imovel['codigo'].lower()}/{n}" for n in os.listdir(pasta) if not n.startswith("."))
    return render_template(
        "admin/imovel_form.html", v=form, imovel=imovel, arquivos=arquivos,
        categorias=imovel_form.CATEGORIAS, tipos=imovel_form.TIPOS, status_opts=imovel_form.STATUS,
        condominios=list(db.condominios.find({}, {"nome": 1, "ativo": 1}).sort("nome", 1)), corretores=_corretores(),
    )


@bp.route("/imoveis")
@role_required(*PAPEIS)
def imoveis():
    user = usuario_atual()
    q = {}
    if user["papel"] == "corretor":
        q["corretor_id"] = user["_id"]
    status = request.args.get("status", "")
    if status in dict(imovel_form.STATUS):
        q["status"] = status
    busca = request.args.get("q", "").strip()[:60]
    if busca:
        rx = {"$regex": re.escape(busca), "$options": "i"}
        q["$or"] = [{"titulo": rx}, {"codigo": rx}, {"local_publico.bairro": rx}]
    lista = list(get_db().imoveis.find(q).sort("atualizado_em", -1).limit(100))
    return render_template("admin/imoveis.html", imoveis=lista, status_opts=imovel_form.STATUS, status=status, busca=busca)


@bp.route("/imoveis/novo", methods=["GET", "POST"])
@role_required(*PAPEIS)
def imovel_novo():
    user = usuario_atual()
    if request.method == "GET":
        return _render_form({"status": "ativo", "categoria": "residencial", "finalidade_venda": True, "estado": "SP", "cidade": "São Paulo"})

    f = request.form
    campos, endereco, erros = imovel_form.parse(f)

    codigo = f.get("codigo", "").strip().upper()
    if codigo and not imovel_form.CODIGO_RE.match(codigo):
        erros.append("Código inválido (use letras, números e hífen, 3 a 20 caracteres).")
    if not erros and not codigo:
        codigo = _proximo_codigo(campos["categoria"])

    if erros:
        for e in erros:
            flash(e, "erro")
        return _render_form(f), 400

    corretor_id = user["_id"]
    if user["papel"] == "admin" and f.get("corretor_id"):
        try:
            cand = ObjectId(f["corretor_id"])
            if get_db().users.find_one({"_id": cand, "papel": {"$in": list(PAPEIS)}}):
                corretor_id = cand
        except Exception:
            pass

    agora = datetime.now(timezone.utc)
    doc = {**campos, "codigo": codigo, "slug": f"{slugify(campos['titulo'])}-{codigo.lower()}",
           "corretor_id": corretor_id, "criado_em": agora, "atualizado_em": agora}
    db = get_db()
    try:
        res = db.imoveis.insert_one(doc)
    except DuplicateKeyError:
        flash(f"Já existe um imóvel com o código {codigo}.", "erro")
        return _render_form(f), 400
    db.imoveis_enderecos.insert_one({"imovel_id": res.inserted_id, **endereco})
    flash(f"Imóvel {codigo} cadastrado.", "ok")
    return redirect(url_for("admin.imovel_editar", codigo=codigo))


@bp.route("/imoveis/<codigo>/editar", methods=["GET", "POST"])
@role_required(*PAPEIS)
def imovel_editar(codigo):
    imovel = _imovel_ou_403(codigo)
    db = get_db()
    if request.method == "GET":
        end = db.imoveis_enderecos.find_one({"imovel_id": imovel["_id"]})
        return _render_form(imovel_form.to_form(imovel, end), imovel)

    f = request.form
    campos, endereco, erros = imovel_form.parse(f)
    if erros:
        for e in erros:
            flash(e, "erro")
        return _render_form(f, imovel), 400

    user = usuario_atual()
    if user["papel"] == "admin" and f.get("corretor_id"):
        try:
            cand = ObjectId(f["corretor_id"])
            if db.users.find_one({"_id": cand, "papel": {"$in": list(PAPEIS)}}):
                campos["corretor_id"] = cand
        except Exception:
            pass
    campos["atualizado_em"] = datetime.now(timezone.utc)
    # código e slug não mudam: preserva os links já compartilhados
    db.imoveis.update_one({"_id": imovel["_id"]}, {"$set": campos})
    db.imoveis_enderecos.update_one({"imovel_id": imovel["_id"]}, {"$set": endereco}, upsert=True)
    flash("Alterações salvas.", "ok")
    return redirect(url_for("admin.imovel_editar", codigo=codigo))


@bp.route("/imoveis/<codigo>/status", methods=["POST"])
@role_required(*PAPEIS)
def imovel_status(codigo):
    imovel = _imovel_ou_403(codigo)
    novo = request.form.get("status")
    if novo not in dict(imovel_form.STATUS):
        abort(400)
    get_db().imoveis.update_one({"_id": imovel["_id"]}, {"$set": {"status": novo, "atualizado_em": datetime.now(timezone.utc)}})
    flash(f"{codigo}: status alterado para «{dict(imovel_form.STATUS)[novo]}».", "ok")
    return redirect(request.referrer or url_for("admin.imoveis"))


# ----------------------------------------------------------- agendamentos
TRANSICOES = {"pendente": ("confirmado", "cancelado"), "confirmado": ("realizado", "cancelado")}
FILTROS_AG = [("abertos", "Em aberto"), ("pendente", "Pendentes"), ("confirmado", "Confirmados"),
              ("realizado", "Realizados"), ("cancelado", "Cancelados"), ("todos", "Todos")]


def _agora():
    return datetime.now(timezone.utc).replace(tzinfo=None)  # o Mongo devolve datas em UTC "ingênuas"


def _ag_ou_403(ag_id):
    try:
        oid = ObjectId(ag_id)
    except InvalidId:
        abort(404)
    ag = get_db().agendamentos.find_one({"_id": oid})
    if not ag:
        abort(404)
    user = usuario_atual()
    if user["papel"] == "corretor" and ag.get("corretor_id") != user["_id"]:
        abort(403)
    return ag


@bp.route("/agendamentos")
@role_required(*PAPEIS)
def agendamentos():
    user = usuario_atual()
    db = get_db()
    q = {}
    if user["papel"] == "corretor":
        q["corretor_id"] = user["_id"]
    filtro = request.args.get("filtro", "abertos")
    if filtro == "abertos":
        q["status"] = {"$in": ["pendente", "confirmado"]}
    elif filtro in ("pendente", "confirmado", "realizado", "cancelado"):
        q["status"] = filtro
    ordem = 1 if filtro in ("abertos", "pendente", "confirmado") else -1
    ags = list(db.agendamentos.find(q).sort("data_hora", ordem).limit(100))
    imoveis = {i["_id"]: i for i in db.imoveis.find({"_id": {"$in": [a["imovel_id"] for a in ags]}})}
    return render_template("admin/agendamentos.html", ags=ags, imoveis=imoveis, filtros=FILTROS_AG, filtro=filtro, agora=_agora())


@bp.route("/agendamentos/<ag_id>")
@role_required(*PAPEIS)
def agendamento(ag_id):
    ag = _ag_ou_403(ag_id)
    db = get_db()
    imovel = db.imoveis.find_one({"_id": ag["imovel_id"]})
    endereco = db.imoveis_enderecos.find_one({"imovel_id": ag["imovel_id"]}) if imovel else None
    conflitos = []
    if ag["status"] in ("pendente", "confirmado") and ag.get("corretor_id"):
        dt = ag["data_hora"].replace(tzinfo=None)
        conflitos = list(db.agendamentos.find({
            "_id": {"$ne": ag["_id"]}, "corretor_id": ag["corretor_id"], "status": "confirmado",
            "data_hora": {"$gt": dt - timedelta(hours=1), "$lt": dt + timedelta(hours=1)},
        }))
    return render_template(
        "admin/agendamento.html", ag=ag, imovel=imovel, endereco=endereco, conflitos=conflitos,
        transicoes=TRANSICOES.get(ag["status"], ()), ja_passou=ag["data_hora"].replace(tzinfo=None) <= _agora(),
    )


@bp.route("/agendamentos/<ag_id>/status", methods=["POST"])
@role_required(*PAPEIS)
def agendamento_status(ag_id):
    ag = _ag_ou_403(ag_id)
    novo = request.form.get("status", "")
    motivo = request.form.get("motivo", "").strip()[:300]
    destino = redirect(url_for("admin.agendamento", ag_id=ag_id))

    if novo not in TRANSICOES.get(ag["status"], ()):
        flash("Essa mudança de status não é permitida.", "erro")
        return destino
    passou = ag["data_hora"].replace(tzinfo=None) <= _agora()
    if novo == "confirmado" and passou:
        flash("Não dá para confirmar uma visita cujo horário já passou.", "erro")
        return destino
    if novo == "realizado" and not passou:
        flash("A visita só pode ser marcada como realizada depois do horário.", "erro")
        return destino
    if novo == "cancelado" and len(motivo) < 3:
        flash("Informe o motivo: o cliente verá essa mensagem.", "erro")
        return destino

    user = usuario_atual()
    extra = {"cancelado_por": "equipe", "motivo": motivo} if novo == "cancelado" else {}
    # filtra também pelo status atual: se outra pessoa mudou antes, nada é gravado
    res = get_db().agendamentos.update_one(
        {"_id": ag["_id"], "status": ag["status"]},
        {
            "$set": {"status": novo, "atualizado_em": datetime.now(timezone.utc), **extra},
            "$push": {"historico": {"status": novo, "por": user["_id"], "por_nome": user["nome"], "em": datetime.now(timezone.utc), "motivo": motivo or None}},
        },
    )
    if res.modified_count and novo in ("confirmado", "cancelado") and ag.get("usuario_id"):
        cliente = get_db().users.find_one({"_id": ag["usuario_id"]}, {"email": 1, "nome": 1})
        imovel = get_db().imoveis.find_one({"_id": ag["imovel_id"]}, {"titulo": 1})
        if cliente:
            quando = ag["data_hora"].replace(tzinfo=timezone.utc).astimezone(TZ).strftime("%d/%m/%Y às %H:%M")
            situacao = "foi CONFIRMADA" if novo == "confirmado" else f"não pôde ser mantida. Motivo: {motivo}"
            send_email(
                cliente["email"], "Atualização da sua visita",
                f"Olá, {cliente['nome']}.\n\nSua visita ao imóvel «{imovel['titulo'] if imovel else ''}» em {quando} {situacao}.\n\n"
                f"Acompanhe em: {link_externo('account.meus_agendamentos')}",
            )
    flash("Status atualizado." if res.modified_count else "Esse agendamento já foi alterado por outra pessoa. Recarregue a página.", "ok" if res.modified_count else "erro")
    return destino


# registra as demais telas do painel (cada módulo usa o mesmo blueprint `bp`)
from blueprints import admin_condominios, admin_leads, admin_usuarios  # noqa: E402,F401
