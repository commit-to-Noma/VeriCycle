# Phase 2 Handoff Checklist

Date: 2026-03-13

## Phase 2 status

Phase 2 is complete and stable for the role model transition with legacy compatibility.

## Completed in Phase 2

1. Runtime role normalization added.
- `collector` is treated as effective `recycler` at runtime.
- No DB migration was required.

2. Capability helper functions added.
- `is_recycler_user`, `is_business_user`, `is_resident_user`, `is_center_user`, `is_admin_user`
- `can_create_opportunity_business`, `can_create_opportunity_resident`, `can_accept_opportunity_recycler`, `can_verify_deposit_center`

3. Auth role set expanded and validated.
- Allowed roles in signup/login: `recycler`, `business`, `resident`, `center`, `admin`
- Recycler signup persists as `collector` for backward compatibility.

4. Template role context standardized.
- Context processor injects `current_effective_role`.
- Auth UI labels use Recycler/Business/Resident/Center/Admin.

5. Role-specific access enforced.
- `/collector`: recycler-only (effective role)
- `/request-pickup`: business-only
- `/household` and household POST actions: resident-only
- `/center`: center or admin

6. Navigation consistency updates.
- Authenticated top nav respects role-specific links.
- Recycler side drawer includes placeholder links for Business Hub and Community Hub.

7. Smoke tests added and passing.
- `scripts/test_phase2_roles_smoke.py`
- Current expected result: `PHASE2_ROLE_SMOKE: PASS`

## Intentional behaviors (not bugs)

1. Recycler users with incomplete profile are redirected from `/collector` to `/profile`.
2. Recycler can still see placeholder Business/Community links in the side drawer, but backend guards enforce role access.
3. Center and admin are restricted from business/resident hubs and redirected to role-home routes.
4. Legacy users stored as `collector` continue to function as recycler users.

## Known non-goals for Phase 2

1. No new database tables for pickup opportunities.
2. No role-row migrations from `collector` to `recycler`.
3. No dashboard rewrites beyond routing/access stabilization.

## Phase 3 recommended starting points

1. Introduce explicit opportunity domain model and persistence.
2. Replace placeholder Business/Community flows with real create/accept lifecycle.
3. Move recycler placeholder links to real recycler opportunity queues.
4. Add route-level unit tests for capability helpers and redirects.
5. Plan controlled migration from persisted `collector` to `recycler` only when all routes and scripts are ready.

## Pre-Phase-3 verification command

Run before starting Phase 3 work:

```bash
python scripts/test_phase2_roles_smoke.py
```
