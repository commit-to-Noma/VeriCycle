import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _seed_user(email: str, password: str, role: str, full_name: str):
    from app import db, bcrypt
    from models import User

    existing = User.query.filter_by(email=email).first()
    if existing:
        return existing, False

    user = User()
    user.email = email
    user.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
    user.role = role
    user.full_name = full_name
    db.session.add(user)
    return user, True


def main():
    db_path = os.path.join(ROOT, "vericycle.db")

    if os.path.exists(db_path):
        os.remove(db_path)
        print("DELETED vericycle.db")
    else:
        print("DELETED vericycle.db (already absent)")

    from app import app, db

    with app.app_context():
        db.drop_all()
        db.create_all()
        print("CREATED fresh schema")

        _seed_user("admin@vericycle.com", "Admin123!", "admin", "VeriCycle Admin")
        _seed_user("test@gmail.com", "Test123!", "collector", "Test Collector")
        _seed_user("demo@vericycle.com", "H3dera!2025", "collector", "Demo Collector")
        _seed_user("mpact@vericycle.com", "Centerh3dera!", "center", "M-Pact Center")

        db.session.commit()
        print("SEEDED admin + test user + agents")


if __name__ == "__main__":
    main()
