"""Deterministic date arithmetic shared by procedural previews and action artifacts."""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal


@dataclass(frozen=True)
class CountingMethod:
    duration: int
    unit: Literal["calendar_days", "business_days"]
    include_trigger: bool
    roll: Literal["none", "next_open", "previous_open"]


@dataclass(frozen=True)
class DeadlineDates:
    nominal: date
    due: date
    calendar: tuple[tuple[date, bool], ...]


def count_days(method, trigger, calendar):
    window = 372 if method.unit == "calendar_days" else 740
    if not 1 <= method.duration <= 365 or not date.min <= trigger <= date.max - timedelta(days=window):
        return None
    consulted = {}

    def is_open(day):
        if day.weekday() >= 5:
            consulted[day] = False
            return False
        value = calendar.get(day)
        if type(value) is bool:
            consulted[day] = value
            return value
        return None

    if method.unit == "calendar_days":
        nominal = trigger + timedelta(days=method.duration - method.include_trigger)
    else:
        day = trigger if method.include_trigger else trigger + timedelta(days=1)
        remaining = method.duration
        for _ in range(732):
            state = is_open(day)
            if state is None:
                return None
            remaining -= state
            if not remaining:
                nominal = day
                break
            day += timedelta(days=1)
        else:
            return None
    if method.roll == "none":
        return DeadlineDates(nominal, nominal, tuple(consulted.items()))
    direction = 1 if method.roll == "next_open" else -1
    for offset in range(8):
        index = nominal.toordinal() + direction * offset
        if not 1 <= index <= date.max.toordinal():
            return None
        day = date.fromordinal(index)
        state = is_open(day)
        if state is None:
            return None
        if state:
            return DeadlineDates(nominal, day, tuple(consulted.items()))
    return None
