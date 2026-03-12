# VeriCycle

VeriCycle is verification infrastructure for recycling and waste activity. It uses autonomous agents to evaluate evidence signals, escalate low-confidence events for review, and anchor verified records to Hedera, creating trusted environmental records for communities, collectors, property managers, and sustainability programs.

## Why Hedera

Hedera is the trust layer. It provides immutable audit records, public verification, and programmable incentives.

## Why agents

Agents are the automation layer. They evaluate signals, assign confidence, escalate uncertain cases, and execute downstream actions only when events are trustworthy.

## Problem solved

Waste and recycling activity is often poorly documented, hard to verify, and easy to falsify. VeriCycle turns real-world recycling and waste events into auditable digital records.

## Phase 5 locked demo stories

These are the only three stories used in judging.

1. Perfect verified flow
- Story: Event has enough signals, auto-verifies, anchors to Hedera, reward and compliance run.
- Final state: Status Verified, confidence >= 0.7, review None, HCS present, HTS present if available, compliance present.
- Label: Judge Demo Verified Event.

2. Approved review flow
- Story: Low-signal event escalates, manager approves, autonomous pipeline resumes.
- Final state: Status Verified, confidence 0.2, review Approved, HCS present, reward/compliance continue.
- Label: Judge Demo Approved Review Event.

3. Rejected review flow
- Story: Low-signal event escalates, manager rejects, pipeline stops.
- Final state: Status Rejected, confidence 0.2, review Rejected, no HCS, no reward, no compliance progression.
- Label: Judge Demo Rejected Review Event.

## Judge-safe sequence

Use the exact screen-by-screen script in docs/phase5_judge_demo_script.md.

## Setup and run

1. Install dependencies.

```bash
pip install -r requirements.txt
npm install
```

2. Reset local database and seed accounts.

```bash
python scripts/reset_db.py
```

3. Start the app.

```bash
python app.py
```

4. Start task worker in a second terminal.

```bash
python -m agents.task_worker
```

## Lock Phase 5 demo events

Run this before recording or live judging:

```bash
python scripts/prepare_phase5_demo_events.py
```

This script guarantees the three labeled judge events exist and prepares them for the live sequence:
- verified auto-flow finalized
- approved review flow waiting in needs_review (for live Approve click)
- rejected review flow finalized

## Accounts

- admin@vericycle.com / Admin123!
- test@gmail.com / Test123!
- demo@vericycle.com / H3dera!2025
- mpact@vericycle.com / Centerh3dera!

## What to test in Phase 5

1. Perfect verified flow
- Auto-verifies
- HCS link exists
- Reward and compliance complete

2. Approved review flow
- Starts at needs_review
- Approve works
- Pipeline resumes

3. Rejected review flow
- Starts at needs_review
- Reject works
- Pipeline stops

4. Proof panel
- Approved event proof shows confidence 0.2
- Verified event proof shows confidence 0.7
- Proof hash visible in both

## Submission narrative

Use docs/submission_narrative_phase5.md for copy-paste final submission language.
