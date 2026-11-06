"""Validação do formulário de condomínio (painel admin)."""
from imovel_form import FOTO_RE


def parse(f):
    erros = []
    t = lambda k, n: f.get(k, "").strip()[:n]

    nome = t("nome", 120)
    if len(nome) < 3:
        erros.append("Informe o nome do condomínio.")
    bairro, cidade, estado = t("bairro", 80), t("cidade", 80), t("estado", 2).upper()
    if not bairro or not cidade or len(estado) != 2:
        erros.append("Informe bairro, cidade e UF (2 letras).")

    fotos = []
    for linha in f.get("fotos", "").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        arquivo, _, legenda = (p.strip() for p in linha.partition("|"))
        if not FOTO_RE.match(arquivo):
            erros.append(f"Foto inválida: «{arquivo[:60]}». Ex.: villa-aurora/01.webp (minúsculas, sem espaços).")
            continue
        fotos.append({"arquivo": arquivo, "legenda": legenda[:80], "ordem": len(fotos) + 1})
    if len(fotos) > 30:
        erros.append("Máximo de 30 fotos.")

    video = t("video_url", 300) or None
    if video and not video.startswith(("https://", "http://")):
        erros.append("O link do vídeo deve começar com http:// ou https://.")
    tour = t("tour_url", 300) or None
    if tour and not tour.startswith("https://"):
        erros.append("O link do tour virtual deve começar com https://.")

    comodidades = []
    for c in f.get("comodidades", "").split(","):
        c = c.strip()[:40]
        if c and c.lower() not in [x.lower() for x in comodidades]:
            comodidades.append(c)

    campos = {
        "nome": nome, "descricao": t("descricao", 5000), "bairro": bairro, "cidade": cidade, "estado": estado,
        "comodidades": comodidades, "fotos": fotos, "video_url": video, "tour_url": tour,
        "administrado_pela_imobiliaria": bool(f.get("administrado_pela_imobiliaria")),
        "ativo": bool(f.get("ativo")),
    }
    return campos, erros


def to_form(c):
    return {
        "nome": c["nome"], "descricao": c.get("descricao", ""), "bairro": c["bairro"], "cidade": c["cidade"], "estado": c["estado"],
        "comodidades": ", ".join(c.get("comodidades", [])),
        "fotos": "\n".join(f"{x['arquivo']} | {x.get('legenda', '')}" for x in c.get("fotos", [])),
        "video_url": c.get("video_url") or "", "tour_url": c.get("tour_url") or "",
        "administrado_pela_imobiliaria": c.get("administrado_pela_imobiliaria"), "ativo": c.get("ativo", True),
    }
