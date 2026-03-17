# VeriCycle Locked Judge Demo Script

This is the locked live sequence.
Do not improvise the order.

## Preflight

1. Start the app and worker.
2. Reset state if needed.
3. Run:

```bash
python scripts/prepare_phase5_demo_events.py
```

4. Confirm the app opens cleanly and the main hubs load.
5. Keep seeded credentials ready for recycler, business, center, and admin.

## Locked demo order

1. Home page
2. Recycler Hub
3. Open pickup opportunities
4. Accepted pickup
5. Verification Center
6. Verified event in Admin Monitor or Proof panel
7. Business Hub
8. Proof Hub or Proof Verifier

## What must be demonstrated live

At minimum, show this full path:

1. business creates request
2. recycler accepts
3. recycler submits
4. center verifies
5. Hedera pipeline runs
6. proof exists

## Step-by-step script

## 0:00-0:20 Step 1 - Home page

Show:

- VeriCycle connects recyclers, businesses, communities, and centers
- the ecosystem framing
- the role-based hubs

Say:

VeriCycle coordinates recycling demand and turns completed activity into verified records, proof of income, EcoCoin incentives, and Hedera-backed proof.

## 0:20-0:45 Step 2 - Recycler Hub

Show:

- Open Pickup Opportunities
- Accepted Pickup Jobs
- Verified Recycling Records

Say:

The Recycler Hub is where collectors find work, submit completed pickups, and build a verified activity history.

## 0:45-1:05 Step 3 - Open pickup opportunity

Click path:

1. Log in as business if needed.
2. Open Business Hub.
3. Create a pickup request.
4. Return to Recycler Hub.
5. Show the request in Open Pickup Opportunities.

Say:

Businesses can create real recycling demand, and recyclers can immediately see and accept that work.

## 1:05-1:25 Step 4 - Accepted pickup

Click path:

1. Accept the pickup in Recycler Hub.
2. Open Accepted Pickup Jobs.
3. Submit the collected material.

Show:

- accepted status
- submitted material and weight
- the job now waiting for verification

Say:

This moves the opportunity from demand coordination into a verifiable recycling event.

## 1:25-1:50 Step 5 - Verification Center

Click path:

1. Open Verification Center.
2. Show the Submitted Pickup Verification Queue.
3. Verify the submitted pickup.

Show:

- submitted pickup lane
- verification action
- event entering proof, reward, and compliance pipeline

Say:

The center is the trusted checkpoint that converts the submitted pickup into a verified event.

## 1:50-2:15 Step 6 - Admin Monitor or Proof panel

Click path:

1. Open Admin Monitor or the proof panel for the new event.
2. Show the verified status.
3. Show proof bundle and Hedera references.

Show:

- verified record
- proof hash
- evidence summary
- HCS and HTS references when available
- clear reward wording if treasury fallback occurs

Say:

VeriCycle does not just log that something happened. It preserves why the event was trusted and how it moved through the pipeline.

## 2:15-2:35 Step 7 - Business Hub

Click path:

1. Return to Business Hub.
2. Show recent pickup requests.
3. Show the verified recycling record for the request.

Show:

- request status progression
- proof link
- Hedera link
- reward outcome wording

Say:

The business can now see the request as a verified recycling record rather than just an unconfirmed pickup claim.

## 2:35-2:55 Step 8 - Proof Hub or Proof Verifier

Click path:

1. Open Proof Hub or Proof Verifier.
2. Open the proof bundle for the verified event.

Show:

- proof bundle
- integrity fields
- transaction references

Say:

This is the audit layer that makes the recycling record independently inspectable.

## 2:55-3:00 Closing line

Say:

VeriCycle turns recycling coordination into verified economic activity, with operational recycler and center flows, business and community coordination layers, and Hedera-backed proof for trust and auditability.
