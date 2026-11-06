import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import mongomock, extensions
extensions.MongoClient = mongomock.MongoClient
from bson import Binary
from werkzeug.security import generate_password_hash
from app import create_app
from config import Config
import criar_admin, getpass

class T(Config):
    TESTING = True; WTF_CSRF_ENABLED = False; SESSION_COOKIE_SECURE = False
app = create_app(T)
from extensions import get_db
def ok(c, m): print(("OK   " if c else "FALHA"), m); assert c, m

def novo(email, senha_hash):
    with app.app_context():
        get_db().users.insert_one({"nome": "Teste", "email": email, "senha_hash": senha_hash, "telefone": "11999990000",
                                   "papel": "admin", "ativo": True, "favoritos": [], "sessao_versao": 0})
def entra(email, senha):
    c = app.test_client(); r = c.post("/login", data={"email": email, "senha": senha}); return r, c

h = generate_password_hash("SenhaBoa#123")
novo("texto@x.com", h)
novo("bytes@x.com", h.encode())                       # hash salvo como bytes (o erro que você viu)
novo("binario@x.com", Binary(h.encode()))             # hash salvo como BSON Binary
novo("bcrypt@x.com", b"$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123")  # formato de outra lib
novo("puro@x.com", "123456")                          # senha em texto puro
novo("vazio@x.com", None)

ok(entra("texto@x.com", "SenhaBoa#123")[0].status_code == 302, "hash em texto: entra")
ok(entra("bytes@x.com", "SenhaBoa#123")[0].status_code == 302, "hash em bytes: entra (antes dava erro 500)")
ok(entra("binario@x.com", "SenhaBoa#123")[0].status_code == 302, "hash em BSON Binary: entra")
ok(entra("bytes@x.com", "errada")[0].status_code == 401, "hash em bytes + senha errada: 401")
for e in ("bcrypt@x.com", "puro@x.com", "vazio@x.com"):
    ok(entra(e, "123456")[0].status_code == 401, f"hash inválido ({e}) nunca gera erro 500")

# criar_admin.py
respostas = iter(["MinhaSenha#2026", "MinhaSenha#2026"])
criar_admin.getpass.getpass = lambda prompt="": next(respostas)
criar_admin.create_app = lambda: app
ok(criar_admin.main(["dono@x.com", "Dono da Imobiliária"]) == 0, "criar_admin cria usuário")
r, c = entra("dono@x.com", "MinhaSenha#2026"); ok(r.status_code == 302 and c.get("/admin/").status_code == 200, "admin criado pelo script entra no painel")
respostas = iter(["OutraSenha#999", "OutraSenha#999"])
criar_admin.getpass.getpass = lambda prompt="": next(respostas)
criar_admin.main(["dono@x.com", "Dono", "corretor"])
ok(entra("dono@x.com", "OutraSenha#999")[0].status_code == 302 and entra("dono@x.com", "MinhaSenha#2026")[0].status_code == 401, "rodar de novo troca a senha")
respostas = iter(["curta", "curta"])
criar_admin.getpass.getpass = lambda prompt="": next(respostas)
ok(criar_admin.main(["x@x.com", "Fulano", "admin"]) == 1, "senha curta é recusada")
print("OK FINAL")
