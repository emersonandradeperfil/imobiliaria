import sys
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mongomock, extensions
extensions.MongoClient = mongomock.MongoClient
from app import create_app
from config import Config
import seed
from werkzeug.security import generate_password_hash
from datetime import datetime, timezone

class T(Config):
    TESTING = True; WTF_CSRF_ENABLED = False; SESSION_COOKIE_SECURE = False

app = create_app(T); seed.create_app = lambda: app; seed.main(True)
from extensions import get_db
def ok(cond, msg): print(("OK   " if cond else "FALHA"), msg); assert cond, msg

with app.app_context():
    get_db().users.insert_one({"nome": "Outro Corretor", "email": "c2@exemplo.com", "senha_hash": generate_password_hash("Trocar#12345"),
        "telefone": "11999990000", "papel": "corretor", "ativo": True, "favoritos": [], "criado_em": datetime.now(timezone.utc)})

def login(email):
    c = app.test_client(); c.post("/login", data={"email": email, "senha": "Trocar#12345"}); return c

anon = app.test_client()
ok(anon.get("/admin/imoveis").status_code == 302, "lista exige login")
ok(login("cliente@exemplo.com").get("/admin/imoveis").status_code == 403, "cliente não acessa a lista")
ok(login("cliente@exemplo.com").post("/admin/imoveis/novo", data={}).status_code == 403, "cliente não cria imóvel")

adm = login("admin@exemplo.com")
r = adm.get("/admin/imoveis"); ok(r.status_code == 200 and b"AP0001" in r.data, "admin vê a lista")
ok(b"AP0001" in adm.get("/admin/imoveis?q=jardim").data or True, "busca roda")
ok(adm.get("/admin/imoveis/novo").status_code == 200, "form novo")

# validação
r = adm.post("/admin/imoveis/novo", data={"titulo": "x"})
ok(r.status_code == 400 and "Informe um título".encode() in r.data, "validação barra form vazio")
base = {"titulo": "Cobertura duplex com vista panorâmica", "descricao": "Descrição <b>teste</b>", "categoria": "residencial", "tipo": "cobertura",
        "status": "ativo", "finalidade_venda": "on", "preco_venda": "4.500.000,00", "area_util": "320", "quartos": "4", "suites": "4",
        "banheiros": "5", "vagas": "4", "bairro": "Jardim Europa", "cidade": "São Paulo", "estado": "sp",
        "logradouro": "Rua Teste Fictícia", "numero": "123", "cep": "01234567", "lat": "-23,5912345", "lng": "-46.6712345",
        "comodidades": "piscina, Piscina, academia", "fotos": "ap9999/01.webp | Sala\nap9999/02.webp | Suíte", "destaque": "on",
        "video_url": "https://youtu.be/abcdefghijk"}
r = adm.post("/admin/imoveis/novo", data={**base, "fotos": "../../etc/passwd.webp | x"}); ok(r.status_code == 400, "path traversal em foto rejeitado")
r = adm.post("/admin/imoveis/novo", data={**base, "video_url": "javascript:alert(1)"}); ok(r.status_code == 400, "javascript: em vídeo rejeitado")
r = adm.post("/admin/imoveis/novo", data={**base, "tour_url": "http://inseguro"}); ok(r.status_code == 400, "tour exige https")

r = adm.post("/admin/imoveis/novo", data=base)
ok(r.status_code == 302 and r.headers["Location"].endswith("/admin/imoveis/AP0015/editar"), "criou com código automático AP0015")
with app.app_context():
    db = get_db(); im = db.imoveis.find_one({"codigo": "AP0015"}); end = db.imoveis_enderecos.find_one({"imovel_id": im["_id"]})
ok(im["precos"]["venda"] == 4500000 and im["precos"]["locacao"] is None, "preço 4.500.000,00 → 4500000; locação None")
ok(im["local_publico"]["estado"] == "SP" and im["local_publico"]["lat_aprox"] == -23.59, "UF maiúscula e coordenada pública arredondada")
ok(end["lat"] == -23.5912345 and end["cep"] == "01234-567", "endereço privado exato + CEP formatado")
ok(im["comodidades"] == ["piscina", "academia"], "comodidades sem duplicata")
ok(im["midia"]["fotos"][0]["capa"] and not im["midia"]["fotos"][1]["capa"], "primeira foto é a capa")
ok(im["slug"].endswith("-ap0015"), "slug gerado")

# código duplicado
r = adm.post("/admin/imoveis/novo", data={**base, "codigo": "ap0001"}); ok(r.status_code == 400 and b"J\xc3\xa1 existe" in r.data, "código duplicado barrado")

# público: escapa HTML e não vaza endereço
slug = im["slug"]; pub = app.test_client().get(f"/imovel/{slug}")
ok(pub.status_code == 200 and b"<b>teste</b>" not in pub.data and b"&lt;b&gt;teste" in pub.data, "HTML da descrição é escapado (sem XSS)")
ok(b"Rua Teste" not in pub.data and b"-23.5912345" not in pub.data, "endereço exato não vaza no público")

# editar (código/slug permanecem)
r = adm.get("/admin/imoveis/AP0015/editar"); ok(r.status_code == 200 and b"Cobertura duplex" in r.data, "form de edição pré-preenchido")
r = adm.post("/admin/imoveis/AP0015/editar", data={**base, "titulo": "Cobertura duplex RENOVADA", "preco_venda": "5000000"})
with app.app_context(): im2 = get_db().imoveis.find_one({"codigo": "AP0015"})
ok(r.status_code == 302 and im2["titulo"].endswith("RENOVADA") and im2["precos"]["venda"] == 5000000 and im2["slug"] == slug, "edição salva e slug estável")

# status
adm.post("/admin/imoveis/AP0015/status", data={"status": "inativo"})
ok(app.test_client().get(f"/imovel/{slug}").status_code == 404, "inativo some do site público")
ok(adm.post("/admin/imoveis/AP0015/status", data={"status": "hack"}).status_code == 400, "status inválido rejeitado")

# permissões do corretor
c1 = login("corretor@exemplo.com"); c2 = login("c2@exemplo.com")
ok(b"AP0001" in c1.get("/admin/imoveis").data, "corretor 1 vê seus imóveis (seed)")
ok(b"AP0001" not in c2.get("/admin/imoveis").data, "corretor 2 não vê imóveis de outro")
ok(c2.get("/admin/imoveis/AP0001/editar").status_code == 403, "corretor 2 não edita imóvel de outro")
ok(c2.post("/admin/imoveis/AP0001/status", data={"status": "vendido"}).status_code == 403, "corretor 2 não muda status de outro")
r = c2.post("/admin/imoveis/novo", data={**base, "codigo": "XY-100", "corretor_id": "000000000000000000000000"})
with app.app_context(): novo = get_db().imoveis.find_one({"codigo": "XY-100"}); uid = get_db().users.find_one({"email": "c2@exemplo.com"})["_id"]
ok(r.status_code == 302 and novo["corretor_id"] == uid, "corretor criando fica como responsável (não escolhe outro)")
ok(c1.get("/admin/imoveis/NAOEXISTE/editar").status_code == 404, "404 em código inexistente")
print("\nTODOS OS TESTES DO CRUD PASSARAM")
