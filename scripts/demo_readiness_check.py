#!/usr/bin/env python
"""Demo readiness check for final judge-facing flow and UI trust markers."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402
from models import User  # noqa: E402

REQUIRED_ACCOUNTS = [
    "recycler@vericycle.com",
    "business@vericycle.com",
    "center@vericycle.com",
    "resident@vericycle.com",
    "admin@vericycle.com",
]

TEXT_CHECKS = {
    "templates/collector.html": [
        "Submission Successful",
        "Submitted ✔",
        "Verified (pending)",
        "Anchored (pending)",
        "Rewarded (pending)",
        "Proof Ready (pending)",
        "Submitted to Verification Center",
        "Awaiting Verification",
        "Hedera Anchor Pending",
        "Reward Processing",
        "Proof Bundle Generation",
        "submission-success-modal",
        "showSubmissionSuccessModal",
    ],
    "templates/center.html": [
        "center-toast",
        "Verified -> Anchored -> Reward queued",
        "queue-item-verifying-out",
    ],
    "templates/proof_hub.html": [
        "loadMoreProof",
        "proof-row.hidden",
    ],
    "templates/business.html": [
        "loadMoreRequests",
        "loadMoreBusinessProof",
        "850kg / 1000kg monthly goal",
    ],
    "templates/wallet.html": [
        "Redeem to Cash",
        "Coming soon via partners",
        "EcoCoin Rewards History",
    ],
    "templates/admin_monitor.html": [
        "Retry Pipeline",
        "Live Sync",
        "retryStalledPipeline",
    ],
    "templates/household.html": [
        "✔ Verified Local",
        "View After Photo (demo)",
    ],
    "templates/login.html": [
        "resident1",
        "admin1",
    ],
}


def check_accounts() -> bool:
    with app.app_context():
        existing = {
            u.email.lower() for u in User.query.filter(User.email.in_(REQUIRED_ACCOUNTS)).all()
        }

    missing = [acct for acct in REQUIRED_ACCOUNTS if acct not in existing]
    if missing:
        print(f"ACCOUNTS: FAIL missing={missing}")
        return False

    print("ACCOUNTS: PASS")
    return True


def check_templates() -> bool:
    ok = True
    for rel_path, tokens in TEXT_CHECKS.items():
        content = (ROOT / rel_path).read_text(encoding="utf-8")
        missing_tokens = [token for token in tokens if token not in content]
        if missing_tokens:
            ok = False
            print(f"TEXT CHECK FAIL {rel_path}: missing {missing_tokens}")
        else:
            print(f"TEXT CHECK PASS {rel_path}")
    return ok


def check_flow_routes() -> bool:
    # These are sanity checks only; role-protected pages may redirect when anonymous.
    flow_routes = [
        "/home",
        "/business",
        "/collector",
        "/center",
        "/proof-hub",
        "/wallet",
        "/admin/monitor",
        "/household",
    ]

    with app.test_client() as client:
        for route in flow_routes:
            res = client.get(route, follow_redirects=False)
            print(f"ROUTE {route}: status={res.status_code}")
    return True


def check_logins() -> bool:
    ok = True
    with app.test_client() as client:
        for email in REQUIRED_ACCOUNTS:
            res = client.post(
                "/login",
                data={"email": email, "password": "1234"},
                follow_redirects=False,
            )
            passed = res.status_code in (302, 303)
            ok = ok and passed
            print(f"LOGIN {email}: {'PASS' if passed else 'FAIL'} status={res.status_code}")
            if passed:
                client.get("/logout", follow_redirects=False)
    return ok


def main() -> int:
    account_ok = check_accounts()
    text_ok = check_templates()
    route_ok = check_flow_routes()
    login_ok = check_logins()

    overall = account_ok and text_ok and route_ok and login_ok
    print(f"OVERALL: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
