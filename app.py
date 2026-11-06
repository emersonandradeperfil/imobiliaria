from flask import Flask, render_template, request, redirect, url_for, session, flash
from database import init_db, mongo
import bcrypt
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = "123456"  # Chave de sessão

init_db(app)

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

# --- ROTAS PÚBLICAS E CLIENTE ---

@app.route('/')
def index():
    db = mongo.db
    imoveis_destaque = list(db.imoveis.find({"destaque": True, "status": "ativo"}).limit(6))
    return render_template('index.html', imoveis=imoveis_destaque)

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
            
            # Redireciona dependendo do papel
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
            return redirect(url_for('cadastrar_cliente'))
            
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
        
    return render_template('cadastrar.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Você saiu da sua conta.', 'info')
    return redirect(url_for('index'))

# --- PAINEL ADMIN (CRUD IMOVEIS E USUÁRIOS) ---

@app.route('/admin/imoveis')
@login_required
@admin_required
def admin_imoveis():
    imoveis = list(mongo.db.imoveis.find())
    return render_template('admin/imoveis_lista.html', imoveis=imoveis)

@app.route('/admin/imoveis/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_imovel_novo():
    if request.method == 'POST':
        db = mongo.db
        codigo = request.form.get('codigo')
        titulo = request.form.get('titulo')
        slug = request.form.get('slug') or titulo.lower().replace(" ", "-")
        
        # 1. Dados Públicos do Imóvel
        imovel_doc = {
            "codigo": codigo,
            "slug": slug,
            "titulo": titulo,
            "descricao": request.form.get('descricao'),
            "finalidade": request.form.getlist('finalidade'),
            "categoria": request.form.get('categoria'),
            "tipo": request.form.get('tipo'),
            "status": request.form.get('status', 'ativo'),
            "destaque": 'destaque' in request.form,
            "precos": {
                "venda": float(request.form.get('preco_venda') or 0),
                "condominio": float(request.form.get('preco_condominio') or 0),
                "iptu": float(request.form.get('preco_iptu') or 0)
            },
            "areas": {
                "util": float(request.form.get('area_util') or 0),
                "total": float(request.form.get('area_total') or 0)
            },
            "quartos": int(request.form.get('quartos') or 0),
            "suites": int(request.form.get('suites') or 0),
            "banheiros": int(request.form.get('banheiros') or 0),
            "vagas": int(request.form.get('vagas') or 0),
            "local_publico": {
                "bairro": request.form.get('bairro'),
                "cidade": request.form.get('cidade'),
                "estado": request.form.get('estado')
            },
            "midia": {
                "fotos": [{"arquivo": request.form.get('foto_capa'), "ordem": 1, "capa": True}]
            },
            "criado_em": datetime.utcnow()
        }
        
        res = db.imoveis.insert_one(imovel_doc)
        
        # 2. Dados Privados (Endereço, Andar e Posição Solar)
        db.imoveis_enderecos.insert_one({
            "imovel_id": res.inserted_id,
            "logradouro": request.form.get('logradouro'),
            "numero": request.form.get('numero'),
            "complemento": request.form.get('complemento'),
            "cep": request.form.get('cep'),
            "andar": int(request.form.get('andar') or 0),
            "posicao_solar": request.form.get('posicao_solar')
        })
        
        flash('Imóvel cadastrado com sucesso!', 'success')
        return redirect(url_for('admin_imoveis'))
        
    return render_template('admin/imovel_form.html')

@app.route('/admin/imoveis/excluir/<codigo>')
@login_required
@admin_required
def admin_imovel_excluir(codigo):
    db = mongo.db
    imovel = db.imoveis.find_one({"codigo": codigo})
    if imovel:
        db.imoveis_enderecos.delete_one({"imovel_id": imovel["_id"]})
        db.imoveis.delete_one({"_id": imovel["_id"]})
        flash('Imóvel excluído com sucesso!', 'success')
    return redirect(url_for('admin_imoveis'))

@app.route('/admin/usuarios', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_usuarios():
    if request.method == 'POST':
        # Cadastro de Usuários/Corretores pelo Admin
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

# --- PAINEL DO CORRETOR (FOCADO E SIMPLES) ---

@app.route('/corretor/painel')
@login_required
def painel_corretor():
    # Painel direto sem complicação para os corretores
    leads = list(mongo.db.leads.find().sort("criado_em", -1))
    agendamentos = list(mongo.db.agendamentos.find().sort("data_hora", 1))
    return render_template('corretor/painel.html', leads=leads, agendamentos=agendamentos)

if __name__ == '__main__':
    app.run(debug=True)