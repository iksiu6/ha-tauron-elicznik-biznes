"""Konfiguracja przez UI: logowanie, wybór punktu poboru, interwał odczytów."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .api import Meter, TauronAuthError, TauronBlockedError, TauronBusinessClient, TauronError
from .const import (
    CONF_HISTORY_DAYS,
    CONF_METER_ID,
    CONF_METER_NAME,
    CONF_REGISTER_MULTIPLIER,
    CONF_SCAN_INTERVAL,
    CONF_STATISTICS,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_HISTORY_DAYS,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    NAME,
)

_LOGGER = logging.getLogger(__name__)

CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD, autocomplete="current-password")
        ),
    }
)


def _settings_schema(defaults: Mapping[str, Any]) -> dict:
    return {
        vol.Required(
            CONF_SCAN_INTERVAL, default=int(defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=MIN_SCAN_INTERVAL,
                max=MAX_SCAN_INTERVAL,
                step=5,
                unit_of_measurement="min",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Required(CONF_STATISTICS, default=bool(defaults.get(CONF_STATISTICS, True))): selector.BooleanSelector(),
        vol.Required(
            CONF_HISTORY_DAYS, default=int(defaults.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS))
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=MAX_HISTORY_DAYS, step=1, unit_of_measurement="dni", mode=selector.NumberSelectorMode.BOX
            )
        ),
        vol.Required(
            CONF_REGISTER_MULTIPLIER, default=float(defaults.get(CONF_REGISTER_MULTIPLIER, 0) or 0)
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=100000, step="any", mode=selector.NumberSelectorMode.BOX)
        ),
    }


async def _login(hass: HomeAssistant, username: str, password: str) -> list[Meter]:
    # Tymczasowa, osobna sesja tylko do weryfikacji danych logowania.
    client = TauronBusinessClient(username, password)
    try:
        return await client.login()
    finally:
        await client.close()


def _map_errors(err: Exception) -> str:
    if isinstance(err, TauronAuthError):
        return "invalid_auth"
    if isinstance(err, TauronBlockedError):
        return "blocked"
    if isinstance(err, TauronError):
        return "cannot_connect"
    _LOGGER.exception("Nieoczekiwany błąd logowania")
    return "unknown"


class TauronBusinessConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, str] = {}
        self._meters: list[Meter] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TauronOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                meters = await _login(self.hass, user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
            except Exception as err:  # noqa: BLE001
                errors["base"] = _map_errors(err)
            else:
                business = [m for m in meters if m.is_business]
                if not business:
                    errors["base"] = "no_business_meter"
                else:
                    self._credentials = {
                        CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    }
                    self._meters = business
                    return await self.async_step_meter()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(CREDENTIALS_SCHEMA, user_input or {}),
            errors=errors,
        )

    async def async_step_meter(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            meter = next(m for m in self._meters if m.meter_id == user_input[CONF_METER_ID])
            await self.async_set_unique_id(f"{self._credentials[CONF_USERNAME].lower()}_{meter.meter_id}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"{NAME} {meter.name}",
                data={**self._credentials, CONF_METER_ID: meter.meter_id, CONF_METER_NAME: meter.name},
                options={
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_STATISTICS: user_input[CONF_STATISTICS],
                    CONF_HISTORY_DAYS: int(user_input[CONF_HISTORY_DAYS]),
                    CONF_REGISTER_MULTIPLIER: float(user_input.get(CONF_REGISTER_MULTIPLIER, 0) or 0),
                },
            )

        options = [selector.SelectOptionDict(value=m.meter_id, label=f"PPE {m.name}") for m in self._meters]
        schema = vol.Schema(
            {
                vol.Required(CONF_METER_ID, default=self._meters[0].meter_id): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.DROPDOWN)
                ),
                **_settings_schema({}),
            }
        )
        return self.async_show_form(step_id="meter", data_schema=schema)

    # ---------------------------------------------------------- ponowne logowanie
    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _login(self.hass, entry.data[CONF_USERNAME], user_input[CONF_PASSWORD])
            except Exception as err:  # noqa: BLE001
                errors["base"] = _map_errors(err)
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): CREDENTIALS_SCHEMA.schema[CONF_PASSWORD]}),
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )

    # ---------------------------------------------------------- zmiana loginu/hasła
    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                meters = await _login(self.hass, user_input[CONF_USERNAME], user_input[CONF_PASSWORD])
            except Exception as err:  # noqa: BLE001
                errors["base"] = _map_errors(err)
            else:
                if not any(m.meter_id == entry.data[CONF_METER_ID] for m in meters):
                    errors["base"] = "meter_not_found"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={
                            CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                        },
                    )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                CREDENTIALS_SCHEMA, {CONF_USERNAME: entry.data[CONF_USERNAME]}
            ),
            errors=errors,
        )


class TauronOptionsFlow(OptionsFlow):
    """Zmiana interwału odczytów i ustawień statystyk po instalacji."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_STATISTICS: user_input[CONF_STATISTICS],
                    CONF_HISTORY_DAYS: int(user_input[CONF_HISTORY_DAYS]),
                    CONF_REGISTER_MULTIPLIER: float(user_input.get(CONF_REGISTER_MULTIPLIER, 0) or 0),
                }
            )
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=vol.Schema(_settings_schema(current)))
