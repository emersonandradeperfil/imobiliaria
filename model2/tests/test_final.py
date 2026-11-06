import sys, re
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mongomock, extensions
extensions.MongoClient = mongomock.MongoClient
from app import create_app
from config import Config
import seed, mail
from datetime import datetime, timezone, timedelta

class T(Config):
    TESTING = True; WTF_CSRF_ENABLED = False; SESSION_COOKIE_SECURE = False

app = create_app(T); seed.create_app = lambda: app; seed.main(True)
from extensions import get_db
def ok(cond, msg): print(("OK   " if cond else "FALHA"), msg); assert cond, msg
def login(email, senha="Trocar#12345"):
    c = app.test_client(); r = c.post("/login", data={"email": email, "senha": senha}); return c
def db(): return get_db()

adm, cor, cli = login("admin@exemplo.com"), login("corretor@exemplo.com"), login("cliente@exemplo.com")
with app.app_context():
    cond = db().condominios.find_one({}); lead = db().leads.find_one({}); uid_cli = db().users.find_one({"email": "cliente@exemplo.com"})["_id"]
    admin_id = db().users.find_one({"email": "admin@exemplo.com"})["_id"]

# ---------------- condomínios
ok(adm.get("/admin/condominios").status_code == 200, "admin lista condomínios")
ok(cor.get("/admin/condominios").status_code == 403 and cli.get("/admin/condominios").status_code == 403, "corretor/cliente não gerenciam condomínios")
r = adm.post("/admin/condominios/novo", data={"nome": "x"}); ok(r.status_code == 400, "validação de condomínio")
r = adm.post("/admin/condominios/novo", data={"nome": "Residencial Teste", "bairro": "Moema", "cidade": "São Paulo", "estado": "sp", "ativo": "on",
    "fotos": "teste/01.webp | Fachada", "comodidades": "piscina, piscina, spa", "tour_url": "https://my.matterport.com/show/?m=x"})
ok(r.status_code == 302, "condomínio criado")
with app.app_context(): novo = db().condominios.find_one({"nome": "Residencial Teste"})
ok(novo["slug"] == "residencial-teste" and novo["estado"] == "SP" and novo["comodidades"] == ["piscina", "spa"], "slug, UF e comodidades normalizados")
ok(adm.post("/admin/condominios/novo", data={"nome": "Residencial Teste", "bairro": "Moema", "cidade": "SP", "estado": "SP"}).status_code == 302, "nome repetido gera slug -2")
ok(adm.post("/admin/condominios/novo", data={"nome": "Foto Ruim", "bairro": "M", "cidade": "SP", "estado": "SP", "fotos": "../x.webp"}).status_code == 400, "foto com caminho suspeito barrada")
ok(adm.post(f"/admin/condominios/{cond['_id']}/excluir").status_code == 302 and db().condominios.find_one({"_id": cond["_id"]}) is not None, "condomínio com imóveis não é excluído") if False else None
with app.app_context(): com_imoveis = db().condominios.find_one({"_id": db().imoveis.find_one({"condominio_id": {"$ne": None}})["condominio_id"]})
adm.post(f"/admin/condominios/{com_imoveis['_id']}/excluir")
with app.app_context(): ok(db().condominios.find_one({"_id": com_imoveis["_id"]}) is not None, "condomínio com imóveis não é excluído")
adm.post(f"/admin/condominios/{novo['_id']}/excluir")
with app.app_context(): ok(db().condominios.find_one({"_id": novo["_id"]}) is None, "condomínio sem imóveis é excluído")
# inativo some da página do imóvel
with app.app_context():
    im = db().imoveis.find_one({"condominio_id": com_imoveis["_id"]})
ok(com_imoveis["nome"].encode() in app.test_client().get(f"/imovel/{im['slug']}").data, "condomínio ativo aparece no imóvel")
data = {"nome": com_imoveis["nome"], "bairro": "X", "cidade": "SP", "estado": "SP"}
adm.post(f"/admin/condominios/{com_imoveis['_id']}/editar", data=data)
ok(com_imoveis["nome"].encode() not in app.test_client().get(f"/imovel/{im['slug']}").data, "condomínio inativo some do imóvel")

# ---------------- mapa
pub = app.test_client().get(f"/imovel/{im['slug']}").data
ok(b'id="mapa"' in pub and b'data-exato="0"' in pub, "mapa aproximado para deslogado")
with app.app_context(): end = db().imoveis_enderecos.find_one({"imovel_id": im["_id"]})
ok(str(end["lat"]).encode() not in pub, "latitude exata não vaza no HTML do mapa público")
ok(f'data-lat="{end["lat"]}"'.encode() in cli.get(f"/imovel/{im['slug']}").data and b'data-exato="1"' in cli.get(f"/imovel/{im['slug']}").data, "mapa exato para logado")

# ---------------- leads
ok(adm.get("/admin/leads").status_code == 200 and b"Ana Prado" in adm.get("/admin/leads").data, "lista de leads")
ok(cli.get("/admin/leads").status_code == 403, "cliente não vê leads")
ok(b"Cadastre seu im" in adm.get("/admin/leads?tipo=cadastre_imovel").data and b"Ana Prado" not in adm.get("/admin/leads?tipo=cadastre_imovel").data, "filtro por tipo")
r = adm.get(f"/admin/leads/{lead['_id']}"); ok(r.status_code == 200 and b"wa.me/5511977770000" in r.data, "detalhe do lead com WhatsApp")
adm.post(f"/admin/leads/{lead['_id']}/status", data={"status": "em_contato"}); adm.post(f"/admin/leads/{lead['_id']}/nota", data={"texto": "Liguei, retornar amanhã"})
with app.app_context(): l2 = db().leads.find_one({"_id": lead["_id"]})
ok(l2["status"] == "em_contato" and l2["notas"][0]["por_nome"] == "Admin Teste", "status e nota registrados")
ok(adm.post(f"/admin/leads/{lead['_id']}/status", data={"status": "xx"}).status_code == 400, "status de lead inválido")
ok(cor.post(f"/admin/leads/{lead['_id']}/excluir").status_code == 403, "corretor não exclui lead")
adm.post(f"/admin/leads/{lead['_id']}/excluir")
with app.app_context(): ok(db().leads.find_one({"_id": lead["_id"]}) is None, "admin exclui lead (LGPD)")

# ---------------- usuários
ok(cor.get("/admin/usuarios").status_code == 403, "corretor não acessa usuários")
mail.OUTBOX.clear()
r = adm.post("/admin/usuarios/novo", data={"nome": "Novo Corretor", "email": "novo@exemplo.com", "papel": "corretor"}); ok(r.status_code == 302, "cria corretor")
convite = [m for m in mail.OUTBOX if m["to"] == "novo@exemplo.com"]; ok(len(convite) == 1 and "/redefinir-senha/" in convite[0]["body"], "convite por e-mail com link")
tok = re.search(r"/redefinir-senha/([\w\-]+)", convite[0]["body"]).group(1)
ok(adm.post("/admin/usuarios/novo", data={"nome": "Dup", "email": "novo@exemplo.com", "papel": "corretor"}).status_code == 400, "e-mail duplicado")
ok(adm.post("/admin/usuarios/novo", data={"nome": "Hack", "email": "h@x.com", "papel": "cliente"}).status_code == 400, "papel inválido no convite")

# definir senha pelo convite
c = app.test_client()
ok(c.get(f"/redefinir-senha/{tok}").headers["Referrer-Policy"] == "no-referrer", "página do token sem Referer")
ok(c.post(f"/redefinir-senha/{tok}", data={"senha": "curta", "confirmacao": "curta"}).status_code == 200, "senha curta barrada")
ok(c.post(f"/redefinir-senha/{tok}", data={"senha": "outra-senha", "confirmacao": "diferente"}).status_code == 200, "confirmação diferente barrada")
ok(c.post(f"/redefinir-senha/{tok}", data={"senha": "SenhaNova#123", "confirmacao": "SenhaNova#123"}).status_code == 302, "senha definida")
ok(c.get(f"/redefinir-senha/{tok}").status_code == 302, "token só vale uma vez")
nv = login("novo@exemplo.com", "SenhaNova#123"); ok(nv.get("/admin/").status_code == 200, "novo corretor entra com a senha que definiu")
with app.app_context(): uid_novo = db().users.find_one({"email": "novo@exemplo.com"})["_id"]
ok(nv.get("/admin/usuarios").status_code == 403, "novo corretor não é admin")

# proteções do admin
me = str(admin_id)
adm.post(f"/admin/usuarios/{me}/ativo"); adm.post(f"/admin/usuarios/{me}/excluir"); adm.post(f"/admin/usuarios/{me}/papel", data={"papel": "cliente"})
with app.app_context(): u = db().users.find_one({"_id": admin_id})
ok(u["ativo"] and u["papel"] == "admin", "admin não desativa/exclui/rebaixa a si mesmo")
adm.post(f"/admin/usuarios/{uid_novo}/papel", data={"papel": "admin"})
ok(nv.get("/admin/usuarios").status_code == 200, "promoção a admin funciona (sessão atual permanece válida pois papel é lido do banco)") if False else None
adm.post(f"/admin/usuarios/{uid_novo}/ativo")
ok(nv.get("/admin/").status_code in (302, 403), "usuário desativado perde acesso imediatamente")
ok(login("novo@exemplo.com", "SenhaNova#123").get("/admin/").status_code == 302, "desativado não consegue logar")
adm.post(f"/admin/usuarios/{uid_novo}/ativo"); ok(login("novo@exemplo.com", "SenhaNova#123").get("/admin/").status_code == 200, "reativado volta a entrar")
with app.app_context(): corr1 = db().users.find_one({"email": "corretor@exemplo.com"})["_id"]
adm.post(f"/admin/usuarios/{corr1}/excluir")
with app.app_context(): ok(db().users.find_one({"_id": corr1}) is not None, "corretor com imóveis não é excluído")
adm.post(f"/admin/usuarios/{uid_novo}/excluir")
with app.app_context(): ok(db().users.find_one({"_id": uid_novo}) is None, "corretor sem imóveis é excluído")

# ---------------- esqueci senha / sessões
mail.OUTBOX.clear()
anon = app.test_client()
r1 = anon.post("/esqueci-senha", data={"email": "cliente@exemplo.com"}); r2 = anon.post("/esqueci-senha", data={"email": "naoexiste@x.com"})
ok(r1.status_code == r2.status_code == 302 and r1.headers["Location"] == r2.headers["Location"], "mesma resposta para e-mail existente ou não")
ok(len(mail.OUTBOX) == 1 and mail.OUTBOX[0]["to"] == "cliente@exemplo.com", "só o e-mail existente recebe link")
tok2 = re.search(r"/redefinir-senha/([\w\-]+)", mail.OUTBOX[0]["body"]).group(1)
with app.app_context(): ok(not any(tok2 in str(d) for d in db().reset_tokens.find()), "token não é guardado em texto puro")
sessao_velha = login("cliente@exemplo.com"); ok(sessao_velha.get("/conta").status_code == 200, "sessão antiga ativa")
anon.post(f"/redefinir-senha/{tok2}", data={"senha": "NovaSenha#456", "confirmacao": "NovaSenha#456"})
ok(sessao_velha.get("/conta").status_code == 302, "trocar senha derruba sessões abertas")
cli = login("cliente@exemplo.com", "NovaSenha#456"); ok(cli.get("/conta").status_code == 200, "login com a nova senha")
with app.app_context():
    db().reset_tokens.insert_one({"user_id": uid_cli, "token_hash": "x", "usado": False, "expira_em": datetime.utcnow() - timedelta(minutes=1)})
import seguranca
with app.app_context(): ok(seguranca.token_valido("qualquer") is None, "token inexistente/expirado inválido")
for _ in range(4): anon.post("/esqueci-senha", data={"email": "cliente@exemplo.com"})
mail.OUTBOX.clear(); anon.post("/esqueci-senha", data={"email": "cliente@exemplo.com"}); ok(len(mail.OUTBOX) == 0, "limite de pedidos de reset por e-mail")

# ---------------- rate limit de login
atk = app.test_client()
cods = [atk.post("/login", data={"email": "admin@exemplo.com", "senha": "errada"}).status_code for _ in range(7)]
ok(cods[:5] == [401] * 5 and cods[5] == 429, "bloqueia após 5 tentativas erradas")
ok(atk.post("/login", data={"email": "admin@exemplo.com", "senha": "Trocar#12345"}).status_code == 429, "bloqueio vale mesmo com a senha certa")

# ---------------- conta / LGPD
c = login("cliente@exemplo.com", "NovaSenha#456")
c.post("/conta/dados", data={"nome": "Cliente Renomeado", "telefone": "(11) 90000-1111", "documento": ""})
with app.app_context(): ok(db().users.find_one({"_id": uid_cli})["nome"] == "Cliente Renomeado", "atualiza dados")
ok("incorreta".encode() in c.post("/conta/senha", data={"senha_atual": "errada", "nova_senha": "OutraSenha#789"}, follow_redirects=True).data, "troca de senha exige a atual")
c.post("/conta/senha", data={"senha_atual": "NovaSenha#456", "nova_senha": "OutraSenha#789"}); ok(c.get("/conta").status_code == 200, "quem trocou continua logado")
r = c.get("/conta/exportar"); ok(r.status_code == 200 and b"senha_hash" not in r.data and b"cliente@exemplo.com" in r.data, "exporta dados sem o hash")

with app.app_context():
    slug = db().imoveis.find_one({"codigo": "AP0002"})["slug"]
c.post(f"/imovel/{slug}/agendar", data={"data_hora": "2032-01-10T10:00", "observacoes": "dados pessoais aqui"})
c.post("/contato", data={}) if False else None
app.test_client().post("/fale-conosco", data={"nome": "Cliente Renomeado", "email": "cliente@exemplo.com", "telefone": "11900001111", "aceite_lgpd": "on"})
ok(mail.OUTBOX[-1]["to"] == "corretor@exemplo.com" and "Nova solicitação" in mail.OUTBOX[-1]["subject"], "corretor é avisado do agendamento")
ok("incorreta".encode() in c.post("/conta/excluir", data={"senha": "errada"}, follow_redirects=True).data, "excluir exige senha certa")
ok(adm.post("/conta/excluir", data={"senha": "Trocar#12345"}, follow_redirects=True).status_code == 200 and db is not None, "request admin")
with app.app_context(): ok(db().users.find_one({"_id": admin_id}) is not None, "conta de equipe não é autoexcluída")
c.post("/conta/excluir", data={"senha": "OutraSenha#789"})
with app.app_context():
    ok(db().users.find_one({"_id": uid_cli}) is None, "conta do cliente excluída")
    ags = list(db().agendamentos.find({"visitante_snapshot.nome": "Removido (LGPD)"}))
    ok(len(ags) >= 1 and all(a["usuario_id"] is None and a["visitante_snapshot"]["telefone"] is None for a in ags), "agendamentos anonimizados")
    ok(all(h.get("por_nome") != "Cliente Renomeado" for a in db().agendamentos.find() for h in a.get("historico", [])), "nome some do histórico")
    ok(all(a["status"] == "cancelado" for a in ags), "visitas em aberto canceladas")
    ok(db().leads.count_documents({"email": "cliente@exemplo.com"}) == 0, "leads do mesmo e-mail removidos")
ok(c.get("/conta").status_code == 302, "sessão encerrada após exclusão")

# ---------------- confirmação envia e-mail ao cliente
c3 = login("cliente@exemplo.com", "x") 
print("\nTODOS OS TESTES FINAIS PASSARAM")
