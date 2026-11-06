import sys, re
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mongomock, extensions
extensions.MongoClient = mongomock.MongoClient
from app import create_app
from config import Config
import seed

class T(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False

# roda o seed no mesmo "banco" em memória
app = create_app(T)
seed_app_factory = seed.create_app
seed.create_app = lambda: app
seed.main(True)

c = app.test_client()
def ok(cond, msg): print(("OK   " if cond else "FALHA"), msg); assert cond, msg

r = c.get("/"); ok(r.status_code == 200 and b"Destaques" in r.data, "home")
r = c.get("/imoveis?finalidade=locacao&categoria=comercial"); ok(r.status_code == 200, "listagem filtrada")
r = c.get("/imoveis?preco_max=abc&quartos=-1&bairro[$ne]=x"); ok(r.status_code == 200, "filtros inválidos não quebram")

with app.app_context():
    from extensions import get_db
    db = get_db(); im = db.imoveis.find_one({"codigo": "AP0001"}); end = db.imoveis_enderecos.find_one({"imovel_id": im["_id"]})
slug = im["slug"]

r = c.get(f"/imovel/{slug}")
ok(r.status_code == 200, "detalhe deslogado")
ok(end["logradouro"].encode() not in r.data and str(end["lat"]).encode() not in r.data, "endereço/coordenada exata NÃO vazam para deslogado")
ok("O endereço completo".encode() in r.data, "mostra aviso de login")
ok(c.post(f"/imovel/{slug}/agendar", data={"data_hora": "2030-01-01T10:00"}).status_code == 302, "agendar deslogado redireciona")
ok(c.get("/admin/").status_code == 302, "admin deslogado redireciona")

# cadastro
r = c.post("/cadastro", data={"nome": "Maria Souza", "email": "maria@x.com", "telefone": "(11) 98888-7777", "senha": "senhaforte1", "aceite_lgpd": "on", "papel": "admin"})
ok(r.status_code == 302, "cadastro ok")
with app.app_context():
    u = get_db().users.find_one({"email": "maria@x.com"})
ok(u["papel"] == "cliente" and u["lgpd"]["versao_politica"] == "1.0" and u["senha_hash"] != "senhaforte1", "papel forçado=cliente, LGPD gravada, senha com hash")
ok(c.post("/cadastro", data={"nome": "Maria", "email": "maria@x.com", "telefone": "11988887777", "senha": "senhaforte1", "aceite_lgpd": "on"}).status_code == 400, "e-mail duplicado bloqueado")

r = c.get(f"/imovel/{slug}")
ok(end["logradouro"].encode() in r.data, "logado vê o endereço")
r = c.post(f"/imovel/{slug}/agendar", data={"data_hora": "2030-05-10T14:00", "observacoes": "teste"}); ok(r.status_code == 302, "agendamento criado")
ok(c.post(f"/imovel/{slug}/agendar", data={"data_hora": "2030-05-10T14:00"}, follow_redirects=True).data.count("já está reservado".encode()) == 1, "conflito de horário")
ok("Escolha uma data futura".encode() in c.post(f"/imovel/{slug}/agendar", data={"data_hora": "2000-01-01T10:00"}, follow_redirects=True).data, "data no passado bloqueada")
r = c.get("/meus-agendamentos"); ok("10/05/2030 às 14:00".encode() in r.data, "lista agendamento (fuso BR)")
c.post(f"/favoritos/{slug}"); ok(slug.encode() in c.get("/favoritos").data, "favoritar")
ok(c.get("/admin/").status_code == 403, "cliente não acessa o painel")
c.post("/logout"); ok(c.get("/favoritos").status_code == 302, "logout")

# redirect aberto
r = c.post("/login?next=//evil.com", data={"email": "maria@x.com", "senha": "senhaforte1"}); ok(r.headers["Location"] == "/", "open redirect bloqueado")
ok(c.post("/login", data={"email": "maria@x.com", "senha": "errada"}).status_code == 401, "senha errada")

# corretor / admin
c.post("/login", data={"email": "corretor@exemplo.com", "senha": "Trocar#12345"})
r = c.get("/admin/"); ok(r.status_code == 200 and b"Maria Souza" in r.data, "corretor vê painel com a visita")
c.post("/logout")

# leads
r = c.post("/cadastre-seu-imovel", data={"nome": "João Lima", "email": "j@x.com", "telefone": "11977776666", "tipo_imovel": "cobertura", "bairro": "Jardim Europa", "aceite_lgpd": "on"})
ok(r.status_code == 302, "lead cadastre_imovel")
r = c.post("/fale-conosco", data={"nome": "Bot", "email": "b@x.com", "telefone": "11977776666", "website": "spam", "aceite_lgpd": "on"})
with app.app_context():
    ok(get_db().leads.count_documents({}) == 4, "honeypot descartou o robô")
ok(c.get("/administracao-condominios").status_code == 200, "página adm. condomínios")
ok(c.get("/imovel/nao-existe").status_code == 404, "404")
print("\nTODOS OS TESTES PASSARAM")
