"""One local service day. All times are integer minutes, all quantities are FoodGo units."""

import itertools
from datetime import date
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

Minute = Annotated[int, Field(ge=0, le=1440)]
Positive = Annotated[int, Field(ge=1)]
Nonnegative = Annotated[int, Field(ge=0)]


def ordered(pair):
    if pair[0] >= pair[1]:
        raise ValueError("Time windows must have a positive duration.")
    return pair


Window = Annotated[list[Minute], Field(min_length=2, max_length=2), AfterValidator(ordered)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Stop(Record):
    place: str
    start: Minute
    end: Minute

    @model_validator(mode="after")
    def ordered_times(self):
        ordered([self.start, self.end])
        return self


class Driver(Record):
    shifts: list[Window]
    capacity: Positive
    load: Nonnegative
    position: str | None
    last_seen: Minute | None
    return_to: str
    cold_carrier: bool | None
    stops: list[Stop]

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.load > self.capacity:
            raise ValueError("Existing cargo exceeds vehicle capacity.")
        shifts = sorted(self.shifts)
        if any(a[1] > b[0] for a, b in itertools.pairwise(shifts)):
            raise ValueError("Overlapping shifts.")
        stops = sorted(self.stops, key=lambda s: s.start)
        if any(a.end > b.start for a, b in itertools.pairwise(stops)):
            raise ValueError("Overlapping fixed appointments.")
        return self


class Pickup(Record):
    as_of: Minute
    cancelled_driver: str
    units: Positive
    perishable: bool
    pickup: str
    dropoff: str
    pickup_window: Window
    dropoff_window: Window
    max_onboard: Positive | None


class Board(Record):
    service_date: str
    timezone: str
    handling_minutes: Positive
    fresh_for: Nonnegative
    drivers: dict[str, Driver]
    cases: dict[str, Pickup]

    @model_validator(mode="after")
    def validate_references(self):
        date.fromisoformat(self.service_date)
        if not self.timezone or any(
            x.cancelled_driver not in self.drivers for x in self.cases.values()
        ):
            raise ValueError("Missing time zone or cancelled driver.")
        return self


class Roads(Record):
    source: str
    fetched_utc: str
    places: list[str]
    minutes: list[list[Nonnegative | None]]
    snap_metres: dict[str, Nonnegative]

    @model_validator(mode="after")
    def validate_matrix(self):
        size = len(self.places)
        if (
            len(set(self.places)) != size
            or len(self.minutes) != size
            or any(len(r) != size for r in self.minutes)
        ):
            raise ValueError("Invalid travel matrix dimensions or duplicate places.")
        return self
