import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, db, User, bcrypt

with app.app_context():
    user = User.query.filter_by(email="test@gmail.com").first()
    if not user:
        raise RuntimeError("test@gmail.com not found")

    user.role = "admin"
    user.password_hash = bcrypt.generate_password_hash("Test123!").decode("utf-8")
    user.full_name = user.full_name or "Test Admin"
    user.phone_number = user.phone_number or "0123456789"
    user.id_number = user.id_number or "ID-TEST-ADMIN"
    user.address = user.address or "Demo Address"
    db.session.commit()

    print("OK: test@gmail.com role=admin password reset to Test123!")
