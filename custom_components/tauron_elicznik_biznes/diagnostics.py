"""Diagnostyka (Ustawienia → Urządzenia → Pobierz diagnostykę)."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import TauronConfigEntry

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: TauronConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "meters": [asdict(m) for m in coordinator.client.meters],
        "meter_info": data.meter_info if data else None,
        "energy": {
            k: {p: asdict(v) if v else None for p, v in periods.items()} for k, periods in (data.energy if data else {}).items()
        },
        "power": data.power.entries if data and data.power else None,
        "last_hour": str(data.last_hour) if data else None,
        "power_profiles": {k: asdict(v) if v else None for k, v in (data.power_profiles if data else {}).items()},
        "readings": {k: asdict(v) if v else None for k, v in (data.readings if data else {}).items()},
        "register_multiplier": data.register_multiplier if data else None,
        "register_multiplier_source": data.register_multiplier_source if data else None,
        "capacity_fee": {k: asdict(v) if v else None for k, v in (data.capacity_fee if data else {}).items()},
        "meter_details": asdict(data.meter_details) if data and data.meter_details else None,
        "inbox": asdict(data.inbox) if data and data.inbox else None,
    }
