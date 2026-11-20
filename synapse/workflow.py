"""Read-only operations presented to Synapse Custom for composition."""
from food_rescue.service import open_case, screen, evaluate


def get_cancelled_pickup(case_id: str) -> dict:
    """Read the cancellation, quantity, deadlines and current dispatch snapshot reference."""
    return open_case(case_id)


def screen_volunteers(case_ref: str) -> dict:
    """Check shift, check-in, cargo and handling requirements. Return driver_ids and exclusion counts."""
    return screen(case_ref)


def evaluate_routes(case_ref: str, driver_ids: list[str]) -> dict:
    """Check routes for the screened driver IDs, fixed stops and shift return. Return the full ranked report."""
    return evaluate(case_ref, driver_ids)
