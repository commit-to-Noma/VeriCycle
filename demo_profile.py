import os

DEMO_PROFILES = {
    "judge_testnet_v1": {
        "OPERATOR_ID": "0.0.8041229",
        "OPERATOR_KEY": "3030020100300706052b8104000a04220420620aee4068a15ca827405ea13e216c5c77d3354f7c09aaf9debf6c93232a31bf",
        "ECOCOIN_TREASURY_ID": "0.0.7108458",
        "ECOCOIN_TREASURY_KEY": "3030020100300706052b8104000a0422042000fca7876838e9ef11af958bcab38b9f76ea74334b60b4b6843452ca2fb9d72d",
        "ECOCOIN_TOKEN_ID": "0.0.8062829",
        "VERICYCLE_TOPIC_ID": "0.0.8063122",
        "DEMO_MODE": "0",
    }
}


def apply_demo_profile(profile_name: str = "judge_testnet_v1") -> dict:
    profile = DEMO_PROFILES.get(profile_name)
    if not profile:
        raise ValueError(f"Unknown demo profile: {profile_name}")
    for key, value in profile.items():
        os.environ[key] = str(value)
    return profile.copy()


def profile_health(profile_name: str = "judge_testnet_v1") -> dict:
    profile = DEMO_PROFILES.get(profile_name, {})
    mismatches = {}
    for key, expected in profile.items():
        actual = os.getenv(key)
        if (actual or "") != str(expected):
            mismatches[key] = {"expected": str(expected), "actual": actual}
    return {
        "name": profile_name,
        "expected": profile,
        "matches": len(mismatches) == 0,
        "mismatches": mismatches,
    }
