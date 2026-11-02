"""Test całej integracji w Home Assistant na atrapie eLicznika."""
import datetime as dt
import functools

import aiohttp
import pytest
from aiohttp.test_utils import TestServer
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.tauron_elicznik_biznes.const import DOMAIN
from tests.fake_elicznik import PASSWORD, USER, FakeTauron, patch_urls


@pytest.fixture(autouse=True)
def auto_enable(recorder_mock, enable_custom_integrations, socket_enabled):
    yield


@pytest.fixture
async def fake(monkeypatch):
    monkeypatch.setattr(aiohttp, "CookieJar", functools.partial(aiohttp.CookieJar, unsafe=True))
    fake = FakeTauron()
    server = TestServer(fake.app)
    await server.start_server()
    fake.base = str(server.make_url("")).rstrip("/")
    patch_urls(monkeypatch, fake.base)
    yield fake
    await server.close()


async def _configure(hass, interval=60):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"username": "zly@x.pl", "password": "x"})
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"username": USER, "password": PASSWORD})
    assert result["step_id"] == "meter"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"meter_id": "11111_22222_11111", "scan_interval": interval, "import_statistics": True, "history_days": 3,
         "register_multiplier": 0},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()
    return hass.config_entries.async_entries(DOMAIN)[0]


async def test_full_setup(recorder_mock, hass, fake):
    await hass.config.async_set_time_zone("Europe/Warsaw")
    entry = await _configure(hass)
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.options["scan_interval"] == 60

    states = {s.entity_id: s for s in hass.states.async_all("sensor")}
    ent_reg = er.async_get(hass)
    ids = {e.unique_id: e.entity_id for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)}
    import json
    import os
    if os.environ.get("DUMP_ENTITIES"):
        rows = []
        for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
            stt = states.get(e.entity_id)
            rows.append({"entity_id": e.entity_id, "key": e.unique_id.removeprefix(entry.unique_id + "_"),
                         "name": e.original_name, "unit": stt.attributes.get("unit_of_measurement") if stt else None,
                         "disabled": bool(e.disabled_by), "category": str(e.entity_category) if e.entity_category else None})
        with open(os.environ["DUMP_ENTITIES"], "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)

    y = states[ids[f"{entry.unique_id}_consumed_yesterday"]]
    assert float(y.state) == pytest.approx(494.7)
    assert y.attributes["unit_of_measurement"] == "kWh"
    t3 = states[ids[f"{entry.unique_id}_reactive_inductive_yesterday_t3"]]
    assert t3.attributes["unit_of_measurement"] == "kvarh"
    assert float(t3.state) == pytest.approx(74.205, rel=1e-3)
    tg = states[ids[f"{entry.unique_id}_tg_phi_yesterday"]]
    assert float(tg.state) == pytest.approx(0.15)
    assert float(states[ids[f"{entry.unique_id}_power_max_month"]].state) == 40
    assert states[ids[f"{entry.unique_id}_tariff"]].state == "B23"
    # strefy "dziś" domyślnie wyłączone
    assert ent_reg.async_get(ids[f"{entry.unique_id}_consumed_today_t1"]).disabled

    # --- v0.2.0
    u = entry.unique_id

    def st(key):
        return states[ids[f"{u}_{key}"]]

    assert float(st("power_15min_last").state) == pytest.approx(35.0)  # indeks 21: 30 + 21 % 8
    assert float(st("power_max_yesterday").state) == pytest.approx(41.4)
    assert st("power_max_yesterday").attributes["czas"].endswith("17:45:00+01:00")
    assert float(st("register_multiplier").state) == 1500
    assert st("register_multiplier").attributes["zrodlo"] == "auto"
    reg = st("register_consumed")
    assert reg.attributes["unit_of_measurement"] == "kWh" and reg.attributes["state_class"] == "total_increasing"
    assert float(reg.state) == pytest.approx(reg.attributes["wskazanie_liczydla"] * 1500, rel=1e-6)
    assert st("register_reactive_capacitive").state == "unknown"  # brak odczytów
    assert float(st("capacity_fee_usage_peak_previous_month").state) == pytest.approx(71646.3)
    assert float(st("capacity_fee_hours_peak_previous_month").state) == 330
    assert st("meter_model").state == "ZMY405"
    assert st("meter_number").state == "L000000000001"
    assert st("meter_last_event").state == "Brak zdarzeń"
    assert st("inbox_unread").state == "1"
    assert st("inbox_unread").attributes["ostatnia"]["id"] == "81"

    # nowe zdarzenie licznika i nowa wiadomość -> zdarzenia HA
    events = []
    hass.bus.async_listen("tauron_elicznik_biznes_meter_event", lambda e: events.append(e.data))
    hass.bus.async_listen("tauron_elicznik_biznes_new_message", lambda e: events.append(e.data))
    fake.events_html = "<tr><td>2026-11-02 10:00</td><td>Zanik napięcia L2</td></tr>"
    fake.unread = 2
    import custom_components.tauron_elicznik_biznes.api as api_mod
    orig = api_mod.parse_inbox

    def parse_with_new(page):
        inbox = orig(page)
        inbox.messages.insert(0, api_mod.InboxMessage("99", "Zdarzenia", "02.11.2026", "Nowe", "Treść", True))
        return inbox

    api_mod.parse_inbox = parse_with_new
    try:
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
    finally:
        api_mod.parse_inbox = orig
    assert {"meter_id": "11111_22222_11111", "data": "2026-11-02 10:00", "opis": "Zanik napięcia L2"} in events
    assert any(e.get("id") == "99" for e in events)
    assert hass.states.get(ids[f"{u}_meter_last_event"]).state == "Zanik napięcia L2"
    assert hass.states.get(ids[f"{u}_inbox_unread"]).state == "2"

    # statystyki zewnętrzne
    await async_wait_recording_done(hass)
    from homeassistant.components.recorder.statistics import list_statistic_ids
    from homeassistant.components.recorder import get_instance

    stat_ids = await get_instance(hass).async_add_executor_job(list_statistic_ids, hass)
    ours = {s["statistic_id"] for s in stat_ids if s["statistic_id"].startswith(DOMAIN)}
    assert f"{DOMAIN}:590000000000000001_consumed" in ours, ours
    assert f"{DOMAIN}:590000000000000001_power" in ours, ours
    assert len(ours) == 5

    # zmiana interwału w opcjach
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"scan_interval": 30, "import_statistics": False, "history_days": 3, "register_multiplier": 1200},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.runtime_data.update_interval == dt.timedelta(minutes=30)
    mult = [s for s in hass.states.async_all("sensor") if s.entity_id.endswith("przekladnia_liczydla")][0]
    assert float(mult.state) == 1200 and mult.attributes["zrodlo"] == "manual"
