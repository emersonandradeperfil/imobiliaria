# Imobiliária alto padrão (protótipo)

Flask + MongoDB Atlas. Templates Jinja2, HTML/CSS/JS puro.

## Rodar localmente
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # edite MONGO_URI e SECRET_KEY (COOKIE_SECURE=0 em http local)
python seed.py --reset          # dados fictícios + 3 logins de teste
flask --app app run --debug
```
Logins de teste (senha `Trocar#12345`): `admin@exemplo.com`, `corretor@exemplo.com`, `cliente@exemplo.com`.
**Nunca rode o seed em produção.**

## Testes
```bash
pip install -r requirements-dev.txt
sh tests/run_all.sh
```

## Fotos
- Imóveis: `static/img/imoveis/<codigo-minusculo>/01.webp` (ex.: `ap0001/01.webp`).
- Condomínios: `static/img/condominios/<pasta>/01.webp`.
- Faça commit/push dos arquivos **antes** de listar os nomes no painel. Sem arquivo, aparece um placeholder.

## Deploy no Render (Web Service ligado ao GitHub)
- Build: `pip install -r requirements.txt` · Start: `gunicorn "app:create_app()"`
- Variáveis: `MONGO_URI`, `MONGO_DB`, `SECRET_KEY` (longa e aleatória), `COOKIE_SECURE=1`, `TRUST_PROXY=1`, `BASE_URL=https://seu-site.onrender.com`
- Atlas > Network Access: liberar `0.0.0.0/0` (IPs do Render free são dinâmicos) e usar usuário do banco com senha forte.
- Crie o primeiro admin com `python criar_admin.py seu@email.com "Seu Nome"` (pede a senha no terminal e usa o `MONGO_URI` do `.env`). **Não crie usuários à mão no Atlas**: o hash da senha precisa estar no formato certo. Depois convide a equipe pelo painel.

## E-mail (opcional)
Preencha `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` (e `NOTIFY_EMAIL` para avisos de novos contatos).
Sem SMTP, nada quebra: os e-mails (inclusive links de senha) só aparecem no **log do servidor**, e o admin vê o link na tela ao convidar alguém.
Envia: link de redefinição/convite, aviso de nova visita ao corretor, confirmação/recusa ao cliente, aviso de novo contato à equipe.

## O que tem no painel (`/admin`)
| Tela | Quem acessa |
|---|---|
| Imóveis (CRUD, status, busca) | admin (todos) · corretor (só os seus) |
| Agendamentos (confirmar, recusar com motivo, histórico) | admin · corretor (só os seus) |
| Leads (status, notas, excluir) | admin · corretor (excluir só admin) |
| Condomínios (CRUD) | admin |
| Usuários (convidar, papel, ativar/desativar, excluir) | admin |

## Segurança, em resumo
- Endereço e coordenada exata ficam em `imoveis_enderecos` e só são lidos com usuário logado; o mapa público é só um círculo de ~800 m.
- Senhas com hash (scrypt), CSRF em todos os formulários, sessões invalidadas ao trocar senha/desativar conta.
- Login: 5 erros por e-mail ou 30 por IP bloqueiam por 15 min. Redefinição de senha: token de uso único, 60 min, guardado só como hash.
- Admin não consegue se auto-excluir/rebaixar, e sempre sobra ao menos um admin ativo.
- LGPD: aceite versionado, página «Minha conta» com exportação dos dados e exclusão da conta; admin exclui leads e usuários.

## Limitações conhecidas (para a versão oficial)
- Fotos no repositório: ok para validação; em produção use storage externo (Cloudinary, S3...).
- Não há CSP (Content-Security-Policy) nem captcha nos formulários públicos.
- O mapa usa tiles do OpenStreetMap (uso leve); em produção, use um provedor de mapas contratado.
- A política de privacidade é um texto placeholder e precisa de revisão jurídica.
