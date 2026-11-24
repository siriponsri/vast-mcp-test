import re

PROFILE_PATTERN = r"mock(?:-[0-9a-f]{32})?"
TOOL_NAMES = {"health", "search_gpu_offers", "estimate_run_cost"}


def valid_profile(profile: str) -> bool:
    return re.fullmatch(PROFILE_PATTERN, profile) is not None
