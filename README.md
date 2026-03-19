# VeriCycle

**Financial and Verification Infrastructure for the Informal Recycling Economy**

VeriCycle turns recycling into verifiable income.

It replaces risky cash-based reward flows with EcoCoin, creates immutable Proof of Income for informal recyclers, and gives businesses and municipalities auditable sustainability records.

[![Built with Hedera](https://img.shields.io/badge/Built%20with-Hedera-000)](https://hedera.com) [![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://python.org) [![Flask](https://img.shields.io/badge/Flask-Web%20App-informational)](https://flask.palletsprojects.com)

---

## Table of Contents

- [Overview](#overview)
- [The Problem](#the-problem)
- [The Solution](#the-solution)
- [Why Blockchain](#why-blockchain-why-not-web2-alone)
- [Why Hedera](#why-hedera)
- [Who Benefits](#who-benefits)
- [Key Features](#product-mvp)
- [Technology Stack](#tech-stack)
- [Quick Start](#setup)
- [Roadmap](#roadmap)
- [Vision](#vision)
- [Architecture](#architecture)

---

## Overview

**VeriCycle upgrades survival work into a trusted, portable, and economically visible asset.**

VeriCycle enables:

- **Proof of Income** for informal recyclers
- **Verified sustainability records** for businesses
- **Auditable recycling evidence** for communities and municipalities

---

## The Problem

Recycling already happens at scale, but it lacks trust, visibility, and verification.

For informal recyclers, the problem is not effort. It is invisibility. Their work creates real environmental and economic value, but without Proof of Income or trusted records, that value cannot enter formal systems.

### Global Context
- **15+ million people** globally rely on informal waste picking for survival (World Bank)
- **In South Africa**, ~90,000 waste pickers recover 80–90% of recyclables (CSIR, WWF, SERI)
- **By 2050**, global waste projected to reach **3.4 billion tonnes annually** (World Bank)

### The Gap

Despite massive real-world recycling activity, informal recyclers face:
- ❌ No proof of income
- ❌ No verifiable work history
- ❌ No trusted recycling record

**For Businesses:**
- Cannot prove what was recycled
- Cannot verify who collected it
- Cannot track where it went

**For Communities:**
- Waste complaints handled through informal channels (WhatsApp, etc.)
- No tracking or accountability
- No visibility into outcomes

**👉 The problem is not collection. The problem is trust and verification.**

---

## The Solution

VeriCycle creates a verification network for recycling that connects:

- **Recyclers** — collect and submit materials
- **Businesses** — request pickups and track sustainability
- **Communities** — report issues and request service
- **Recycling Centers** — verify deposits and validate submissions
- **Autonomous Agents** — process and finalize verification

### Each recycling event becomes:

✅ **A verified record** — immutable, timestamped event log  
✅ **A Hedera-anchored transaction** — on-chain proof  
✅ **A Proof of Income entry** — supports financial inclusion  
✅ **A sustainability proof** — enables ESG reporting  
✅ **A reward-triggering event** — earns EcoCoin  

### Solution Summary

VeriCycle converts recycling labor into a portable economic record: verifiable work history, immutable Proof of Income, and auditable sustainability evidence that can be trusted across institutions.

### Flexibility by Design

Recyclers can:
- Accept pickup requests from businesses, OR
- Independently collect and submit materials

This ensures the system reflects real-world behavior, not just structured workflows.

VeriCycle does not digitize recycling. It makes it economically visible.

---

## Why Blockchain? Why Not Web2 Alone?

Recycling involves **multiple independent stakeholders**.

Without a shared ledger:
- Each party maintains its own version of truth
- Records are not trusted across entities
- Disputes cannot be resolved transparently

### VeriCycle's Hybrid Approach

| Layer | Purpose |
|-------|---------|
| **Web2** (Flask, SQLAlchemy) | Runs the application, stores operational data |
| **Hedera** (HCS + HTS) | Secures the truth, provides immutable event logs, enables cross-party verification |

👉 **VeriCycle uses Web2 for usability and Hedera for trust.**

---

## Why Hedera

VeriCycle leverages:

- **Hedera Consensus Service (HCS)** → Immutable recycling event logs
- **Hedera Token Service (HTS)** → EcoCoin reward system

### Why Hedera is the Perfect Fit

Hedera is the shared trust layer that allows independent stakeholders - recyclers, centers, businesses, and municipalities - to rely on the same verified record without trusting each other directly.

✅ **Low transaction costs** — supports high-frequency real-world events  
✅ **Fast finality** — near real-time verification  
✅ **Energy efficiency** — aligned with sustainability mission  

### Energy Comparison

Hedera consumes **~0.000003 kWh per transaction**:

| Blockchain | Cost per Tx |
|-----------|------------|
| **Hedera** | 0.000003 kWh |
| Bitcoin | 885 kWh |
| Ethereum | 102 kWh |

👉 **Hedera is 295 million times more efficient than Bitcoin.**

### Value for Hedera

VeriCycle drives:
- Real-world transaction volume through high-frequency events
- New Hedera accounts (recyclers, businesses, centers)
- Increased TPS through micro-transactions
- A **sustainability-aligned, non-speculative use case**

👉 **This positions Hedera as infrastructure for real economic activity, not just financial speculation.**

---

## Who Benefits

### 🔄 Recyclers (Primary Impact)
- **Earn EcoCoin** → Predictable income signal
- **Build Proof of Income** → Financial inclusion potential  
- **Reduce exploitation** → Verified, immutable records

### 🏢 Businesses
- **Verified recycling records** → Credible ESG reporting  
- **Traceability** → Compliance and audit readiness  
- **Proof** → Reduces greenwashing risk

### 👥 Communities
- **Structured reporting** → Replaces WhatsApp-based systems  
- **Visibility** → Track what gets resolved  
- **Accountability** → Transparent process

### 🏭 Recycling Centers / Municipalities
- **Verification authority** → Trusted system role  
- **Data insights** → Planning and accountability  
- **Verifiable records** → Compliance documentation

### 💼 Market Opportunity

- **10,000+ companies** report sustainability data through GRI
- **$30+ trillion** in global assets under ESG management
- Companies using sustainability strategies: **48% profit increases** (McKinsey)

👉 **Verified sustainability data is no longer optional — it is economically valuable.**

---

## EcoCoin (Incentive Model)

EcoCoin is a reward token issued for verified recycling activity.

It represents:
- **Verified contribution** — proven participation in recycling
- **Measurable environmental impact** — backed by on-ground verification
- **Future financial value** — accessible through partner networks

### Value Sources

- Business sustainability budgets
- Municipalities and local governments
- NGOs and environmental organizations
- Sponsored environmental campaigns
- Future verification and reporting services

**Key insight:** EcoCoin links financial incentives directly to verified environmental impact.

---

## Product (MVP)

A **fully working system**, not a concept or prototype.

### Role-Based Dashboards
- **Recycler** → Accept/submit opportunities
- **Business** → Create requests, track verification
- **Community** → Report issues, request pickups
- **Center** → Verify deposits, confirm materials
- **Admin** → Monitor pipeline, audit entire system

### Core Features ✅
- Pickup request system
- Recycler submission flow
- Center verification system
- Hedera integration (HCS + HTS)
- Proof generation system
- EcoCoin reward system
- Agent-based verification pipeline
- Admin monitoring and audit tools
- QR-assisted workflows

### Demo Flow

1. **Business** creates pickup request
2. **Recycler** accepts or submits materials independently
3. **Recycler** delivers to center
4. **Center** verifies deposit (weight, material type)
5. **Agent pipeline** processes event through verification stages
6. **Hedera** anchors transaction with immutable proof
7. **System** generates proof bundle
8. **Business & Recycler** view verified results
9. **EcoCoin** reward recorded or issued

---

## Why People Will Use It

| Current System | VeriCycle |
|---------------|-----------|
| Cash payments | Digital records |
| No proof | Verified income |
| No history | Trackable activity |
| Informal | Formal, auditable |
| No visibility | Complete transparency |

### Key UX Insight
**Users do not need blockchain knowledge. Blockchain is invisible. Value is obvious.**

---

## Tech Stack

**Built for real-world deployment, not experimentation.**

### Backend
- **Flask** — web application framework
- **SQLAlchemy** — database ORM
- **Flask-Login & Flask-Bcrypt** — authentication & security
- Worker-based agent pipeline

### Blockchain
- **Hedera Consensus Service (HCS)** — event anchoring
- **Hedera Token Service (HTS)** — EcoCoin tokens
- **Hedera SDK** — JavaScript + Python integration

### Frontend
- HTML / CSS / JavaScript
- Role-based template system
- QR-assisted workflows
- Responsive design

### Infrastructure
- **Docker** — containerization
- **Gunicorn** — application server
- **SQLite** (development) / **PostgreSQL** (production)

---

## Setup

### Prerequisites
```
Python 3.11+
Node.js 18+
pip and npm
Git
```

### Quick Start

**1. Install Dependencies**
```bash
pip install -r requirements.txt
npm install
```

**2. Initialize Database**
```bash
python scripts/reset_db.py
```

**3. Configure Environment**

Copy `.env.example` to `.env` and fill in:
```
SECRET_KEY=your_secret_key
FLASK_ENV=development
FLASK_DEBUG=1
VERICYCLE_TOPIC_ID=your_topic_id
OPERATOR_ID=your_operator_id
OPERATOR_KEY=your_operator_key
ECOCOIN_TOKEN_ID=your_token_id
ECOCOIN_TREASURY_ID=your_treasury_id
ECOCOIN_TREASURY_KEY=your_treasury_key
DEMO_MODE=true
ENCRYPTION_KEY=your_encryption_key
```

**4. Run Application** (Terminal 1)
```bash
python app.py
```
App available at `http://127.0.0.1:5000`

**5. Run Agent Worker** (Terminal 2 - recommended)
```bash
python -m agents.task_worker
```

**6. Run Smoke Tests**
```bash
pytest -q
```

### Demo Accounts

| Email | Password | Role |
|-------|----------|------|
| `admin@vericycle.com` | `Admin123!` | Administrator |
| `recycler@vericycle.com` | `Recycler123!` | Recycler |
| `business@vericycle.com` | `Business123!` | Business |
| `resident@vericycle.com` | `Resident123!` | Resident |
| `center@vericycle.com` | `Center123!` | Recycling Center |

### Useful Commands

**Prepare deterministic demo events:**
```bash
python scripts/prepare_phase5_demo_events.py
```

**Run validation tests:**
```bash
python scripts/test_pages_smoke.py
python scripts/test_phase3_opportunities_smoke.py
python scripts/test_phase6_business_and_labels.py
python scripts/test_review_transitions.py
python scripts/run_single_account_demo_check.py
```

---

## Deployment

### Docker
```bash
gunicorn -w 4 -b 0.0.0.0:$PORT app:app
```

### Production Checklist
- [ ] Set `FLASK_ENV=production`
- [ ] Configure secure SECRET_KEY and ENCRYPTION_KEY
- [ ] Use environment-managed Hedera credentials
- [ ] Deploy with managed database (PostgreSQL)
- [ ] Enable secret storage policies
- [ ] Configure reverse proxy (nginx)
- [ ] Set up monitoring and alerting
- [ ] Enable HTTPS

---

## Roadmap

### Phase 1 (Now) ✅
- MVP completion ✅
- UI/UX refinement
- Proof system optimization

### Phase 2
- Partner onboarding (centers + businesses)
- Pilot programs
- Reward pool integration

### Phase 3
- Municipality integration
- Analytics dashboards
- Ecosystem scaling

### Phase 4
- Financial inclusion integrations
- Token utility expansion
- Global expansion

---

## Vision

**A circular economy only works when contribution can be proven.**

VeriCycle makes recycling:

- **Visible** — tracked from collection to verification
- **Trusted** — backed by Hedera consensus  
- **Economically meaningful** — generates Proof of Income and ESG value

Every recycling event deserves to be recorded, verified, and valued.

## Architecture

VeriCycle runs a hybrid architecture:

| Layer | Responsibility |
|-------|----------------|
| Application Layer | Flask app, role-based workflows, proof generation |
| Coordination Layer | Agent pipeline: Collector -> Verifier -> Logbook -> Reward -> Compliance |
| Trust Layer | Hedera HCS for immutable event logs, HTS for EcoCoin reward rails |
| Evidence Layer | Proof bundles, business sustainability records, recycler Proof of Income history |

This separation keeps user experience simple while preserving cross-party trust and auditability.

---

## Supporting Materials

- **Demo Script:** [Phase 5 Judge Demo](docs/phase5_judge_demo_script.md)
- **Architecture:** See [Architecture Snapshot](README.md#architecture) section
- **Agent Pipeline:** CollectorAgent → VerifierAgent → LogbookAgent → RewardAgent → ComplianceAgent

---

## Support & Contributing

For questions, issues, or contributions, please reach out to the VeriCycle team.

VeriCycle is built for the informal economy while embracing formal verification infrastructure. Your feedback shapes our roadmap.

---

*VeriCycle: Making recycling visible, trusted, and economically meaningful.*

**Built for real-world impact. Powered by Hedera. Verified forever.**
