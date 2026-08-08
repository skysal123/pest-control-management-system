"""Application factory for OneStep MultiServices pest control management."""
from datetime import datetime
import os

from flask import Flask
from config import Config
from extensions import db, login_manager, mail
from models import User


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class)

    # Make sure the instance folder exists (SQLite path uses it)
    base = os.path.dirname(os.path.dirname(__file__))
    os.makedirs(os.path.join(base, "instance"), exist_ok=True)

    # Init extensions
    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    # Inject business globals into all templates
    @app.context_processor
    def inject_globals():
        return {
            "business_name": app.config["BUSINESS_NAME"],
            "business_phone": app.config["BUSINESS_PHONE"],
            "business_email": app.config["BUSINESS_EMAIL"],
            "business_whatsapp": app.config["BUSINESS_WHATSAPP"],
            "business_address": app.config["BUSINESS_ADDRESS"],
            "business_city": app.config["BUSINESS_CITY"],
            "now_year": datetime.utcnow().year,
            "warranty_days": app.config["WARRANTY_DAYS"],
        }

    # Register blueprints
    from blueprints.public import bp as public_bp
    from blueprints.auth import bp as auth_bp
    from blueprints.admin import bp as admin_bp
    from blueprints.technician import bp as technician_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(technician_bp)

    # robots.txt — keep crawlers out of admin/technician
    @app.route("/robots.txt")
    def robots():
        return (
            "User-agent: *\nDisallow: /admin/\nDisallow: /technician/\n",
            200,
            {"Content-Type": "text/plain"},
        )

    # CLI commands
    register_cli(app)
    return app


def register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db():
        """Create all database tables."""
        db.create_all()
        print("Database tables created.")

    @app.cli.command("seed")
    def seed_cmd():
        """Seed database with admin user, technicians, and pest-control services."""
        from seed import run_seed
        run_seed(app)


__all__ = ["create_app", "db"]
