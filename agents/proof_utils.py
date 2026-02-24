import hashlib
import json


def build_proof_hash(*, activity_id, user_email, amount, description, created_at, verifier_trust_weight):
    payload = {
        "activity_id": activity_id,
        "user_email": user_email or "",
        "amount": float(amount or 0),
        "description": description or "",
        "created_at": created_at or "",
        "verifier_trust_weight": verifier_trust_weight,
    }
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
