# VeriCycle

VeriCycle connects recyclers, businesses, communities, and centers and turns recycling activity into verified recycling records, proof of income, EcoCoin incentives, and Hedera-backed proof.

It is a Flask application with a role-based UI, an agent-driven verification pipeline, proof bundle generation, and Hedera-linked evidence for verified recycling events.

## What the app does

VeriCycle closes the loop between who creates recycling demand and who verifies the outcome.

- Recyclers use the Recycler Hub to trigger direct deposits, accept pickup opportunities, submit collected material, earn EcoCoin, and build proof-of-income history.
- Businesses use the Business Hub to create pickup requests, track recent requests, and review verified recycling records with proof and Hedera links.
- Communities use the Community Hub to publish neighborhood pickup demand and improve reliability signals.
- Centers use the Verification Center to confirm direct deposits and recycler-submitted pickups, which then enter the proof, reward, and compliance pipeline.
- Admin and proof tooling show verification status, flagged events, proof bundles, and auditability.

## Core outcomes

VeriCycle turns recycling activity into:

- verified recycling records
- proof of income
- EcoCoin incentives
- Hedera-backed proof

## Main working flows

### Recycler deposit flow

1. Recycler opens Recycler Hub.
2. Recycler creates a direct recycling event or shows a drop-off QR code.
3. Verification Center confirms weight and material.
4. VeriCycle runs the agent pipeline.
5. Proof bundle and Hedera references become available.
6. Reward status is shown clearly, including fallback states when treasury refill is required.

### Business pickup opportunity flow

1. Business opens Business Hub and creates a pickup request.
2. Recycler sees the request in Open Pickup Opportunities.
3. Recycler accepts the job and submits collected material.
4. Verification Center verifies the submitted pickup.
5. VeriCycle creates a verified recycling record with proof and Hedera-linked evidence.
6. Business Hub shows the verified record, proof link, and reward outcome.

## Current scope

- Recycler and center flows are fully operational.
- Business and community participation are implemented as ecosystem coordination layers.
- Admin and proof tooling demonstrate verification and auditability.

## Setup and run

1. Install dependencies.

```bash
pip install -r requirements.txt
npm install
```

2. Reset the local database and seed accounts.

```bash
python scripts/reset_db.py
```

3. Start the app.

```bash
python app.py
```

4. Start the worker in a second terminal.

```bash
python -m agents.task_worker
```

## Locked demo order

Use this order live:

1. Home page
2. Recycler Hub
3. Open pickup opportunities
4. Accepted pickup
5. Verification Center
6. Verified event in Admin Monitor or Proof panel
7. Business Hub
8. Proof Hub or Proof Verifier

The minimum live story is:

1. business creates request
2. recycler accepts
3. recycler submits
4. center verifies
5. Hedera pipeline runs
6. proof exists

Use the exact screen-by-screen script in docs/phase5_judge_demo_script.md.

## Deterministic demo prep

Run this before recording or live judging:

```bash
python scripts/prepare_phase5_demo_events.py
```

This prepares the deterministic judge review stories used in Admin Monitor:

- Judge Demo Verified Event
- Judge Demo Approved Review Event
- Judge Demo Rejected Review Event

These review stories remain available for auditability and oversight, but the primary live ecosystem demo should follow the locked order above.

## Accounts

- admin@vericycle.com / Admin123!
- test@gmail.com / Test123!
- demo@vericycle.com / H3dera!2025
- mpact@vericycle.com / Centerh3dera!

## Phase 6 checks

Run these focused checks:

1. Business Hub works.
2. Reward fallback wording is human-readable.
3. Recycler flow still works.
4. Center flow still works.
5. Proof flow still works.
6. Locked demo sequence is repeatable from fresh state.

Useful scripts already in the repo:

```bash
python scripts/test_pages_smoke.py
python scripts/test_phase3_opportunities_smoke.py
python scripts/test_review_transitions.py
python scripts/run_single_account_demo_check.py
```

## Submission narrative

Use docs/submission_narrative_phase5.md for final submission copy.
