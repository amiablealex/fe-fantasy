"""Flask application factory."""
from __future__ import annotations

import logging

from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import get_config, validate_production_config
from app.extensions import csrf, db, login_manager, migrate

# Imported for their side effect: registering models on SQLAlchemy's metadata
# so Alembic autogenerate can see them. Do not remove.
from app import models  # noqa: F401


def create_app(config_class=None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    app.config.from_object(config_class or get_config())

    # Trust exactly one layer of proxy headers (Railway's edge). Without this,
    # `url_for(_external=True)` builds http:// links in reset emails and the
    # secure session cookie is never set.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    _configure_logging(app)
    validate_production_config(app)
    _init_extensions(app)
    _register_blueprints(app)
    _register_user_loader()
    _register_hooks(app)
    _register_error_handlers(app)
    _register_cli(app)

    return app


def _configure_logging(app: Flask) -> None:
    level = logging.DEBUG if app.config["DEBUG"] else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app.logger.setLevel(level)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

def _init_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)


def _register_blueprints(app: Flask) -> None:
    from app.admin.routes import admin_bp
    from app.auth.routes import auth_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    @app.route("/health")
    def health():
        from sqlalchemy import text

        try:
            db.session.execute(text("SELECT 1"))
            return {"status": "ok", "version": app.config["APP_VERSION"]}, 200
        except Exception:
            app.logger.exception("Health check failed")
            return {"status": "error"}, 500

    @app.route("/")
    def index():
        return render_template("index.html", title=None)


def _register_user_loader() -> None:
    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None


def _register_hooks(app: Flask) -> None:
    from app.utils import touch_last_seen

    @app.before_request
    def _touch_last_seen():
        touch_last_seen()


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(401)
    def unauthorised(_e):
        return render_template("errors/403.html", title="Not permitted"), 401

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("errors/403.html", title="Not permitted"), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("errors/404.html", title="Not found"), 404

    @app.errorhandler(500)
    def server_error(_e):  # pragma: no cover
        return render_template("errors/500.html", title="Error"), 500


def _register_cli(app: Flask) -> None:
    from app.cli import (
        backfill_results_command,
        config_check,
        set_admin,
        sync_season_command,
    )

    app.cli.add_command(set_admin)
    app.cli.add_command(config_check)
    app.cli.add_command(sync_season_command)
    app.cli.add_command(backfill_results_command)
