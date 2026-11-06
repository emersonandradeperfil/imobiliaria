# Modelo de dados MongoDB: Protótipo Imobiliária Alto Padrão

Banco: `imobiliaria` (Atlas Free M0) · Driver: PyMongo · Back-end: Flask

## Visão geral das coleções

| Coleção | Para que serve |
|---|---|
| `users` | Clientes, corretores e admins (login) |
| `imoveis` | Dados **públicos** do imóvel (o que o visitante deslogado vê) |
| `imoveis_enderecos` | Dados **privados** de localização (só logado) |
| `condominios` | Condomínios (vitrine e administração predial) |
| `agendamentos` | Visitas agendadas |
| `leads` | Contato, "Cadastre seu imóvel" e "Administração de condomínio" |

> **Por que o endereço fica em coleção separada?**
> Se o endereço morasse dentro de `imoveis`, qualquer rota/consulta que esquecesse de filtrar o campo vazaria o dado. Separado, a listagem e a página pública **nunca tocam** em `imoveis_enderecos`. Só a rota protegida por login faz essa consulta.

---

## `users`

```json
{
  "_id": "ObjectId",
  "nome": "Maria Souza",
  "email": "maria@email.com",
  "senha_hash": "$2b$12$...",
  "telefone": "+5511999999999",
  "documento": "000.000.000-00",
  "papel": "cliente",
  "ativo": true,
  "favoritos": ["ObjectId (imoveis)"],
  "lgpd": {
    "aceite_em": "2026-11-06T12:00:00Z",
    "versao_politica": "1.0"
  },
  "criado_em": "2026-11-06T12:00:00Z",
  "ultimo_login": "2026-11-06T12:00:00Z"
}
```

- `papel`: `cliente` | `corretor` | `admin`
- `senha_hash`: use bcrypt ou argon2, **nunca** a senha em texto.
- `documento`: usado para a segurança do corretor na visita. Colete só se a cliente realmente exigir (LGPD: minimização).
- Índice único: `email`.

---

## `imoveis` (público)

```json
{
  "_id": "ObjectId",
  "codigo": "AP0001",
  "slug": "apartamento-4-suites-vila-nova-conceicao-ap0001",
  "titulo": "Apartamento 4 suítes na Vila Nova Conceição",
  "descricao": "Texto longo...",

  "finalidade": ["venda", "locacao"],
  "categoria": "residencial",
  "tipo": "apartamento",
  "status": "ativo",
  "destaque": true,

  "precos": {
    "venda": 4500000,
    "locacao": 18000,
    "condominio": 3200,
    "iptu": 1500
  },
  "ocultar_preco": false,

  "areas": { "util": 320, "total": 360, "terreno": null },
  "quartos": 4,
  "suites": 4,
  "banheiros": 6,
  "vagas": 4,

  "local_publico": {
    "bairro": "Vila Nova Conceição",
    "cidade": "São Paulo",
    "estado": "SP",
    "lat_aprox": -23.59,
    "lng_aprox": -46.67
  },

  "condominio_id": "ObjectId (condominios)",
  "corretor_id": "ObjectId (users)",

  "comodidades": ["piscina", "academia", "salão de festas", "segurança 24h"],

  "midia": {
    "fotos": [
      { "arquivo": "ap0001/01-sala.webp", "legenda": "Sala", "ordem": 1, "capa": true },
      { "arquivo": "ap0001/02-suite.webp", "legenda": "Suíte master", "ordem": 2, "capa": false }
    ],
    "video_url": "https://youtu.be/xxxx",
    "tour_url": "https://my.matterport.com/show/?m=xxxx"
  },

  "criado_em": "2026-11-06T12:00:00Z",
  "atualizado_em": "2026-11-06T12:00:00Z"
}
```

- `status`: `ativo` | `reservado` | `vendido` | `alugado` | `inativo`
- `categoria`: `residencial` | `comercial`
- `tipo`: `apartamento`, `casa`, `cobertura`, `casa_condominio`, `conjunto_comercial`, `sala_comercial`, `loja`, `galpao`...
- `lat_aprox` / `lng_aprox`: coordenada **arredondada** (2 casas) para mostrar só a região no mapa.
- `fotos[].arquivo`: caminho dentro de `static/img/imoveis/` (protótipo). Depois, vira URL de storage externo sem mudar a estrutura.
- Índices: `codigo` (único), `slug` (único), `{status, finalidade, categoria}`, `local_publico.bairro`, `precos.venda`, `precos.locacao`.

---

## `imoveis_enderecos` (privado, só logado)

```json
{
  "_id": "ObjectId",
  "imovel_id": "ObjectId (imoveis)",
  "logradouro": "Avenida Exemplo",
  "numero": "320",
  "complemento": "Apto 142",
  "bloco": "A",
  "cep": "04000-000",
  "lat": -23.5912345,
  "lng": -46.6712345
}
```

- Índice único: `imovel_id`.

---

## `condominios`

```json
{
  "_id": "ObjectId",
  "nome": "Residencial Exemplo",
  "slug": "residencial-exemplo",
  "descricao": "Texto...",
  "bairro": "Vila Nova Conceição",
  "cidade": "São Paulo",
  "estado": "SP",
  "comodidades": ["piscina", "quadra"],
  "fotos": [{ "arquivo": "condominios/exemplo/01.webp", "ordem": 1 }],
  "video_url": null,
  "tour_url": null,
  "administrado_pela_imobiliaria": true,
  "criado_em": "2026-11-06T12:00:00Z"
}
```

- O endereço exato do condomínio também deve ser tratado como privado se identificar o imóvel. Mostrar só bairro para deslogado.

---

## `agendamentos`

```json
{
  "_id": "ObjectId",
  "imovel_id": "ObjectId (imoveis)",
  "usuario_id": "ObjectId (users)",
  "corretor_id": "ObjectId (users)",
  "data_hora": "2026-11-20T14:00:00Z",
  "status": "pendente",
  "observacoes": "Vou acompanhado da esposa",
  "visitante_snapshot": {
    "nome": "Maria Souza",
    "telefone": "+5511999999999",
    "documento": "000.000.000-00"
  },
  "criado_em": "2026-11-06T12:00:00Z"
}
```

- `status`: `pendente` | `confirmado` | `realizado` | `cancelado`
- `visitante_snapshot`: cópia dos dados no momento do agendamento, para o corretor ter o registro mesmo que o usuário edite o perfil depois.
- Índice: `{imovel_id, data_hora}` (evita conflito de horário) e `usuario_id`.

---

## `leads`

```json
{
  "_id": "ObjectId",
  "tipo": "cadastre_imovel",
  "nome": "João Lima",
  "email": "joao@email.com",
  "telefone": "+5511988888888",
  "mensagem": "Tenho uma cobertura para vender",
  "dados": {
    "tipo_imovel": "cobertura",
    "bairro": "Jardim Europa",
    "finalidade": "venda"
  },
  "status": "novo",
  "lgpd": { "aceite_em": "2026-11-06T12:00:00Z", "versao_politica": "1.0" },
  "criado_em": "2026-11-06T12:00:00Z"
}
```

- `tipo`: `contato` | `cadastre_imovel` | `adm_condominio`
- `dados`: campo livre, muda conforme o tipo (por isso Mongo cai bem aqui). Em `adm_condominio`, por exemplo: `nome_condominio`, `qtd_unidades`, `cidade`.
- `status`: `novo` | `em_contato` | `concluido`

---

## Mapa: página → coleção

| Página | Lê/escreve |
|---|---|
| Home, listagem | `imoveis` |
| Detalhe (deslogado) | `imoveis`, `condominios` |
| Detalhe (logado) | + `imoveis_enderecos` |
| Agendar visita | `agendamentos` (+ `users`) |
| Favoritos | `users.favoritos` |
| Contato / Cadastre seu imóvel / Adm. condomínio | `leads` |
| Painel admin | todas |

## Cuidados no Atlas + Render

- A string de conexão vai em **variável de ambiente** no Render (`MONGO_URI`). **Nunca** commite no GitHub.
- No Atlas, em *Network Access*, o Render free usa IPs dinâmicos, então será preciso liberar `0.0.0.0/0`. Isso é aceitável em protótipo, desde que o usuário do banco tenha senha forte e permissão mínima.
- Fotos no repositório: mantenha WebP leve (idealmente < 200 KB cada), porque o repositório cresce rápido com imóveis de alto padrão (30+ fotos cada).
- Upload de fotos pelo painel **não persiste** no disco do Render free. No protótipo, você coloca as fotos na pasta, faz push e informa o nome do arquivo no cadastro.
