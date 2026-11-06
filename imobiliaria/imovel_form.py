"""Leitura e validação do formulário de imóvel (painel admin).

parse() devolve (campos_do_imovel, endereco, erros). Nada é gravado aqui.
"""
import re

from bson import ObjectId
from bson.errors import InvalidId

from extensions import get_db

CATEGORIAS = [("residencial", "Residencial"), ("comercial", "Comercial")]
TIPOS = [
    ("apartamento", "Apartamento"), ("cobertura", "Cobertura"), ("casa", "Casa"),
    ("casa_condominio", "Casa em condomínio"), ("terreno", "Terreno"),
    ("conjunto_comercial", "Conjunto comercial"), ("sala_comercial", "Sala comercial"),
    ("loja", "Loja"), ("galpao", "Galpão"),
]
STATUS = [
    ("ativo", "Ativo"), ("reservado", "Reservado"), ("vendido", "Vendido"),
    ("alugado", "Alugado"), ("inativo", "Inativo (oculto)"),
]
FOTO_RE = re.compile(r"^[a-z0-9_\-]+(/[a-z0-9_\-]+)*\.(webp|jpg|jpeg|png)$")
CODIGO_RE = re.compile(r"^[A-Z0-9\-]{3,20}$")
CEP_RE = re.compile(r"^\d{5}-?\d{3}$")


def _money(txt):
    s = (txt or "").strip().replace("R$", "").replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    v = float(s)  # ValueError se inválido
    if v < 0 or v > 1e10:
        raise ValueError
    return int(v) if v == int(v) else round(v, 2)


def _int(txt, maximo=1000):
    s = (txt or "").strip()
    if not s:
        return 0
    n = int(s)
    if n < 0 or n > maximo:
        raise ValueError
    return n


def _float(txt):
    s = (txt or "").strip().replace(",", ".")
    return float(s) if s else None


def _oid(txt, colecao, filtro=None):
    """ObjectId existente na coleção, ou None."""
    try:
        oid = ObjectId(txt)
    except (InvalidId, TypeError):
        return None
    q = {"_id": oid, **(filtro or {})}
    return oid if get_db()[colecao].find_one(q, {"_id": 1}) else None


def parse(f):
    erros = []

    def texto(k, maxlen):
        return f.get(k, "").strip()[:maxlen]

    def numero(fn, k, rotulo, **kw):
        try:
            return fn(f.get(k, ""), **kw)
        except ValueError:
            erros.append(f"Valor inválido em «{rotulo}».")
            return None

    titulo = texto("titulo", 150)
    if len(titulo) < 5:
        erros.append("Informe um título (mín. 5 caracteres).")
    descricao = texto("descricao", 5000)
    if not descricao:
        erros.append("Informe a descrição.")

    categoria = f.get("categoria")
    if categoria not in dict(CATEGORIAS):
        erros.append("Escolha a categoria.")
    tipo = f.get("tipo")
    if tipo not in dict(TIPOS):
        erros.append("Escolha o tipo do imóvel.")
    status = f.get("status", "ativo")
    if status not in dict(STATUS):
        status = "ativo"

    finalidade = [x for x in ("venda", "locacao") if f.get("finalidade_" + x)]
    if not finalidade:
        erros.append("Marque venda e/ou locação.")
    ocultar = bool(f.get("ocultar_preco"))

    p_venda = numero(_money, "preco_venda", "Preço de venda")
    p_loc = numero(_money, "preco_locacao", "Preço de locação")
    if not ocultar:
        if "venda" in finalidade and not p_venda:
            erros.append("Informe o preço de venda (ou marque «Preço sob consulta»).")
        if "locacao" in finalidade and not p_loc:
            erros.append("Informe o valor da locação (ou marque «Preço sob consulta»).")
    precos = {
        "venda": p_venda if "venda" in finalidade else None,
        "locacao": p_loc if "locacao" in finalidade else None,
        "condominio": numero(_money, "condominio_valor", "Condomínio"),
        "iptu": numero(_money, "iptu", "IPTU"),
    }

    util = numero(_money, "area_util", "Área útil")
    if not util:
        erros.append("Informe a área útil.")
    areas = {"util": util, "total": numero(_money, "area_total", "Área total"), "terreno": numero(_money, "area_terreno", "Terreno")}

    quartos = numero(_int, "quartos", "Dormitórios") or 0
    suites = numero(_int, "suites", "Suítes") or 0
    banheiros = numero(_int, "banheiros", "Banheiros") or 0
    vagas = numero(_int, "vagas", "Vagas") or 0

    bairro, cidade = texto("bairro", 80), texto("cidade", 80)
    estado = texto("estado", 2).upper()
    if not bairro or not cidade or len(estado) != 2:
        erros.append("Informe bairro, cidade e UF (2 letras).")

    # endereço privado
    logradouro, num = texto("logradouro", 150), texto("numero", 20)
    if not logradouro or not num:
        erros.append("Informe logradouro e número (ficam visíveis só para usuários logados).")
    cep = texto("cep", 9)
    if cep and not CEP_RE.match(cep):
        erros.append("CEP inválido.")
    elif cep and "-" not in cep:
        cep = cep[:5] + "-" + cep[5:]
    lat = numero(_float, "lat", "Latitude")
    lng = numero(_float, "lng", "Longitude")
    if (lat is not None and not -90 <= lat <= 90) or (lng is not None and not -180 <= lng <= 180):
        erros.append("Coordenadas fora do intervalo válido.")
        lat = lng = None
    endereco = {
        "logradouro": logradouro, "numero": num, "complemento": texto("complemento", 80) or None,
        "bloco": texto("bloco", 40) or None, "cep": cep or None, "lat": lat, "lng": lng,
    }

    # mídia
    fotos = []
    for linha in f.get("fotos", "").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        arquivo, _, legenda = (p.strip() for p in linha.partition("|"))
        if not FOTO_RE.match(arquivo):
            erros.append(f"Foto inválida: «{arquivo[:60]}». Use algo como ap0001/01.webp (minúsculas, sem espaços).")
            continue
        fotos.append({"arquivo": arquivo, "legenda": legenda[:80], "ordem": len(fotos) + 1, "capa": not fotos})
    if len(fotos) > 60:
        erros.append("Máximo de 60 fotos.")
    video = texto("video_url", 300) or None
    if video and not video.startswith(("https://", "http://")):
        erros.append("O link do vídeo deve começar com http:// ou https://.")
    tour = texto("tour_url", 300) or None
    if tour and not tour.startswith("https://"):
        erros.append("O link do tour virtual deve começar com https://.")

    comodidades = []
    for c in f.get("comodidades", "").split(","):
        c = c.strip()[:40]
        if c and c.lower() not in [x.lower() for x in comodidades]:
            comodidades.append(c)

    campos = {
        "titulo": titulo, "descricao": descricao,
        "finalidade": finalidade, "categoria": categoria, "tipo": tipo, "status": status,
        "destaque": bool(f.get("destaque")),
        "precos": precos, "ocultar_preco": ocultar, "areas": areas,
        "quartos": quartos, "suites": suites, "banheiros": banheiros, "vagas": vagas,
        "local_publico": {
            "bairro": bairro, "cidade": cidade, "estado": estado,
            # a coordenada pública é sempre a exata arredondada (~1 km)
            "lat_aprox": round(lat, 2) if lat is not None else None,
            "lng_aprox": round(lng, 2) if lng is not None else None,
        },
        "condominio_id": _oid(f.get("condominio_id"), "condominios"),
        "comodidades": comodidades,
        "midia": {"fotos": fotos, "video_url": video, "tour_url": tour},
    }
    return campos, endereco, erros


def to_form(imovel, endereco):
    """Converte um imóvel do banco em dict plano para pré-preencher o formulário."""
    i, e = imovel, endereco or {}
    p, a, m = i.get("precos", {}), i.get("areas", {}), i.get("midia", {})
    fin = i.get("finalidade", [])
    v = lambda x: "" if x is None else x
    return {
        "titulo": i["titulo"], "descricao": i["descricao"], "categoria": i["categoria"], "tipo": i["tipo"],
        "status": i["status"], "destaque": i.get("destaque"), "ocultar_preco": i.get("ocultar_preco"),
        "finalidade_venda": "venda" in fin, "finalidade_locacao": "locacao" in fin,
        "preco_venda": v(p.get("venda")), "preco_locacao": v(p.get("locacao")),
        "condominio_valor": v(p.get("condominio")), "iptu": v(p.get("iptu")),
        "area_util": v(a.get("util")), "area_total": v(a.get("total")), "area_terreno": v(a.get("terreno")),
        "quartos": i.get("quartos", 0), "suites": i.get("suites", 0), "banheiros": i.get("banheiros", 0), "vagas": i.get("vagas", 0),
        "bairro": i["local_publico"]["bairro"], "cidade": i["local_publico"]["cidade"], "estado": i["local_publico"]["estado"],
        "logradouro": v(e.get("logradouro")), "numero": v(e.get("numero")), "complemento": v(e.get("complemento")),
        "bloco": v(e.get("bloco")), "cep": v(e.get("cep")), "lat": v(e.get("lat")), "lng": v(e.get("lng")),
        "condominio_id": str(i["condominio_id"]) if i.get("condominio_id") else "",
        "corretor_id": str(i["corretor_id"]) if i.get("corretor_id") else "",
        "comodidades": ", ".join(i.get("comodidades", [])),
        "fotos": "\n".join(f"{x['arquivo']} | {x.get('legenda', '')}" for x in m.get("fotos", [])),
        "video_url": v(m.get("video_url")), "tour_url": v(m.get("tour_url")),
    }
