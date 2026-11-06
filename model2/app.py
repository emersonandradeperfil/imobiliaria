import logging

from flask import Flask, render_template
from flask_wtf.csrf import CSRFProtect

import helpers
from config import Config
from extensions import ensure_indexes

csrf = CSRFProtect()


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    csrf.init_app(app)
    if app.config.get("TRUST_PROXY"):
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    @app.after_request
    def cabecalhos(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return resp

    from blueprints.account import bp as account_bp
    from blueprints.admin import bp as admin_bp
    from blueprints.auth import bp as auth_bp
    from blueprints.leads import bp as leads_bp
    from blueprints.public import bp as public_bp

    for bp in (public_bp, auth_bp, account_bp, leads_bp, admin_bp):
        app.register_blueprint(bp)

    app.jinja_env.filters["brl"] = helpers.brl
    app.jinja_env.filters["data_br"] = helpers.data_br
    app.jinja_env.filters["whatsapp"] = helpers.whatsapp
    app.jinja_env.globals.update(
        foto_url=helpers.foto_url,
        capa=helpers.capa,
        youtube_embed=helpers.youtube_embed,
        usuario_atual=helpers.usuario_atual,
    )

    @app.errorhandler(403)
    def erro_403(e):
        return render_template("erro.html", codigo=403, msg="Você não tem acesso a esta página."), 403

    @app.errorhandler(404)
    def erro_404(e):
        return render_template("erro.html", codigo=404, msg="Página não encontrada."), 404

    if not app.testing:
        try:
            with app.app_context():
                ensure_indexes()
        except Exception as exc:  # sem banco no boot não derruba o app
            logging.getLogger(__name__).warning("Não criei índices: %s", exc)

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
