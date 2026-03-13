#!/usr/bin/env python
"""Quick smoke test for core VeriCycle pages across public, collector, and admin roles."""

import os
import sys
from typing import Iterable

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from app import app, db
from models import User


def expect_status(client, path: str, allowed: Iterable[int] = (200,)):
    res = client.get(path, follow_redirects=False)
    if res.status_code not in tuple(allowed):
        raise RuntimeError(f"GET {path} returned {res.status_code}, expected {tuple(allowed)}")
    return res.status_code


def force_login(client, user: User):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def ensure_collector_profile_complete():
    collector = User.query.filter_by(email="test@gmail.com").first()
    if not collector:
        return

    changed = False
    if not collector.full_name:
        collector.full_name = "Test Collector"
        changed = True
    if not collector.phone_number:
        collector.phone_number = "0000000000"
        changed = True
    if not collector.id_number:
        collector.id_number = "TEST-ID-000"
        changed = True

    if changed:
        db.session.commit()


def run_public_checks(client):
    for path in ["/", "/home", "/login", "/public-data", "/proof-integrity"]:
        expect_status(client, path, (200,))


def run_collector_checks(client):
    collector = User.query.filter_by(email="test@gmail.com").first()
    if not collector:
        collector = User.query.filter_by(role="collector").order_by(User.id.asc()).first()
    if not collector:
        raise RuntimeError("Missing collector account")
    force_login(client, collector)
    expect_status(client, "/collector", (200, 302))
    expect_status(client, "/profile", (200,))
    expect_status(client, "/request-pickup", (302,))
    expect_status(client, "/household", (200, 302))
    expect_status(client, "/search", (200,))
    expect_status(client, "/network", (200,))
    expect_status(client, "/swap", (200,))


def run_admin_checks(client):
    admin = User.query.filter_by(email="admin@vericycle.com").first()
    if not admin:
        admin = User.query.filter(User.role.in_(["admin", "center"]))\
            .order_by(User.id.asc()).first()
    if not admin:
        raise RuntimeError("Missing admin/center account")
    force_login(client, admin)
    expect_status(client, "/admin/monitor", (200,))
    expect_status(client, "/proof-hub", (200,))


def main():
    with app.app_context():
        ensure_collector_profile_complete()

    with app.test_client() as client:
        run_public_checks(client)

    with app.app_context():
        with app.test_client() as client:
            run_collector_checks(client)

    with app.app_context():
        with app.test_client() as client:
            run_admin_checks(client)

    print("PASS: core page smoke checks completed")


if __name__ == "__main__":
    main()
