"""Application factory for OneStep MultiServices pest control management."""
from datetime import datetime
import os

from flask import Flask
from config import Config
from extensions import db, login_manager, mail
from models import User, Notification, Service
from catalog import group_services_map


def _ensure_db_folder(uri: str) -> None:
    """Create the parent folder of a file-based SQLite database if it is missing.

    The folder is derived from the resolved URI (already absolute thanks to
    config._database_uri) so it works no matter where the app was started from.
    """
    if not uri.startswith("sqlite:///"):
        return
    path = uri[len("sqlite:///"):]
    if not path or path == ":memory:":
        return
    if path.startswith("/") and not (len(path) > 2 and path[2] == ":"):
        path = path[1:]
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)


def _service_map() -> dict:
    """Active services grouped as {category: [{id, name, slug}]} for service pickers."""
    try:
        services = Service.query.filter_by(status="ACTIVE").order_by(Service.name).all()
        return group_services_map(services)
    except Exception:
        return {}


def _appointment_wa_text(booking) -> str:
    """Plain-text appointment message, used to pre-fill a wa.me chat link."""
    try:
        from notifications import appointment_booked_message
        return appointment_booked_message(booking)
    except Exception:  # noqa: BLE001
        return ""


def _prepare_database(app: Flask) -> None:
    """Make sure the schema exists, print what we are using, and back up the data.

    Runs on every start. It never deletes anything: ``create_all`` only adds
    missing tables, and the backup is a copy of the live file.
    """
    from extensions import db as _db
    from db_tools import backup_database, database_path, database_stats

    with app.app_context():
        try:
            _db.create_all()
        except Exception as exc:  # noqa: BLE001
            print(f"[db] WARNING could not ensure schema: {exc}")
            return

        # create_all() only adds missing tables - columns need a migration.
        try:
            from migrations import run_migrations

            changes = run_migrations(_db)
            if changes:
                print(f"[db] migrated: {', '.join(changes)}")
        except Exception as exc:  # noqa: BLE001
            print(f"[db] WARNING migration failed: {exc}")

        path = database_path(app)
        stats = database_stats(app)
        print(f"[db] file    : {path}")
        if stats:
            print("[db] rows    : " + ", ".join(f"{k}={v}" for k, v in stats.items()))
        else:
            print("[db] rows    : (no tables yet)")

        # The reloader runs create_app() twice (parent + child); back up once.
        # Also skip for one-off CLI commands (flask db-stats, flask seed, ...).
        if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
            return
        if os.environ.get("FLASK_RUN_FROM_CLI") == "true":
            return
        dest = backup_database(app, label="autobackup")
        if dest:
            print(f"[db] backup  : {dest}")


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class)

    # Make sure the database folder exists (SQLite path uses it)
    _ensure_db_folder(app.config["SQLALCHEMY_DATABASE_URI"])

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
        from whatsapp import wa_link
        return {
            "business_name": app.config["BUSINESS_NAME"],
            "business_phone": app.config["BUSINESS_PHONE"],
            "business_email": app.config["BUSINESS_EMAIL"],
            "business_whatsapp": app.config["BUSINESS_WHATSAPP"],
            "business_address": app.config["BUSINESS_ADDRESS"],
            "business_city": app.config["BUSINESS_CITY"],
            "now_year": datetime.utcnow().year,
            "warranty_days": app.config["WARRANTY_DAYS"],
            "wa_link": wa_link,
            "appointment_wa_text": _appointment_wa_text,
            "service_map": _service_map(),
        }

    # Unread notification count for the admin badge (guarded so public pages stay cheap/safe)
    @app.context_processor
    def inject_admin_unread():
        count = 0
        try:
            from flask_login import current_user
            if (
                current_user.is_authenticated
                and hasattr(current_user, "is_admin")
                and current_user.is_admin
            ):
                count = Notification.query.filter_by(
                    user_id=current_user.id, status="unread"
                ).count()
        except Exception:
            count = 0
        return {"admin_unread_count": count}

    @app.context_processor
    def inject_asset_version():
        """Cache-bust static CSS so browser picks up style changes at once."""
        import os
        static_dir = app.static_folder or ""
        newest = 0.0
        for name in ("css/style.css", "css/admin.css"):
            path = os.path.join(static_dir, *name.split("/"))
            try:
                newest = max(newest, os.path.getmtime(path))
            except OSError:
                pass
        return {"asset_version": str(int(newest))}

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

    # Make sure the schema is in place and keep a backup of the live data.
    _prepare_database(app)
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

    @app.cli.command("db-stats")
    def db_stats_cmd():
        """Show the live database path and row counts."""
        from db_tools import database_path, database_stats
        print(f"file: {database_path(app)}")
        for table, count in database_stats(app).items():
            print(f"  {table}: {count}")

    @app.cli.command("backup-db")
    def backup_db_cmd():
        """Back up the live database into instance/backups/."""
        from db_tools import backup_database
        dest = backup_database(app, label="manual")
        print(f"Backup written: {dest}")

    @app.cli.command("list-backups")
    def list_backups_cmd():
        """List the available database backups, newest first."""
        from db_tools import list_backups
        rows = list_backups(app)
        if not rows:
            print("No backups found.")
            return
        for row in rows:
            print(f"  {row['modified']}  {row['size_kb']:>7} KB  {row['name']}")

    @app.cli.command("restore-db")
    def restore_db_cmd(backup):
        """Restore the live database from a backup file (path or filename)."""
        from db_tools import backup_dir, restore_database
        candidate = backup
        if not os.path.isfile(candidate):
            candidate = os.path.join(backup_dir(app), backup)
        path = restore_database(app, candidate)
        print(f"Database restored from {candidate}")
        print(f"Live database is now: {path}")
        print("Restart the app to pick up the restored data.")

    @app.cli.command("reset-db")
    def reset_db_cmd():
        """Delete all transactional data. Users and services are kept."""
        from db_tools import database_path
        print("This deletes every lead, booking, customer, notification, feedback")
        print("and warranty reminder. Users and services are kept.")
        print(f"Database: {database_path(app)}")
        answer = input("Type RESET to confirm: ").strip()
        if answer != "RESET":
            print("Cancelled - nothing was changed.")
            return
        from models import Booking, Customer, Feedback, Lead, Notification, WarrantyReminder
        for model in (Notification, Feedback, WarrantyReminder, Booking, Lead, Customer):
            db.session.query(model).delete()
        db.session.commit()
        print("All transactional data deleted.")


__all__ = ["create_app", "db"]
