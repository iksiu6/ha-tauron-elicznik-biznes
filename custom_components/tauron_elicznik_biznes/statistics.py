"""Import godzinowych danych do statystyk długoterminowych (panel Energia)."""
from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMeanType, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)

from .const import DOMAIN, ENERGY_CONSUMED, ENERGY_REACTIVE_CAP, ENERGY_REACTIVE_IND, ENERGY_RETURNED, TZ

if TYPE_CHECKING:
    from .coordinator import TauronCoordinator

_LOGGER = logging.getLogger(__name__)

MAX_DAYS_PER_RUN = 31   # ograniczenie liczby zapytań w jednym cyklu
FINAL_AFTER_DAYS = 3    # brak danych starszych niż N dni traktujemy jako trwałą lukę

STAT_NAMES = {
    ENERGY_CONSUMED: "energia pobrana",
    ENERGY_RETURNED: "energia oddana",
    ENERGY_REACTIVE_IND: "energia bierna indukcyjna",
    ENERGY_REACTIVE_CAP: "energia bierna pojemnościowa",
}


def _metadata(statistic_id: str, name: str, unit: str) -> StatisticMetaData:
    return StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=name,
        source=DOMAIN,
        statistic_id=statistic_id,
        unit_class="energy" if unit == "kWh" else "reactive_energy",
        unit_of_measurement=unit,
    )


def hourly_points(day: dt.date, values: list[float | None]) -> list[tuple[dt.datetime, float | None]]:
    """Godzina i (0..23) eLicznika = przedział [i:00, i+1:00) czasu lokalnego."""
    points = []
    for i, v in enumerate(values[:24]):
        # Czas ścienny - eLicznik zwraca 24 wartości także w dni zmiany czasu.
        start = dt.datetime.combine(day, dt.time(i), TZ)
        points.append((start.astimezone(dt.UTC), v))
    return points


async def async_import_hourly(coordinator: "TauronCoordinator", energy_key: str, unit: str, today: dt.date) -> None:
    hass = coordinator.hass
    statistic_id = coordinator.statistic_id(energy_key)
    ppe = coordinator.config_entry.data.get("meter_name") or coordinator.meter_id

    last = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, True, {"sum"}
    )
    if last.get(statistic_id):
        row = last[statistic_id][0]
        last_start = dt.datetime.fromtimestamp(row["start"], dt.UTC)
        running_sum = float(row.get("sum") or 0.0)
        start_day = last_start.astimezone(TZ).date()
    else:
        last_start = None
        running_sum = 0.0
        start_day = today - dt.timedelta(days=coordinator.history_days)

    end_day = min(today, start_day + dt.timedelta(days=MAX_DAYS_PER_RUN - 1))
    merged: dict[dt.datetime, float] = {}
    stop = False
    day = start_day
    while day <= end_day and not stop:
        data = await coordinator.get_day(energy_key, day)
        final = day < today - dt.timedelta(days=FINAL_AFTER_DAYS)
        for start, value in hourly_points(day, data.values):
            if value is None:
                if final:
                    continue  # trwała luka w danych
                stop = True   # dane jeszcze nie spłynęły - wrócimy w kolejnym cyklu
                break
            if last_start is not None and start <= last_start:
                continue
            merged[start] = merged.get(start, 0.0) + value  # kolizja godzin przy zmianie czasu
        day += dt.timedelta(days=1)

    if not merged:
        return

    stats: list[StatisticData] = []
    for start in sorted(merged):
        running_sum += merged[start]
        stats.append(StatisticData(start=start, state=merged[start], sum=round(running_sum, 4)))

    async_add_external_statistics(
        hass, _metadata(statistic_id, f"Tauron {ppe} {STAT_NAMES[energy_key]}", unit), stats
    )
    _LOGGER.debug("Zaimportowano %s godzin do %s", len(stats), statistic_id)


async def async_import_power(coordinator: "TauronCoordinator", today: dt.date) -> None:
    """Moc 15-min -> statystyki godzinowe (średnia / min / max) w kW."""
    hass = coordinator.hass
    statistic_id = coordinator.statistic_id("power")
    ppe = coordinator.config_entry.data.get("meter_name") or coordinator.meter_id

    last = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, True, {"mean"}
    )
    if last.get(statistic_id):
        last_start = dt.datetime.fromtimestamp(last[statistic_id][0]["start"], dt.UTC)
        start_day = last_start.astimezone(TZ).date()
    else:
        last_start = None
        start_day = today - dt.timedelta(days=coordinator.history_days)

    end_day = min(today, start_day + dt.timedelta(days=MAX_DAYS_PER_RUN - 1))
    hours: dict[dt.datetime, list[float]] = {}
    day = start_day
    stop = False
    while day <= end_day and not stop:
        profile = await coordinator.get_power_day(day)
        final = day < today - dt.timedelta(days=FINAL_AFTER_DAYS)
        for i, value in enumerate(profile.values):
            if value is None:
                if final:
                    continue
                stop = True
                break
            local = (dt.datetime.combine(day, dt.time(0)) + dt.timedelta(minutes=15 * i)).replace(tzinfo=TZ)
            hour = local.replace(minute=0).astimezone(dt.UTC)
            hours.setdefault(hour, []).append(value)
        day += dt.timedelta(days=1)

    stats: list[StatisticData] = []
    for start in sorted(hours):
        vals = hours[start]
        if last_start is not None and start <= last_start:
            continue
        if len(vals) < 4 and start == max(hours):
            continue  # niepełna ostatnia godzina - dokończymy w kolejnym cyklu
        stats.append(
            StatisticData(start=start, mean=round(sum(vals) / len(vals), 3), min=min(vals), max=max(vals))
        )
    if not stats:
        return
    meta = StatisticMetaData(
        mean_type=StatisticMeanType.ARITHMETIC,
        has_sum=False,
        name=f"Tauron {ppe} moc 15-min",
        source=DOMAIN,
        statistic_id=statistic_id,
        unit_class="power",
        unit_of_measurement="kW",
    )
    async_add_external_statistics(hass, meta, stats)
    _LOGGER.debug("Zaimportowano %s godzin mocy do %s", len(stats), statistic_id)
