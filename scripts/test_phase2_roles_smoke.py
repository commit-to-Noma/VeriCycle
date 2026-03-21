import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, db, User
from extensions import bcrypt

TEST_PASSWORD = "Phase2Smoke!pass"
TEST_USERS = {
    "recycler": "collector",  # legacy persisted value; effective role resolves to recycler
    "business": "business",
    "resident": "resident",
    "center": "center",
    "admin": "admin",
}

EXPECTED = {
    "recycler": {
        "/collector": (302, "/profile"),
        "/request-pickup": (302, "/collector"),
        "/household": (302, "/collector"),
        "/center": (302, "/collector"),
    },
    "business": {
        "/collector": (302, "/business"),
        "/request-pickup": (200, ""),
        "/household": (302, "/business"),
        "/center": (302, "/business"),
    },
    "resident": {
        "/collector": (302, "/household"),
        "/request-pickup": (302, "/household"),
        "/household": (200, ""),
        "/center": (302, "/household"),
    },
    "center": {
        "/collector": (302, "/center"),
        "/request-pickup": (302, "/center"),
        "/household": (302, "/center"),
        "/center": (200, ""),
    },
    "admin": {
        "/collector": (302, "/admin/monitor"),
        "/request-pickup": (302, "/admin/monitor"),
        "/household": (302, "/admin/monitor"),
        "/center": (302, "/admin/monitor"),
    },
}


def upsert_user(email: str, role: str):
    user = User.query.filter_by(email=email).first()
    password_hash = bcrypt.generate_password_hash(TEST_PASSWORD).decode("utf-8")
    if not user:
        user = User()
        user.email = email
        user.password_hash = password_hash
        user.role = role
        db.session.add(user)
    else:
        user.role = role
        user.password_hash = password_hash
    db.session.commit()


def get_result(client, path: str):
    response = client.get(path, follow_redirects=False)
    return response.status_code, response.headers.get("Location", "")


def main():
    with app.app_context():
        db.create_all()
        for role_name, persisted_role in TEST_USERS.items():
            upsert_user(f"phase2_smoke_{role_name}@example.com", persisted_role)

    failures = []

    with app.test_client() as client:
        for role_name in TEST_USERS.keys():
            email = f"phase2_smoke_{role_name}@example.com"
            login_role = "recycler" if role_name == "recycler" else role_name
            login_response = client.post(
                "/login",
                data={"email": email, "password": TEST_PASSWORD, "role": login_role},
                follow_redirects=False,
            )

            if login_response.status_code not in (302, 303):
                failures.append(
                    f"[{role_name}] login failed with status {login_response.status_code}"
                )
                continue

            for path, expected in EXPECTED[role_name].items():
                actual = get_result(client, path)
                if actual != expected:
                    failures.append(
                        f"[{role_name}] {path} expected {expected} but got {actual}"
                    )

            client.get("/logout", follow_redirects=False)

    if failures:
        print("PHASE2_ROLE_SMOKE: FAIL")
        for item in failures:
            print(" -", item)
        raise SystemExit(1)

    print("PHASE2_ROLE_SMOKE: PASS")


if __name__ == "__main__":
    main()
