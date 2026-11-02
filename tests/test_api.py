import datetime as dt

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

from custom_components.tauron_elicznik_biznes.api import (
    TauronAuthError,
    TauronBusinessClient,
    parse_meter_info,
    parse_meters,
)
from custom_components.tauron_elicznik_biznes.statistics import hourly_points
from tests.fake_elicznik import INDEX_HTML, PASSWORD, USER, FakeTauron, patch_urls

METER = "11111_22222_11111"


def _session():
    # unsafe=True: atrapa działa na 127.0.0.1
    return aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))


def test_parse_meters():
    meters = parse_meters(INDEX_HTML)
    assert [(m.meter_id, m.name, m.kind) for m in meters] == [
        ("11111_22222_11111", "590000000000000001", "WO"),
        ("22222_11111", "590000000000000001", None),
    ]
    assert meters[0].is_business and not meters[1].is_business
    assert parse_meter_info(INDEX_HTML)["Tariff"] == "B23"


def test_hourly_points_dst():
    # 29.03.2026 - zmiana na czas letni: 2:00 nie istnieje -> kolizja z 3:00 (sumowana w imporcie)
    pts = hourly_points(dt.date(2026, 3, 29), [1.0] * 24)
    assert len(pts) == 24
    assert pts[0][0] == dt.datetime(2026, 3, 28, 23, tzinfo=dt.UTC)
    # 25.10.2026 - zmiana na czas zimowy
    pts = hourly_points(dt.date(2026, 10, 25), [1.0] * 24)
    assert pts[-1][0] == dt.datetime(2026, 10, 25, 22, tzinfo=dt.UTC)


@pytest.fixture
async def fake(monkeypatch, socket_enabled):
    fake = FakeTauron()
    server = TestServer(fake.app)
    await server.start_server()
    base = str(server.make_url("")).rstrip("/")
    fake.base = base
    patch_urls(monkeypatch, base)
    yield fake
    await server.close()


async def test_login_and_data(fake):
    client = TauronBusinessClient(USER, PASSWORD, _session())
    try:
        meters = await client.login()
        assert meters[0].meter_id == METER
        day = await client.get_day(METER, "consumed", dt.date(2026, 11, 1))
        assert day.total == pytest.approx(494.7)
        assert day.zones["3"] == pytest.approx(494.7)
        ind = await client.get_day(METER, "reactive_inductive", dt.date(2026, 11, 1))
        assert ind.total == pytest.approx(494.7 * 0.15, rel=1e-3)
        month = await client.get_energy(METER, "consumed", dt.date(2026, 11, 1), dt.date(2026, 11, 30), "month")
        assert month.total == pytest.approx(654.45)
        power = await client.get_power(METER, dt.date(2026, 11, 1), dt.date(2026, 11, 2))
        assert power.maximum == 40 and power.contracted == 620 and power.average_of_max == 36.5
        # payload zgodny z index-wo.js
        assert fake.requests[0] == {"from": "01.11.2026", "to": "01.11.2026", "profile": "full time",
                                    "type": "consum", "energy": "1"}
        assert fake.requests[1]["type"] == "indukcyjna" and fake.requests[1]["energy"] == "3"
        assert fake.logins == 1
    finally:
        await client._session.close()


async def test_relogin_after_session_expired(fake):
    client = TauronBusinessClient(USER, PASSWORD, _session())
    try:
        await client.get_day(METER, "consumed", dt.date(2026, 11, 1))
        fake.sessions.clear()  # serwer unieważnia sesję -> RE_LOGIN
        day = await client.get_day(METER, "returned", dt.date(2026, 11, 1))
        assert day.has_data
        assert fake.logins == 2
    finally:
        await client._session.close()


async def test_invalid_password(fake):
    client = TauronBusinessClient(USER, "zle", _session())
    try:
        with pytest.raises(TauronAuthError):
            await client.login()
    finally:
        await client._session.close()


def test_parse_meter_and_inbox():
    from pathlib import Path

    from custom_components.tauron_elicznik_biznes.api import parse_inbox, parse_meter_details

    fx = Path(__file__).parent / "fixtures"
    lic = (fx / "licznik.html").read_text(encoding="utf-8")
    d = parse_meter_details(lic.replace("{events}", '<tr><td colspan="2">Brak zarejestrowanych zdarzeń.</td></tr>'))
    assert (d.number, d.model, d.phases, d.contracted_power, d.events) == ("L000000000001", "ZMY405", "3", None, [])
    d = parse_meter_details(lic.replace("{events}", "<tr><td>2026-11-01 10:00</td><td>Zanik fazy L2</td></tr>"))
    assert d.events == [{"data": "2026-11-01 10:00", "opis": "Zanik fazy L2"}]
    inbox = parse_inbox((fx / "inbox.html").read_text(encoding="utf-8").replace("{unread}", "1"))
    assert inbox.unread == 1
    assert [(m.id, m.unread) for m in inbox.messages] == [("81", True), ("41", False)]
    assert inbox.messages[1].title == "Na czym polegają taryfy strefowe"
    assert inbox.messages[0].preview.startswith("Konkurs") and "Czytaj" not in inbox.messages[0].preview


async def test_new_endpoints(fake):
    client = TauronBusinessClient(USER, PASSWORD, _session())
    try:
        today = dt.date.today()
        profile = await client.get_power_profile(METER, today - dt.timedelta(days=1))
        assert len(profile.values) == 96 and profile.is_complete and profile.contracted == 620
        readings = await client.get_readings(METER, "consumed", today - dt.timedelta(days=1), today)
        assert len(readings) == 4 and readings[0].total == 200.0 and readings[0].zones["3"] == 95.0
        assert await client.get_readings(METER, "reactive_capacitive", today, today) == []
        fee = await client.get_capacity_fee(METER, dt.date(2026, 10, 1), dt.date(2026, 10, 31))
        assert fee.usage_peak == 71646.3 and fee.hours_off_peak == 198 and fee.has_data
        details = await client.get_meter_details(METER)
        assert details.model == "ZMY405"
        assert (await client.get_inbox(METER)).unread == 1
    finally:
        await client._session.close()
