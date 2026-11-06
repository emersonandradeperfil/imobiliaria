import os
from flask_pymongo import PyMongo
from dotenv import load_dotenv

load_dotenv()

mongo = PyMongo()

def init_db(app):
    app.config["MONGO_URI"] = os.getenv("MONGO_URI")
    # app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "chave-padrao-insegura")
    mongo.init_app(app)
    return mongo