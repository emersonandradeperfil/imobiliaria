import sys
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mongomock, extensions
extensions.MongoClient = mongomock.MongoClient
from app import create_app
from config import Config
import seed, mail
class T(Config):
    TESTING = True; WTF_CSRF_ENABLED = False; SESSION_COOKIE_SECURE = False
app = create_app(T); seed.create_app = lambda: app; seed.main(True)
from extensions import get_db
def ok(c, m): print(("OK   " if c else "FALHA"), m); assert c, m
def login(e):
    c = app.test_client(); c.post("/login", data={"email": e, "senha": "Trocar#12345"}); return c
cli, cor = login("cliente@exemplo.com"), login("corretor@exemplo.com")
with app.app_context(): im = get_db().imoveis.find_one({"codigo": "AP0001"})
cli.post(f"/imovel/{im['slug']}/agendar", data={"data_hora": "2033-02-01T09:00"})
with app.app_context(): ag = get_db().agendamentos.find_one({})
mail.OUTBOX.clear()
cor.post(f"/admin/agendamentos/{ag['_id']}/status", data={"status": "confirmado"})
ok(len(mail.OUTBOX) == 1 and mail.OUTBOX[0]["to"] == "cliente@exemplo.com" and "CONFIRMADA" in mail.OUTBOX[0]["body"] and "01/02/2033 às 09:00" in mail.OUTBOX[0]["body"], "cliente recebe e-mail de confirmação (horário em fuso BR)")
mail.OUTBOX.clear()
cor.post(f"/admin/agendamentos/{ag['_id']}/status", data={"status": "cancelado", "motivo": "Imóvel reservado"})
ok("Imóvel reservado" in mail.OUTBOX[0]["body"], "cliente recebe o motivo do cancelamento")
# lead notifica equipe
class T2(T): NOTIFY_EMAIL = "equipe@exemplo.com"
app2 = create_app(T2); seed.create_app = lambda: app2; seed.main(True)
mail.OUTBOX.clear()
app2.test_client().post("/fale-conosco", data={"nome": "Zé Teste", "email": "z@x.com", "telefone": "11988887777", "aceite_lgpd": "on"})
ok(len(mail.OUTBOX) == 1 and mail.OUTBOX[0]["to"] == "equipe@exemplo.com" and "/admin/leads/" in mail.OUTBOX[0]["body"], "equipe é avisada de novo lead")
print("OK FINAL")
