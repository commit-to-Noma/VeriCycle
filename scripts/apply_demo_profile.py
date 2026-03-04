import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from demo_profile import apply_demo_profile, profile_health


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "judge_testnet_v1"
    applied = apply_demo_profile(name)
    health = profile_health(name)
    print(json.dumps({"applied": applied, "health": health}, indent=2))
