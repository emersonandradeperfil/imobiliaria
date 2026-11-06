import re
from datetime import datetime, timezone

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from extensions import get_db
from helpers import link_externo
from mail import send_email

bp = Blueprint("leads", __name__)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Um único formulário reaproveitado para os 3 tipos de lead
LEADS = {
    "contato": {
        "rota": "/fale-conosco",
        "titulo": "Fale conosco",
        "intro": "Envie sua mensagem e retornaremos em breve.",
        "extras": [],
    },
    "cadastre_imovel": {
        "rota": "/cadastre-seu-imovel",
        "titulo": "Cadastre seu imóvel",
        "intro": "Quer vender ou alugar seu imóvel conosco? Conte um pouco sobre ele.",
        "extras": [("tipo_imovel", "Tipo de imóvel"), ("bairro", "Bairro"), ("finalidade", "Venda ou locação?")],
    },
    "adm_condominio": {
        "rota": "/administracao-condominios",
        "titulo": "Administração para o seu condomínio",
        "intro": "Conheça nossa administração predial. Deixe seus dados para um contato.",
        "extras": [("nome_condominio", "Nome do condomínio"), ("qtd_unidades", "Quantidade de unidades"), ("cidade", "Cidade")],
    },
}


def form_lead(tipo):
    cfg = LEADS[tipo]
    if request.method == "POST":
        f = request.form
        if f.get("website"):  # honeypot: campo escondido que só robôs preenchem
            return redirect(url_for("leads." + tipo))
        nome = f.get("nome", "").strip()[:120]
        email = f.get("email", "").strip().lower()[:120]
        telefone = re.sub(r"\D", "", f.get("telefone", ""))[:15]
        erros = []
        if len(nome) < 3:
            erros.append("Informe seu nome.")
        if not EMAIL_RE.match(email):
            erros.append("E-mail inválido.")
        if len(telefone) < 10:
            erros.append("Informe um telefone com DDD.")
        if not f.get("aceite_lgpd"):
            erros.append("É necessário aceitar a Política de Privacidade.")
        if erros:
            for e in erros:
                flash(e, "erro")
            return render_template("lead_form.html", cfg=cfg, tipo=tipo, form=f), 400

        agora = datetime.now(timezone.utc)
        res = get_db().leads.insert_one(
            {
                "tipo": tipo,
                "nome": nome,
                "email": email,
                "telefone": telefone,
                "mensagem": f.get("mensagem", "").strip()[:2000],
                "dados": {campo: f.get(campo, "").strip()[:200] for campo, _ in cfg["extras"]},
                "status": "novo",
                "lgpd": {"aceite_em": agora, "versao_politica": current_app.config["VERSAO_POLITICA"]},
                "criado_em": agora,
            }
        )
        if current_app.config.get("NOTIFY_EMAIL"):
            send_email(current_app.config["NOTIFY_EMAIL"], f"Novo contato: {cfg['titulo']}",
                       f"{nome} enviou o formulário «{cfg['titulo']}».\nVeja no painel: {link_externo('admin.lead', lead_id=res.inserted_id)}")
        flash("Recebemos seu contato! Retornaremos em breve.", "ok")
        return redirect(url_for("leads." + tipo))
    return render_template("lead_form.html", cfg=cfg, tipo=tipo, form={})


for _tipo, _cfg in LEADS.items():
    bp.add_url_rule(_cfg["rota"], endpoint=_tipo, view_func=form_lead, methods=["GET", "POST"], defaults={"tipo": _tipo})
