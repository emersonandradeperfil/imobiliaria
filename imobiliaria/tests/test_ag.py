import sys
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mongomock, extensions
extensions.MongoClient = mongomock.MongoClient
from app import create_app
from config import Config
import seed
from werkzeug.security import generate_password_hash
from datetime import datetime, timezone, timedelta

class T(Config):
    TESTING = True; WTF_CSRF_ENABLED = False; SESSION_COOKIE_SECURE = False

app = create_app(T); seed.create_app = lambda: app; seed.main(True)
from extensions import get_db
def ok(cond, msg): print(("OK   " if cond else "FALHA"), msg); assert cond, msg
with app.app_context():
    db = get_db()
    db.users.insert_one({"nome": "Outro Corretor", "email": "c2@exemplo.com", "senha_hash": generate_password_hash("Trocar#12345"),
        "telefone": "11999990000", "papel": "corretor", "ativo": True, "favoritos": [], "criado_em": datetime.now(timezone.utc)})
    im1 = db.imoveis.find_one({"codigo": "AP0001"}); im2 = db.imoveis.find_one({"codigo": "AP0002"})
    end1 = db.imoveis_enderecos.find_one({"imovel_id": im1["_id"]})
def login(email):
    c = app.test_client(); c.post("/login", data={"email": email, "senha": "Trocar#12345"}); return c

cli = login("cliente@exemplo.com")
cli.post(f"/imovel/{im1['slug']}/agendar", data={"data_hora": "2031-03-10T10:00", "observacoes": "levo meu arquiteto"})
cli.post(f"/imovel/{im2['slug']}/agendar", data={"data_hora": "2031-03-10T10:30"})
with app.app_context():
    a1 = get_db().agendamentos.find_one({"imovel_id": im1["_id"]}); a2 = get_db().agendamentos.find_one({"imovel_id": im2["_id"]})
ok(len(a1["historico"]) == 1 and a1["historico"][0]["status"] == "pendente", "agendamento já nasce com histórico")
id1, id2 = str(a1["_id"]), str(a2["_id"])

ok(app.test_client().get("/admin/agendamentos").status_code == 302, "lista exige login")
ok(cli.get("/admin/agendamentos").status_code == 403, "cliente não acessa a lista")
ok(cli.get(f"/admin/agendamentos/{id1}").status_code == 403, "cliente não acessa o detalhe")
ok(cli.post(f"/admin/agendamentos/{id1}/status", data={"status": "confirmado"}).status_code == 403, "cliente não confirma a própria visita")

c1, c2, adm = login("corretor@exemplo.com"), login("c2@exemplo.com"), login("admin@exemplo.com")
r = c1.get("/admin/agendamentos"); ok(r.status_code == 200 and b"Cliente Teste" in r.data, "corretor 1 vê a visita na lista")
ok(b"Cliente Teste" not in c2.get("/admin/agendamentos").data, "corretor 2 não vê visita alheia")
ok(c2.get(f"/admin/agendamentos/{id1}").status_code == 403, "corretor 2 não abre detalhe alheio")
ok(c2.post(f"/admin/agendamentos/{id1}/status", data={"status": "confirmado"}).status_code == 403, "corretor 2 não confirma visita alheia")
ok(adm.get(f"/admin/agendamentos/{id1}").status_code == 200, "admin abre qualquer detalhe")
ok(c1.get("/admin/agendamentos/xyz").status_code == 404, "id inválido → 404")

r = c1.get(f"/admin/agendamentos/{id1}")
ok(end1["logradouro"].encode() in r.data and b"levo meu arquiteto" in r.data and b"wa.me/5511999990000" in r.data, "detalhe mostra endereço, observação e WhatsApp")

ok("n\u00e3o \u00e9 permitida".encode() in c1.post(f"/admin/agendamentos/{id1}/status", data={"status": "realizado"}, follow_redirects=True).data, "pendente → realizado barrado")
c1.post(f"/admin/agendamentos/{id1}/status", data={"status": "confirmado"})
with app.app_context(): ok(get_db().agendamentos.find_one({"_id": a1["_id"]})["status"] == "confirmado", "corretor confirmou")
r = c1.get(f"/admin/agendamentos/{id2}"); ok("já tem uma visita confirmada".encode() in r.data, "alerta de conflito de agenda (10:00 x 10:30)")

ok("Informe o motivo".encode() in c1.post(f"/admin/agendamentos/{id2}/status", data={"status": "cancelado", "motivo": ""}, follow_redirects=True).data, "recusa exige motivo")
c1.post(f"/admin/agendamentos/{id2}/status", data={"status": "cancelado", "motivo": "Horário indisponível, sugiro 14h"})
ok("Horário indisponível".encode() in cli.get("/meus-agendamentos").data, "cliente vê o motivo da recusa")
with app.app_context(): d2 = get_db().agendamentos.find_one({"_id": a2["_id"]})
ok(d2["status"] == "cancelado" and len(d2["historico"]) == 2 and d2["historico"][-1]["por_nome"] == "Corretora Teste", "histórico registra quem cancelou")
ok("não é permitida".encode() in c1.post(f"/admin/agendamentos/{id2}/status", data={"status": "confirmado"}, follow_redirects=True).data, "cancelado é final")

ok("só pode ser marcada".encode() in c1.post(f"/admin/agendamentos/{id1}/status", data={"status": "realizado"}, follow_redirects=True).data, "realizada antes do horário barrado")
with app.app_context():
    passado = datetime.now(timezone.utc) - timedelta(days=1)
    pid = get_db().agendamentos.insert_one({"imovel_id": im1["_id"], "usuario_id": a1["usuario_id"], "corretor_id": im1["corretor_id"], "data_hora": passado,
        "status": "confirmado", "historico": [], "visitante_snapshot": {"nome": "X", "telefone": "11", "documento": None}}).inserted_id
    pid_pend = get_db().agendamentos.insert_one({"imovel_id": im1["_id"], "usuario_id": a1["usuario_id"], "corretor_id": im1["corretor_id"], "data_hora": passado,
        "status": "pendente", "historico": [], "visitante_snapshot": {"nome": "Y", "telefone": "11", "documento": None}}).inserted_id
c1.post(f"/admin/agendamentos/{pid}/status", data={"status": "realizado"})
with app.app_context(): ok(get_db().agendamentos.find_one({"_id": pid})["status"] == "realizado", "visita passada marcada como realizada")
ok("já passou".encode() in c1.post(f"/admin/agendamentos/{pid_pend}/status", data={"status": "confirmado"}, follow_redirects=True).data, "não confirma horário no passado")

# cliente cancela a própria → histórico
cli.post(f"/agendamentos/{id1}/cancelar")
with app.app_context(): d1 = get_db().agendamentos.find_one({"_id": a1["_id"]})
ok(d1["status"] == "cancelado" and d1["cancelado_por"] == "cliente" and d1["historico"][-1]["por_nome"] == "Cliente Teste", "cliente cancela e fica no histórico")
ok(b"Cliente Teste" in c1.get("/admin/agendamentos?filtro=cancelado").data, "aba de cancelados")
ok(c1.get("/admin/").status_code == 200, "dashboard ok")
print("\nTODOS OS TESTES DE AGENDAMENTO PASSARAM")
