import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, db, seed_demo_data  # noqa: E402
from models import Activity, PickupOpportunity  # noqa: E402


def main() -> int:
    with app.app_context():
        seed_demo_data(force_reset=False)

        completed_flows = Activity.query.filter(
            Activity.pipeline_stage.in_(['attested', 'rewarded', 'logged', 'verified'])
        ).count()
        pending_flows = Activity.query.filter(
            Activity.pipeline_stage.in_(['created', 'signals_collected', 'verified', 'logged'])
        ).count()
        flagged_flows = Activity.query.filter_by(pipeline_stage='needs_review').count()
        community_requests = PickupOpportunity.query.filter_by(source_role='resident').count()
        business_requests = PickupOpportunity.query.filter_by(source_role='business').count()

        print('DEMO DATA SEEDED')
        print(f'completed_flows={completed_flows}')
        print(f'pending_or_inflight_flows={pending_flows}')
        print(f'flagged_flows={flagged_flows}')
        print(f'community_requests={community_requests}')
        print(f'business_requests={business_requests}')

        db.session.commit()

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
