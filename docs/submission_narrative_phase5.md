# VeriCycle Final Submission Narrative

## Final project description

VeriCycle connects recyclers, businesses, communities, and centers through a verified recycling coordination system. The product turns recycling activity into verified recycling records, proof of income, EcoCoin incentives, and Hedera-backed proof.

The live application includes a Recycler Hub, Business Hub, Community Hub, Verification Center, Admin Monitor, Proof Hub, and Proof Verifier. Together they show how recycling demand can be created, fulfilled, verified, rewarded, and audited.

## Why Hedera

Hedera is the trust layer for VeriCycle. Verified events can be linked to Hedera so judges and operators can inspect anchored records and reward-related transaction references through public explorers.

## Why agents

Agents are the automation layer. They evaluate evidence, move verified events through logbook, reward, and compliance stages, and escalate low-confidence cases for human review when automation alone should not decide.

## What problem it solves

Recycling activity is often real but poorly documented. Informal recyclers struggle to prove work history or income, while businesses and communities struggle to coordinate pickup demand and verify that material was actually processed.

VeriCycle addresses this by:

- giving recyclers verified event history and proof-of-income artifacts
- letting businesses publish pickup demand and retain verified recycling records
- letting communities surface neighborhood recycling demand and reliability signals
- giving centers and admins auditable tooling for verification and review

## What is fully operational today

- Recycler and center flows are fully operational.
- Business and community participation are implemented as ecosystem coordination layers.
- Admin and proof tooling demonstrate verification and auditability.

## Main working flows

### Recycler deposit flow

A recycler can generate or trigger a deposit flow, a center verifies the material, VeriCycle runs the pipeline, and the result appears as a verified recycling record with proof and reward status.

### Business pickup opportunity flow

A business creates a pickup request, a recycler accepts and submits the job, a center verifies it, and the business then sees a verified recycling record with proof and Hedera-linked evidence.

## Reward handling

When treasury balance is available, reward transfer references are shown normally. When treasury balance is empty, VeriCycle still finalizes the record and presents clear fallback messaging instead of raw system output:

- Reward finalized (no transfer)
- Reward recorded, treasury refill required

## Auditability and trust

The Admin Monitor and proof tooling show flagged events, deterministic review stories, proof bundles, confidence details, and transaction references. This demonstrates that VeriCycle is not only a workflow app but also a verification and audit layer.
