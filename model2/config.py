import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


class Config:
    NOME_SITE = "Nome da Imobiliária"  # troque pela marca do cliente

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-troque-isto")
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB = os.environ.get("MONGO_DB", "imobiliaria")

    # LGPD: suba a versão sempre que o texto da política mudar
    VERSAO_POLITICA = "1.0"
    # Se a cliente exigir documento do visitante (segurança do corretor)
    EXIGIR_DOCUMENTO = False

    # URL pública do site (usada nos links dos e-mails). Ex.: https://meusite.onrender.com
    BASE_URL = os.environ.get("BASE_URL", "")
    # Atrás do proxy do Render, use TRUST_PROXY=1 para enxergar o IP real do visitante
    TRUST_PROXY = os.environ.get("TRUST_PROXY", "0") == "1"
    # E-mail (opcional). Sem SMTP_HOST, os e-mails só aparecem no log do servidor.
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM = os.environ.get("SMTP_FROM", "nao-responder@exemplo.com")
    NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "")  # recebe aviso de novos leads
    RESET_TOKEN_MIN = 60

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024  # 1 MB por requisição
