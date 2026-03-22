import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app  # noqa: E402
from models import OpportunityAssignment, PickupOpportunity, User  # noqa: E402


TARGET_NOTES = [
    "Sandton Mall Cardboard Batch",
    "Rosebank Office Plastic Pickup",
    "Midrand Glass Recycling",
    "Illegal Dumping - Soweto Field",
    "Park Cleanup - Randburg",
    "Incomplete Pipeline Test",
    "Recycler2 diversity acceptance job",
]


with app.app_context():
    rows = PickupOpportunity.query.order_by(PickupOpportunity.id.desc()).all()
    print("--- scenario rows ---")
    for token in TARGET_NOTES:
        match = next((x for x in rows if token in (x.notes or "")), None)
        if not match:
            print(f"{token} => missing")
            continue
        print(
            f"{token} => id={match.id} status={match.status} kg={match.estimated_kg} material={match.material_type}"
        )

    recycler2_exists = bool(User.query.filter_by(email="recycler2@vericycle.com").first())
    accepted_count = OpportunityAssignment.query.filter_by(status="accepted").count()
    submitted_count = OpportunityAssignment.query.filter_by(status="submitted").count()
    print(f"recycler2 exists => {recycler2_exists}")
    print(f"assignments accepted={accepted_count} submitted={submitted_count}")
