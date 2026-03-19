import os
import sys
from uuid import uuid4

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, db  # noqa: E402
from extensions import bcrypt  # noqa: E402
from models import User  # noqa: E402

TEST_PASSWORD = "PytestSmoke!pass"


def _upsert_user(email: str, role: str, complete_profile: bool) -> User:
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User()
        user.email = email
        db.session.add(user)

    user.role = role
    user.password_hash = bcrypt.generate_password_hash(TEST_PASSWORD).decode("utf-8")

    if complete_profile:
        user.full_name = "Pytest User"
        user.phone_number = "0110000000"
        user.id_number = f"ID-{uuid4().hex[:8]}"
        user.address = "Pytest Address"
    else:
        user.full_name = None
        user.phone_number = None
        user.id_number = None

    db.session.commit()
    return user


def _login(client, email: str, role: str):
    return client.post(
        "/login",
        data={"email": email, "password": TEST_PASSWORD, "role": role},
        follow_redirects=False,
    )


def test_role_access_matrix_smoke():
    matrix = {
        "recycler": {
            "persisted_role": "collector",
            "profile_complete": False,
            "checks": {
                "/collector": (302, "/profile"),
                "/request-pickup": (302, "/collector"),
                "/household": (302, "/collector"),
                "/center": (302, "/collector"),
            },
        },
        "business": {
            "persisted_role": "business",
            "profile_complete": True,
            "checks": {
                "/collector": (302, "/request-pickup"),
                "/request-pickup": (200, ""),
                "/household": (302, "/request-pickup"),
                "/center": (302, "/request-pickup"),
            },
        },
        "resident": {
            "persisted_role": "resident",
            "profile_complete": True,
            "checks": {
                "/collector": (302, "/household"),
                "/request-pickup": (200, ""),
                "/household": (200, ""),
                "/center": (302, "/household"),
            },
        },
        "center": {
            "persisted_role": "center",
            "profile_complete": True,
            "checks": {
                "/collector": (302, "/center"),
                "/request-pickup": (302, "/center"),
                "/household": (302, "/center"),
                "/center": (200, ""),
            },
        },
        "admin": {
            "persisted_role": "admin",
            "profile_complete": True,
            "checks": {
                "/collector": (302, "/admin/monitor"),
                "/request-pickup": (302, "/admin/monitor"),
                "/household": (302, "/admin/monitor"),
                "/center": (200, ""),
            },
        },
    }

    with app.app_context():
        db.create_all()
        for role_name, cfg in matrix.items():
            _upsert_user(
                email=f"pytest_smoke_{role_name}@example.com",
                role=cfg["persisted_role"],
                complete_profile=cfg["profile_complete"],
            )

    with app.test_client() as client:
        for role_name, cfg in matrix.items():
            login_role = "recycler" if role_name == "recycler" else role_name
            login_response = _login(client, f"pytest_smoke_{role_name}@example.com", login_role)
            assert login_response.status_code in (302, 303), f"login failed for {role_name}"

            for path, (expected_status, expected_location_prefix) in cfg["checks"].items():
                response = client.get(path, follow_redirects=False)
                assert response.status_code == expected_status, f"{role_name} {path}"

                if expected_location_prefix:
                    location = response.headers.get("Location", "")
                    assert location.startswith(expected_location_prefix), (
                        f"{role_name} {path}: expected redirect to {expected_location_prefix}, got {location}"
                    )

            client.get("/logout", follow_redirects=False)


def test_business_pdf_and_silent_collector_redirect():
    email = f"pytest_business_pdf_{uuid4().hex[:8]}@example.com"

    with app.app_context():
        _upsert_user(email=email, role="business", complete_profile=True)

    with app.test_client() as client:
        login_response = _login(client, email, "business")
        assert login_response.status_code in (302, 303)

        pdf_response = client.get("/api/income-report.pdf", follow_redirects=False)
        assert pdf_response.status_code == 200
        assert "application/pdf" in (pdf_response.headers.get("Content-Type") or "")

        collector_response = client.get("/collector", follow_redirects=False)
        assert collector_response.status_code == 302
        assert (collector_response.headers.get("Location") or "").startswith("/request-pickup")

        with client.session_transaction() as session:
            flashes = list(session.get("_flashes", []))

        assert flashes == []
