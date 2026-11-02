"""Koordynator odczytów eLicznika."""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    CapacityFee,
    EnergyData,
    Inbox,
    MeterDetails,
    PowerData,
    PowerProfile,
    RegisterReading,
    TauronAuthError,
    TauronBlockedError,
    TauronBusinessClient,
    TauronError,
)
from .const import (
    CONF_HISTORY_DAYS,
    CONF_METER_ID,
    CONF_REGISTER_MULTIPLIER,
    CONF_SCAN_INTERVAL,
    CONF_STATISTICS,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ENERGY_CONSUMED,
    ENERGY_REACTIVE_IND,
    ENERGY_TYPES,
    EVENT_MESSAGE,
    EVENT_METER,
    PERIOD_MONTH,
    PERIOD_TODAY,
    PERIOD_YEAR,
    PERIOD_YESTERDAY,
    READING_TYPES,
    TZ,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class TauronData:
    meter_info: dict[str, str] = field(default_factory=dict)
    energy: dict[str, dict[str, EnergyData | None]] = field(default_factory=dict)
    power: PowerData | None = None
    last_hour: dt.datetime | None = None  # koniec ostatniej godziny z danymi
    updated: dt.datetime | None = None
    # v0.2.0
    power_profiles: dict[str, PowerProfile | None] = field(default_factory=dict)  # today / yesterday
    readings: dict[str, RegisterReading | None] = field(default_factory=dict)   # ostatni stan liczydła
    register_multiplier: float | None = None
    register_multiplier_source: str | None = None  # "auto" / "manual"
    capacity_fee: dict[str, CapacityFee | None] = field(default_factory=dict)   # month / previous_month
    meter_details: MeterDetails | None = None
    inbox: Inbox | None = None

    def last_power(self) -> tuple[dt.datetime, float] | None:
        """Ostatnia dostępna moc 15-min: (koniec przedziału, kW)."""
        for period in (PERIOD_TODAY, PERIOD_YESTERDAY):
            profile = self.power_profiles.get(period)
            if profile:
                pts = profile.points()
                if pts:
                    start, value = pts[-1]
                    return start + dt.timedelta(minutes=15), value
        return None

    def max_power(self, period: str) -> tuple[dt.datetime, float] | None:
        profile = self.power_profiles.get(period)
        pts = profile.points() if profile else []
        if not pts:
            return None
        start, value = max(pts, key=lambda p: p[1])
        return start + dt.timedelta(minutes=15), value

    def register_value(self, energy_key: str, zone: str | None = None) -> float | None:
        reading = self.readings.get(energy_key)
        if reading is None or self.register_multiplier is None:
            return None
        raw = reading.total if zone is None else reading.zones.get(zone)
        return None if raw is None else round(raw * self.register_multiplier, 3)

    def tg_phi(self, period: str, zone: str | None = None) -> float | None:
        """tg φ = energia bierna indukcyjna / energia czynna pobrana (jak w eLiczniku)."""
        consumed = self.energy.get(ENERGY_CONSUMED, {}).get(period)
        inductive = self.energy.get(ENERGY_REACTIVE_IND, {}).get(period)
        if not consumed or not inductive or not consumed.has_data or not inductive.has_data:
            return None
        if zone is None:
            p, q = consumed.total, inductive.total
        else:
            p, q = consumed.zones.get(zone), inductive.zones.get(zone)
        if p is None or q is None or p <= 0:
            return None
        return round(q / p, 3)

    def zone_names(self) -> dict[str, str]:
        for period in (PERIOD_YESTERDAY, PERIOD_TODAY, PERIOD_MONTH, PERIOD_YEAR):
            d = self.energy.get(ENERGY_CONSUMED, {}).get(period)
            if d and d.zone_names:
                return d.zone_names
        return {}


class TauronCoordinator(DataUpdateCoordinator[TauronData]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: TauronBusinessClient) -> None:
        minutes = entry.options.get(CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.data[CONF_METER_ID]}",
            update_interval=dt.timedelta(minutes=int(minutes)),
        )
        self.client = client
        self.meter_id: str = entry.data[CONF_METER_ID]
        # Pamięć podręczna kompletnych dni (24 h z danymi) - nie pobieramy ich ponownie.
        self._day_cache: dict[tuple[str, dt.date], EnergyData] = {}
        self._power_cache: dict[dt.date, PowerProfile] = {}
        self._fee_cache: dict[dt.date, CapacityFee] = {}
        self._auto_multiplier: float | None = None
        self._seen_events: set[str] | None = None
        self._seen_messages: set[str] | None = None

    @property
    def import_statistics(self) -> bool:
        return self.config_entry.options.get(CONF_STATISTICS, self.config_entry.data.get(CONF_STATISTICS, True))

    @property
    def history_days(self) -> int:
        return int(
            self.config_entry.options.get(
                CONF_HISTORY_DAYS, self.config_entry.data.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS)
            )
        )

    async def get_day(self, energy_key: str, day: dt.date) -> EnergyData:
        key = (energy_key, day)
        if key in self._day_cache:
            return self._day_cache[key]
        data = await self.client.get_day(self.meter_id, energy_key, day)
        today = dt.datetime.now(TZ).date()
        if day < today and data.values and all(v is not None for v in data.values):
            self._day_cache[key] = data
        return data

    async def get_power_day(self, day: dt.date) -> PowerProfile:
        if day in self._power_cache:
            return self._power_cache[day]
        profile = await self.client.get_power_profile(self.meter_id, day)
        if day < dt.datetime.now(TZ).date() and profile.is_complete:
            self._power_cache[day] = profile
        return profile

    @property
    def manual_multiplier(self) -> float:
        return float(
            self.config_entry.options.get(
                CONF_REGISTER_MULTIPLIER, self.config_entry.data.get(CONF_REGISTER_MULTIPLIER, 0)
            )
            or 0
        )

    def _prune_cache(self, keep_from: dt.date) -> None:
        for key in [k for k in self._day_cache if k[1] < keep_from]:
            self._day_cache.pop(key, None)
        for day in [d for d in self._power_cache if d < keep_from]:
            self._power_cache.pop(day, None)

    async def _async_update_data(self) -> TauronData:
        try:
            return await self._fetch()
        except TauronAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TauronBlockedError as err:
            raise UpdateFailed(f"Konto zablokowane przez TAURON (zbyt wiele logowań): {err}") from err
        except TauronError as err:
            raise UpdateFailed(str(err)) from err
        except Exception as err:  # noqa: BLE001 - błędy sieci itp.
            raise UpdateFailed(f"Błąd komunikacji z eLicznikiem: {err}") from err

    async def _fetch(self) -> TauronData:
        now = dt.datetime.now(TZ)
        today = now.date()
        yesterday = today - dt.timedelta(days=1)
        month_start = today.replace(day=1)
        next_month = (month_start + dt.timedelta(days=32)).replace(day=1)
        month_end = next_month - dt.timedelta(days=1)

        data = TauronData()
        for energy_key in ENERGY_TYPES:
            periods: dict[str, EnergyData | None] = {}
            periods[PERIOD_TODAY] = await self.get_day(energy_key, today)
            periods[PERIOD_YESTERDAY] = await self.get_day(energy_key, yesterday)
            periods[PERIOD_MONTH] = await self.client.get_energy(
                self.meter_id, energy_key, month_start, month_end, "month"
            )
            periods[PERIOD_YEAR] = await self.client.get_energy(
                self.meter_id, energy_key, today.replace(month=1, day=1), today.replace(month=12, day=31), "year"
            )
            data.energy[energy_key] = periods

        data.power = await self.client.get_power(self.meter_id, month_start, today)

        # --- moc 15-min
        data.power_profiles[PERIOD_TODAY] = await self.get_power_day(today)
        data.power_profiles[PERIOD_YESTERDAY] = await self.get_power_day(yesterday)

        # --- stany liczydeł + przekładnia
        readings_all: dict[str, list[RegisterReading]] = {}
        for energy_key in READING_TYPES:
            rows = await self.client.get_readings(self.meter_id, energy_key, today - dt.timedelta(days=2), today)
            readings_all[energy_key] = rows
            data.readings[energy_key] = rows[-1] if rows else None
        self._set_multiplier(data, readings_all.get(ENERGY_CONSUMED, []), today, yesterday)

        # --- opłata mocowa: bieżący i poprzedni (zamknięty) miesiąc
        prev_end = month_start - dt.timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        data.capacity_fee[PERIOD_MONTH] = await self.client.get_capacity_fee(self.meter_id, month_start, month_end)
        if prev_start not in self._fee_cache:
            fee = await self.client.get_capacity_fee(self.meter_id, prev_start, prev_end)
            if fee.has_data:
                self._fee_cache = {prev_start: fee}
            data.capacity_fee["previous_month"] = fee
        else:
            data.capacity_fee["previous_month"] = self._fee_cache[prev_start]

        # --- licznik i wiadomości (błąd parsowania HTML nie może blokować reszty danych)
        try:
            data.meter_details = await self.client.get_meter_details(self.meter_id)
            self._fire_new_events(data.meter_details)
        except TauronError:
            raise
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Nie udało się odczytać danych licznika")
        try:
            data.inbox = await self.client.get_inbox(self.meter_id)
            self._fire_new_messages(data.inbox)
        except TauronError:
            raise
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Nie udało się odczytać wiadomości")

        data.meter_info = dict(self.client.meter_info)
        data.last_hour = self._last_hour(data, today, yesterday)
        data.updated = now

        if self.import_statistics:
            try:
                await self._import_statistics(today)
            except TauronError:
                raise
            except Exception:  # noqa: BLE001 - statystyki nie mogą blokować sensorów
                _LOGGER.exception("Błąd importu statystyk")

        self._prune_cache(today - dt.timedelta(days=self.history_days + 2))
        return data

    def _set_multiplier(
        self, data: TauronData, rows: list[RegisterReading], today: dt.date, yesterday: dt.date
    ) -> None:
        """Przekładnia = energia pobrana wczoraj (kWh) / przyrost liczydła 0:00 -> 0:00."""
        if self.manual_multiplier > 0:
            data.register_multiplier = self.manual_multiplier
            data.register_multiplier_source = "manual"
            return
        midnight = {r.timestamp.date(): r.total for r in rows if r.timestamp.time() == dt.time(0)}
        consumed = data.energy.get(ENERGY_CONSUMED, {}).get(PERIOD_YESTERDAY)
        if (
            consumed is not None
            and consumed.has_data
            and all(v is not None for v in consumed.values)
            and midnight.get(today) is not None
            and midnight.get(yesterday) is not None
        ):
            diff = midnight[today] - midnight[yesterday]
            if diff > 0 and consumed.total and consumed.total > 0:
                ratio = consumed.total / diff
                if ratio >= 20:
                    ratio = round(ratio / 5) * 5
                elif ratio >= 2:
                    ratio = round(ratio)
                else:
                    ratio = round(ratio, 2) if abs(ratio - 1) > 0.05 else 1.0
                if self._auto_multiplier != ratio:
                    _LOGGER.debug("Wykryta przekładnia liczydła: %s", ratio)
                self._auto_multiplier = ratio
        data.register_multiplier = self._auto_multiplier
        data.register_multiplier_source = "auto" if self._auto_multiplier is not None else None

    def _fire_new_events(self, details: MeterDetails | None) -> None:
        if details is None:
            return
        keys = {f"{e.get('data')}|{e.get('opis')}" for e in details.events}
        if self._seen_events is not None:
            for event in details.events:
                if f"{event.get('data')}|{event.get('opis')}" not in self._seen_events:
                    self.hass.bus.async_fire(EVENT_METER, {"meter_id": self.meter_id, **event})
        self._seen_events = (self._seen_events or set()) | keys

    def _fire_new_messages(self, inbox: Inbox | None) -> None:
        if inbox is None:
            return
        ids = {m.id for m in inbox.messages}
        if self._seen_messages is not None:
            for msg in inbox.messages:
                if msg.id not in self._seen_messages:
                    self.hass.bus.async_fire(
                        EVENT_MESSAGE,
                        {"meter_id": self.meter_id, "id": msg.id, "kategoria": msg.category, "data": msg.date,
                         "tytul": msg.title, "tresc": msg.preview},
                    )
        self._seen_messages = (self._seen_messages or set()) | ids

    @staticmethod
    def _last_hour(data: TauronData, today: dt.date, yesterday: dt.date) -> dt.datetime | None:
        consumed = data.energy.get(ENERGY_CONSUMED, {})
        for day, period in ((today, PERIOD_TODAY), (yesterday, PERIOD_YESTERDAY)):
            d = consumed.get(period)
            if not d:
                continue
            idx = [i for i, v in enumerate(d.values) if v is not None]
            if idx:
                return dt.datetime.combine(day, dt.time(0), TZ) + dt.timedelta(hours=idx[-1] + 1)
        return None

    # ------------------------------------------------------------------ statystyki
    def statistic_id(self, energy_key: str) -> str:
        ppe = self.config_entry.data.get("meter_name") or self.meter_id
        object_id = "".join(c if c.isalnum() else "_" for c in f"{ppe}_{energy_key}").lower()
        return f"{DOMAIN}:{object_id}"

    async def _import_statistics(self, today: dt.date) -> None:
        from .statistics import async_import_hourly

        from .statistics import async_import_power

        for energy_key, spec in ENERGY_TYPES.items():
            await async_import_hourly(self, energy_key, spec["unit"], today)
        await async_import_power(self, today)
