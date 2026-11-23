"""Insert a pickup + delivery between fixed bookings; use only directed, observed road estimates."""

from dataclasses import dataclass


class Infeasible(ValueError):
    pass


@dataclass(frozen=True)
class Booking:
    origin: str
    start: int
    destination: str
    end: int


def exclusion(driver_id, driver, case, fresh_for):
    if driver_id == case.cancelled_driver:
        return "cancelled_original"
    if not any(a <= case.as_of < b for a, b in driver.shifts):
        return "off_shift"
    if driver.capacity - driver.load < case.units:
        return "capacity"
    if case.perishable and driver.cold_carrier is False:
        return "cold_carrier_unavailable"
    if (
        driver.position is None
        or driver.last_seen is None
        or not 0 <= case.as_of - driver.last_seen <= fresh_for
    ):
        return "unverified_position"
    if case.perishable and driver.cold_carrier is None:
        return "unverified_cold_carrier"
    return None


def route_for_driver(driver, case, handling, matrix, reservations):
    shift_end = next(end for start, end in driver.shifts if start <= case.as_of < end)
    fixed = [Booking(s.place, s.start, s.place, s.end) for s in driver.stops]
    fixed.extend(reservations)
    if any(driver.last_seen < stop.end <= case.as_of for stop in fixed):
        return None, ["unverified_position"]
    fixed = sorted(
        (s for s in fixed if s.end > case.as_of and s.start < shift_end), key=lambda s: s.start
    )
    start_at, origin = case.as_of, driver.position
    if fixed and fixed[0].start < start_at:
        current = fixed.pop(0)
        try:
            if driver.last_seen < current.start:
                if driver.last_seen + matrix(origin, current.origin) > current.start:
                    return None, ["existing_booking"]
                arrival = current.start + matrix(current.origin, current.destination)
            else:
                arrival = driver.last_seen + matrix(origin, current.destination)
        except Infeasible as exc:
            return None, [str(exc)]
        if arrival > current.end:
            return None, ["existing_booking"]
        start_at, origin = current.end, current.destination

    def simulate(slot):
        at, place, driving = start_at, origin, 0
        pickup_at = delivered = pickup_done = None
        for i in range(len(fixed) + 1):
            if i == slot:
                travel = matrix(place, case.pickup)
                driving += travel
                pickup_at = max(at + travel, case.pickup_window[0])
                onward = matrix(case.pickup, case.dropoff)
                if case.perishable:
                    # Wait at the donor if an early loading would exceed the transport limit.
                    pickup_at = max(pickup_at, case.dropoff_window[0] - case.max_onboard)
                pickup_done = pickup_at + handling
                if pickup_done > case.pickup_window[1]:
                    raise Infeasible("pickup_deadline")
                travel = onward
                driving += travel
                delivered = max(pickup_done + travel, case.dropoff_window[0]) + handling
                if delivered > case.dropoff_window[1]:
                    raise Infeasible("delivery_deadline")
                if case.perishable and delivered - pickup_done > case.max_onboard:
                    raise Infeasible("cold_time_limit")
                at, place = delivered, case.dropoff
            if i < len(fixed):
                stop = fixed[i]
                travel = matrix(place, stop.origin)
                driving += travel
                if at + travel > stop.start:
                    raise Infeasible("existing_booking")
                if stop.origin != stop.destination:
                    booked_drive = matrix(stop.origin, stop.destination)
                    if stop.start + booked_drive > stop.end:
                        raise Infeasible("existing_booking")
                    driving += booked_drive
                at, place = stop.end, stop.destination
        home = matrix(place, driver.return_to)
        if at + home > shift_end:
            raise Infeasible("shift_return")
        return {
            "pickup_at": pickup_at,
            "pickup_done": pickup_done,
            "delivered_at": delivered,
            "deadline_slack_min": case.dropoff_window[1] - delivered,
            "shift_return_at": at + home,
            "road_minutes_full_tour": driving + home,
            "bookings_before_pickup": slot,
        }

    choices, failures = [], set()
    for slot in range(len(fixed) + 1):
        try:
            choices.append(simulate(slot))
        except Infeasible as exc:
            failures.add(str(exc))
    if not choices:
        return None, sorted(failures)
    return min(choices, key=lambda r: (r["delivered_at"], r["road_minutes_full_tour"])), []


def make_matrix(roads):
    index = {place: i for i, place in enumerate(roads.places)}

    def minutes(origin, destination):
        if origin not in index or destination not in index:
            raise Infeasible("road_unknown")
        value = roads.minutes[index[origin]][index[destination]]
        if value is None:
            raise Infeasible("road_unknown")
        return value

    return minutes
