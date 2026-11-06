"""Envio de e-mail simples via SMTP.

- Sem SMTP_HOST configurado: o e-mail é apenas registrado no log (útil em desenvolvimento).
- Em testes (app.testing): vai para OUTBOX, sem enviar nada.
- O envio roda numa thread para não travar a resposta ao usuário.
"""
import logging
import smtplib
import threading
from email.message import EmailMessage

from flask import current_app

log = logging.getLogger(__name__)
OUTBOX = []


def email_configurado():
    return bool(current_app.config.get("SMTP_HOST")) or current_app.testing


def send_email(to, subject, body):
    if not to:
        return
    subject = " ".join(str(subject).split())  # sem quebras de linha (header injection)
    cfg = current_app.config
    if current_app.testing:
        OUTBOX.append({"to": to, "subject": subject, "body": body})
        return
    if not cfg.get("SMTP_HOST"):
        log.warning("E-mail NÃO enviado (SMTP não configurado). Para: %s | %s\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = cfg["SMTP_FROM"], to, subject
    msg.set_content(body)
    dados = (cfg["SMTP_HOST"], cfg["SMTP_PORT"], cfg.get("SMTP_USER"), cfg.get("SMTP_PASSWORD"))
    threading.Thread(target=_enviar, args=(dados, msg), daemon=True).start()


def _enviar(dados, msg):
    host, port, user, senha = dados
    try:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.starttls()
            if user:
                s.login(user, senha)
            s.send_message(msg)
    except Exception:
        log.exception("Falha ao enviar e-mail")
