"""Integracja Tauron eLicznik dla klientów biznesowych."""
from __future__ import annotations

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import TauronBusinessClient
from .coordinator import TauronCoordinator

PLATFORMS = [Platform.SENSOR]

type TauronConfigEntry = ConfigEntry[TauronCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: TauronConfigEntry) -> bool:
    # Osobna sesja z własnym słoikiem ciasteczek (sesja eLicznika nie może mieszać się z innymi integracjami).
    session = async_create_clientsession(hass, cookie_jar=aiohttp.CookieJar())
    client = TauronBusinessClient(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD], session)
    coordinator = TauronCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: TauronConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TauronConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
