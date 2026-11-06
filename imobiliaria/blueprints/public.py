from flask import Blueprint, abort, render_template, request

from extensions import get_db
from helpers import usuario_atual

bp = Blueprint("public", __name__)


def _int(valor):
    try:
        n = int(valor)
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


@bp.route("/")
def home():
    db = get_db()
    base = {"status": "ativo", "destaque": True}
    venda = list(db.imoveis.find({**base, "finalidade": "venda"}).limit(6))
    locacao = list(db.imoveis.find({**base, "finalidade": "locacao"}).limit(6))
    bairros = sorted(db.imoveis.distinct("local_publico.bairro", {"status": "ativo"}))
    return render_template("home.html", venda=venda, locacao=locacao, bairros=bairros)


@bp.route("/imoveis")
def listagem():
    db = get_db()
    f = request.args
    q = {"status": "ativo"}

    finalidade = f.get("finalidade")
    if finalidade in ("venda", "locacao"):
        q["finalidade"] = finalidade
    if f.get("categoria") in ("residencial", "comercial"):
        q["categoria"] = f["categoria"]
    if f.get("bairro"):
        q["local_publico.bairro"] = f["bairro"]
    quartos = _int(f.get("quartos"))
    if quartos:
        q["quartos"] = {"$gte": quartos}
    preco_max = _int(f.get("preco_max"))
    if preco_max and finalidade:  # preço só faz sentido com finalidade escolhida
        campo = "precos.locacao" if finalidade == "locacao" else "precos.venda"
        q[campo] = {"$lte": preco_max}

    imoveis = list(db.imoveis.find(q).sort("criado_em", -1).limit(48))
    bairros = sorted(db.imoveis.distinct("local_publico.bairro", {"status": "ativo"}))
    return render_template("listagem.html", imoveis=imoveis, bairros=bairros, f=f)


@bp.route("/imovel/<slug>")
def detalhe(slug):
    db = get_db()
    imovel = db.imoveis.find_one({"slug": slug, "status": {"$in": ["ativo", "reservado"]}})
    if not imovel:
        abort(404)

    condominio = None
    if imovel.get("condominio_id"):
        condominio = db.condominios.find_one({"_id": imovel["condominio_id"], "ativo": {"$ne": False}})

    # REGRA DE OURO: o endereço só é consultado se houver usuário logado.
    # Deslogado: a coleção imoveis_enderecos nem é tocada.
    user = usuario_atual()
    endereco = None
    favorito = False
    if user:
        endereco = db.imoveis_enderecos.find_one({"imovel_id": imovel["_id"]})
        favorito = imovel["_id"] in user.get("favoritos", [])

    similares = list(
        db.imoveis.find(
            {
                "status": "ativo",
                "_id": {"$ne": imovel["_id"]},
                "local_publico.bairro": imovel["local_publico"]["bairro"],
            }
        ).limit(3)
    )
    return render_template(
        "imovel.html",
        i=imovel,
        condominio=condominio,
        endereco=endereco,
        favorito=favorito,
        similares=similares,
    )


@bp.route("/quem-somos")
def quem_somos():
    return render_template("pagina.html", titulo="Quem somos", texto="Conteúdo institucional da imobiliária (placeholder).")


@bp.route("/privacidade")
def privacidade():
    return render_template(
        "pagina.html",
        titulo="Política de Privacidade",
        texto="Texto da política de privacidade e termos de uso (placeholder). Deve ser revisado por um profissional jurídico antes de ir ao ar.",
    )
