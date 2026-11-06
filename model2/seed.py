"""Popula o banco com dados FICTÍCIOS para validar a estrutura.

Uso:
    python seed.py            # só insere se as coleções estiverem vazias
    python seed.py --reset    # apaga tudo e recria

NÃO rode em produção: cria usuários de teste com senha conhecida.
"""
import os
import random
import re
import sys
import unicodedata
from datetime import datetime, timezone

from werkzeug.security import generate_password_hash

from app import create_app
from extensions import ensure_indexes, get_db

random.seed(7)
AGORA = datetime.now(timezone.utc)

BAIRROS = {
    "Vila Nova Conceição": (-23.5876, -46.6683),
    "Jardim Europa": (-23.5718, -46.6845),
    "Itaim Bibi": (-23.5850, -46.6770),
    "Jardim Paulistano": (-23.5780, -46.6990),
    "Moema": (-23.6000, -46.6650),
    "Vila Olímpia": (-23.5950, -46.6860),
    "Pinheiros": (-23.5670, -46.6920),
    "Cidade Jardim": (-23.5870, -46.7100),
}
RUAS = ["Rua das Acácias", "Alameda dos Ipês", "Avenida das Palmeiras", "Rua dos Jacarandás", "Rua das Magnólias", "Alameda das Orquídeas"]
COMODIDADES_RES = ["piscina", "academia", "salão de festas", "segurança 24h", "spa", "quadra de tênis", "brinquedoteca", "churrasqueira", "adega", "home theater"]
COMODIDADES_COM = ["recepção", "segurança 24h", "heliponto", "auditório", "fibra óptica", "gerador", "ar-condicionado central"]
CONDOMINIOS = [
    ("Residencial Villa Aurora", "Vila Nova Conceição"),
    ("Edifício Jardins do Parque", "Jardim Europa"),
    ("Torre Corporativa Faria Lima Prime", "Itaim Bibi"),
]
ROTULOS_FOTO = ["Sala", "Suíte master", "Cozinha", "Varanda", "Área de lazer"]


def slugify(txt):
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", txt.lower()).strip("-")


def main(reset):
    app = create_app()
    with app.app_context():
        db = get_db()
        if reset:
            for c in ("users", "imoveis", "imoveis_enderecos", "condominios", "agendamentos", "leads", "reset_tokens", "tentativas"):
                db[c].delete_many({})
        elif db.imoveis.count_documents({}) > 0:
            print("Já existem imóveis. Use --reset para recriar.")
            return
        ensure_indexes()

        senha = os.environ.get("SEED_PASSWORD", "Trocar#12345")
        usuarios = [
            ("Admin Teste", "admin@exemplo.com", "admin"),
            ("Corretora Teste", "corretor@exemplo.com", "corretor"),
            ("Cliente Teste", "cliente@exemplo.com", "cliente"),
        ]
        ids = {}
        for nome, email, papel in usuarios:
            r = db.users.insert_one({
                "nome": nome, "email": email, "senha_hash": generate_password_hash(senha),
                "telefone": "11999990000", "documento": None, "papel": papel, "ativo": True,
                "favoritos": [], "lgpd": {"aceite_em": AGORA, "versao_politica": "1.0"},
                "criado_em": AGORA, "ultimo_login": None,
            })
            ids[papel] = r.inserted_id

        cond_ids = {}
        for nome, bairro in CONDOMINIOS:
            r = db.condominios.insert_one({
                "nome": nome, "slug": slugify(nome),
                "descricao": "Condomínio de alto padrão com infraestrutura completa de lazer e segurança. (texto fictício)",
                "bairro": bairro, "cidade": "São Paulo", "estado": "SP",
                "comodidades": random.sample(COMODIDADES_RES, 4),
                "fotos": [], "video_url": None, "tour_url": None,
                "administrado_pela_imobiliaria": nome != CONDOMINIOS[1][0], "ativo": True,
                "criado_em": AGORA,
            })
            cond_ids[bairro] = r.inserted_id

        modelos = [
            ("apartamento", "residencial", ["venda"]), ("apartamento", "residencial", ["venda", "locacao"]),
            ("cobertura", "residencial", ["venda"]), ("casa_condominio", "residencial", ["venda"]),
            ("casa", "residencial", ["locacao"]), ("apartamento", "residencial", ["locacao"]),
            ("conjunto_comercial", "comercial", ["locacao"]), ("sala_comercial", "comercial", ["venda", "locacao"]),
            ("loja", "comercial", ["locacao"]), ("cobertura", "residencial", ["venda", "locacao"]),
            ("apartamento", "residencial", ["venda"]), ("casa", "residencial", ["venda"]),
            ("conjunto_comercial", "comercial", ["venda"]), ("apartamento", "residencial", ["locacao"]),
        ]
        for n, (tipo, categoria, fin) in enumerate(modelos, start=1):
            bairro, (lat, lng) = random.choice(list(BAIRROS.items()))
            res = categoria == "residencial"
            suites = random.randint(2, 5) if res else 0
            area = random.randint(180, 520) if res else random.randint(60, 400)
            venda = round(area * random.randint(18, 32) * 1000, -4) if "venda" in fin else None
            loc = round(area * random.randint(60, 110), -2) if "locacao" in fin else None
            codigo = f"{'AP' if res else 'CM'}{n:04d}"
            titulo = f"{tipo.replace('_', ' ').capitalize()} {'com ' + str(suites) + ' suítes ' if res else 'de ' + str(area) + ' m² '}em {bairro}"
            r = db.imoveis.insert_one({
                "codigo": codigo, "slug": f"{slugify(titulo)}-{codigo.lower()}",
                "titulo": titulo,
                "descricao": "Imóvel de alto padrão com acabamento refinado e excelente localização. (texto fictício para validação do layout)",
                "finalidade": fin, "categoria": categoria, "tipo": tipo,
                "status": "reservado" if n == 9 else "ativo", "destaque": n <= 8,
                "precos": {"venda": venda, "locacao": loc, "condominio": random.randint(15, 45) * 100, "iptu": random.randint(8, 30) * 100},
                "ocultar_preco": n == 3,
                "areas": {"util": area, "total": area + random.randint(10, 40), "terreno": None},
                "quartos": suites + (1 if res else 0), "suites": suites,
                "banheiros": suites + 2 if res else 2, "vagas": random.randint(2, 5) if res else random.randint(1, 6),
                "local_publico": {
                    "bairro": bairro, "cidade": "São Paulo", "estado": "SP",
                    "lat_aprox": round(lat, 2), "lng_aprox": round(lng, 2),  # arredondado de propósito
                },
                "condominio_id": cond_ids.get(bairro),
                "corretor_id": ids["corretor"],
                "comodidades": random.sample(COMODIDADES_RES if res else COMODIDADES_COM, 4),
                "midia": {
                    "fotos": [{"arquivo": f"{codigo.lower()}/{i:02d}.webp", "legenda": ROTULOS_FOTO[i - 1], "ordem": i, "capa": i == 1} for i in range(1, 6)],
                    "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ" if n == 1 else None,
                    "tour_url": None,
                },
                "criado_em": AGORA, "atualizado_em": AGORA,
            })
            db.imoveis_enderecos.insert_one({
                "imovel_id": r.inserted_id,
                "logradouro": random.choice(RUAS), "numero": str(random.randint(100, 999)),
                "complemento": f"Apto {random.randint(11, 182)}" if tipo in ("apartamento", "cobertura") else None,
                "bloco": None, "cep": "04000-000",
                "lat": round(lat + random.uniform(-0.004, 0.004), 6), "lng": round(lng + random.uniform(-0.004, 0.004), 6),
            })

        exemplos = [
            ("contato", "Ana Prado", "ana@exemplo.com", "Gostaria de informações sobre locação de salas comerciais.", {}),
            ("cadastre_imovel", "Carlos Menezes", "carlos@exemplo.com", "Tenho uma cobertura para vender.", {"tipo_imovel": "cobertura", "bairro": "Jardim Europa", "finalidade": "venda"}),
            ("adm_condominio", "Síndica Helena", "helena@exemplo.com", "Queremos orçamento de administração.", {"nome_condominio": "Edifício Aurora", "qtd_unidades": "48", "cidade": "São Paulo"}),
        ]
        for tipo, nome, email, msg, dados in exemplos:
            db.leads.insert_one({"tipo": tipo, "nome": nome, "email": email, "telefone": "11977770000", "mensagem": msg, "dados": dados,
                                 "status": "novo", "lgpd": {"aceite_em": AGORA, "versao_politica": "1.0"}, "criado_em": AGORA})

        print("Seed concluído:")
        print(f"  {db.imoveis.count_documents({})} imóveis · {db.condominios.count_documents({})} condomínios · {db.users.count_documents({})} usuários")
        print(f"  Logins de teste (senha: {senha}): admin@exemplo.com · corretor@exemplo.com · cliente@exemplo.com")


if __name__ == "__main__":
    main("--reset" in sys.argv)
