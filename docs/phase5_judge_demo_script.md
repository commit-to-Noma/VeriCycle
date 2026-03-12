# VeriCycle Phase 5 Judge Demo Script (3 Minutes)

This script is the lock for the live demo.
Do not improvise event choices.

## Preflight (before recording)

1. Start app and worker.
2. Run:

```bash
python scripts/prepare_phase5_demo_events.py
```

3. Confirm these labels exist in Admin Monitor:
- Judge Demo Verified Event
- Judge Demo Approved Review Event
- Judge Demo Rejected Review Event

## Step-by-step timeline

## 0:00-0:20 Step 1 - Open Admin Monitor

Click path:
1. Log in as admin or center reviewer.
2. Open /admin/monitor.

Show:
- Event stream
- Flagged Events panel
- Agent Society Overview

Say:
VeriCycle is waste and recycling verification infrastructure. Agents validate evidence, low-confidence cases are escalated, and verified records are anchored to Hedera.

## 0:20-0:45 Step 2 - Show perfect verified event

Click path:
1. Find Judge Demo Verified Event.
2. Open its card and click View proof.

Show:
- Confidence 0.7
- Review empty/None
- HCS transaction link
- Reward and compliance completion states

Say:
This event had sufficient evidence, so the agents verified it automatically and completed the full pipeline.

## 0:45-1:15 Step 3 - Show low-signal flagged event

Click path:
1. In Flagged Events, find Judge Demo Approved Review Event while still pending.
2. Click View proof.

Show:
- Confidence 0.2
- Resident confirmation signal only
- Pending review

Say:
This event does not have enough evidence to be trusted automatically, so the system escalates it instead of writing a false record.

## 1:15-1:45 Step 4 - Approve flagged event

Click path:
1. Click Approve on Judge Demo Approved Review Event.
2. Wait for refresh.

Show:
- Event leaves flagged queue
- Event becomes Verified
- Pipeline resumes to logbook/reward/compliance
- HCS appears

Say:
A manager only intervenes when confidence is too low. Once approved, the autonomous pipeline continues.

## 1:45-2:15 Step 5 - Show rejected event

Click path:
1. Open Judge Demo Rejected Review Event.
2. Click View proof.

Show:
- Rejected status
- Confidence 0.2
- No HCS link
- No reward transfer

Say:
If a manager rejects the event, the system preserves the decision as an auditable dispute and stops downstream actions.

## 2:15-2:50 Step 6 - Open proof panel on both paths

Click path:
1. Open View proof on Judge Demo Approved Review Event.
2. Open View proof on Judge Demo Verified Event.

Show in both bundles:
- Evidence signals
- Confidence
- Review status
- Proof hash
- Agent decisions

Say:
Every event produces a proof bundle showing what evidence was used, what the agents decided, and whether the record was anchored to Hedera.

## 2:50-3:00 Closing line

Say:
VeriCycle gives communities and programs a trustworthy record layer for recycling and waste activity, combining autonomous agent verification with human oversight and Hedera-backed auditability.
