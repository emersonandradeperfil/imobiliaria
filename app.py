import os
import random
import string
import html
import unicodedata
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from database import init_db, mongo
import bcrypt
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from functools import wraps
from werkzeug.utils import secure_filename
from bson.objectid import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError
import requests
from dotenv import load_dotenv
import re
import cloudinary
import cloudinary.uploader

# Carrega as variáveis de ambiente do arquivo .env local
load_dotenv()

app = Flask(__name__)

# Fuso horário padrão do Brasil (Brasília)
BR_TZ = ZoneInfo("America/Sao_Paulo")

# Limite máximo de upload (ex.: 15 MB por requisição)
app.config['MAX_CONTENT_LENGTH'] = 15 * 1024 * 1024

# SECRET_KEY
secret_key_env = os.getenv("SECRET_KEY")
if not secret_key_env:
    app.secret_key = "123456-trocar-em-producao"
else:
    app.secret_key = secret_key_env

init_db(app)

# Configuração da pasta de uploads de imóveis (usada no modo 'local' ou como fallback)
UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'upload')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Configuração do Cloudinary + chave de alternância ('cloudinary' | 'local')
STORAGE_MODE = os.getenv("STORAGE_MODE", "cloudinary").strip().lower()
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "").strip()
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "").strip()

CLOUDINARY_CONFIGURADO = bool(
    CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET
)

if CLOUDINARY_CONFIGURADO:
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD_NAME,
        api_key=CLOUDINARY_API_KEY,
        api_secret=CLOUDINARY_API_SECRET,
        secure=True,
    )

# --- FUNÇÕES AUXILIARES DE SEGURANÇA E INTEGRAÇÃO ---
def sanitizar_texto(texto):
    if not texto:
        return ""
    return html.escape(str(texto).strip())

def oid_seguro(valor_id):
    if not valor_id:
        return None
    try:
        return ObjectId(str(valor_id).strip())
    except (InvalidId, TypeError):
        return None

def gerar_slug_base(texto, fallback="item"):
    texto_norm = unicodedata.normalize("NFKD", str(texto or "").strip().lower())
    texto_sem_acento = "".join(c for c in texto_norm if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "-", texto_sem_acento).strip("-")
    return slug or fallback

def gerar_slug_unico_condominio(db, nome_limpo):
    base_slug = gerar_slug_base(nome_limpo, fallback="condominio")
    slug_candidato = base_slug
    contador = 2
    while db.condominios.find_one({"slug": slug_candidato}):
        slug_candidato = f"{base_slug}-{contador}"
        contador += 1
    return slug_candidato

def enviar_email_mailgun(para_email, assunto, corpo_texto):
    api_key = os.getenv('MAILGUN_API_KEY')
    domain = os.getenv('MAILGUN_DOMAIN')
    if not api_key or not domain or not para_email:
        return False
    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{domain}/messages",
            auth=("api", api_key),
            data={
                "from": f"Teca Borges Imóveis <postmaster@{domain}>",
                "to": [para_email],
                "subject": assunto,
                "text": corpo_texto
            },
            timeout=5
        )
        return 200 <= resp.status_code < 300
    except Exception as e:
        print(f"Erro ao enviar e-mail via Mailgun: {e}")
        return False

def resolver_condominio(nome_raw):
    """Busca ou cria o condomínio pelo nome e retorna (condominio_id, condominio_nome)."""
    nome_limpo = sanitizar_texto(nome_raw)
    if not nome_limpo:
        return None, ""
    db = mongo.db
    existente = db.condominios.find_one({
        "nome": {"$regex": f"^{re.escape(nome_limpo)}$", "$options": "i"}
    })
    if existente:
        if not existente.get("slug"):
            slug_atualizado = gerar_slug_unico_condominio(db, existente.get("nome", nome_limpo))
            db.condominios.update_one({"_id": existente["_id"]}, {"$set": {"slug": slug_atualizado}})
        return existente["_id"], existente.get("nome", nome_limpo)

    slug_cond = gerar_slug_unico_condominio(db, nome_limpo)
    try:
        res = db.condominios.insert_one({
            "nome": nome_limpo,
            "slug": slug_cond,
            "criado_em": datetime.now(BR_TZ)
        })
        return res.inserted_id, nome_limpo
    except DuplicateKeyError:
        existente_apos_conflito = db.condominios.find_one({
            "nome": {"$regex": f"^{re.escape(nome_limpo)}$", "$options": "i"}
        })
        if existente_apos_conflito:
            return existente_apos_conflito["_id"], existente_apos_conflito.get("nome", nome_limpo)
        slug_retry = f"{slug_cond}-{random.randint(10, 99)}"
        res = db.condominios.insert_one({
            "nome": nome_limpo,
            "slug": slug_retry,
            "criado_em": datetime.now(BR_TZ)
        })
        return res.inserted_id, nome_limpo

def excluir_dados_usuario_lgpd(user_doc):
    """Remove definitivamente o usuário e seus dados pessoais vinculados (LGPD), preservando imóveis."""
    db = mongo.db
    uid = user_doc["_id"]
    email = user_doc.get("email")

    if 'agendamentos' in db.list_collection_names():
        db.agendamentos.delete_many({"cliente_id": uid})
        db.agendamentos.update_many(
            {"corretor_responsavel_id": uid},
            {"$set": {"corretor_responsavel_id": None}}
        )

    if 'leads' in db.list_collection_names():
        if email:
            db.leads.delete_many({"email": email})
        db.leads.update_many(
            {"corretor_responsavel_id": uid},
            {"$set": {"corretor_responsavel_id": None}}
        )

    if email:
        if 'otps' in db.list_collection_names():
            db.otps.delete_many({"email": email})
        if 'login_tentativas' in db.list_collection_names():
            db.login_tentativas.delete_many({"email": email})

    db.imoveis.update_many({"proprietario_id": uid}, {"$set": {"proprietario_id": None}})
    db.imoveis.update_many({"criado_por": uid}, {"$set": {"criado_por": None}})

    db.users.delete_one({"_id": uid})

MAX_TENTATIVAS_LOGIN = 5
BLOQUEIO_LOGIN_MINUTOS = 15
MAX_TENTATIVAS_OTP = 5
EXPIRACAO_OTP_MINUTOS = 10

def _obter_chave_tentativa_login(email):
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown').split(',')[0].strip()
    return f"{email.lower()}|{ip}"

# --- DECORATORS DE SEGURANÇA ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Faça login para acessar esta página.', 'warning')
            return redirect(url_for('login', next=request.path))
        
        uid = oid_seguro(session['user_id'])
        if not uid:
            session.clear()
            return redirect(url_for('login'))

        user_existe = mongo.db.users.find_one({"_id": uid, "ativo": {"$ne": False}})
        if not user_existe:
            session.clear()
            flash('Sua conta foi desativada ou removida. Faça login novamente.', 'danger')
            return redirect(url_for('login'))
            
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('papel') != 'admin':
            flash('Acesso restrito a administradores.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def corretor_ou_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('papel') not in ['admin', 'corretor']:
            flash('Acesso restrito a administradores e corretores.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def proprietario_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('papel') not in ['proprietario', 'parceiro']:
            flash('Acesso restrito a proprietários e parceiros.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def gerar_proximo_codigo():
    ultimo_imovel = mongo.db.imoveis.find_one({}, sort=[("criado_em", -1)])
    if ultimo_imovel and "codigo" in ultimo_imovel:
        try:
            prefixo = ultimo_imovel["codigo"][:2]
            numero = int(ultimo_imovel["codigo"][2:]) + 1
            return f"{prefixo}{numero:04d}"
        except ValueError:
            pass
    return "AP0001"

def gerar_codigo_proprietario(papel="proprietario"):
    prefixo = "PA" if papel == "parceiro" else "PR"
    ultimo_prop = mongo.db.users.find_one({"papel": papel}, sort=[("criado_em", -1)])
    if ultimo_prop and "codigo" in ultimo_prop:
        try:
            numero = int(ultimo_prop["codigo"][2:]) + 1
            return f"{prefixo}{numero:04d}"
        except ValueError:
            pass
    return f"{prefixo}0001"

# --- FUNÇÕES AUXILIARES DE ARMAZENAMENTO DE FOTOS (CLOUDINARY + FALLBACK LOCAL) ---
def _salvar_arquivo_local(file_storage, codigo, cat, ordem, extensao, pasta_imovel):
    os.makedirs(pasta_imovel, exist_ok=True)
    nome_arquivo = secure_filename(f"{codigo}_{cat}_{ordem}{extensao}")
    caminho_completo = os.path.join(pasta_imovel, nome_arquivo)
    file_storage.seek(0)
    file_storage.save(caminho_completo)
    return f"upload/{codigo}/{nome_arquivo}"

def _excluir_recurso_foto(foto_dict):
    if not isinstance(foto_dict, dict):
        return

    public_id = foto_dict.get("public_id")
    if public_id and CLOUDINARY_CONFIGURADO:
        try:
            cloudinary.uploader.destroy(public_id, resource_type="image")
        except Exception as e:
            print(f"Erro ao remover foto '{public_id}' no Cloudinary: {e}")

    arquivo_rel = foto_dict.get("arquivo")
    if arquivo_rel and not str(arquivo_rel).endswith("/default.jpg") and arquivo_rel != "upload/default.jpg":
        caminho_fisico = os.path.join(app.root_path, 'static', str(arquivo_rel).replace("/", os.sep))
        if os.path.isfile(caminho_fisico):
            try:
                os.remove(caminho_fisico)
            except Exception as e:
                print(f"Erro ao deletar arquivo físico: {e}")

# --- FUNÇÃO PARA PROCESSAR UPLOADS DINÂMICOS DE FOTOS ---
def processar_upload_fotos_dinamicas(request_files, request_form, codigo, pasta_imovel, fotos_existentes=None):
    lista_fotos = list(fotos_existentes) if fotos_existentes else []
    contador_ordem = max([f.get("ordem", 0) for f in lista_fotos], default=0) + 1
    extensoes_permitidas = {".jpg", ".jpeg", ".png", ".webp"}
    usar_cloudinary = (STORAGE_MODE == "cloudinary") and CLOUDINARY_CONFIGURADO

    for key in request_files:
        if key.startswith("fotos_"):
            idx = key.split("_")[1]
            cat_select = request_form.get(f"cat_{idx}")
            
            if cat_select == "personalizado":
                custom_name = request_form.get(f"custom_cat_{idx}", "").strip()
                cat = custom_name.lower().replace(" ", "_") if custom_name else "outro"
                legenda = custom_name or "Outro"
            else:
                cat = cat_select if cat_select else "outros"
                legenda = cat.capitalize()
            
            arquivos = request_files.getlist(key)
            for file in arquivos:
                if file and file.filename != '':
                    extensao = os.path.splitext(file.filename)[1].lower()
                    if extensao not in extensoes_permitidas:
                        continue

                    is_capa = True if (cat == 'capa' and not any(f.get('capa') for f in lista_fotos)) else False
                    foto_salva = None

                    if usar_cloudinary:
                        try:
                            file.seek(0)
                            res_cloud = cloudinary.uploader.upload(
                                file,
                                folder=f"teca_borges/imoveis/{codigo}",
                                resource_type="image",
                            )
                            foto_salva = {
                                "url": res_cloud.get("secure_url"),
                                "public_id": res_cloud.get("public_id"),
                                "arquivo": None,
                                "storage": "cloudinary",
                                "categoria": cat,
                                "legenda": legenda,
                                "ordem": contador_ordem,
                                "capa": is_capa
                            }
                        except Exception as e:
                            print(f"Falha no upload para Cloudinary (usando fallback local): {e}")

                    if not foto_salva:
                        caminho_rel = _salvar_arquivo_local(file, codigo, cat, contador_ordem, extensao, pasta_imovel)
                        foto_salva = {
                            "url": None,
                            "public_id": None,
                            "arquivo": caminho_rel,
                            "storage": "local",
                            "categoria": cat,
                            "legenda": legenda,
                            "ordem": contador_ordem,
                            "capa": is_capa
                        }

                    lista_fotos.append(foto_salva)
                    contador_ordem += 1
                    
    if not lista_fotos:
        lista_fotos.append({
            "url": None,
            "public_id": None,
            "arquivo": f"upload/{codigo}/default.jpg",
            "storage": "local",
            "categoria": "capa",
            "legenda": "Capa",
            "ordem": 1,
            "capa": True
        })
        
    return lista_fotos

@app.route('/ping')
def ping():
    return "OK", 200

# --- ROTAS PÚBLICAS E CLIENTE ---

@app.route('/')
def index():
    db = mongo.db
    imoveis_ativos = list(db.imoveis.find({"status": "ativo", "destaque": True}).sort("criado_em", -1))
    
    secoes = {
        "Apartamentos": [i for i in imoveis_ativos if i.get('tipo') == 'apartamento'],
        "Coberturas": [i for i in imoveis_ativos if i.get('tipo') == 'cobertura'],
        "Casas de Condomínio": [i for i in imoveis_ativos if i.get('tipo') == 'casa'],
        "Conjuntos Comerciais": [i for i in imoveis_ativos if i.get('tipo') == 'comercial']
    }
    
    favoritos_ids = []
    uid = oid_seguro(session.get('user_id'))
    if uid:
        user = db.users.find_one({"_id": uid})
        if user and 'favoritos' in user:
            favoritos_ids = [str(fav_id) for fav_id in user['favoritos']]
    
    return render_template('index.html', secoes=secoes, favoritos_ids=favoritos_ids)

@app.route('/cadastrar')
def cadastrar_cliente():
    return render_template('cadastrar.html')

@app.route('/imovel/<slug>')
def imovel_detalhe(slug):
    db = mongo.db
    imovel = db.imoveis.find_one({"slug": slug, "status": "ativo"})
    if not imovel:
        return "Imóvel não encontrado", 404
    
    condominio = db.condominios.find_one({"_id": imovel.get("condominio_id")})
    
    bairro_atual = (imovel.get("local_publico") or {}).get("bairro", "").strip()
    imoveis_destaque = []
    ids_excluidos = [imovel["_id"]]

    if bairro_atual:
        mesmo_bairro = list(
            db.imoveis.find({
                "status": "ativo",
                "_id": {"$nin": ids_excluidos},
                "local_publico.bairro": {"$regex": f"^{re.escape(bairro_atual)}$", "$options": "i"}
            }).sort("criado_em", -1).limit(5)
        )
        imoveis_destaque.extend(mesmo_bairro)
        ids_excluidos.extend([i["_id"] for i in mesmo_bairro])

    if len(imoveis_destaque) < 5:
        faltam = 5 - len(imoveis_destaque)
        extras_home = list(
            db.imoveis.find({
                "status": "ativo",
                "destaque": True,
                "_id": {"$nin": ids_excluidos}
            }).sort("criado_em", -1).limit(faltam)
        )
        imoveis_destaque.extend(extras_home)
    
    endereco_privado = None
    uid = oid_seguro(session.get('user_id'))
    if uid:
        user_check = db.users.find_one({"_id": uid, "ativo": {"$ne": False}})
        if user_check:
            endereco_privado = db.imoveis_enderecos.find_one({"imovel_id": imovel["_id"]})
        else:
            session.clear()
        
    return render_template(
        'imovel_detalhe.html', 
        imovel=imovel, 
        condominio=condominio, 
        imoveis_destaque=imoveis_destaque,
        endereco_privado=endereco_privado,
        today=datetime.now(BR_TZ).date().isoformat()
    )

@app.route('/imovel/<slug>/galeria')
def imovel_galeria(slug):
    db = mongo.db
    imovel = db.imoveis.find_one({"slug": slug, "status": "ativo"})
    if not imovel:
        return "Imóvel não encontrado", 404

    if 'user_id' not in session:
        flash('Faça login ou libere seu acesso na página do imóvel para ver a galeria completa.', 'warning')
        return redirect(url_for('imovel_detalhe', slug=slug))

    uid = oid_seguro(session.get('user_id'))
    user_check = db.users.find_one({"_id": uid, "ativo": {"$ne": False}}) if uid else None
    if not user_check:
        session.clear()
        return redirect(url_for('imovel_detalhe', slug=slug))

    aba_inicial = request.args.get('aba', 'fotos')
    return render_template('imovel_galeria.html', imovel=imovel, aba_inicial=aba_inicial)

# --- OTP PERSISTIDO NO MONGODB COM EXPIRAÇÃO E LIMITE DE TENTATIVAS ---
def _salvar_otp(email, tipo, extra_fields=None):
    codigo = str(random.randint(1000, 9999))
    agora = datetime.now(BR_TZ)
    doc = {
        "codigo": codigo,
        "tipo": tipo,
        "tentativas": 0,
        "expira_em": agora + timedelta(minutes=EXPIRACAO_OTP_MINUTOS),
        "criado_em": agora
    }
    if extra_fields:
        doc.update(extra_fields)
    mongo.db.otps.update_one({"email": email}, {"$set": doc}, upsert=True)
    return codigo

def _validar_otp(email, tipo, codigo_informado):
    registro = mongo.db.otps.find_one({"email": email, "tipo": tipo})
    if not registro:
        return None, "Código incorreto ou expirado!"

    agora = datetime.now(BR_TZ)
    expira_em = registro.get("expira_em")
    if expira_em:
        if expira_em.tzinfo is None:
            expira_em = expira_em.replace(tzinfo=BR_TZ)
        if agora > expira_em:
            mongo.db.otps.delete_one({"_id": registro["_id"]})
            return None, "Código expirado! Solicite um novo código."

    tentativas = registro.get("tentativas", 0)
    if tentativas >= MAX_TENTATIVAS_OTP:
        mongo.db.otps.delete_one({"_id": registro["_id"]})
        return None, "Limite de tentativas excedido! Solicite um novo código."

    if str(codigo_informado or "").strip() != str(registro.get("codigo")):
        mongo.db.otps.update_one({"_id": registro["_id"]}, {"$inc": {"tentativas": 1}})
        restantes = max(0, MAX_TENTATIVAS_OTP - (tentativas + 1))
        if restantes == 0:
            mongo.db.otps.delete_one({"_id": registro["_id"]})
            return None, "Código incorreto. Limite de tentativas atingido; solicite um novo código."
        return None, f"Código incorreto! Restam {restantes} tentativa(s)."

    return registro, None

@app.route('/api/enviar-otp-imovel', methods=['POST'])
def enviar_otp_imovel():
    dados = request.json or {}
    email = sanitizar_texto(dados.get('email'))
    nome = sanitizar_texto(dados.get('nome'))
    whatsapp = sanitizar_texto(dados.get('whatsapp'))
    imoid = dados.get('imovel_id')
    
    if not email:
        return jsonify({"status": "error", "message": "E-mail obrigatório."}), 400
        
    if mongo.db.users.find_one({"email": email}):
        return jsonify({"status": "error", "message": "Este e-mail já está cadastrado no sistema. Faça login para continuar."}), 400
        
    codigo = _salvar_otp(email, "imovel", {"nome": nome, "whatsapp": whatsapp, "imovel_id": imoid})
    enviar_email_mailgun(
        email,
        "Teca Borges - Código de verificação para ver imóvel",
        f"""Olá {nome}!

Seu código de verificação é: {codigo} (válido por {EXPIRACAO_OTP_MINUTOS} minutos).

Sua senha provisória de acesso é: 123456

Você pode alterá-la a qualquer momento acessando o seu painel de perfil no site."""
    )
    return jsonify({"status": "success"})

@app.route('/api/verificar-otp-e-liberar-imovel', methods=['POST'])
def verificar_otp_e_liberar_imovel():
    dados = request.json or {}
    email = sanitizar_texto(dados.get('email'))
    codigo_informado = dados.get('codigo')
    
    registro, erro = _validar_otp(email, "imovel", codigo_informado)
    if erro:
        return jsonify({"status": "error", "message": erro}), 400

    db = mongo.db
    nome = registro["nome"]
    whatsapp = registro["whatsapp"]
    imoid = registro["imovel_id"]
    imovel_oid = oid_seguro(imoid)
    
    user = db.users.find_one({"email": email})
    if not user:
        senha_temp = bcrypt.hashpw("123456".encode('utf-8'), bcrypt.gensalt())
        res_user = db.users.insert_one({
            "nome": nome,
            "email": email,
            "senha_hash": senha_temp,
            "telefone": whatsapp,
            "papel": "cliente",
            "ativo": True,
            "favoritos": [],
            "criado_em": datetime.now(BR_TZ)
        })
        user_id = res_user.inserted_id
    else:
        user_id = user["_id"]
        db.users.update_one({"_id": user_id}, {"$set": {"nome": nome, "telefone": whatsapp, "ativo": True}})

    if imovel_oid:
        db.leads.insert_one({
            "nome": nome,
            "email": email,
            "telefone": whatsapp,
            "imovel_id": imovel_oid,
            "origem": "Liberação Dados Imóvel (OTP)",
            "criado_em": datetime.now(BR_TZ)
        })
    
    session['user_id'] = str(user_id)
    session['user_nome'] = nome
    session['user_whatsapp'] = whatsapp
    session['papel'] = "cliente"
    
    db.otps.delete_one({"_id": registro["_id"]})
    
    imovel_doc = db.imoveis.find_one({"_id": imovel_oid}) if imovel_oid else None
    slug_destino = imovel_doc.get("slug") if imovel_doc else ""
    return jsonify({"status": "success", "slug": slug_destino})

# --- BUSCA PERSONALIZADA (USUÁRIO LOGADO DIRETO E VISITANTE VIA OTP) ---
@app.route('/api/salvar-busca-logado', methods=['POST'])
def salvar_busca_logado():
    uid = oid_seguro(session.get('user_id'))
    if not uid:
        return jsonify({"status": "error", "message": "Sessão expirada. Faça login novamente."}), 401

    db = mongo.db
    user = db.users.find_one({"_id": uid, "ativo": {"$ne": False}})
    if not user:
        session.clear()
        return jsonify({"status": "error", "message": "Usuário não encontrado."}), 401

    dados = request.json or {}
    tipo_imovel = sanitizar_texto(dados.get('tipo'))
    bairro = sanitizar_texto(dados.get('bairro'))
    observacoes = sanitizar_texto(dados.get('observacoes'))

    if not tipo_imovel or not bairro:
        return jsonify({"status": "error", "message": "Informe o tipo de imóvel e a região."}), 400

    nome = user.get("nome") or session.get("user_nome") or ""
    email = user.get("email") or ""
    telefone = user.get("telefone") or ""

    lead_data = {
        "cliente_id": user["_id"],
        "nome": nome,
        "email": email,
        "telefone": telefone,
        "whatsapp": telefone,
        "tipo_imovel": tipo_imovel,
        "bairro": bairro,
        "observacoes": observacoes,
        "origem": "Busca Personalizada Site (Usuário Logado)",
        "verificado": True,
        "criado_em": datetime.now(BR_TZ)
    }
    db.leads.insert_one(lead_data)
    return jsonify({"status": "success"})

@app.route('/api/enviar-otp-busca', methods=['POST'])
def enviar_otp_busca():
    dados = request.json or {}
    email = sanitizar_texto(dados.get('email'))
    
    if not email:
        return jsonify({"status": "error", "message": "E-mail obrigatório."}), 400
        
    if mongo.db.users.find_one({"email": email}):
        return jsonify({"status": "error", "message": "Este e-mail já está cadastrado no sistema. Faça login para continuar."}), 400
        
    codigo = _salvar_otp(email, "busca")
    enviar_email_mailgun(
        email,
        "Teca Borges - Código de verificação para sua busca",
        f"""Olá!
Seu código de verificação para busca personalizada é: {codigo} (válido por {EXPIRACAO_OTP_MINUTOS} minutos)."""
    )
    return jsonify({"status": "success"})

@app.route('/api/verificar-otp-e-salvar-busca', methods=['POST'])
def verificar_otp_e_salvar_busca():
    dados = request.json or {}
    email = sanitizar_texto(dados.get('email'))
    codigo_informado = dados.get('codigo')
    
    registro, erro = _validar_otp(email, "busca", codigo_informado)
    if erro:
        return jsonify({"status": "error", "message": erro}), 400

    db = mongo.db
    nome = sanitizar_texto(dados.get('nome'))
    whatsapp = sanitizar_texto(dados.get('whatsapp'))
    
    lead_data = {
        "nome": nome,
        "email": email,
        "telefone": whatsapp,
        "whatsapp": whatsapp,
        "tipo_imovel": sanitizar_texto(dados.get('tipo')),
        "bairro": sanitizar_texto(dados.get('bairro')),
        "observacoes": sanitizar_texto(dados.get('observacoes')),
        "origem": "Busca Personalizada Site (OTP)",
        "verificado": True,
        "criado_em": datetime.now(BR_TZ)
    }
    
    db.leads.insert_one(lead_data)
    
    user = db.users.find_one({"email": email})
    if not user:
        senha_temp = bcrypt.hashpw("123456".encode('utf-8'), bcrypt.gensalt())
        db.users.insert_one({
            "nome": nome,
            "email": email,
            "senha_hash": senha_temp,
            "telefone": whatsapp,
            "papel": "cliente",
            "ativo": True,
            "favoritos": [],
            "criado_em": datetime.now(BR_TZ)
        })
        
    db.otps.delete_one({"_id": registro["_id"]})
    return jsonify({"status": "success"})

# --- OTP PARA CADASTRO DE CLIENTE ---
@app.route('/api/enviar-otp-cadastro', methods=['POST'])
def enviar_otp_cadastro():
    dados = request.json or {}
    email = sanitizar_texto(dados.get('email'))
    
    if not email:
        return jsonify({"status": "error", "message": "E-mail obrigatório."}), 400
        
    if mongo.db.users.find_one({"email": email}):
        return jsonify({"status": "error", "message": "Este e-mail já está cadastrado."}), 400
        
    codigo = _salvar_otp(email, "cadastro", {
        "nome": sanitizar_texto(dados.get('nome')),
        "senha": dados.get('senha'),
        "telefone": sanitizar_texto(dados.get('telefone')),
        "origem_canal": sanitizar_texto(dados.get('origem_canal')) or "Não informado"
    })
    enviar_email_mailgun(
        email,
        "Teca Borges - Confirmação de Cadastro",
        f"""Olá!

Seu código de verificação é: {codigo} (válido por {EXPIRACAO_OTP_MINUTOS} minutos)."""
    )
    return jsonify({"status": "success"})

@app.route('/api/verificar-otp-e-cadastrar', methods=['POST'])
def verificar_otp_e_cadastrar():
    dados = request.json or {}
    email = sanitizar_texto(dados.get('email'))
    codigo_informado = dados.get('codigo')
    
    registro, erro = _validar_otp(email, "cadastro", codigo_informado)
    if erro:
        return jsonify({"status": "error", "message": erro}), 400

    db = mongo.db
    nome = registro["nome"]
    senha = registro["senha"]
    telefone = registro["telefone"]
    origem_canal = sanitizar_texto(registro.get("origem_canal")) or "Não informado"
    
    senha_hash = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt())
    
    db.users.insert_one({
        "nome": nome,
        "email": email,
        "senha_hash": senha_hash,
        "telefone": telefone,
        "origem_canal": origem_canal,
        "papel": "cliente",
        "ativo": True,
        "favoritos": [],
        "criado_em": datetime.now(BR_TZ)
    })
    
    db.otps.delete_one({"_id": registro["_id"]})
    return jsonify({"status": "success"})

def _url_retorno_segura(destino):
    if not destino or not isinstance(destino, str):
        return None
    destino = destino.strip()
    if destino.startswith('/') and not destino.startswith('//'):
        return destino
    return None


@app.route('/login', methods=['GET', 'POST'])
def login():
    proxima_pagina = request.args.get('next') or request.form.get('next')
    if request.method == 'POST':
        email = sanitizar_texto(request.form.get('email'))
        senha = request.form.get('senha') or ""
        chave_tentativa = _obter_chave_tentativa_login(email)
        agora = datetime.now(BR_TZ)

        registro_tentativa = mongo.db.login_tentativas.find_one({"chave": chave_tentativa})
        if registro_tentativa and registro_tentativa.get("bloqueado_ate"):
            bloqueado_ate = registro_tentativa["bloqueado_ate"]
            if bloqueado_ate.tzinfo is None:
                bloqueado_ate = bloqueado_ate.replace(tzinfo=BR_TZ)
            if agora < bloqueado_ate:
                minutos_restantes = max(1, int((bloqueado_ate - agora).total_seconds() // 60) + 1)
                flash(f'Muitas tentativas incorretas. Tente novamente em {minutos_restantes} minuto(s).', 'error')
                return render_template('login.html', next=proxima_pagina)

        user = mongo.db.users.find_one({"email": email, "ativo": {"$ne": False}})
        senha_valida = False
        if user and 'senha_hash' in user and senha:
            hash_armazenado = user['senha_hash']
            hash_bytes = hash_armazenado.encode('utf-8') if isinstance(hash_armazenado, str) else hash_armazenado
            try:
                senha_valida = bcrypt.checkpw(senha.encode('utf-8'), hash_bytes)
            except Exception:
                senha_valida = False

        if user and senha_valida:
            mongo.db.login_tentativas.delete_one({"chave": chave_tentativa})
            session['user_id'] = str(user['_id'])
            session['user_nome'] = user['nome']
            session['papel'] = user.get('papel', 'cliente')

            origem_base = sanitizar_texto(request.form.get('origem_canal'))
            origem_detalhe = sanitizar_texto(request.form.get('origem_detalhe'))
            if origem_base:
                origem_final = f"{origem_base} ({origem_detalhe})" if origem_detalhe else origem_base
                update_login = {
                    "ultimo_canal_acesso": origem_final,
                    "ultimo_login_em": agora
                }
                if not user.get("origem_canal") or user.get("origem_canal") == "Não informado":
                    update_login["origem_canal"] = origem_final
                mongo.db.users.update_one({"_id": user["_id"]}, {"$set": update_login})

            destino_seguro = _url_retorno_segura(proxima_pagina)
            if destino_seguro and '/imovel/' in destino_seguro:
                return redirect(destino_seguro)

            if user['papel'] == 'admin':
                return redirect(url_for('admin_imoveis'))
            elif user['papel'] == 'corretor':
                return redirect(url_for('painel_corretor'))
            elif user['papel'] in ['proprietario', 'parceiro']:
                return redirect(url_for('painel_proprietario'))
            if destino_seguro:
                return redirect(destino_seguro)
            return redirect(url_for('index'))
        else:
            falhas_atuais = (registro_tentativa.get("falhas", 0) if registro_tentativa else 0) + 1
            update_tentativa = {
                "email": email,
                "falhas": falhas_atuais,
                "atualizado_em": agora
            }
            if falhas_atuais >= MAX_TENTATIVAS_LOGIN:
                update_tentativa["bloqueado_ate"] = agora + timedelta(minutes=BLOQUEIO_LOGIN_MINUTOS)
                mensagem_erro = f'Muitas tentativas incorretas. Acesso bloqueado por {BLOQUEIO_LOGIN_MINUTOS} minutos.'
            else:
                restantes = MAX_TENTATIVAS_LOGIN - falhas_atuais
                mensagem_erro = f'Usuário não cadastrado ou senha incorreta ({restantes} tentativa(s) restante(s)).'

            mongo.db.login_tentativas.update_one({"chave": chave_tentativa}, {"$set": update_tentativa}, upsert=True)
            flash(mensagem_erro, 'error')
            
    return render_template('login.html', next=proxima_pagina)

@app.route('/esqueci-senha', methods=['POST'])
def esqueci_senha():
    email = sanitizar_texto(request.form.get('email_recuperacao'))
    user = mongo.db.users.find_one({"email": email, "ativo": {"$ne": False}})
    
    if user:
        caracteres = string.ascii_letters + string.digits
        senha_temporaria = ''.join(random.choice(caracteres) for _ in range(6))
        senha_hash = bcrypt.hashpw(senha_temporaria.encode('utf-8'), bcrypt.gensalt())
        mongo.db.users.update_one({"_id": user["_id"]}, {"$set": {"senha_hash": senha_hash}})
        enviar_email_mailgun(
            email,
            "Teca Borges - Sua nova senha temporária",
            f"""Olá, {user['nome']},
Sua nova senha temporária é: {senha_temporaria}"""
        )

    flash('Se este e-mail estiver cadastrado, as instruções foram enviadas.', 'success')
    return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# --- ROTAS DE FAVORITOS E CLIENTE ---

@app.route('/imovel/favoritar/<imoid>', methods=['POST'])
@login_required
def favoritar_imovel(imoid):
    db = mongo.db
    user_id = oid_seguro(session.get('user_id'))
    imovel_obj_id = oid_seguro(imoid)
    if not user_id or not imovel_obj_id:
        return jsonify({"status": "error", "message": "ID inválido."}), 400

    user = db.users.find_one({"_id": user_id})
    favoritos = user.get("favoritos", []) if user else []
    
    if imovel_obj_id in favoritos:
        db.users.update_one({"_id": user_id}, {"$pull": {"favoritos": imovel_obj_id}})
        favoritado = False
    else:
        db.users.update_one({"_id": user_id}, {"$push": {"favoritos": imovel_obj_id}})
        favoritado = True  
    return jsonify({"status": "success", "favoritado": favoritado})

@app.route('/api/enviar-otp-favorito', methods=['POST'])
def enviar_otp_favorito():
    dados = request.json or {}
    email = sanitizar_texto(dados.get('email'))
    nome = sanitizar_texto(dados.get('nome'))
    telefone = sanitizar_texto(dados.get('telefone'))
    imovel_id = dados.get('imovel_id')
    
    if not email:
        return jsonify({"status": "error", "message": "E-mail obrigatório."}), 400
        
    if mongo.db.users.find_one({"email": email}):
        return jsonify({"status": "error", "message": "Este e-mail já está cadastrado no sistema. Faça login para continuar."}), 400
        
    codigo = _salvar_otp(email, "favorito", {"nome": nome, "telefone": telefone, "imovel_id": imovel_id})
    enviar_email_mailgun(
        email,
        "Teca Borges - Código de verificação para favoritar imóvel",
        f"""Olá {nome}!

Seu código de verificação é: {codigo} (válido por {EXPIRACAO_OTP_MINUTOS} minutos).

Sua senha provisória de acesso é: 123456

Você pode alterá-la a qualquer momento acessando o seu painel de perfil no site."""
    )
    return jsonify({"status": "success"})

@app.route('/api/verificar-otp-e-salvar-favorito', methods=['POST'])
def verificar_otp_e_salvar_favorito():
    dados = request.json or {}
    email = sanitizar_texto(dados.get('email'))
    codigo_informado = dados.get('codigo')
    
    registro, erro = _validar_otp(email, "favorito", codigo_informado)
    if erro:
        return jsonify({"status": "error", "message": erro}), 400

    db = mongo.db
    nome = registro["nome"]
    telefone = registro["telefone"]
    imovel_id_str = registro["imovel_id"]
    imovel_obj_id = oid_seguro(imovel_id_str)
    if not imovel_obj_id:
        return jsonify({"status": "error", "message": "Imóvel inválido."}), 400
    
    user = db.users.find_one({"email": email})
    if user:
        user_id = user["_id"]
        db.users.update_one({"_id": user_id}, {"$set": {"nome": nome, "telefone": telefone, "ativo": True}})
    else:
        senha_temp = bcrypt.hashpw("123456".encode('utf-8'), bcrypt.gensalt())
        res_user = db.users.insert_one({
            "nome": nome,
            "email": email,
            "senha_hash": senha_temp,
            "telefone": telefone,
            "papel": "cliente",
            "ativo": True,
            "favoritos": [],
            "criado_em": datetime.now(BR_TZ)
        })
        user_id = res_user.inserted_id

    db.users.update_one({"_id": user_id}, {"$addToSet": {"favoritos": imovel_obj_id}})
    db.leads.insert_one({
        "nome": nome,
        "email": email,
        "telefone": telefone,
        "imovel_id": imovel_obj_id,
        "origem": "Modal Favorito Site (OTP)",
        "criado_em": datetime.now(BR_TZ)
    })
    
    session['user_id'] = str(user_id)
    session['user_nome'] = nome
    session['papel'] = "cliente"
    
    db.otps.delete_one({"_id": registro["_id"]})
    return jsonify({"status": "success", "redirect_url": url_for('meus_favoritos')})

# --- TRAVA DE SEGURANÇA DE DATA NO BACKEND PARA AGENDAMENTOS ---
@app.route('/imovel/agendar/<imoid>', methods=['POST'])
@login_required
def agendar_visita(imoid):
    db = mongo.db
    user_id = oid_seguro(session.get('user_id'))
    imovel_oid = oid_seguro(imoid)
    if not user_id or not imovel_oid:
        flash('Imóvel inválido.', 'danger')
        return redirect(request.referrer or url_for('index'))

    data = request.form.get('data')
    hora = request.form.get('hora')
    observacoes = sanitizar_texto(request.form.get('observacoes', ''))
    
    if not data or not hora:
        flash('Informe a data e o horário desejados.', 'danger')
        return redirect(request.referrer or url_for('index'))
        
    try:
        if len(hora.split(':')) == 2:
            hora += ":00"
        data_hora = datetime.strptime(f"{data} {hora}", '%Y-%m-%d %H:%M:%S')
        
        if data_hora.date() < datetime.now(BR_TZ).date():
            flash('Não é permitido agendar visitas para datas anteriores a hoje.', 'danger')
            return redirect(request.referrer or url_for('index'))
            
    except Exception:
        flash('Formato de data ou hora inválido.', 'danger')
        return redirect(request.referrer or url_for('index'))

    db.agendamentos.insert_one({
        "cliente_id": user_id,
        "imovel_id": imovel_oid,
        "data_hora": data_hora,
        "observacoes": observacoes,
        "status": "pendente",
        "criado_em": datetime.now(BR_TZ)
    })
    flash('Visita agendada com sucesso!', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/cliente/favoritos')
@login_required
def meus_favoritos():
    db = mongo.db
    uid = oid_seguro(session.get('user_id'))
    user = db.users.find_one({"_id": uid}) if uid else None
    fav_ids = user.get("favoritos", []) if user else []
    imoveis_favoritos = list(db.imoveis.find({"_id": {"$in": fav_ids}, "status": "ativo"}))
    return render_template('cliente/favoritos.html', imoveis=imoveis_favoritos, active_tab='favoritos')

@app.route('/cliente/agendamentos')
@login_required
def meus_agendamentos():
    db = mongo.db
    uid = oid_seguro(session.get('user_id'))
    pipeline = [
        {"$match": {"cliente_id": uid}},
        {"$sort": {"data_hora": 1}},
        {"$lookup": {"from": "imoveis", "localField": "imovel_id", "foreignField": "_id", "as": "imovel_info"}},
        {"$unwind": {"path": "$imovel_info", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {"from": "imoveis_enderecos", "localField": "imovel_id", "foreignField": "imovel_id", "as": "endereco_privado"}},
        {"$unwind": {"path": "$endereco_privado", "preserveNullAndEmptyArrays": True}}
    ]
    agendamentos = list(db.agendamentos.aggregate(pipeline)) if (uid and 'agendamentos' in db.list_collection_names()) else []
    return render_template('cliente/agendamentos.html', agendamentos=agendamentos, active_tab='agendamentos')

@app.route('/perfil', methods=['GET', 'POST'])
@login_required
def meu_perfil():
    db = mongo.db
    user_id = oid_seguro(session.get('user_id'))
    user = db.users.find_one({"_id": user_id})
    
    if request.method == 'POST':
        nome = sanitizar_texto(request.form.get('nome'))
        email = sanitizar_texto(request.form.get('email'))
        telefone = sanitizar_texto(request.form.get('telefone'))
        nova_senha = request.form.get('senha')
        
        if email != user.get('email'):
            existe_outro = db.users.find_one({"email": email, "_id": {"$ne": user_id}})
            if existe_outro:
                flash("Este e-mail já está cadastrado.", "danger")
                return redirect(url_for('meu_perfil'))
        
        update_data = {
            "nome": nome,
            "email": email,
            "telefone": telefone
        }
        
        if nova_senha and nova_senha.strip() != "":
            update_data["senha_hash"] = bcrypt.hashpw(nova_senha.encode('utf-8'), bcrypt.gensalt())
            
        db.users.update_one({"_id": user_id}, {"$set": update_data})
        session['user_nome'] = nome
        flash("Perfil atualizado com sucesso!", "success")
        return redirect(url_for('meu_perfil'))
        
    return render_template('admin/perfil.html', user=user, active_tab='perfil')

@app.route('/perfil/excluir', methods=['POST'])
@login_required
def excluir_propria_conta():
    if session.get('papel') != 'cliente':
        flash('Apenas contas de clientes podem ser excluídas por esta opção.', 'danger')
        return redirect(url_for('meu_perfil'))

    db = mongo.db
    user_id = oid_seguro(session.get('user_id'))
    user = db.users.find_one({"_id": user_id}) if user_id else None
    if not user:
        session.clear()
        return redirect(url_for('index'))

    senha_confirmacao = request.form.get('senha_confirmacao') or ""
    senha_valida = False
    if 'senha_hash' in user and senha_confirmacao:
        hash_armazenado = user['senha_hash']
        hash_bytes = hash_armazenado.encode('utf-8') if isinstance(hash_armazenado, str) else hash_armazenado
        try:
            senha_valida = bcrypt.checkpw(senha_confirmacao.encode('utf-8'), hash_bytes)
        except Exception:
            senha_valida = False

    if not senha_valida:
        flash('Senha incorreta. A exclusão da conta não foi realizada.', 'danger')
        return redirect(url_for('meu_perfil'))

    excluir_dados_usuario_lgpd(user)
    session.clear()
    flash('Sua conta e seus dados pessoais foram excluídos permanentemente.', 'success')
    return redirect(url_for('index'))

# --- PAINEL DO PROPRIETÁRIO / PARCEIRO ---
@app.route('/proprietario/painel')
@login_required
@proprietario_required
def painel_proprietario():
    db = mongo.db
    proprietario_id = oid_seguro(session.get('user_id'))
    
    imoveis_prop = list(db.imoveis.find({"proprietario_id": proprietario_id, "status": "ativo"}))
    imovel_ids = [imv["_id"] for imv in imoveis_prop]
    
    imoveis_com_metricas = []
    for imv in imoveis_prop:
        imv_id = imv["_id"]
        total_curtidas = db.users.count_documents({"favoritos": imv_id, "ativo": {"$ne": False}})
        total_agendamentos = db.agendamentos.count_documents({"imovel_id": imv_id}) if 'agendamentos' in db.list_collection_names() else 0
        total_leads = db.leads.count_documents({"imovel_id": imv_id}) if 'leads' in db.list_collection_names() else 0
        
        imoveis_com_metricas.append({
            "imovel": imv,
            "curtidas": total_curtidas,
            "agendamentos": total_agendamentos,
            "leads": total_leads
        })
        
    agendamentos = []
    if 'agendamentos' in db.list_collection_names() and imovel_ids:
        pipeline_ag = [
            {"$match": {"imovel_id": {"$in": imovel_ids}}},
            {"$sort": {"data_hora": 1}},
            {"$lookup": {"from": "users", "localField": "cliente_id", "foreignField": "_id", "as": "cliente_info"}},
            {"$unwind": {"path": "$cliente_info", "preserveNullAndEmptyArrays": True}},
            {"$lookup": {"from": "imoveis", "localField": "imovel_id", "foreignField": "_id", "as": "imovel_info"}},
            {"$unwind": {"path": "$imovel_info", "preserveNullAndEmptyArrays": True}}
        ]
        agendamentos = list(db.agendamentos.aggregate(pipeline_ag))
        
    interessados_curtidas = []
    if imovel_ids:
        usuarios_fav = list(db.users.find({"ativo": {"$ne": False}, "favoritos": {"$in": imovel_ids}}))
        for u in usuarios_fav:
            favs = u.get("favoritos", [])
            for fid in favs:
                if fid in imovel_ids:
                    imv_doc = db.imoveis.find_one({"_id": fid})
                    if imv_doc:
                        interessados_curtidas.append({
                            "cliente": u,
                            "imovel": imv_doc
                        })
        
    return render_template(
        'proprietario/painel.html', 
        imoveis=imoveis_com_metricas, 
        agendamentos=agendamentos,
        curtidas=interessados_curtidas,
        active_tab='proprietario_painel'
    )

# --- ROTAS DE GESTÃO DE IMÓVEIS (RESTRITAS EXCLUSIVAMENTE AO ADMIN) ---

@app.route('/admin/painel')
@login_required
@admin_required
def admin_painel():
    db = mongo.db
    
    corretores = list(db.users.find({"papel": {"$in": ["corretor", "admin"]}, "ativo": {"$ne": False}}))
    
    pipeline_leads = [
        {"$match": {"origem": {"$nin": ["Busca Personalizada Site (OTP)", "Busca Personalizada Site (Usuário Logado)"]}}},
        {"$sort": {"criado_em": -1}},
        {"$lookup": {"from": "imoveis", "localField": "imovel_id", "foreignField": "_id", "as": "imovel_info"}},
        {"$unwind": {"path": "$imovel_info", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {"from": "users", "localField": "corretor_responsavel_id", "foreignField": "_id", "as": "corretor_info"}},
        {"$unwind": {"path": "$corretor_info", "preserveNullAndEmptyArrays": True}}
    ]
    leads = list(db.leads.aggregate(pipeline_leads))
    
    pipeline_agendamentos = [
        {"$sort": {"criado_em": -1}},
        {"$lookup": {"from": "users", "localField": "cliente_id", "foreignField": "_id", "as": "cliente_info"}},
        {"$unwind": {"path": "$cliente_info", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {"from": "imoveis", "localField": "imovel_id", "foreignField": "_id", "as": "imovel_info"}},
        {"$unwind": {"path": "$imovel_info", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {"from": "users", "localField": "corretor_responsavel_id", "foreignField": "_id", "as": "corretor_info"}},
        {"$unwind": {"path": "$corretor_info", "preserveNullAndEmptyArrays": True}}
    ]
    agendamentos = list(db.agendamentos.aggregate(pipeline_agendamentos)) if 'agendamentos' in db.list_collection_names() else []
    
    pipeline_buscas = [
        {"$match": {"origem": {"$in": ["Busca Personalizada Site (OTP)", "Busca Personalizada Site (Usuário Logado)"]}}},
        {"$sort": {"criado_em": -1}},
        {"$lookup": {"from": "users", "localField": "corretor_responsavel_id", "foreignField": "_id", "as": "corretor_info"}},
        {"$unwind": {"path": "$corretor_info", "preserveNullAndEmptyArrays": True}}
    ]
    buscas = list(db.leads.aggregate(pipeline_buscas))
    
    usuarios_favoritos = list(db.users.find({"ativo": {"$ne": False}, "favoritos": {"$exists": True, "$not": {"$size": 0}}}))
    curtidas_lista = []
    for u in usuarios_favoritos:
        favs = u.get("favoritos", [])
        imoveis_favs = list(db.imoveis.find({"_id": {"$in": favs}, "status": "ativo"}))
        for imv in imoveis_favs:
            curtidas_lista.append({
                "cliente": u,
                "imovel": imv
            })
            
    hoje_str = datetime.now(BR_TZ).date().isoformat()
    
    return render_template(
        'admin/painel.html',
        corretores=corretores,
        leads=leads,
        agendamentos=agendamentos,
        buscas=buscas,
        curtidas=curtidas_lista,
        today=hoje_str,
        active_tab='admin_painel'
    )

@app.route('/admin/lead/atribuir/<lead_id>', methods=['POST'])
@login_required
@admin_required
def admin_atribuir_lead(lead_id):
    db = mongo.db
    lid = oid_seguro(lead_id)
    if not lid:
        flash('Lead inválido.', 'danger')
        return redirect(url_for('admin_painel') + '#leads')

    corretor_oid = oid_seguro(request.form.get('corretor_id'))
    update_data = {
        "corretor_responsavel_id": corretor_oid,
        "status": "em_andamento" if corretor_oid else "pendente",
        "atualizado_em": datetime.now(BR_TZ)
    }
    
    db.leads.update_one({"_id": lid}, {"$set": update_data})
    flash('Corretor atribuído com sucesso!', 'success')
    return redirect(url_for('admin_painel') + '#leads')

@app.route('/admin/curtida/gerar-lead', methods=['POST'])
@login_required
@admin_required
def admin_gerar_lead_de_curtida():
    db = mongo.db
    uid = oid_seguro(request.form.get('user_id'))
    imovel_oid = oid_seguro(request.form.get('imovel_id'))
    corretor_oid = oid_seguro(request.form.get('corretor_id'))
    
    cliente = db.users.find_one({"_id": uid}) if uid else None
    if not cliente or not imovel_oid:
        flash('Cliente ou imóvel inválido.', 'danger')
        return redirect(url_for('admin_painel') + '#curtidas')
        
    db.leads.insert_one({
        "nome": cliente.get('nome'),
        "email": cliente.get('email'),
        "telefone": cliente.get('telefone'),
        "imovel_id": imovel_oid,
        "origem": "Curtida de Imóvel (Painel Admin)",
        "corretor_responsavel_id": corretor_oid,
        "status": "em_andamento" if corretor_oid else "pendente",
        "criado_em": datetime.now(BR_TZ)
    })
    
    flash('Lead gerado com sucesso a partir da curtida!', 'success')
    return redirect(url_for('admin_painel') + '#curtidas')

@app.route('/admin/agendamento/atribuir/<ag_id>', methods=['POST'])
@login_required
@admin_required
def admin_atribuir_agendamento(ag_id):
    db = mongo.db
    aid = oid_seguro(ag_id)
    if not aid:
        flash('Agendamento inválido.', 'danger')
        return redirect(url_for('admin_painel') + '#agendamentos')

    corretor_oid = oid_seguro(request.form.get('corretor_id'))
    update_data = {
        "corretor_responsavel_id": corretor_oid,
        "status": "em_andamento" if corretor_oid else "pendente",
        "atualizado_em": datetime.now(BR_TZ)
    }
    
    db.agendamentos.update_one({"_id": aid}, {"$set": update_data})
    flash('Corretor atribuído ao agendamento com sucesso!', 'success')
    return redirect(url_for('admin_painel') + '#agendamentos')

@app.route('/admin/agendamento/reagendar/<ag_id>', methods=['POST'])
@login_required
@admin_required
def admin_reagendar_visita(ag_id):
    db = mongo.db
    aid = oid_seguro(ag_id)
    if not aid:
        flash('Agendamento inválido.', 'danger')
        return redirect(url_for('admin_painel') + '#agendamentos')

    nova_data = request.form.get('nova_data')
    nova_hora = request.form.get('nova_hora')
    
    if not nova_data or not nova_hora:
        flash('Informe a nova data e o horário.', 'danger')
        return redirect(url_for('admin_painel') + '#agendamentos')
        
    try:
        if len(nova_hora.split(':')) == 2:
            nova_hora += ":00"
        data_hora_nova = datetime.strptime(f"{nova_data} {nova_hora}", '%Y-%m-%d %H:%M:%S')
        
        if data_hora_nova.date() < datetime.now(BR_TZ).date():
            flash('Não é permitido reagendar visitas para datas anteriores a hoje.', 'danger')
            return redirect(url_for('admin_painel') + '#agendamentos')
            
    except Exception:
        flash('Formato inválido.', 'danger')
        return redirect(url_for('admin_painel') + '#agendamentos')
        
    db.agendamentos.update_one(
        {"_id": aid},
        {
            "$set": {
                "data_hora": data_hora_nova,
                "status": "reagendado",
                "atualizado_em": datetime.now(BR_TZ)
            }
        }
    )
    flash('Visita reagendada com sucesso!', 'success')
    return redirect(url_for('admin_painel') + '#agendamentos')

@app.route('/admin/imoveis')
@login_required
@corretor_ou_admin_required
def admin_imoveis():
    db = mongo.db
    tipo_filtro = request.args.get('tipo')
    match_query = {"status": "ativo"}
    if tipo_filtro:
        match_query["tipo"] = tipo_filtro
        
    pipeline = [
        {"$match": match_query},
        {"$sort": {"criado_em": -1}},
        {"$lookup": {"from": "users", "localField": "proprietario_id", "foreignField": "_id", "as": "proprietario_info"}},
        {"$unwind": {"path": "$proprietario_info", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {"from": "users", "localField": "criado_por", "foreignField": "_id", "as": "criador_info"}},
        {"$unwind": {"path": "$criador_info", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {"from": "condominios", "localField": "condominio_id", "foreignField": "_id", "as": "condominio_info"}},
        {"$unwind": {"path": "$condominio_info", "preserveNullAndEmptyArrays": True}}
    ]
    imoveis = list(db.imoveis.aggregate(pipeline))
    return render_template('admin/imoveis_lista.html', imoveis=imoveis, tipo_atual=tipo_filtro, active_tab='imoveis')

@app.route('/admin/imoveis/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_imovel_novo():
    db = mongo.db
    if request.method == 'POST':
        codigo = gerar_proximo_codigo()
        titulo = sanitizar_texto(request.form.get('titulo'))
        slug = sanitizar_texto(request.form.get('slug')) or gerar_slug_base(titulo, fallback=codigo.lower())
        
        condominio_oid, condominio_nome = resolver_condominio(request.form.get('condominio_nome'))
        proprietario_oid = oid_seguro(request.form.get('proprietario_id'))
        
        pasta_imovel = os.path.join(app.config['UPLOAD_FOLDER'], codigo)
        lista_fotos = processar_upload_fotos_dinamicas(request.files, request.form, codigo, pasta_imovel)

        videos = []
        for campo_video in ['video_youtube_1', 'video_youtube_2']:
            v_info = extrair_youtube_embed(request.form.get(campo_video))
            if v_info:
                videos.append(v_info)

        imovel_doc = {
            "codigo": codigo,
            "slug": slug,
            "titulo": titulo,
            "descricao": sanitizar_texto(request.form.get('descricao')),
            "tipo": sanitizar_texto(request.form.get('tipo')),
            "status": "ativo",
            "destaque": True if request.form.get('destaque') == '1' else False,
            "precos": {
                "venda": float(request.form.get('preco_venda') or 0),
                "locacao": float(request.form.get('preco_locacao') or 0),
                "condominio": float(request.form.get('preco_condominio') or 0),
                "iptu": float(request.form.get('preco_iptu') or 0)
            },
            "caracteristicas": {
                "util": float(request.form.get('area_util') or 0),
                "total": float(request.form.get('area_total') or 0),
                "quartos": int(request.form.get('quartos') or 0),
                "suites": int(request.form.get('suites') or 0),
                "banheiros": int(request.form.get('banheiros') or 0),
                "vagas": int(request.form.get('vagas') or 0),
                "itens": {
                    "facilidades": request.form.getlist('feat_facilidades'),
                    "diferenciais": request.form.getlist('feat_diferenciais'),
                    "area_externa": request.form.getlist('feat_area_externa'),
                    "comodos": request.form.getlist('feat_comodos')
                }
            },
            "local_publico": {
                "bairro": sanitizar_texto(request.form.get('bairro')),
                "cidade": sanitizar_texto(request.form.get('cidade', 'São Paulo')),
                "estado": sanitizar_texto(request.form.get('estado', 'SP'))
            },
            "condominio_id": condominio_oid,
            "condominio_nome": condominio_nome,
            "proprietario_id": proprietario_oid,
            "criado_por": oid_seguro(session.get('user_id')),
            "midia": {"fotos": lista_fotos, "videos": videos},
            "criado_em": datetime.now(BR_TZ)
        }
        
        res = db.imoveis.insert_one(imovel_doc)
        andar_input = request.form.get('andar')
        andar_val = int(andar_input) if andar_input and andar_input.strip() != "" else None

        db.imoveis_enderecos.insert_one({
            "imovel_id": res.inserted_id,
            "logradouro": sanitizar_texto(request.form.get('logradouro')),
            "numero": sanitizar_texto(request.form.get('numero')),
            "complemento": sanitizar_texto(request.form.get('complemento', '')),
            "cep": sanitizar_texto(request.form.get('cep', '')),
            "andar": andar_val,
            "posicao_solar": sanitizar_texto(request.form.get('posicao_solar', ''))
        })
        
        # flash(f'Imóvel {codigo} cadastrado com sucesso!', 'success')
        return redirect(url_for('admin_imoveis'))
        
    proprietarios = list(db.users.find({"papel": {"$in": ["proprietario", "parceiro"]}, "ativo": {"$ne": False}}))
    condominios = list(db.condominios.find().sort("nome", 1))
    codigo_sugerido = gerar_proximo_codigo()
    return render_template('admin/imovel_form.html', proprietarios=proprietarios, condominios=condominios, codigo_sugerido=codigo_sugerido, active_tab='imoveis')

def extrair_youtube_embed(url_texto):
    if not url_texto:
        return None
    url_texto = url_texto.strip()

    # 1. YouTube
    match_yt = re.search(
        r"(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/shorts\/)([A-Za-z0-9_-]{11})",
        url_texto
    )
    if match_yt:
        video_id = match_yt.group(1)
        return {
            "url_original": url_texto,
            "plataforma": "youtube",
            "video_id": video_id,
            "embed_url": f"https://www.youtube.com/embed/{video_id}"
        }

    # 2. Google Drive
    match_drive = re.search(
        r"drive\.google\.com\/(?:file\/d\/|open\?id=|uc\?id=)([A-Za-z0-9_-]+)",
        url_texto
    )
    if match_drive:
        file_id = match_drive.group(1)
        return {
            "url_original": url_texto,
            "plataforma": "google_drive",
            "video_id": file_id,
            "embed_url": f"https://drive.google.com/file/d/{file_id}/preview"
        }

    return None

@app.route('/admin/imoveis/editar/<codigo>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_imovel(codigo):
    db = mongo.db
    imovel = db.imoveis.find_one({"codigo": codigo})
    if not imovel:
        flash("Imóvel não encontrado.", "danger")
        return redirect(url_for('admin_imoveis'))
        
    if request.method == 'POST':
        titulo = sanitizar_texto(request.form.get('titulo'))
        descricao = sanitizar_texto(request.form.get('descricao'))
        tipo = sanitizar_texto(request.form.get('tipo'))
        condominio_oid, condominio_nome = resolver_condominio(request.form.get('condominio_nome'))
        proprietario_oid = oid_seguro(request.form.get('proprietario_id'))
        
        pasta_imovel = os.path.join(app.config['UPLOAD_FOLDER'], codigo)
        
        fotos_atuais = imovel.get("midia", {}).get("fotos", [])
        lista_fotos = processar_upload_fotos_dinamicas(request.files, request.form, codigo, pasta_imovel, fotos_atuais)

        videos = []
        for campo_video in ['video_youtube_1', 'video_youtube_2']:
            v_info = extrair_youtube_embed(request.form.get(campo_video))
            if v_info:
                videos.append(v_info)
        
        db.imoveis.update_one(
            {"codigo": codigo},
            {
                "$set": {
                    "titulo": titulo,
                    "descricao": descricao,
                    "tipo": tipo,
                    "destaque": True if request.form.get('destaque') == '1' else False,
                    "precos.venda": float(request.form.get('preco_venda') or 0),
                    "precos.locacao": float(request.form.get('preco_locacao') or 0),
                    "precos.condominio": float(request.form.get('preco_condominio') or 0),
                    "precos.iptu": float(request.form.get('preco_iptu') or 0),
                    "caracteristicas.util": float(request.form.get('area_util') or 0),
                    "caracteristicas.total": float(request.form.get('area_total') or 0),
                    "caracteristicas.quartos": int(request.form.get('quartos') or 0),
                    "caracteristicas.suites": int(request.form.get('suites') or 0),
                    "caracteristicas.banheiros": int(request.form.get('banheiros') or 0),
                    "caracteristicas.vagas": int(request.form.get('vagas') or 0),
                    "caracteristicas.itens": {
                        "facilidades": request.form.getlist('feat_facilidades'),
                        "diferenciais": request.form.getlist('feat_diferenciais'),
                        "area_externa": request.form.getlist('feat_area_externa'),
                        "comodos": request.form.getlist('feat_comodos')
                    },
                    "local_publico.bairro": sanitizar_texto(request.form.get('bairro')),
                    "condominio_id": condominio_oid,
                    "condominio_nome": condominio_nome,
                    "proprietario_id": proprietario_oid,
                    "midia.fotos": lista_fotos,
                    "midia.videos": videos
                }
            }
        )
        
        andar_input = request.form.get('andar')
        andar_val = int(andar_input) if andar_input and andar_input.strip() != "" else None
        
        db.imoveis_enderecos.update_one(
            {"imovel_id": imovel["_id"]},
            {
                "$set": {
                    "logradouro": sanitizar_texto(request.form.get('logradouro')),
                    "numero": sanitizar_texto(request.form.get('numero')),
                    "complemento": sanitizar_texto(request.form.get('complemento', '')),
                    "cep": sanitizar_texto(request.form.get('cep', '')),
                    "andar": andar_val,
                    "posicao_solar": sanitizar_texto(request.form.get('posicao_solar', ''))
                }
            },
            upsert=True
        )
        
        flash(f'Imóvel {codigo} atualizado com sucesso!', 'success')
        return redirect(url_for('admin_imoveis'))
        
    proprietarios = list(db.users.find({"papel": {"$in": ["proprietario", "parceiro"]}, "ativo": {"$ne": False}}))
    condominios = list(db.condominios.find().sort("nome", 1))
    endereco = db.imoveis_enderecos.find_one({"imovel_id": imovel["_id"]})

    if not imovel.get("condominio_nome") and imovel.get("condominio_id"):
        cond_doc = db.condominios.find_one({"_id": imovel["condominio_id"]})
        if cond_doc:
            imovel["condominio_nome"] = cond_doc.get("nome", "")
    
    return render_template(
        'admin/imovel_form.html', 
        imovel=imovel, 
        endereco=endereco,
        proprietarios=proprietarios, 
        condominios=condominios, 
        codigo_sugerido=codigo, 
        editando=True,
        active_tab='imoveis'
    )

@app.route('/admin/imoveis/remover-foto/<codigo>', methods=['POST'])
@login_required
@admin_required
def remover_foto_imovel(codigo):
    db = mongo.db
    dados = request.json or {}
    caminho_foto = dados.get('arquivo')
    public_id_alvo = dados.get('public_id')
    
    imovel = db.imoveis.find_one({"codigo": codigo})
    if not imovel:
        return jsonify({"status": "error", "message": "Imóvel não encontrado."}), 404
        
    fotos = imovel.get("midia", {}).get("fotos", [])
    novas_fotos = []
    fotos_removidas = []

    for f in fotos:
        match_arquivo = bool(caminho_foto and f.get("arquivo") == caminho_foto)
        match_public_id = bool(public_id_alvo and f.get("public_id") == public_id_alvo)
        if match_arquivo or match_public_id:
            fotos_removidas.append(f)
        else:
            novas_fotos.append(f)

    for f_rem in fotos_removidas:
        _excluir_recurso_foto(f_rem)

    if not fotos_removidas and caminho_foto:
        _excluir_recurso_foto({"arquivo": caminho_foto, "public_id": public_id_alvo})
                
    db.imoveis.update_one(
        {"codigo": codigo},
        {"$set": {"midia.fotos": novas_fotos}}
    )
    
    return jsonify({"status": "success"})

@app.route('/admin/imoveis/excluir/<codigo>')
@login_required
@admin_required
def admin_imovel_excluir(codigo):
    db = mongo.db
    db.imoveis.update_one({"codigo": codigo}, {"$set": {"status": "inativo", "desativado_em": datetime.now(BR_TZ)}})
    return redirect(url_for('admin_imoveis'))

@app.route('/admin/usuarios', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_usuarios():
    db = mongo.db
    if request.method == 'POST':
        nome = sanitizar_texto(request.form.get('nome'))
        email = sanitizar_texto(request.form.get('email'))
        senha = request.form.get('senha') or ""
        papel = sanitizar_texto(request.form.get('papel'))
        telefone = sanitizar_texto(request.form.get('telefone'))
        
        if db.users.find_one({"email": email}):
            flash('Este e-mail já está cadastrado no sistema!', 'danger')
        else:
            senha_hash = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt())
            novo_usuario = {
                "nome": nome, 
                "email": email, 
                "senha_hash": senha_hash, 
                "telefone": telefone, 
                "papel": papel, 
                "ativo": True, 
                "criado_em": datetime.now(BR_TZ)
            }
            if papel in ['proprietario', 'parceiro']:
                novo_usuario["codigo"] = gerar_codigo_proprietario(papel)
                
            db.users.insert_one(novo_usuario)
            return redirect(url_for('admin_usuarios'))
            
    usuarios = list(db.users.find())
    return render_template('admin/usuarios.html', usuarios=usuarios, active_tab='usuarios')

@app.route('/admin/usuarios/alterar-papel/<user_id>', methods=['POST'])
@login_required
@admin_required
def alterar_papel(user_id):
    db = mongo.db
    uid = oid_seguro(user_id)
    if not uid:
        flash('Usuário inválido.', 'danger')
        return redirect(url_for('admin_usuarios'))

    novo_papel = sanitizar_texto(request.form.get('papel'))
    if novo_papel in ['admin', 'corretor', 'cliente', 'proprietario', 'parceiro']:
        db.users.update_one({"_id": uid}, {"$set": {"papel": novo_papel}})
        flash('Papel do usuário atualizado com sucesso!', 'success')
    else:
        flash('Papel inválido.', 'danger')
        
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/usuarios/excluir/<user_id>')
@login_required
@admin_required
def excluir_usuario(user_id):
    db = mongo.db
    uid = oid_seguro(user_id)
    if not uid:
        flash('Usuário inválido.', 'danger')
        return redirect(url_for('admin_usuarios'))

    if str(uid) == str(session.get('user_id')):
        flash('Você não pode excluir sua própria conta de administrador por aqui.', 'warning')
        return redirect(url_for('admin_usuarios'))

    user_alvo = db.users.find_one({"_id": uid})
    if not user_alvo:
        flash('Usuário não encontrado.', 'danger')
        return redirect(url_for('admin_usuarios'))

    excluir_dados_usuario_lgpd(user_alvo)
    flash('Usuário e seus dados pessoais foram excluídos permanentemente (LGPD).', 'success')
    return redirect(url_for('admin_usuarios'))

@app.route('/corretor/painel')
@login_required
def painel_corretor():
    db = mongo.db
    corretor_id = oid_seguro(session.get('user_id'))
    papel = session.get('papel')
    
    query_agendamentos_filtro = {}
    if papel != 'admin':
        query_agendamentos_filtro = {
            "$or": [
                {"status": "pendente"},
                {"corretor_responsavel_id": None},
                {"corretor_responsavel_id": corretor_id}
            ]
        }

    pipeline_agendamentos = [
        {"$match": query_agendamentos_filtro},
        {"$sort": {"criado_em": -1}},
        {"$lookup": {"from": "users", "localField": "cliente_id", "foreignField": "_id", "as": "cliente_info"}},
        {"$unwind": {"path": "$cliente_info", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {"from": "imoveis", "localField": "imovel_id", "foreignField": "_id", "as": "imovel_info"}},
        {"$unwind": {"path": "$imovel_info", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {"from": "imoveis_enderecos", "localField": "imovel_id", "foreignField": "imovel_id", "as": "endereco_privado"}},
        {"$unwind": {"path": "$endereco_privado", "preserveNullAndEmptyArrays": True}}
    ]
    agendamentos = list(db.agendamentos.aggregate(pipeline_agendamentos)) if 'agendamentos' in db.list_collection_names() else []
    
    hoje_str = datetime.now(BR_TZ).date().isoformat()

    query_leads_filtro = {
        "origem": {"$nin": ["Busca Personalizada Site (OTP)", "Busca Personalizada Site (Usuário Logado)"]}
    }
    if papel != 'admin':
        query_leads_filtro["$or"] = [
            {"corretor_responsavel_id": {"$exists": False}},
            {"corretor_responsavel_id": None},
            {"status": "pendente"},
            {"corretor_responsavel_id": corretor_id}
        ]

    pipeline_leads = [
        {"$match": query_leads_filtro},
        {"$sort": {"criado_em": -1}},
        {"$lookup": {"from": "imoveis", "localField": "imovel_id", "foreignField": "_id", "as": "imovel_info"}},
        {"$unwind": {"path": "$imovel_info", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {"from": "imoveis_enderecos", "localField": "imovel_id", "foreignField": "imovel_id", "as": "endereco_privado"}},
        {"$unwind": {"path": "$endereco_privado", "preserveNullAndEmptyArrays": True}}
    ]
    leads = list(db.leads.aggregate(pipeline_leads))
    
    curtidas_pipeline = [
        {"$match": {"ativo": {"$ne": False}}},
        {"$unwind": "$favoritos"},
        {"$group": {"_id": "$favoritos", "total_curtidas": {"$sum": 1}}},
        {"$match": {"total_curtidas": {"$gte": 1}}},
        {"$sort": {"total_curtidas": -1}}
    ]
    ranking_curtidas = list(db.users.aggregate(curtidas_pipeline))
    
    imoveis_curtidos = []
    for item in ranking_curtidas:
        imovel_doc = db.imoveis.find_one({"_id": item["_id"], "status": "ativo"})
        if imovel_doc:
            endereco_doc = db.imoveis_enderecos.find_one({"imovel_id": imovel_doc["_id"]})
            imoveis_curtidos.append({
                "imovel": imovel_doc,
                "endereco": endereco_doc,
                "total_curtidas": item["total_curtidas"]
            })

    query_buscas_filtro = {
        "origem": {"$in": ["Busca Personalizada Site (OTP)", "Busca Personalizada Site (Usuário Logado)"]},
        "corretor_responsavel_id": corretor_id
    }
    pipeline_buscas_corretor = [
        {"$match": query_buscas_filtro},
        {"$sort": {"criado_em": -1}}
    ]
    buscas_corretor = list(db.leads.aggregate(pipeline_buscas_corretor))

    return render_template('corretor/painel.html', 
                           leads=leads, 
                           agendamentos=agendamentos, 
                           imoveis_curtidos=imoveis_curtidos,
                           buscas_corretor=buscas_corretor,
                           today=hoje_str, 
                           active_tab='painel_corretor')

@app.route('/corretor/lead/atender/<lead_id>')
@login_required
@corretor_ou_admin_required
def atender_lead(lead_id):
    db = mongo.db
    corretor_id = oid_seguro(session.get('user_id'))
    lid = oid_seguro(lead_id)
    if not lid:
        flash('Lead inválido.', 'danger')
        return redirect(url_for('painel_corretor') + '#leads')
    
    resultado = db.leads.find_one_and_update(
        {
            "_id": lid,
            "$or": [
                {"corretor_responsavel_id": {"$exists": False}},
                {"corretor_responsavel_id": None},
                {"status": "pendente"}
            ]
        },
        {
            "$set": {
                "status": "em_andamento",
                "corretor_responsavel_id": corretor_id,
                "atualizado_em": datetime.now(BR_TZ)
            }
        },
        return_document=True
    )
    
    if not resultado:
        flash('Este lead já foi assumido por outro corretor!', 'warning')
    else:
        flash('Você assumiu este lead com sucesso!', 'success')
        
    return redirect(url_for('painel_corretor') + '#leads')

@app.route('/corretor/agendamento/atender/<ag_id>')
@login_required
@corretor_ou_admin_required
def atender_agendamento(ag_id):
    db = mongo.db
    corretor_id = oid_seguro(session.get('user_id'))
    aid = oid_seguro(ag_id)
    if not aid:
        flash('Agendamento inválido.', 'danger')
        return redirect(url_for('painel_corretor'))
    
    resultado = db.agendamentos.find_one_and_update(
        {
            "_id": aid,
            "status": "pendente"
        },
        {
            "$set": {
                "status": "em_andamento",
                "corretor_responsavel_id": corretor_id,
                "atualizado_em": datetime.now(BR_TZ)
            }
        },
        return_document=True
    )
    
    if not resultado:
        flash('Este atendimento já foi assumido por outro corretor!', 'warning')
    else:
        flash('Você assumiu este atendimento com sucesso!', 'success')
        
    return redirect(url_for('painel_corretor'))

@app.route('/corretor/agendamento/status/<ag_id>/<novo_status>')
@login_required
@corretor_ou_admin_required
def alterar_status_agendamento_corretor(ag_id, novo_status):
    db = mongo.db
    corretor_id = oid_seguro(session.get('user_id'))
    aid = oid_seguro(ag_id)
    if not aid:
        flash('Agendamento inválido.', 'danger')
        return redirect(url_for('painel_corretor'))
    
    papel = session.get('papel')
    query = {"_id": aid}
    if papel != 'admin':
        query["corretor_responsavel_id"] = corretor_id

    resultado = db.agendamentos.update_one(
        query,
        {"$set": {"status": sanitizar_texto(novo_status), "atualizado_em": datetime.now(BR_TZ)}}
    )
    
    if resultado.modified_count > 0:
        flash('Status do agendamento atualizado com sucesso!', 'success')
    else:
        flash('Ação não permitida ou agendamento não encontrado.', 'danger')
        
    return redirect(url_for('painel_corretor'))

@app.route('/corretor/agendamento/reagendar/<ag_id>', methods=['POST'])
@login_required
@corretor_ou_admin_required
def reagendar_visita_corretor(ag_id):
    db = mongo.db
    corretor_id = oid_seguro(session.get('user_id'))
    aid = oid_seguro(ag_id)
    if not aid:
        flash('Agendamento inválido.', 'danger')
        return redirect(url_for('painel_corretor'))

    nova_data = request.form.get('nova_data')
    nova_hora = request.form.get('nova_hora')
    
    if not nova_data or not nova_hora:
        flash('Informe a nova data e o novo horário para o reagendamento.', 'danger')
        return redirect(url_for('painel_corretor'))
        
    try:
        if len(nova_hora.split(':')) == 2:
            nova_hora += ":00"
        data_hora_nova = datetime.strptime(f"{nova_data} {nova_hora}", '%Y-%m-%d %H:%M:%S')
        
        if data_hora_nova.date() < datetime.now(BR_TZ).date():
            flash('Não é permitido reagendar visitas para datas anteriores a hoje.', 'danger')
            return redirect(url_for('painel_corretor'))
            
    except Exception:
        flash('Formato de data ou hora inválido.', 'danger')
        return redirect(url_for('painel_corretor'))

    papel = session.get('papel')
    query = {"_id": aid}
    if papel != 'admin':
        query["corretor_responsavel_id"] = corretor_id

    resultado = db.agendamentos.update_one(
        query,
        {
            "$set": {
                "data_hora": data_hora_nova,
                "status": "reagendado",
                "atualizado_em": datetime.now(BR_TZ)
            }
        }
    )
    
    if resultado.modified_count > 0:
        flash('Visita reagendada com sucesso!', 'success')
    else:
        flash('Erro ao reagendar. Verifique se você é o responsável por este atendimento.', 'danger')
        
    return redirect(url_for('painel_corretor'))

if __name__ == '__main__':
    app.run(debug=True)