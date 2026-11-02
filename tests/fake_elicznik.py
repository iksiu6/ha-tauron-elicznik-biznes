"""Atrapa serwisu logowanie.tauron-dystrybucja.pl + elicznik (odwzorowana na podstawie realnych odpowiedzi)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

from aiohttp import web

FIXTURES = Path(__file__).parent / "fixtures"
TZ = ZoneInfo("Europe/Warsaw")
MULTIPLIER = 1500

USER = "firma@example.com"
PASSWORD = "tajne"

HOURS = [29.4, 29.55, 31.35, 29.85, 29.55, 29.85, 26.7, 12.9, 0, 0, 0, 0.6, 0, 0, 2.25, 24.6, 39.3, 34.5, 28.65,
         28.5, 28.5, 28.5, 28.2, 31.95]
ZONES_NAMES = {"1": "szczyt przedpołudniowy (T1)", "2": "szczyt popołudniowy (T2)", "3": "pozostałe godziny doby (T3)"}

INDEX_HTML = """<html><body>
<form action="https://elicznik.tauron-dystrybucja.pl/ustaw_punkt" method="post">
<select name="site[client]" tabindex="-1">
<option  selected="selected"  value="11111_22222_11111" data-data='{"type": "WO"}'>590000000000000001 / </option>
<option value="22222_11111">590000000000000001 / </option>
</select></form>
<select name="feedback"><option value="Brakujące odczyty z licznika">Brakujące odczyty z licznika</option></select>
<script type="text/javascript">
	const METER = {
            NRPL: '22222',
            IDPP: '11111',
            TO: '2026-11-01',
            KIND: 'WO',
            Tariff: 'B23',
            Prosument: '',
	};
</script></body></html>"""

LOGIN_HTML = """<html><body><form id="kc-form-login" class="x" action="{action}" method="post">
<input name="username" type="email"><input name="password" type="password"><input name="credentialId" type="hidden">
</form>{error}</body></html>"""


def energy_json(values, zone="3"):
    s = sum(v for v in values if v is not None)
    return {"success": True, "data": {"values": values, "zones": {"1": 0, "2": 0, zone: s}, "zonesName": ZONES_NAMES,
                                      "sum": s}}


class FakeTauron:
    def __init__(self) -> None:
        self.sessions: set[str] = set()
        self.logins = 0
        self.requests: list[dict] = []
        self.expire_after: int | None = None  # po ilu zapytaniach API unieważnić sesję
        self.app = web.Application()
        r = self.app.router
        r.add_get("/login", self.login_redirect)
        r.add_get("/realms/ext/protocol/cas/login", self.login_page)
        r.add_post("/realms/ext/login-actions/authenticate", self.authenticate)
        r.add_get("/", self.index)
        r.add_post("/ustaw_punkt", self.select)
        r.add_post("/energia/wo/api", self.energy)
        r.add_post("/index/wo/api", self.power)
        r.add_post("/moc/wo/api", self.power_profile)
        r.add_post("/odczyty/api", self.readings)
        r.add_get("/licznik", self.meter_page)
        r.add_get("/inbox", self.inbox)
        self.base = ""
        self.events_html = '<tr><td colspan="2">Brak zarejestrowanych zdarzeń.</td></tr>'
        self.unread = 1

    def _ok(self, request) -> bool:
        return request.cookies.get("PHPSESSID") in self.sessions

    async def login_redirect(self, request):
        assert request.query.get("service", "").startswith("https://elicznik.tauron-dystrybucja.pl")
        raise web.HTTPFound(f"/realms/ext/protocol/cas/login?service={request.query['service']}")

    async def login_page(self, request):
        action = f"{self.base}/realms/ext/login-actions/authenticate?session_code=abc&amp;execution=e1&amp;client_id=extranet_elicznik"
        return web.Response(text=LOGIN_HTML.format(action=action, error=""), content_type="text/html")

    async def authenticate(self, request):
        assert request.query.get("client_id") == "extranet_elicznik"
        form = await request.post()
        if form.get("username") != USER or form.get("password") != PASSWORD:
            return web.Response(text=LOGIN_HTML.format(action="x", error="Nieprawidłowy e-mail lub hasło"),
                                content_type="text/html")
        self.logins += 1
        sid = f"sess{self.logins}"
        self.sessions.add(sid)
        resp = web.HTTPFound("/?ticket=ST-1")
        resp.set_cookie("PHPSESSID", sid)
        raise resp

    async def index(self, request):
        if not self._ok(request):
            raise web.HTTPFound("/login?service=https://elicznik.tauron-dystrybucja.pl")
        return web.Response(text=INDEX_HTML, content_type="text/html")

    async def select(self, request):
        if not self._ok(request):
            raise web.HTTPFound("/login?service=https://elicznik.tauron-dystrybucja.pl")
        form = await request.post()
        assert form["site[client]"] == "11111_22222_11111"
        raise web.HTTPFound("/")

    async def energy(self, request):
        if not self._ok(request):
            return web.json_response({"success": False, "data": "RE_LOGIN"})
        form = dict(await request.post())
        self.requests.append(form)
        if self.expire_after is not None and len(self.requests) >= self.expire_after:
            self.sessions.clear()
            self.expire_after = None
        if form["type"] == "oplata_moc":
            return web.json_response({"success": True, "data": {"sum": "71646.3", "allData": {
                "USAGE_PEAK": "71646.3", "USAGE_OFF_PEAK": "17251.8", "HOURS_PEAK": "330", "HOURS_OFF_PEAK": "198",
                "Taryfa": "Taryfa mocowa", "CNT_LACK": "0"}}})
        factor = {"1": 1, "2": 0.5, "3": 0.15, "6": 0}[form["energy"]]
        if form["profile"] == "full time":
            vals = [None if v is None else round(v * factor, 3) for v in HOURS]
            return web.json_response(energy_json(vals))
        if form["profile"] == "month":
            vals = [494.7 * factor, 159.75 * factor] + [None] * 28
            return web.json_response(energy_json(vals))
        return web.json_response(energy_json([1000 * factor] * 10 + [654.45 * factor]))

    async def power(self, request):
        if not self._ok(request):
            return web.json_response({"success": False, "data": "RE_LOGIN"})
        return web.json_response({"success": True, "data": [
            {"Data": "2026-11-01 17:30", "Wartosc": "40", "Pum": "620", "Nadwyzka": "0"},
            {"Data": "2026-11-01 02:30", "Wartosc": "33", "Pum": "620", "Nadwyzka": "0"},
        ]})


    async def power_profile(self, request):
        if not self._ok(request):
            return web.json_response({"success": False, "data": "RE_LOGIN"})
        form = dict(await request.post())
        day = dt.datetime.strptime(form["from"], "%d.%m.%Y").date()
        values = [round(30 + (i % 8), 1) for i in range(96)]
        values[70] = 41.4  # maksimum dnia (17:30-17:45)
        if day >= dt.datetime.now(TZ).date():
            values = values[:22] + [None] * 74  # dziś dane do 05:30
        return web.json_response({"success": True, "data": {"sum": sum(v or 0 for v in values), "values": values,
                                                             "mocUmowna": "620"}})

    async def readings(self, request):
        if not self._ok(request):
            return web.json_response({"success": False, "data": "RE_LOGIN"})
        form = dict(await request.post())
        if form["type"] == "bierna-pojemnosciowa-pobrana":
            return web.json_response({"success": False, "data": []})
        start = dt.datetime.strptime(form["from"], "%d.%m.%Y").date()
        end = dt.datetime.strptime(form["to"], "%d.%m.%Y").date()
        daily = sum(HOURS) / MULTIPLIER * {"energia-pobrana": 1, "energia-oddana": 0.5,
                                           "bierna-indukcyjna-pobrana": 0.15}[form["type"]]
        rows, c, day = [], 200.0, start
        while day <= end:
            rows.append({"Date": f"{day:%d.%m.%Y} 0:00:00", "JM": "kWh", "C": round(c, 4), "S1": 70.0, "S2": 35.0,
                         "S3": round(c - 105.0, 4)})
            rows.append({"Date": f"{day:%d.%m.%Y} 5:12:44", "JM": "kWh", "C": round(c + 0.1, 4), "S1": 70.0,
                         "S2": 35.0, "S3": round(c - 104.9, 4)})
            c += daily
            day += dt.timedelta(days=1)
        return web.json_response({"success": True, "data": rows})

    async def meter_page(self, request):
        if not self._ok(request):
            raise web.HTTPFound("/login?service=https://elicznik.tauron-dystrybucja.pl")
        html = (FIXTURES / "licznik.html").read_text(encoding="utf-8").replace("{events}", self.events_html)
        return web.Response(text=INDEX_HTML.replace("</body>", html + "</body>"), content_type="text/html")

    async def inbox(self, request):
        if not self._ok(request):
            raise web.HTTPFound("/login?service=https://elicznik.tauron-dystrybucja.pl")
        html = (FIXTURES / "inbox.html").read_text(encoding="utf-8").replace("{unread}", str(self.unread))
        return web.Response(text=INDEX_HTML.replace("</body>", html + "</body>"), content_type="text/html")


def patch_urls(monkeypatch, base: str) -> None:
    """Przekierowuje adresy integracji na atrapę."""
    from custom_components.tauron_elicznik_biznes import api

    monkeypatch.setattr(api, "URL_SERVICE", base)
    monkeypatch.setattr(api, "URL_LOGIN", f"{base}/login?service=https://elicznik.tauron-dystrybucja.pl")
    monkeypatch.setattr(api, "URL_SELECT_METER", f"{base}/ustaw_punkt")
    monkeypatch.setattr(api, "URL_ENERGY_WO", f"{base}/energia/wo/api")
    monkeypatch.setattr(api, "URL_POWER_WO", f"{base}/index/wo/api")
    monkeypatch.setattr(api, "URL_BLOCKED", f"{base}/blokada")
    monkeypatch.setattr(api, "URL_POWER_PROFILE_WO", f"{base}/moc/wo/api")
    monkeypatch.setattr(api, "URL_READINGS", f"{base}/odczyty/api")
    monkeypatch.setattr(api, "URL_METER_PAGE", f"{base}/licznik")
    monkeypatch.setattr(api, "URL_INBOX", f"{base}/inbox")
