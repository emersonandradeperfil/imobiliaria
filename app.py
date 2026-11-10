import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from database import init_db, mongo
import bcrypt
from datetime import datetime
from functools import wraps
from werkzeug.utils import secure_filename
from bson.objectid import ObjectId

app = Flask(__name__)
app.secret_key = "123456"  # Chave de sessão

init_db(app)

# Configuração da pasta de uploads de imóveis
UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'upload')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Decorators de Segurança e Permissões
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Faça login para acessar esta página.', 'warning')
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

# Helper para gerar o próximo código sequencial (ex: AP0002)
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

# --- ROTAS PÚBLICAS E CLIENTE ---

@app.route('/')
def index():
    db = mongo.db
    # Busca apenas os ativos e em destaque
    imoveis_ativos = list(db.imoveis.find({"status": "ativo", "destaque": True}).sort("criado_em", -1))
    
    # Separa por categorias dinamicamente
    secoes = {
        "Apartamentos": [i for i in imoveis_ativos if i.get('tipo') == 'apartamento'],
        "Coberturas": [i for i in imoveis_ativos if i.get('tipo') == 'cobertura'],
        "Casas de Condomínio": [i for i in imoveis_ativos if i.get('tipo') == 'casa'],
        "Conjuntos Comerciais": [i for i in imoveis_ativos if i.get('tipo') == 'comercial']
    }
    
    return render_template('index.html', secoes=secoes)

@app.route('/imovel/<slug>')
def imovel_detalhe(slug):
    db = mongo.db
    imovel = db.imoveis.find_one({"slug": slug})
    if not imovel:
        return "Imóvel não encontrado", 404
    
    condominio = db.condominios.find_one({"_id": imovel.get("condominio_id")})
    
    endereco_privado = None
    if 'user_id' in session:
        endereco_privado = db.imoveis_enderecos.find_one({"imovel_id": imovel["_id"]})
        
    return render_template(
        'imovel_detalhe.html', 
        imovel=imovel, 
        condominio=condominio, 
        endereco_privado=endereco_privado
    )

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        senha = request.form.get('senha')
        
        user = mongo.db.users.find_one({"email": email})
        if user and bcrypt.checkpw(senha.encode('utf-8'), user['senha_hash'].encode('utf-8') if isinstance(user['senha_hash'], str) else user['senha_hash']):
            session['user_id'] = str(user['_id'])
            session['user_nome'] = user['nome']
            session['papel'] = user['papel']
            flash('Login realizado com sucesso!', 'success')
            
            if user['papel'] == 'admin':
                return redirect(url_for('admin_imoveis'))
            elif user['papel'] == 'corretor':
                return redirect(url_for('painel_corretor'))
            return redirect(url_for('index'))
        else:
            flash('E-mail ou senha inválidos.', 'danger')
            
    return render_template('login.html')

@app.route('/cadastrar', methods=['GET', 'POST'])
def cadastrar_cliente():
    if request.method == 'POST':
        nome = request.form.get('nome')
        email = request.form.get('email')
        senha = request.form.get('senha')
        telefone = request.form.get('telefone')
        
        if mongo.db.users.find_one({"email": email}):
            flash('Este e-mail já está cadastrado.', 'danger')
            return redirect(url_for('login'))
            
        senha_hash = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt())
        
        mongo.db.users.insert_one({
            "nome": nome,
            "email": email,
            "senha_hash": senha_hash,
            "telefone": telefone,
            "papel": "cliente",
            "ativo": True,
            "favoritos": [],
            "criado_em": datetime.utcnow()
        })
        
        flash('Cadastro realizado com sucesso! Faça login para continuar.', 'success')
        return redirect(url_for('login'))
        
    return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    flash('Você saiu da sua conta.', 'info')
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
        favoritado = True  # True em Python vira true em JSON puro
        
    # Retorna um JSON para o JavaScript atualizar a tela sem refresh
    return {"status": "success", "favoritado": favoritado}

@app.route('/imovel/agendar/<imoid>', methods=['POST'])
@login_required
def agendar_visita(imoid):
    db = mongo.db
    user_id = session.get('user_id')
    
    data = request.form.get('data')
    hora = request.form.get('hora')
    observacoes = request.form.get('observacoes', '')
    
    if not data or not hora:
        flash('Informe a data e o horário desejados para o agendamento.', 'danger')
        return redirect(request.referrer or url_for('index'))
        
    data_hora_str = f"{data} {hora}"
    try:
        data_hora = datetime.strptime(data_hora_str, '%Y-%m-%d %H:%M')
    except ValueError:
        data_hora = datetime.utcnow()
        
    db.agendamentos.insert_one({
        "cliente_id": ObjectId(user_id),
        "imovel_id": ObjectId(imoid),
        "data_hora": data_hora,
        "observacoes": observacoes,
        "status": "pendente",
        "criado_em": datetime.utcnow()
    })
    
    flash('Visita agendada com sucesso! O corretor entrará em contato para confirmação.', 'success')
    return redirect(request.referrer or url_for('index'))

# Rota para capturar Lead via Modal de Favoritos (Visitantes não logados)
@app.route('/api/lead-favorito', methods=['POST'])
def api_lead_favorito():
    db = mongo.db
    data = request.get_json()
    
    nome = data.get('nome')
    email = data.get('email')
    telefone = data.get('telefone')
    imovel_id_str = data.get('imovel_id')
    
    if not email or not imovel_id_str:
        return {"status": "error", "message": "Dados incompletos."}, 400
        
    imovel_obj_id = ObjectId(imovel_id_str)
    
    # Verifica se o usuário já existe no sistema pelo e-mail
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
        user = db.users.find_one({"_id": user_id})

    # Adiciona o imóvel aos favoritos do usuário
    db.users.update_one(
        {"_id": user_id},
        {"$addToSet": {"favoritos": imovel_obj_id}}
    )
    
    # Registra o contato na coleção de Leads para o corretor acompanhar
    db.leads.insert_one({
        "nome": nome,
        "email": email,
        "telefone": telefone,
        "imovel_id": imovel_obj_id,
        "origem": "Modal Favorito Site",
        "criado_em": datetime.utcnow()
    })
    
    # Faz o login automático na sessão do navegador
    session['user_id'] = str(user_id)
    session['user_nome'] = nome
    session['papel'] = user.get('papel', 'cliente')
    
    return {"status": "success", "message": "Lead capturado com sucesso!"}

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
    agendamentos = list(db.agendamentos.find({"cliente_id": ObjectId(session.get('user_id'))})) if 'agendamentos' in db.list_collection_names() else []
    
    return render_template('cliente/agendamentos.html', agendamentos=agendamentos, active_tab='agendamentos')

# --- PAINEL ADMIN (CRUD IMOVEIS E USUÁRIOS) ---

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
    return render_template('admin/imoveis_lista.html', imoveis=imoveis, tipo_atual=tipo_filtro)

@app.route('/admin/imoveis/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_imovel_novo():
    db = mongo.db
    if request.method == 'POST':
        codigo = gerar_proximo_codigo()
        titulo = request.form.get('titulo')
        slug = request.form.get('slug') or titulo.lower().replace(" ", "-")
        
        condominio_id = request.form.get('condominio_id')
        corretor_id = request.form.get('corretor_id')
        
        # Processamento do Upload da Imagem
        foto_relativa = f"upload/{codigo}/default.jpg"
        file = request.files.get('foto_capa')
        
        pasta_imovel = os.path.join(app.config['UPLOAD_FOLDER'], codigo)
        os.makedirs(pasta_imovel, exist_ok=True)
        
        if file and file.filename != '':
            extensao = os.path.splitext(file.filename)[1]
            nome_arquivo = secure_filename(f"{codigo}_capa{extensao}")
            caminho_salvar = os.path.join(pasta_imovel, nome_arquivo)
            file.save(caminho_salvar)
            foto_relativa = f"upload/{codigo}/{nome_arquivo}"

        imovel_doc = {
            "codigo": codigo,
            "slug": slug,
            "titulo": titulo,
            "descricao": request.form.get('descricao'),
            "tipo": request.form.get('tipo'),
            "status": "ativo",
            "destaque": True if request.form.get('destaque') == '1' else False,
            "precos": {
                "venda": float(request.form.get('preco_venda') or 0),
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
                "bairro": request.form.get('bairro'),
                "cidade": request.form.get('cidade', 'São Paulo'),
                "estado": request.form.get('estado', 'SP')
            },
            "condominio_id": ObjectId(condominio_id) if condominio_id else None,
            "corretor_id": ObjectId(corretor_id) if corretor_id else None,
            "midia": {
                "fotos": [{"arquivo": foto_relativa, "legenda": "Capa", "ordem": 1, "capa": True}]
            },
            "criado_em": datetime.utcnow()
        }
        
        res = db.imoveis.insert_one(imovel_doc)
        
        andar_input = request.form.get('andar')
        andar_val = int(andar_input) if andar_input and andar_input.strip() != "" else None

        db.imoveis_enderecos.insert_one({
            "imovel_id": res.inserted_id,
            "logradouro": request.form.get('logradouro'),
            "numero": request.form.get('numero'),
            "complemento": request.form.get('complemento', ''),
            "cep": request.form.get('cep', ''),
            "andar": andar_val,
            "posicao_solar": request.form.get('posicao_solar', '')
        })
        
        flash(f'Imóvel {codigo} cadastrado com sucesso!', 'success')
        return redirect(url_for('admin_imoveis'))
        
    corretores = list(db.users.find({"papel": {"$in": ["corretor", "admin"]}}))
    condominios = list(db.condominios.find())
    codigo_sugerido = gerar_proximo_codigo()
    return render_template('admin/imovel_form.html', corretores=corretores, condominios=condominios, codigo_sugerido=codigo_sugerido)

@app.route('/admin/imovel/editar/<codigo>', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_imovel(codigo):
    db = mongo.db
    imovel = db.imoveis.find_one({"codigo": codigo})
    
    if not imovel:
        flash("Imóvel não encontrado.", "error")
        return redirect(url_for('admin_imoveis'))
        
    endereco = db.imoveis_enderecos.find_one({"imovel_id": imovel["_id"]})
    
    if request.method == 'POST':
        titulo = request.form.get('titulo')
        slug = request.form.get('slug') or titulo.lower().replace(" ", "-")
        is_destaque = True if request.form.get('destaque') == '1' else False
        
        # Garante a existência da pasta física do imóvel
        pasta_imovel = os.path.join(app.config['UPLOAD_FOLDER'], codigo)
        os.makedirs(pasta_imovel, exist_ok=True)
        
        # Processamento de nova imagem enviada na edição
        file = request.files.get('foto_capa')
        if file and file.filename != '':
            extensao = os.path.splitext(file.filename)[1]
            nome_arquivo = secure_filename(f"{codigo}_capa{extensao}")
            caminho_salvar = os.path.join(pasta_imovel, nome_arquivo)
            file.save(caminho_salvar)
            foto_relativa = f"upload/{codigo}/{nome_arquivo}"
            
            # Atualiza a foto de capa no banco se uma nova foi enviada
            db.imoveis.update_one(
                {"codigo": codigo},
                {"$set": {"midia.fotos": [{"arquivo": foto_relativa, "legenda": "Capa", "ordem": 1, "capa": True}]}}
            )
        
        # Atualiza dados públicos na coleção 'imoveis'
        db.imoveis.update_one(
            {"codigo": codigo},
            {"$set": {
                "titulo": titulo,
                "slug": slug,
                "descricao": request.form.get('descricao'),
                "tipo": request.form.get('tipo'),
                "destaque": is_destaque,
                "precos.venda": float(request.form.get('preco_venda') or 0),
                "caracteristicas.area_util": float(request.form.get('area_util') or 0),
                "caracteristicas.quartos": int(request.form.get('quartos') or 0),
                "caracteristicas.suites": int(request.form.get('suites') or 0),
                "caracteristicas.banheiros": int(request.form.get('banheiros') or 0),
                "caracteristicas.vagas": int(request.form.get('vagas') or 0),
                "local_publico.bairro": request.form.get('bairro'),
                "corretor_id": ObjectId(request.form.get('corretor_id')) if request.form.get('corretor_id') else None,
                "condominio_id": ObjectId(request.form.get('condominio_id')) if request.form.get('condominio_id') else None
            }}
        )
        
        andar_input = request.form.get('andar')
        andar_val = int(andar_input) if andar_input and andar_input.strip() != "" else None

        db.imoveis_enderecos.update_one(
            {"imovel_id": imovel["_id"]},
            {"$set": {
                "logradouro": request.form.get('logradouro'),
                "numero": request.form.get('numero'),
                "complemento": request.form.get('complemento', ''),
                "cep": request.form.get('cep', ''),
                "andar": andar_val,
                "posicao_solar": request.form.get('posicao_solar', '')
            }},
            upsert=True
        )
        
        flash(f"Imóvel {codigo} atualizado com sucesso!", "success")
        return redirect(url_for('admin_imoveis'))
        
    corretores = list(db.users.find({"papel": {"$in": ["corretor", "admin"]}}))
    condominios = list(db.condominios.find())
    return render_template('admin/imovel_form.html', imovel=imovel, endereco=endereco, corretores=corretores, condominios=condominios, editando=True)

@app.route('/admin/imoveis/excluir/<codigo>')
@login_required
@admin_required
def admin_imovel_excluir(codigo):
    db = mongo.db
    resultado = db.imoveis.update_one(
        {"codigo": codigo},
        {"$set": {"status": "inativo", "desativado_em": datetime.utcnow()}}
    )
    if resultado.modified_count > 0:
        flash(f'Imóvel {codigo} removido da vitrine do site (mantido no histórico interno do banco).', 'info')
    return redirect(url_for('admin_imoveis'))

@app.route('/admin/usuarios', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_usuarios():
    if request.method == 'POST':
        nome = request.form.get('nome')
        email = request.form.get('email')
        senha = request.form.get('senha')
        papel = request.form.get('papel')
        telefone = request.form.get('telefone')
        
        if mongo.db.users.find_one({"email": email}):
            flash('Este e-mail já existe.', 'danger')
        else:
            senha_hash = bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt())
            mongo.db.users.insert_one({
                "nome": nome,
                "email": email,
                "senha_hash": senha_hash,
                "telefone": telefone,
                "papel": papel,
                "ativo": True,
                "criado_em": datetime.utcnow()
            })
            flash(f'Usuário {nome} ({papel}) cadastrado com sucesso!', 'success')
            
    usuarios = list(mongo.db.users.find())
    return render_template('admin/usuarios.html', usuarios=usuarios)

@app.route('/admin/usuario/excluir/<user_id>')
@login_required
@admin_required
def excluir_usuario(user_id):
    db = mongo.db
    if session.get('user_id') == user_id:
        flash("Você não pode excluir sua própria conta logada.", "danger")
        return redirect(url_for('admin_usuarios'))
        
    db.users.delete_one({"_id": ObjectId(user_id)})
    flash("Usuário excluído com sucesso!", "info")
    return redirect(url_for('admin_usuarios'))

@app.route('/admin/usuario/alterar-papel/<user_id>', methods=['POST'])
@login_required
@admin_required
def alterar_papel(user_id):
    novo_papel = request.form.get('papel')
    db = mongo.db
    
    db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"papel": novo_papel}}
    )
    flash("Papel do usuário atualizado com sucesso!", "success")
    return redirect(url_for('admin_usuarios'))

@app.route('/perfil', methods=['GET', 'POST'])
@login_required
def meu_perfil():
    db = mongo.db
    user_id = session.get('user_id')
    user = db.users.find_one({"_id": ObjectId(user_id)})
    
    if request.method == 'POST':
        nome = request.form.get('nome')
        email = request.form.get('email')
        telefone = request.form.get('telefone')
        nova_senha = request.form.get('senha')
        
        # Verifica se o e-mail foi alterado e se já pertence a outro usuário
        if email != user.get('email'):
            existe_outro = db.users.find_one({"email": email, "_id": {"$ne": ObjectId(user_id)}})
            if existe_outro:
                flash("Este e-mail já está sendo utilizado por outro usuário.", "danger")
                return redirect(url_for('meu_perfil'))
        
        update_data = {
            "nome": nome,
            "email": email,
            "telefone": telefone
        }
        
        if nova_senha and nova_senha.strip() != "":
            update_data["senha_hash"] = bcrypt.hashpw(nova_senha.encode('utf-8'), bcrypt.gensalt())
            
        db.users.update_one({"_id": ObjectId(user_id)}, {"$set": update_data})
        session['user_nome'] = nome  # Atualiza a sessão caso o nome mude
        
        flash("Perfil atualizado com sucesso!", "success")
        return redirect(url_for('meu_perfil'))
        
    return render_template('admin/perfil.html', user=user, active_tab='perfil')

# --- PAINEL DO CORRETOR ---

@app.route('/corretor/painel')
@login_required
def painel_corretor():
    db = mongo.db
    
    # Pipeline para Leads
    pipeline_leads = [
        {"$sort": {"criado_em": -1}},
        {
            "$lookup": {
                "from": "imoveis",
                "localField": "imovel_id",
                "foreignField": "_id",
                "as": "imovel_info"
            }
        },
        {
            "$unwind": {
                "path": "$imovel_info",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$lookup": {
                "from": "imoveis_enderecos",
                "localField": "imovel_id",
                "foreignField": "imovel_id",
                "as": "endereco_privado"
            }
        },
        {
            "$unwind": {
                "path": "$endereco_privado",
                "preserveNullAndEmptyArrays": True
            }
        }
    ]
    leads = list(db.leads.aggregate(pipeline_leads))
    
    # Pipeline para Agendamentos (trazendo dados do cliente e do imóvel)
    pipeline_agendamentos = [
        {"$sort": {"data_hora": 1}},
        {
            "$lookup": {
                "from": "users",
                "localField": "cliente_id",
                "foreignField": "_id",
                "as": "cliente_info"
            }
        },
        {
            "$unwind": {
                "path": "$cliente_info",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$lookup": {
                "from": "imoveis",
                "localField": "imovel_id",
                "foreignField": "_id",
                "as": "imovel_info"
            }
        },
        {
            "$unwind": {
                "path": "$imovel_info",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$lookup": {
                "from": "imoveis_enderecos",
                "localField": "imovel_id",
                "foreignField": "imovel_id",
                "as": "endereco_privado"
            }
        },
        {
            "$unwind": {
                "path": "$endereco_privado",
                "preserveNullAndEmptyArrays": True
            }
        }

    ]
    agendamentos = list(db.agendamentos.aggregate(pipeline_agendamentos)) if 'agendamentos' in db.list_collection_names() else []
    
    return render_template('corretor/painel.html', leads=leads, agendamentos=agendamentos, active_tab='corretor')

if __name__ == '__main__':
    app.run(debug=True)