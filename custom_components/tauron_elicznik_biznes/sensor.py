"""Sensory eLicznika biznesowego."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TauronConfigEntry
from .const import (
    CONF_METER_NAME,
    DOMAIN,
    ENERGY_CONSUMED,
    ENERGY_REACTIVE_CAP,
    ENERGY_REACTIVE_IND,
    ENERGY_RETURNED,
    ENERGY_TYPES,
    MANUFACTURER,
    PERIOD_MONTH,
    PERIOD_TODAY,
    PERIOD_YEAR,
    PERIOD_YESTERDAY,
    PERIODS,
    READING_TYPES,
    ZONES,
)
from .coordinator import TauronCoordinator, TauronData

ENERGY_LABELS = {
    ENERGY_CONSUMED: "Energia pobrana",
    ENERGY_RETURNED: "Energia oddana",
    ENERGY_REACTIVE_IND: "Energia bierna indukcyjna",
    ENERGY_REACTIVE_CAP: "Energia bierna pojemnościowa",
}
PERIOD_LABELS = {
    PERIOD_TODAY: "dziś",
    PERIOD_YESTERDAY: "wczoraj",
    PERIOD_MONTH: "bieżący miesiąc",
    PERIOD_YEAR: "bieżący rok",
}
# Sumy narastające w okresie (zerowane na początku dnia/miesiąca/roku).
# "Wczoraj" to wartość zamknięta - bez state_class, żeby nie psuć statystyk.
PERIOD_STATE_CLASS = {
    PERIOD_TODAY: SensorStateClass.TOTAL_INCREASING,
    PERIOD_YESTERDAY: None,
    PERIOD_MONTH: SensorStateClass.TOTAL_INCREASING,
    PERIOD_YEAR: SensorStateClass.TOTAL_INCREASING,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: TauronConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    zones = sorted(coordinator.data.zone_names()) or ZONES
    entities: list[SensorEntity] = []

    for energy_key in ENERGY_TYPES:
        for period in PERIODS:
            entities.append(TauronEnergySensor(coordinator, energy_key, period, None))
            for zone in zones:
                entities.append(TauronEnergySensor(coordinator, energy_key, period, zone))

    for period in PERIODS:
        entities.append(TauronTgPhiSensor(coordinator, period, None))
        for zone in zones:
            entities.append(TauronTgPhiSensor(coordinator, period, zone))

    for desc in (*POWER_SENSORS, *POWER_PROFILE_SENSORS, *CAPACITY_FEE_SENSORS, *METER_SENSORS, *INBOX_SENSORS):
        entities.append(TauronValueSensor(coordinator, desc))

    for energy_key in READING_TYPES:
        entities.append(TauronRegisterSensor(coordinator, energy_key, None))
        for zone in zones:
            entities.append(TauronRegisterSensor(coordinator, energy_key, zone))

    async_add_entities(entities)


class TauronEntity(CoordinatorEntity[TauronCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: TauronCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        ppe = entry.data.get(CONF_METER_NAME) or coordinator.meter_id
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        tariff = (coordinator.data.meter_info or {}).get("Tariff") if coordinator.data else None
        details = coordinator.data.meter_details if coordinator.data else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.meter_id)},
            name=f"Tauron PPE {ppe}",
            manufacturer=MANUFACTURER,
            model=f"eLicznik biznes{f' - taryfa {tariff}' if tariff else ''}",
            model_id=details.model if details and details.model else None,
            hw_version=f"licznik {details.number}" if details and details.number else None,
            serial_number=ppe,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://elicznik.tauron-dystrybucja.pl",
        )

    @property
    def tdata(self) -> TauronData:
        return self.coordinator.data


class TauronEnergySensor(TauronEntity, SensorEntity):
    _unrecorded_attributes = frozenset({"values"})

    def __init__(self, coordinator: TauronCoordinator, energy_key: str, period: str, zone: str | None) -> None:
        key = f"{energy_key}_{period}" + (f"_t{zone}" if zone else "")
        super().__init__(coordinator, key)
        self._energy_key = energy_key
        self._period = period
        self._zone = zone
        unit = ENERGY_TYPES[energy_key]["unit"]
        self._attr_name = f"{ENERGY_LABELS[energy_key]} {PERIOD_LABELS[period]}" + (f" T{zone}" if zone else "")
        self._attr_suggested_display_precision = 2
        self._attr_state_class = PERIOD_STATE_CLASS[period]
        if unit == "kWh":
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        else:
            self._attr_device_class = SensorDeviceClass.REACTIVE_ENERGY
            self._attr_native_unit_of_measurement = "kvarh"
        self._attr_icon = "mdi:transmission-tower-import" if energy_key == ENERGY_CONSUMED else (
            "mdi:transmission-tower-export" if energy_key == ENERGY_RETURNED else "mdi:sine-wave"
        )
        # Strefy dla "dziś" domyślnie wyłączone - ograniczenie liczby encji
        if zone and period == PERIOD_TODAY:
            self._attr_entity_registry_enabled_default = False

    def _data(self):
        return self.tdata.energy.get(self._energy_key, {}).get(self._period) if self.tdata else None

    @property
    def native_value(self) -> float | None:
        d = self._data()
        if d is None or not d.has_data:
            return None
        if self._zone is None:
            return round(d.total, 3)
        v = d.zones.get(self._zone)
        return round(v, 3) if v is not None else 0.0

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        d = self._data()
        if d is None:
            return None
        attrs: dict[str, Any] = {}
        if self._zone:
            attrs["strefa"] = d.zone_names.get(self._zone)
        else:
            attrs["values"] = d.values
            attrs["strefy"] = {f"T{k}": round(v, 3) for k, v in d.zones.items()}
        return attrs


class TauronTgPhiSensor(TauronEntity, SensorEntity):
    _attr_icon = "mdi:angle-acute"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: TauronCoordinator, period: str, zone: str | None) -> None:
        super().__init__(coordinator, f"tg_phi_{period}" + (f"_t{zone}" if zone else ""))
        self._period = period
        self._zone = zone
        self._attr_name = f"Tg φ {PERIOD_LABELS[period]}" + (f" T{zone}" if zone else "")
        ppe = coordinator.config_entry.data.get(CONF_METER_NAME) or coordinator.meter_id
        period_slug = {PERIOD_TODAY: "dzis", PERIOD_YESTERDAY: "wczoraj", PERIOD_MONTH: "biezacy_miesiac",
                       PERIOD_YEAR: "biezacy_rok"}[period]
        self.entity_id = f"sensor.tauron_ppe_{ppe}_tg_fi_{period_slug}" + (f"_t{zone}" if zone else "")
        self._attr_state_class = SensorStateClass.MEASUREMENT if period != PERIOD_YESTERDAY else None
        if zone and period == PERIOD_TODAY:
            self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> float | None:
        return self.tdata.tg_phi(self._period, self._zone) if self.tdata else None


@dataclass(frozen=True, kw_only=True)
class TauronValueDescription(SensorEntityDescription):
    value_fn: Callable[[TauronData], Any]
    attrs_fn: Callable[[TauronData], dict[str, Any] | None] = lambda d: None


def _power_attrs(d: TauronData) -> dict[str, Any] | None:
    if not d.power:
        return None
    top = d.power.max_entry
    return {
        "data_pomiaru": top.get("Data") if top else None,
        "najwyzsze_moce": [{"data": e.get("Data"), "moc_kw": e.get("Wartosc")} for e in d.power.entries],
    }


POWER_SENSORS: tuple[TauronValueDescription, ...] = (
    TauronValueDescription(
        key="power_max_month",
        name="Moc maksymalna bieżący miesiąc",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.power.maximum if d.power else None,
        attrs_fn=_power_attrs,
    ),
    TauronValueDescription(
        key="power_avg_of_max_month",
        name="Średnia z mocy maksymalnych bieżący miesiąc",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.power.average_of_max if d.power else None,
    ),
    TauronValueDescription(
        key="power_excess_month",
        name="Przekroczenie mocy umownej bieżący miesiąc",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:alert-circle-outline",
        value_fn=lambda d: d.power.excess if d.power else None,
    ),
    TauronValueDescription(
        key="power_contracted",
        name="Moc umowna",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.power.contracted if d.power else None,
    ),
    TauronValueDescription(
        key="tariff",
        name="Taryfa",
        icon="mdi:cash-clock",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (d.meter_info or {}).get("Tariff"),
    ),
    TauronValueDescription(
        key="last_data_hour",
        name="Dane dostępne do",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.last_hour,
    ),
    TauronValueDescription(
        key="last_update",
        name="Ostatnia aktualizacja",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.updated,
    ),
)


class TauronValueSensor(TauronEntity, SensorEntity):
    entity_description: TauronValueDescription
    _unrecorded_attributes = frozenset({"values", "wiadomosci", "zdarzenia", "najwyzsze_moce"})

    def __init__(self, coordinator: TauronCoordinator, description: TauronValueDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.tdata) if self.tdata else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.entity_description.attrs_fn(self.tdata) if self.tdata else None


# ----------------------------------------------------------------------------- v0.2.0
REGISTER_LABELS = {
    ENERGY_CONSUMED: "Stan licznika energia pobrana",
    ENERGY_RETURNED: "Stan licznika energia oddana",
    ENERGY_REACTIVE_IND: "Stan licznika energia bierna indukcyjna",
    ENERGY_REACTIVE_CAP: "Stan licznika energia bierna pojemnościowa",
}


class TauronRegisterSensor(TauronEntity, SensorEntity):
    """Stan liczydła (zakładka Odczyty) przemnożony przez przekładnię - nadaje się do panelu Energia."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: TauronCoordinator, energy_key: str, zone: str | None) -> None:
        super().__init__(coordinator, f"register_{energy_key}" + (f"_t{zone}" if zone else ""))
        self._energy_key = energy_key
        self._zone = zone
        self._attr_name = REGISTER_LABELS[energy_key] + (f" T{zone}" if zone else "")
        if READING_TYPES[energy_key]["unit"] == "kWh":
            self._attr_device_class = SensorDeviceClass.ENERGY
            self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        else:
            self._attr_device_class = SensorDeviceClass.REACTIVE_ENERGY
            self._attr_native_unit_of_measurement = "kvarh"
        self._attr_icon = "mdi:counter"

    @property
    def native_value(self) -> float | None:
        return self.tdata.register_value(self._energy_key, self._zone) if self.tdata else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        reading = self.tdata.readings.get(self._energy_key) if self.tdata else None
        if reading is None:
            return None
        raw = reading.total if self._zone is None else reading.zones.get(self._zone)
        return {
            "data_odczytu": reading.timestamp.isoformat(),
            "wskazanie_liczydla": raw,
            "przekladnia": self.tdata.register_multiplier,
        }


def _profile_attrs(period: str) -> Callable[[TauronData], dict[str, Any] | None]:
    def attrs(d: TauronData) -> dict[str, Any] | None:
        mx = d.max_power(period)
        return {"czas": mx[0].isoformat()} if mx else None

    return attrs


def _last_power_attrs(d: TauronData) -> dict[str, Any] | None:
    last = d.last_power()
    profile = d.power_profiles.get(PERIOD_TODAY)
    attrs: dict[str, Any] = {"koniec_przedzialu": last[0].isoformat() if last else None}
    if profile:
        attrs["values"] = profile.values
        attrs["moc_umowna"] = profile.contracted
    return attrs


POWER_PROFILE_SENSORS: tuple[TauronValueDescription, ...] = (
    TauronValueDescription(
        key="power_15min_last",
        name="Moc 15-min ostatnia",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:flash",
        value_fn=lambda d: (lp[1] if (lp := d.last_power()) else None),
        attrs_fn=_last_power_attrs,
    ),
    TauronValueDescription(
        key="power_max_today",
        name="Moc maksymalna dziś",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: (mx[1] if (mx := d.max_power(PERIOD_TODAY)) else None),
        attrs_fn=_profile_attrs(PERIOD_TODAY),
    ),
    TauronValueDescription(
        key="power_max_yesterday",
        name="Moc maksymalna wczoraj",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        value_fn=lambda d: (mx[1] if (mx := d.max_power(PERIOD_YESTERDAY)) else None),
        attrs_fn=_profile_attrs(PERIOD_YESTERDAY),
    ),
    TauronValueDescription(
        key="register_multiplier",
        name="Przekładnia liczydła",
        icon="mdi:multiplication",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.register_multiplier,
        attrs_fn=lambda d: {"zrodlo": d.register_multiplier_source},
    ),
    TauronValueDescription(
        key="register_reading_time",
        name="Data odczytu liczydła",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (r.timestamp if (r := d.readings.get(ENERGY_CONSUMED)) else None),
    ),
)

FEE_PERIODS = {"previous_month": "poprzedni miesiąc", PERIOD_MONTH: "bieżący miesiąc"}


def _fee_value(period: str, attr: str) -> Callable[[TauronData], Any]:
    def value(d: TauronData) -> Any:
        fee = d.capacity_fee.get(period)
        return getattr(fee, attr) if fee else None

    return value


def _fee_attrs(period: str) -> Callable[[TauronData], dict[str, Any] | None]:
    def attrs(d: TauronData) -> dict[str, Any] | None:
        fee = d.capacity_fee.get(period)
        return {"taryfa": fee.tariff, "brakujace_dane": fee.missing} if fee else None

    return attrs


CAPACITY_FEE_SENSORS: tuple[TauronValueDescription, ...] = tuple(
    desc
    for period, label in FEE_PERIODS.items()
    for desc in (
        TauronValueDescription(
            key=f"capacity_fee_usage_peak_{period}",
            name=f"Opłata mocowa energia szczytowego zapotrzebowania {label}",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            suggested_display_precision=1,
            icon="mdi:cash-clock",
            value_fn=_fee_value(period, "usage_peak"),
            attrs_fn=_fee_attrs(period),
        ),
        TauronValueDescription(
            key=f"capacity_fee_hours_peak_{period}",
            name=f"Opłata mocowa godziny szczytowego zapotrzebowania {label}",
            native_unit_of_measurement=UnitOfTime.HOURS,
            icon="mdi:clock-outline",
            value_fn=_fee_value(period, "hours_peak"),
        ),
        TauronValueDescription(
            key=f"capacity_fee_usage_off_peak_{period}",
            name=f"Opłata mocowa energia pozostała z dni roboczych {label}",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            suggested_display_precision=1,
            icon="mdi:cash-clock",
            value_fn=_fee_value(period, "usage_off_peak"),
        ),
        TauronValueDescription(
            key=f"capacity_fee_hours_off_peak_{period}",
            name=f"Opłata mocowa godziny pozostałe z dni roboczych {label}",
            native_unit_of_measurement=UnitOfTime.HOURS,
            icon="mdi:clock-outline",
            value_fn=_fee_value(period, "hours_off_peak"),
        ),
    )
)


def _detail(attr: str) -> Callable[[TauronData], Any]:
    return lambda d: getattr(d.meter_details, attr) if d.meter_details else None


def _last_event(d: TauronData) -> str | None:
    if not d.meter_details:
        return None
    if not d.meter_details.events:
        return "Brak zdarzeń"
    return d.meter_details.events[0].get("opis", "")[:255]


METER_SENSORS: tuple[TauronValueDescription, ...] = (
    TauronValueDescription(
        key="meter_number",
        name="Numer licznika",
        icon="mdi:identifier",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_detail("number"),
    ),
    TauronValueDescription(
        key="meter_model",
        name="Model licznika",
        icon="mdi:meter-electric",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_detail("model"),
    ),
    TauronValueDescription(
        key="meter_phases",
        name="Fazowość",
        icon="mdi:sine-wave",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_detail("phases"),
    ),
    TauronValueDescription(
        key="meter_last_event",
        name="Ostatnie zdarzenie licznika",
        icon="mdi:alert-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_last_event,
        attrs_fn=lambda d: (
            {
                "data": d.meter_details.events[0].get("data") if d.meter_details.events else None,
                "zdarzenia": d.meter_details.events[:20],
            }
            if d.meter_details
            else None
        ),
    ),
)


def _inbox_attrs(d: TauronData) -> dict[str, Any] | None:
    if not d.inbox:
        return None
    msgs = [
        {"id": m.id, "kategoria": m.category, "data": m.date, "tytul": m.title, "tresc": m.preview,
         "nieprzeczytana": m.unread}
        for m in d.inbox.messages[:10]
    ]
    return {"wiadomosci": msgs, "ostatnia": msgs[0] if msgs else None}


INBOX_SENSORS: tuple[TauronValueDescription, ...] = (
    TauronValueDescription(
        key="inbox_unread",
        name="Nieprzeczytane wiadomości",
        icon="mdi:email-alert-outline",
        native_unit_of_measurement="wiadomości",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.inbox.unread if d.inbox else None,
        attrs_fn=_inbox_attrs,
    ),
)
