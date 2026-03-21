import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _seed_user(email: str, password: str, role: str, full_name: str, hedera_account_id: str | None = None):
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
    if hedera_account_id:
        user.hedera_account_id = hedera_account_id
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

        _seed_user("admin@vericycle.com",    "Admin123!",    "admin",     "VeriCycle Admin", "0.0.7300001")
        _seed_user("recycler@vericycle.com", "Recycler123!", "collector", "Demo Recycler", "0.0.7267109")
        _seed_user("business@vericycle.com", "Business123!", "business",  "Demo Business", "0.0.7300002")
        _seed_user("resident@vericycle.com", "Resident123!", "resident",  "Demo Resident", "0.0.7300003")
        _seed_user("center@vericycle.com",   "Center123!",   "center",    "Demo Center", "0.0.7300004")

        db.session.commit()
        print("SEEDED 5 final demo accounts: admin, recycler, business, resident, center")


if __name__ == "__main__":
    main()
