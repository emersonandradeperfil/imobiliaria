from flask import Flask, render_template, request, redirect, url_for, session, flash
from database import init_db, mongo
from bson import ObjectId
import bcrypt

app = Flask(__name__)
app.secret_key = "123456"

init_db(app)

@app.route('/')
def index():
    # Busca imóveis em destaque para a Home
    imoveis_destaque = list(db.imoveis.find({"destaque": True, "status": "ativo"}).limit(6))
    return render_template('index.html', imoveis=imoveis_destaque)

@app.route('/imovel/<slug>')
def imovel_detalhe(slug):
    imovel = db.imoveis.find_one({"slug": slug})
    if not imovel:
        return "Imóvel não encontrado", 404
    
    condominio = db.condominios.find_one({"_id": imovel.get("condominio_id")})
    
    # SEGURANÇA: Endereço, andar e posição solar só aparecem se o usuário estiver logado![cite: 3]
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
            return redirect(url_for('index'))
        else:
            flash('E-mail ou senha inválidos.', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Você saiu da sua conta.', 'info')
    return redirect(url_for('index'))

if __name__ == '__main__':
    db = mongo.db
    app.run(debug=True)