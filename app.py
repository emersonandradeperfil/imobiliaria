import os
import random
import string
import html
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from database import init_db, mongo
import bcrypt
from datetime import datetime, date
from functools import wraps
from werkzeug.utils import secure_filename
from bson.objectid import ObjectId
import requests
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env local
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "123456")

init_db(app)

# Configuração da pasta de uploads de imóveis
UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'upload')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Dicionário temporário para guardar os códigos OTP gerados
codigos_otp_temp = {}

# --- GUARDIÃO DE TEXTOS / PREVENÇÃO DE INPUT INJECTION (XSS) ---
def sanitizar_texto(texto):
    if not texto:
        return ""
    return html.escape(str(texto).strip())

# --- DECORATOR DE SEGURANÇA ATUALIZADO ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Faça login para acessar esta página.', 'warning')
            return redirect(url_for('login', next=request.path))
        
        # BLINDAGEM: Verifica se o usuário realmente ainda existe no banco de dados
        try:
            user_existe = mongo.db.users.find_one({"_id": ObjectId(session['user_id'])})
            if not user_existe:
                session.clear() # Limpa a sessão fantasma do navegador
                flash('Sua conta foi removida ou não existe mais. Faça login novamente.', 'danger')
                return redirect(url_for('login'))
        except Exception:
            session.clear()
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

# --- FUNÇÃO PARA PROCESSAR UPLOADS DINÂMICOS DE FOTOS ---
def processar_upload_fotos_dinamicas(request_files, request_form, codigo, pasta_imovel, fotos_existentes=None):
    lista_fotos = list(fotos_existentes) if fotos_existentes else []
    contador_ordem = max([f.get("ordem", 0) for f in lista_fotos], default=0) + 1
    
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
                    extensao = os.path.splitext(file.filename)[1]
                    nome_arquivo = secure_filename(f"{codigo}_{cat}_{contador_ordem}{extensao}")
                    file.save(os.path.join(pasta_imovel, nome_arquivo))
                    
                    is_capa = True if (cat == 'capa' and not any(f.get('capa') for f in lista_fotos)) else False
                    
                    lista_fotos.append({
                        "arquivo": f"upload/{codigo}/{nome_arquivo}",
                        "categoria": cat,
                        "legenda": legenda,
                        "ordem": contador_ordem,
                        "capa": is_capa
                    })
                    contador_ordem += 1
                    
    if not lista_fotos:
        lista_fotos.append({"arquivo": f"upload/{codigo}/default.jpg", "categoria": "capa", "legenda": "Capa", "ordem": 1, "capa": True})
        
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
    if 'user_id' in session:
        user = db.users.find_one({"_id": ObjectId(session['user_id'])})
        if user and 'favoritos' in user:
            favoritos_ids = [str(fav_id) for fav_id in user['favoritos']]
    
    return render_template('index.html', secoes=secoes, favoritos_ids=favoritos_ids)

@app.route('/cadastrar')
def cadastrar_cliente():
    return render_template('cadastrar.html')

@app.route('/imovel/<slug>')
def imovel_detalhe(slug):
    db = mongo.db
    imovel = db.imoveis.find_one({"slug": slug})
    if not imovel:
        return "Imóvel não encontrado", 404
    
    condominio = db.condominios.find_one({"_id": imovel.get("condominio_id")})
    
    endereco_privado = None
    if 'user_id' in session:
        try:
            user_check = db.users.find_one({"_id": ObjectId(session.get('user_id'))})
            if user_check:
                endereco_privado = db.imoveis_enderecos.find_one({"imovel_id": imovel["_id"]})
            else:
                session.clear()
        except Exception:
            session.clear()
        
    return render_template(
        'imovel_detalhe.html', 
        imovel=imovel, 
        condominio=condominio, 
        endereco_privado=endereco_privado
    )

# --- OTP PARA LIBERAÇÃO DE DETALHES DO IMÓVEL ---
@app.route('/api/enviar-otp-imovel', methods=['POST'])
def enviar_otp_imovel():
    dados = request.json
    email = sanitizar_texto(dados.get('email'))
    nome = sanitizar_texto(dados.get('nome'))
    whatsapp = sanitizar_texto(dados.get('whatsapp'))
    imoid = dados.get('imovel_id')
    
    if not email:
        return jsonify({"status": "error", "message": "E-mail obrigatório."}), 400
        
    if mongo.db.users.find_one({"email": email}):
        return jsonify({"status": "error", "message": "Este e-mail já está cadastrado no sistema. Faça login para continuar."}), 400
        
    codigo = str(random.randint(1000, 9999))
    codigos_otp_temp[email] = {
        "codigo": codigo,
        "nome": nome,
        "whatsapp": whatsapp,
        "imovel_id": imoid
    }
    
    api_key = os.getenv('MAILGUN_API_KEY')
    domain = os.getenv('MAILGUN_DOMAIN')
    
    try:
        requests.post(
            f"https://api.mailgun.net/v3/{domain}/messages",
            auth=("api", api_key),
            data={
                "from": f"Teca Borges Imóveis <postmaster@{domain}>",
                "to": [email],
                "subject": "Teca Borges - Código de verificação para ver imóvel",
                "text": f"Olá {nome}!\n\nSeu código de verificação é: {codigo}\n"
                f"Sua senha provisória de acesso é: 123456\n\n"
                f"Você pode alterá-la a qualquer momento acessando o seu painel de perfil no site."
            },
            timeout=5
        )
    except Exception as e:
        print(f"Erro ao enviar OTP do imóvel: {e}")
        
    return jsonify({"status": "success"})

@app.route('/api/verificar-otp-e-liberar-imovel', methods=['POST'])
def verificar_otp_e_liberar_imovel():
    dados = request.json
    email = sanitizar_texto(dados.get('email'))
    codigo_informado = dados.get('codigo')
    
    registro = codigos_otp_temp.get(email)
    if registro and registro["codigo"] == codigo_informado:
        db = mongo.db
        nome = registro["nome"]
        whatsapp = registro["whatsapp"]
        imoid = registro["imovel_id"]
        
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
                "criado_em": datetime.utcnow()
            })
            user_id = res_user.inserted_id
        else:
            user_id = user["_id"]
            db.users.update_one({"_id": user_id}, {"$set": {"nome": nome, "telefone": whatsapp}})

        db.leads.insert_one({
            "nome": nome,
            "email": email,
            "telefone": whatsapp,
            "imovel_id": ObjectId(imoid),
            "origem": "Liberação Dados Imóvel (OTP)",
            "criado_em": datetime.utcnow()
        })
        
        session['user_id'] = str(user_id)
        session['user_nome'] = nome
        session['user_whatsapp'] = whatsapp
        session['papel'] = "cliente"
        
        del codigos_otp_temp[email]
        
        imovel_doc = db.imoveis.find_one({"_id": ObjectId(imoid)})
        slug_destino = imovel_doc.get("slug") if imovel_doc else ""
        return jsonify({"status": "success", "slug": slug_destino})
        
    return jsonify({"status": "error", "message": "Código incorreto ou expirado!"}), 400

# --- OTP PARA BUSCA PERSONALIZADA ---
@app.route('/api/enviar-otp-busca', methods=['POST'])
def enviar_otp_busca():
    dados = request.json
    email = sanitizar_texto(dados.get('email'))
    
    if not email:
        return jsonify({"status": "error", "message": "E-mail obrigatório."}), 400
        
    if mongo.db.users.find_one({"email": email}):
        return jsonify({"status": "error", "message": "Este e-mail já está cadastrado no sistema. Faça login para continuar."}), 400
        
    codigo = str(random.randint(1000, 9999))
    codigos_otp_temp[email] = {"codigo": codigo}
    
    api_key = os.getenv('MAILGUN_API_KEY')
    domain = os.getenv('MAILGUN_DOMAIN')
    
    try:
        requests.post(
            f"https://api.mailgun.net/v3/{domain}/messages",
            auth=("api", api_key),
            data={
                "from": f"Teca Borges Imóveis <postmaster@{domain}>",
                "to": [email],
                "subject": "Teca Borges - Código de verificação para sua busca",
                "text": f"Olá!\nSeu código de verificação para busca personalizada é: {codigo}"
            },
            timeout=5
        )
    except Exception as e:
        print(f"Erro ao enviar OTP via Mailgun: {e}")
        
    return jsonify({"status": "success"})

@app.route('/api/verificar-otp-e-salvar-busca', methods=['POST'])
def verificar_otp_e_salvar_busca():
    dados = request.json
    email = sanitizar_texto(dados.get('email'))
    codigo_informado = dados.get('codigo')
    
    registro = codigos_otp_temp.get(email)
    if registro and registro["codigo"] == codigo_informado:
        db = mongo.db
        nome = sanitizar_texto(dados.get('nome'))
        whatsapp = sanitizar_texto(dados.get('whatsapp'))
        
        lead_data = {
            "nome": nome,
            "email": email,
            "whatsapp": whatsapp,
            "tipo_imovel": sanitizar_texto(dados.get('tipo')),
            "bairro": sanitizar_texto(dados.get('bairro')),
            "observacoes": sanitizar_texto(dados.get('observacoes')),
            "origem": "Busca Personalizada Site (OTP)",
            "verificado": True,
            "criado_em": datetime.utcnow()
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
                "criado_em": datetime.utcnow()
            })
            
        del codigos_otp_temp[email]
        return jsonify({"status": "success"})
    
    return jsonify({"status": "error", "message": "Código incorreto ou expirado!"}), 400

# --- OTP PARA CADASTRO DE CLIENTE ---
@app.route('/api/enviar-otp-cadastro', methods=['POST'])
def enviar_otp_cadastro():
    dados = request.json
    email = sanitizar_texto(dados.get('email'))
    
    if not email:
        return jsonify({"status": "error", "message": "E-mail obrigatório."}), 400
        
    if mongo.db.users.find_one({"email": email}):
        return jsonify({"status": "error", "message": "Este e-mail já está cadastrado."}), 400
        
    codigo = str(random.randint(1000, 9999))
    codigos_otp_temp[email] = {
        "codigo": codigo,
        "nome": sanitizar_texto(dados.get('nome')),
        "senha": dados.get('senha'),
        "telefone": sanitizar_texto(dados.get('telefone'))
    }
    
    api_key = os.getenv('MAILGUN_API_KEY')
    domain = os.getenv('MAILGUN_DOMAIN')
    
    try:
        requests.post(
            f"https://api.mailgun.net/v3/{domain}/messages",
            auth=("api", api_key),
            data={
                "from": f"Teca Borges Imóveis <postmaster@{domain}>",
                "to": [email],
                "subject": "Teca Borges - Confirmação de Cadastro",
                "text": f"Olá!\n\nSeu código de verificação é: {codigo}\n"
            },
            timeout=5
        )
    except Exception as e:
        print(f"Erro ao enviar OTP de cadastro: {e}")
        
    return jsonify({"status": "success"})

@app.route('/api/verificar-otp-e-cadastrar', methods=['POST'])
def verificar_otp_e_cadastrar():
    dados = request.json
    email = sanitizar_texto(dados.get('email'))
    codigo_informado = dados.get('codigo')
    
    registro = codigos_otp_temp.get(email)
    if registro and registro["codigo"] == codigo_informado:
        db = mongo.db
        nome = registro["nome"]
        senha = registro["senha"]
        telefone = registro["telefone"]
        
        senha_hash = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt())
        
        db.users.insert_one({
            "nome": nome,
            "email": email,
            "senha_hash": senha_hash,
            "telefone": telefone,
            "papel": "cliente",
            "ativo": True,
            "favoritos": [],
            "criado_em": datetime.utcnow()
        })
        
        del codigos_otp_temp[email]
        return jsonify({"status": "success"})
        
    return jsonify({"status": "error", "message": "Código incorreto ou expirado!"}), 400

@app.route('/login', methods=['GET', 'POST'])
def login():
    proxima_pagina = request.args.get('next') or request.form.get('next')
    if request.method == 'POST':
        email = sanitizar_texto(request.form.get('email'))
        senha = request.form.get('senha')
        
        user = mongo.db.users.find_one({"email": email})
        senha_valida = False
        if user and 'senha_hash' in user:
            hash_armazenado = user['senha_hash']
            hash_bytes = hash_armazenado.encode('utf-8') if isinstance(hash_armazenado, str) else hash_armazenado
            try:
                senha_valida = bcrypt.checkpw(senha.encode('utf-8'), hash_bytes)
            except Exception:
                senha_valida = False

        if user and senha_valida:
            session['user_id'] = str(user['_id'])
            session['user_nome'] = user['nome']
            session['papel'] = user.get('papel', 'cliente')
            
            if user['papel'] == 'admin':
                return redirect(url_for('admin_imoveis'))
            elif user['papel'] == 'corretor':
                return redirect(url_for('painel_corretor'))
            if proxima_pagina:
                return redirect(proxima_pagina)
            return redirect(url_for('index'))
        else:
            flash('Usuário não cadastrado, verificar login e senha', 'error')
            
    return render_template('login.html', next=proxima_pagina)

@app.route('/esqueci-senha', methods=['POST'])
def esqueci_senha():
    email = sanitizar_texto(request.form.get('email_recuperacao'))
    user = mongo.db.users.find_one({"email": email})
    
    if user:
        caracteres = string.ascii_letters + string.digits
        senha_temporaria = ''.join(random.choice(caracteres) for _ in range(6))
        senha_hash = bcrypt.hashpw(senha_temporaria.encode('utf-8'), bcrypt.gensalt())
        mongo.db.users.update_one({"_id": user["_id"]}, {"$set": {"senha_hash": senha_hash}})
        
        api_key = os.getenv('MAILGUN_API_KEY')
        domain = os.getenv('MAILGUN_DOMAIN')
        try:
            requests.post(
                f"https://api.mailgun.net/v3/{domain}/messages",
                auth=("api", api_key),
                data={
                    "from": f"Teca Borges Imóveis <postmaster@{domain}>",
                    "to": [email],
                    "subject": "Teca Borges - Sua nova senha temporária",
                    "text": f"Olá, {user['nome']},\nSua nova senha temporária é: {senha_temporaria}"
                },
                timeout=5
            )
        except Exception as e:
            print(f"Erro ao enviar via Mailgun: {e}")

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
    user_id = session.get('user_id')
    imovel_obj_id = ObjectId(imoid)
    user = db.users.find_one({"_id": ObjectId(user_id)})
    favoritos = user.get("favoritos", [])
    
    if imovel_obj_id in favoritos:
        db.users.update_one({"_id": ObjectId(user_id)}, {"$pull": {"favoritos": imovel_obj_id}})
        favoritado = False
    else:
        db.users.update_one({"_id": ObjectId(user_id)}, {"$push": {"favoritos": imovel_obj_id}})
        favoritado = True  
    return {"status": "success", "favoritado": favoritado}

@app.route('/api/enviar-otp-favorito', methods=['POST'])
def enviar_otp_favorito():
    dados = request.json
    email = sanitizar_texto(dados.get('email'))
    nome = sanitizar_texto(dados.get('nome'))
    telefone = sanitizar_texto(dados.get('telefone'))
    imovel_id = dados.get('imovel_id')
    
    if not email:
        return jsonify({"status": "error", "message": "E-mail obrigatório."}), 400
        
    if mongo.db.users.find_one({"email": email}):
        return jsonify({"status": "error", "message": "Este e-mail já está cadastrado no sistema. Faça login para continuar."}), 400
        
    codigo = str(random.randint(1000, 9999))
    codigos_otp_temp[email] = {
        "codigo": codigo,
        "nome": nome,
        "telefone": telefone,
        "imovel_id": imovel_id
    }
    
    api_key = os.getenv('MAILGUN_API_KEY')
    domain = os.getenv('MAILGUN_DOMAIN')
    try:
        requests.post(
            f"https://api.mailgun.net/v3/{domain}/messages",
            auth=("api", api_key),
            data={
                "from": f"Teca Borges Imóveis <postmaster@{domain}>",
                "to": [email],
                "subject": "Teca Borges - Código de verificação para favoritar imóvel",
                "text": f"Olá {nome}!\n\nSeu código de verificação é: {codigo}\n"
                f"Sua senha provisória de acesso é: 123456\n\n"
                f"Você pode alterá-la a qualquer momento acessando o seu painel de perfil no site."
            },
            timeout=5
        )
    except Exception as e:
        print(f"Erro ao enviar OTP via Mailgun: {e}")
    return jsonify({"status": "success"})

@app.route('/api/verificar-otp-e-salvar-favorito', methods=['POST'])
def verificar_otp_e_salvar_favorito():
    dados = request.json
    email = sanitizar_texto(dados.get('email'))
    codigo_informado = dados.get('codigo')
    
    registro = codigos_otp_temp.get(email)
    if registro and registro["codigo"] == codigo_informado:
        db = mongo.db
        nome = registro["nome"]
        telefone = registro["telefone"]
        imovel_id_str = registro["imovel_id"]
        imovel_obj_id = ObjectId(imovel_id_str)
        
        user = db.users.find_one({"email": email})
        if user:
            user_id = user["_id"]
            db.users.update_one({"_id": user_id}, {"$set": {"nome": nome, "telefone": telefone}})
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
                "criado_em": datetime.utcnow()
            })
            user_id = res_user.inserted_id

        db.users.update_one({"_id": user_id}, {"$addToSet": {"favoritos": imovel_obj_id}})
        db.leads.insert_one({
            "nome": nome,
            "email": email,
            "telefone": telefone,
            "imovel_id": imovel_obj_id,
            "origem": "Modal Favorito Site (OTP)",
            "criado_em": datetime.utcnow()
        })
        
        session['user_id'] = str(user_id)
        session['user_nome'] = nome
        session['papel'] = "cliente"
        
        del codigos_otp_temp[email]
        return jsonify({"status": "success", "redirect_url": url_for('meus_favoritos')})
    return jsonify({"status": "error", "message": "Código incorreto!"}), 400

@app.route('/imovel/agendar/<imoid>', methods=['POST'])
@login_required
def agendar_visita(imoid):
    db = mongo.db
    user_id = session.get('user_id')
    data = request.form.get('data')
    hora = request.form.get('hora')
    observacoes = sanitizar_texto(request.form.get('observacoes', ''))
    
    if not data or not hora:
        flash('Informe a data e o horário desejados.', 'danger')
        return redirect(request.referrer or url_for('index'))
        
    data_hora = datetime.strptime(f"{data} {hora}", '%Y-%m-%d %H:%M:%S')
    db.agendamentos.insert_one({
        "cliente_id": ObjectId(user_id),
        "imovel_id": ObjectId(imoid),
        "data_hora": data_hora,
        "observacoes": observacoes,
        "status": "pendente",
        "criado_em": datetime.utcnow()
    })
    flash('Visita agendada com sucesso!', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/cliente/favoritos')
@login_required
def meus_favoritos():
    db = mongo.db
    user = db.users.find_one({"_id": ObjectId(session.get('user_id'))})
    fav_ids = user.get("favoritos", [])
    imoveis_favoritos = list(db.imoveis.find({"_id": {"$in": fav_ids}, "status": "ativo"}))
    return render_template('cliente/favoritos.html', imoveis=imoveis_favoritos, active_tab='favoritos')

@app.route('/cliente/agendamentos')
@login_required
def meus_agendamentos():
    db = mongo.db
    pipeline = [
        {"$match": {"cliente_id": ObjectId(session.get('user_id'))}},
        {"$sort": {"data_hora": 1}},
        {"$lookup": {"from": "imoveis", "localField": "imovel_id", "foreignField": "_id", "as": "imovel_info"}},
        {"$unwind": {"path": "$imovel_info", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {"from": "imoveis_enderecos", "localField": "imovel_id", "foreignField": "imovel_id", "as": "endereco_privado"}},
        {"$unwind": {"path": "$endereco_privado", "preserveNullAndEmptyArrays": True}}
    ]
    agendamentos = list(db.agendamentos.aggregate(pipeline)) if 'agendamentos' in db.list_collection_names() else []
    return render_template('cliente/agendamentos.html', agendamentos=agendamentos, active_tab='agendamentos')

@app.route('/perfil', methods=['GET', 'POST'])
@login_required
def meu_perfil():
    db = mongo.db
    user_id = session.get('user_id')
    user = db.users.find_one({"_id": ObjectId(user_id)})
    
    if request.method == 'POST':
        nome = sanitizar_texto(request.form.get('nome'))
        email = sanitizar_texto(request.form.get('email'))
        telefone = sanitizar_texto(request.form.get('telefone'))
        nova_senha = request.form.get('senha')
        
        if email != user.get('email'):
            existe_outro = db.users.find_one({"email": email, "_id": {"$ne": ObjectId(user_id)}})
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
            
        db.users.update_one({"_id": ObjectId(user_id)}, {"$set": update_data})
        session['user_nome'] = nome
        
        return redirect(url_for('meu_perfil'))
        
    return render_template('admin/perfil.html', user=user, active_tab='perfil')

# --- ROTAS DE GESTÃO DE IMÓVEIS (RESTRITAS EXCLUSIVAMENTE AO ADMIN) ---

# --- SUPER PAINEL DO ADMINISTRADOR ---

@app.route('/admin/painel')
@login_required
@admin_required
def admin_painel():
    db = mongo.db
    
    # Lista de corretores/admins para os selects de atribuição
    corretores = list(db.users.find({"papel": {"$in": ["corretor", "admin"]}}))
    
    # 1. LEADS (Excluindo as buscas personalizadas)
    pipeline_leads = [
        {"$match": {"origem": {"$ne": "Busca Personalizada Site (OTP)"}}},
        {"$sort": {"criado_em": -1}},
        {"$lookup": {"from": "imoveis", "localField": "imovel_id", "foreignField": "_id", "as": "imovel_info"}},
        {"$unwind": {"path": "$imovel_info", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {"from": "users", "localField": "corretor_responsavel_id", "foreignField": "_id", "as": "corretor_info"}},
        {"$unwind": {"path": "$corretor_info", "preserveNullAndEmptyArrays": True}}
    ]
    leads = list(db.leads.aggregate(pipeline_leads))
    
    # 2. AGENDAMENTOS
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
    
    # 3. BUSCA PRA MIM (Solicitações de busca personalizada)
    pipeline_buscas = [
        {"$match": {"origem": "Busca Personalizada Site (OTP)"}},
        {"$sort": {"criado_em": -1}},
        {"$lookup": {"from": "users", "localField": "corretor_responsavel_id", "foreignField": "_id", "as": "corretor_info"}},
        {"$unwind": {"path": "$corretor_info", "preserveNullAndEmptyArrays": True}}
    ]
    buscas = list(db.leads.aggregate(pipeline_buscas))
    
    # 4. CURTIDAS (Relatório de usuários e imóveis favoritados)
    usuarios_favoritos = list(db.users.find({"favoritos": {"$exists": True, "$not": {"$size": 0}}}))
    curtidas_lista = []
    for u in usuarios_favoritos:
        favs = u.get("favoritos", [])
        imoveis_favs = list(db.imoveis.find({"_id": {"$in": favs}}))
        for imv in imoveis_favs:
            curtidas_lista.append({
                "cliente": u,
                "imovel": imv
            })
            
    hoje_str = date.today().isoformat()
    
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


# --- AÇÕES DO ADMIN: ATRIBUIR / REAGENDAR ---

@app.route('/admin/lead/atribuir/<lead_id>', methods=['POST'])
@login_required
@admin_required
def admin_atribuir_lead(lead_id):
    db = mongo.db
    corretor_id = request.form.get('corretor_id')
    
    update_data = {
        "corretor_responsavel_id": ObjectId(corretor_id) if corretor_id else None,
        "status": "em_andamento" if corretor_id else "pendente",
        "atualizado_em": datetime.utcnow()
    }
    
    db.leads.update_one({"_id": ObjectId(lead_id)}, {"$set": update_data})
    flash('Corretor atribuído com sucesso!', 'success')
    return redirect(url_for('admin_painel') + '#leads')

# --- GERAR LEAD A PARTIR DE UMA CURTIDA ---
@app.route('/admin/curtida/gerar-lead', methods=['POST'])
@login_required
@admin_required
def admin_gerar_lead_de_curtida():
    db = mongo.db
    user_id = request.form.get('user_id')
    imovel_id = request.form.get('imovel_id')
    corretor_id = request.form.get('corretor_id')
    
    cliente = db.users.find_one({"_id": ObjectId(user_id)})
    if not cliente:
        flash('Cliente não encontrado.', 'danger')
        return redirect(url_for('admin_painel') + '#curtidas')
        
    # Insere o novo lead na coleção de leads
    db.leads.insert_one({
        "nome": cliente.get('nome'),
        "email": cliente.get('email'),
        "telefone": cliente.get('telefone'),
        "imovel_id": ObjectId(imovel_id),
        "origem": "Curtida de Imóvel (Painel Admin)",
        "corretor_responsavel_id": ObjectId(corretor_id) if corretor_id else None,
        "status": "em_andamento" if corretor_id else "pendente",
        "criado_em": datetime.utcnow()
    })
    
    flash('Lead gerado com sucesso a partir da curtida!', 'success')
    return redirect(url_for('admin_painel') + '#leads')

@app.route('/admin/agendamento/atribuir/<ag_id>', methods=['POST'])
@login_required
@admin_required
def admin_atribuir_agendamento(ag_id):
    db = mongo.db
    corretor_id = request.form.get('corretor_id')
    
    update_data = {
        "corretor_responsavel_id": ObjectId(corretor_id) if corretor_id else None,
        "status": "em_andamento" if corretor_id else "pendente",
        "atualizado_em": datetime.utcnow()
    }
    
    db.agendamentos.update_one({"_id": ObjectId(ag_id)}, {"$set": update_data})
    flash('Corretor atribuído ao agendamento com sucesso!', 'success')
    return redirect(url_for('admin_painel') + '#agendamentos')

@app.route('/admin/agendamento/reagendar/<ag_id>', methods=['POST'])
@login_required
@admin_required
def admin_reagendar_visita(ag_id):
    db = mongo.db
    nova_data = request.form.get('nova_data')
    nova_hora = request.form.get('nova_hora')
    
    if not nova_data or not nova_hora:
        flash('Informe a nova data e o horário.', 'danger')
        return redirect(url_for('admin_painel') + '#agendamentos')
        
    try:
        if len(nova_hora.split(':')) == 2:
            nova_hora += ":00"
        data_hora_nova = datetime.strptime(f"{nova_data} {nova_hora}", '%Y-%m-%d %H:%M:%S')
    except Exception:
        flash('Formato inválido.', 'danger')
        return redirect(url_for('admin_painel') + '#agendamentos')
        
    db.agendamentos.update_one(
        {"_id": ObjectId(ag_id)},
        {
            "$set": {
                "data_hora": data_hora_nova,
                "status": "reagendado",
                "atualizado_em": datetime.utcnow()
            }
        }
    )
    flash('Visita reagendada com sucesso!', 'success')
    return redirect(url_for('admin_painel') + '#agendamentos')

@app.route('/admin/imoveis')
@login_required
@admin_required
def admin_imoveis():
    db = mongo.db
    tipo_filtro = request.args.get('tipo')
    query = {"status": "ativo"}
    if tipo_filtro:
        query["tipo"] = tipo_filtro
    imoveis = list(db.imoveis.find(query))
    return render_template('admin/imoveis_lista.html', imoveis=imoveis, tipo_atual=tipo_filtro, active_tab='imoveis')

@app.route('/admin/imoveis/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_imovel_novo():
    db = mongo.db
    if request.method == 'POST':
        codigo = gerar_proximo_codigo()
        titulo = sanitizar_texto(request.form.get('titulo'))
        slug = sanitizar_texto(request.form.get('slug')) or titulo.lower().replace(" ", "-")
        
        condominio_id = request.form.get('condominio_id')
        corretor_id = request.form.get('corretor_id')
        
        pasta_imovel = os.path.join(app.config['UPLOAD_FOLDER'], codigo)
        os.makedirs(pasta_imovel, exist_ok=True)
        
        lista_fotos = processar_upload_fotos_dinamicas(request.files, request.form, codigo, pasta_imovel)

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
                "vagas": int(request.form.get('vagas') or 0)
            },
            "local_publico": {
                "bairro": sanitizar_texto(request.form.get('bairro')),
                "cidade": sanitizar_texto(request.form.get('cidade', 'São Paulo')),
                "estado": sanitizar_texto(request.form.get('estado', 'SP'))
            },
            "condominio_id": ObjectId(condominio_id) if condominio_id else None,
            "corretor_id": ObjectId(corretor_id) if corretor_id else None,
            "midia": {"fotos": lista_fotos},
            "criado_em": datetime.utcnow()
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
        
        flash(f'Imóvel {codigo} cadastrado com sucesso!', 'success')
        return redirect(url_for('admin_imoveis'))
        
    corretores = list(db.users.find({"papel": {"$in": ["corretor", "admin"]}}))
    condominios = list(db.condominios.find())
    codigo_sugerido = gerar_proximo_codigo()
    return render_template('admin/imovel_form.html', corretores=corretores, condominios=condominios, codigo_sugerido=codigo_sugerido, active_tab='imoveis')

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
        condominio_id = request.form.get('condominio_id')
        corretor_id = request.form.get('corretor_id')
        
        pasta_imovel = os.path.join(app.config['UPLOAD_FOLDER'], codigo)
        os.makedirs(pasta_imovel, exist_ok=True)
        
        fotos_atuais = imovel.get("midia", {}).get("fotos", [])
        lista_fotos = processar_upload_fotos_dinamicas(request.files, request.form, codigo, pasta_imovel, fotos_atuais)
        
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
                    "local_publico.bairro": sanitizar_texto(request.form.get('bairro')),
                    "condominio_id": ObjectId(condominio_id) if condominio_id else None,
                    "corretor_id": ObjectId(corretor_id) if corretor_id else None,
                    "midia.fotos": lista_fotos
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
        
    corretores = list(db.users.find({"papel": {"$in": ["corretor", "admin"]}}))
    condominios = list(db.condominios.find())
    endereco = db.imoveis_enderecos.find_one({"imovel_id": imovel["_id"]})
    
    return render_template(
        'admin/imovel_form.html', 
        imovel=imovel, 
        endereco=endereco,
        corretores=corretores, 
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
    dados = request.json
    caminho_foto = dados.get('arquivo')
    
    imovel = db.imoveis.find_one({"codigo": codigo})
    if not imovel:
        return jsonify({"status": "error", "message": "Imóvel não encontrado."}), 404
        
    fotos = imovel.get("midia", {}).get("fotos", [])
    novas_fotos = [f for f in fotos if f.get("arquivo") != caminho_foto]
    
    if caminho_foto:
        caminho_fisico = os.path.join(app.root_path, 'static', caminho_foto)
        if os.path.exists(caminho_fisico):
            try:
                os.remove(caminho_fisico)
            except Exception as e:
                print(f"Erro ao deletar arquivo físico: {e}")
                
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
    db.imoveis.update_one({"codigo": codigo}, {"$set": {"status": "inativo", "desativado_em": datetime.utcnow()}})
    flash(f'Imóvel {codigo} desativado.', 'info')
    return redirect(url_for('admin_imoveis'))

# --- GESTÃO DE USUÁRIOS (ADMIN) ---

@app.route('/admin/usuarios', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_usuarios():
    db = mongo.db
    if request.method == 'POST':
        nome = sanitizar_texto(request.form.get('nome'))
        email = sanitizar_texto(request.form.get('email'))
        senha = request.form.get('senha')
        papel = sanitizar_texto(request.form.get('papel'))
        telefone = sanitizar_texto(request.form.get('telefone'))
        
        if db.users.find_one({"email": email}):
            flash('Este e-mail já está cadastrado no sistema!', 'danger')
        else:
            senha_hash = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt())
            db.users.insert_one({
                "nome": nome, 
                "email": email, 
                "senha_hash": senha_hash, 
                "telefone": telefone, 
                "papel": papel, 
                "ativo": True, 
                "criado_em": datetime.utcnow()
            })
            flash('Cadastrado com sucesso!', 'success')
            return redirect(url_for('admin_usuarios'))
            
    usuarios = list(db.users.find())
    return render_template('admin/usuarios.html', usuarios=usuarios, active_tab='usuarios')

@app.route('/admin/usuarios/alterar-papel/<user_id>', methods=['POST'])
@login_required
@admin_required
def alterar_papel(user_id):
    db = mongo.db
    novo_papel = sanitizar_texto(request.form.get('papel'))
    
    if novo_papel in ['admin', 'corretor', 'cliente']:
        db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"papel": novo_papel}}
        )
        
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/usuarios/excluir/<user_id>')
@login_required
@admin_required
def excluir_usuario(user_id):
    db = mongo.db
    db.users.delete_one({"_id": ObjectId(user_id)})
    return redirect(url_for('admin_usuarios'))

# --- PAINEL DO CORRETOR ---

@app.route('/corretor/painel')
@login_required
def painel_corretor():
    db = mongo.db
    corretor_id = ObjectId(session.get('user_id'))
    papel = session.get('papel')
    
    # REGRA DE VISIBILIDADE DOS AGENDAMENTOS
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
    
    hoje_str = date.today().isoformat()

    # REGRA DE VISIBILIDADE DOS LEADS
    query_leads_filtro = {}
    if papel != 'admin':
        query_leads_filtro = {
            "$or": [
                {"corretor_responsavel_id": {"$exists": False}},
                {"corretor_responsavel_id": None},
                {"status": "pendente"},
                {"corretor_responsavel_id": corretor_id}
            ]
        }

    pipeline_leads = [
        {"$match": query_leads_filtro},
        {"$sort": {"criado_em": -1}},
        {"$lookup": {"from": "imoveis", "localField": "imovel_id", "foreignField": "_id", "as": "imovel_info"}},
        {"$unwind": {"path": "$imovel_info", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {"from": "imoveis_enderecos", "localField": "imovel_id", "foreignField": "imovel_id", "as": "endereco_privado"}},
        {"$unwind": {"path": "$endereco_privado", "preserveNullAndEmptyArrays": True}}
    ]
    leads = list(db.leads.aggregate(pipeline_leads))
    
    return render_template('corretor/painel.html', 
                           leads=leads, 
                           agendamentos=agendamentos, 
                           today=hoje_str, 
                           active_tab='painel_corretor')

# --- ASSUMIR / ATENDER LEAD ---
@app.route('/corretor/lead/atender/<lead_id>')
@login_required
@corretor_ou_admin_required
def atender_lead(lead_id):
    db = mongo.db
    corretor_id = ObjectId(session.get('user_id'))
    
    resultado = db.leads.find_one_and_update(
        {
            "_id": ObjectId(lead_id),
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
                "atualizado_em": datetime.utcnow()
            }
        },
        return_document=True
    )
    
    if not resultado:
        flash('Este lead já foi assumido por outro corretor!', 'warning')
    else:
        flash('Você assumiu este lead com sucesso!', 'success')
        
    return redirect(url_for('painel_corretor') + '#leads')

# --- 1. ASSUMIR / ATENDER AGENDAMENTO ---
@app.route('/corretor/agendamento/atender/<ag_id>')
@login_required
@corretor_ou_admin_required
def atender_agendamento(ag_id):
    db = mongo.db
    corretor_id = ObjectId(session.get('user_id'))
    
    resultado = db.agendamentos.find_one_and_update(
        {
            "_id": ObjectId(ag_id),
            "status": "pendente"
        },
        {
            "$set": {
                "status": "em_andamento",
                "corretor_responsavel_id": corretor_id,
                "atualizado_em": datetime.utcnow()
            }
        },
        return_document=True
    )
    
    if not resultado:
        flash('Este atendimento já foi assumido por outro corretor!', 'warning')
    else:
        flash('Você assumiu este atendimento com sucesso!', 'success')
        
    return redirect(url_for('painel_corretor'))

# --- 2. ALTERAR STATUS (CONCLUÍDO / CANCELADO) ---
@app.route('/corretor/agendamento/status/<ag_id>/<novo_status>')
@login_required
@corretor_ou_admin_required
def alterar_status_agendamento_corretor(ag_id, novo_status):
    db = mongo.db
    corretor_id = ObjectId(session.get('user_id'))
    
    papel = session.get('papel')
    query = {"_id": ObjectId(ag_id)}
    if papel != 'admin':
        query["corretor_responsavel_id"] = corretor_id

    resultado = db.agendamentos.update_one(
        query,
        {"$set": {"status": novo_status, "atualizado_em": datetime.utcnow()}}
    )
    
    if resultado.modified_count > 0:
        flash('Status do agendamento atualizado com sucesso!', 'success')
    else:
        flash('Ação não permitida ou agendamento não encontrado.', 'danger')
        
    return redirect(url_for('painel_corretor'))

# --- 3. REAGENDAR VISITA (COM NOVA DATA E HORA) ---
@app.route('/corretor/agendamento/reagendar/<ag_id>', methods=['POST'])
@login_required
@corretor_ou_admin_required
def reagendar_visita_corretor(ag_id):
    db = mongo.db
    corretor_id = ObjectId(session.get('user_id'))
    nova_data = request.form.get('nova_data')
    nova_hora = request.form.get('nova_hora')
    
    if not nova_data or not nova_hora:
        flash('Informe a nova data e o novo horário para o reagendamento.', 'danger')
        return redirect(url_for('painel_corretor'))
        
    try:
        if len(nova_hora.split(':')) == 2:
            nova_hora += ":00"
        data_hora_nova = datetime.strptime(f"{nova_data} {nova_hora}", '%Y-%m-%d %H:%M:%S')
    except Exception as e:
        flash('Formato de data ou hora inválido.', 'danger')
        return redirect(url_for('painel_corretor'))

    papel = session.get('papel')
    query = {"_id": ObjectId(ag_id)}
    if papel != 'admin':
        query["corretor_responsavel_id"] = corretor_id

    resultado = db.agendamentos.update_one(
        query,
        {
            "$set": {
                "data_hora": data_hora_nova,
                "status": "reagendado",
                "atualizado_em": datetime.utcnow()
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