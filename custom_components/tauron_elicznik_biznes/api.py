"""Klient serwisu eLicznik TAURON Dystrybucja dla klientów biznesowych (taryfy B/C, widok "WO").

Moduł nie zależy od Home Assistanta - można go testować samodzielnie.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .const import (
    DATE_FORMAT,
    ENERGY_TYPES,
    READING_TYPES,
    TZ,
    URL_BLOCKED,
    URL_ENERGY_WO,
    URL_INBOX,
    URL_LOGIN,
    URL_METER_PAGE,
    URL_POWER_PROFILE_WO,
    URL_POWER_WO,
    URL_READINGS,
    URL_SELECT_METER,
    URL_SERVICE,
)

_LOGGER = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9",
    "Cache-Control": "no-cache",
}
AJAX_HEADERS = {
    **HEADERS,
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

TIMEOUT = aiohttp.ClientTimeout(total=60)


class TauronError(Exception):
    """Błąd ogólny."""


class TauronAuthError(TauronError):
    """Nieprawidłowy login lub hasło."""


class TauronBlockedError(TauronError):
    """Konto czasowo zablokowane (zbyt wiele logowań)."""


class TauronSessionExpired(TauronError):
    """Sesja wygasła - trzeba zalogować się ponownie."""


@dataclass
class Meter:
    """Punkt poboru dostępny na koncie."""

    meter_id: str
    name: str
    kind: str | None  # "WO" dla widoku biznesowego

    @property
    def is_business(self) -> bool:
        return (self.kind or "").upper() == "WO"


@dataclass
class EnergyData:
    """Odpowiedź /energia/wo/api."""

    values: list[float | None]
    zones: dict[str, float]
    zone_names: dict[str, str]
    total: float | None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "EnergyData":
        values = [None if v is None else float(v) for v in data.get("values") or []]
        zones = {str(k): float(v) for k, v in (data.get("zones") or {}).items() if v is not None}
        has_data = any(v is not None for v in values)
        total = data.get("sum")
        return cls(
            values=values,
            zones=zones,
            zone_names={str(k): v for k, v in (data.get("zonesName") or {}).items()},
            total=round(float(total), 3) if (total is not None and has_data) else None,
        )

    @property
    def has_data(self) -> bool:
        return self.total is not None


@dataclass
class PowerData:
    """Odpowiedź /index/wo/api (type=moc): 10 najwyższych mocy 15-min w okresie."""

    entries: list[dict[str, Any]] = field(default_factory=list)

    @property
    def contracted(self) -> float | None:
        for e in self.entries:
            if e.get("Pum") not in (None, ""):
                return _to_float(e["Pum"])
        return None

    @property
    def max_entry(self) -> dict[str, Any] | None:
        valid = [e for e in self.entries if _to_float(e.get("Wartosc")) is not None]
        if not valid:
            return None
        return max(valid, key=lambda e: _to_float(e["Wartosc"]))

    @property
    def maximum(self) -> float | None:
        e = self.max_entry
        return _to_float(e["Wartosc"]) if e else None

    @property
    def average_of_max(self) -> float | None:
        vals = [_to_float(e.get("Wartosc")) for e in self.entries]
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    @property
    def excess(self) -> float | None:
        vals = [_to_float(e.get("Nadwyzka")) for e in self.entries]
        vals = [v for v in vals if v is not None]
        return max(vals) if vals else None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ".").strip())
    except ValueError:
        return None


def parse_meters(page: str) -> list[Meter]:
    """Wyciąga punkty poboru z <select name="site[client]">."""
    select = re.search(r'<select[^>]+name="site\[client\]"[^>]*>(.*?)</select>', page, re.S)
    if not select:
        return []
    meters: list[Meter] = []
    for opt in re.finditer(r"<option([^>]*)>(.*?)</option>", select.group(1), re.S):
        attrs, label = opt.group(1), html.unescape(opt.group(2)).strip()
        value = re.search(r'value="([^"]+)"', attrs)
        if not value:
            continue
        kind = None
        data = re.search(r"data-data='([^']*)'", attrs)
        if data:
            try:
                kind = json.loads(html.unescape(data.group(1))).get("type")
            except ValueError:
                kind = None
        name = label.rstrip(" /").strip() or value.group(1)
        meters.append(Meter(meter_id=value.group(1), name=name, kind=kind))
    return meters


def parse_meter_info(page: str) -> dict[str, str]:
    """Wyciąga obiekt JS `const METER = {...}` (NRPL, IDPP, Tariff, KIND, TO...)."""
    block = re.search(r"const\s+METER\s*=\s*\{(.*?)\}", page, re.S)
    if not block:
        return {}
    return dict(re.findall(r"(\w+)\s*:\s*'([^']*)'", block.group(1)))


@dataclass
class PowerProfile:
    """Moc 15-min z /moc/wo/api (1 dzień = 96 wartości; brak danych = null)."""

    day: dt.date
    values: list[float | None]
    contracted: float | None

    @classmethod
    def from_json(cls, day: dt.date, data: dict[str, Any]) -> "PowerProfile":
        return cls(
            day=day,
            values=[_to_float(v) for v in data.get("values") or []],
            contracted=_to_float(data.get("mocUmowna")),
        )

    def points(self) -> list[tuple[dt.datetime, float]]:
        """(początek przedziału 15-min w czasie lokalnym, moc kW) dla wartości dostępnych."""
        midnight = dt.datetime.combine(self.day, dt.time(0))
        out = []
        for i, v in enumerate(self.values):
            if v is None:
                continue
            start = (midnight + dt.timedelta(minutes=15 * i)).replace(tzinfo=TZ)
            out.append((start, v))
        return out

    @property
    def has_data(self) -> bool:
        return any(v is not None for v in self.values)

    @property
    def is_complete(self) -> bool:
        return len(self.values) >= 92 and all(v is not None for v in self.values)


@dataclass
class RegisterReading:
    """Stan liczydła z /odczyty/api - wartości BEZ przekładni przekładników."""

    timestamp: dt.datetime
    unit: str
    total: float | None
    zones: dict[str, float | None]

    @classmethod
    def from_json(cls, row: dict[str, Any]) -> "RegisterReading | None":
        try:
            ts = dt.datetime.strptime(row["Date"], "%d.%m.%Y %H:%M:%S").replace(tzinfo=TZ)
        except (KeyError, ValueError):
            return None
        zones = {z[1:]: _to_float(row.get(z)) for z in ("S1", "S2", "S3") if z in row}
        return cls(timestamp=ts, unit=row.get("JM") or "", total=_to_float(row.get("C")), zones=zones)


@dataclass
class CapacityFee:
    """Dane do opłaty mocowej (/energia/wo/api type=oplata_moc)."""

    usage_peak: float | None
    usage_off_peak: float | None
    hours_peak: float | None
    hours_off_peak: float | None
    tariff: str | None
    missing: float | None

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> "CapacityFee":
        data = data or {}
        raw = data.get("allData")
        if isinstance(raw, list):
            raw = raw[0] if raw else {}
        if not isinstance(raw, dict) or not raw:
            raw = data.get("data") if isinstance(data.get("data"), dict) else {}
        return cls(
            usage_peak=_to_float(raw.get("USAGE_PEAK")),
            usage_off_peak=_to_float(raw.get("USAGE_OFF_PEAK")),
            hours_peak=_to_float(raw.get("HOURS_PEAK")),
            hours_off_peak=_to_float(raw.get("HOURS_OFF_PEAK")),
            tariff=(raw.get("Taryfa") or None),
            missing=_to_float(raw.get("CNT_LACK")),
        )

    @property
    def has_data(self) -> bool:
        return bool(self.usage_peak) or bool(self.hours_peak)


@dataclass
class MeterDetails:
    """Dane z zakładki Licznik."""

    number: str | None = None
    model: str | None = None
    phases: str | None = None
    contracted_power: str | None = None
    ppe: str | None = None
    events: list[dict[str, str]] = field(default_factory=list)


@dataclass
class InboxMessage:
    id: str
    category: str
    date: str
    title: str
    preview: str
    unread: bool


@dataclass
class Inbox:
    unread: int = 0
    messages: list[InboxMessage] = field(default_factory=list)


def _strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def parse_meter_details(page: str) -> MeterDetails:
    values: dict[str, str] = {}
    for m in re.finditer(r'<div class="label-n-value">\s*<h4>(.*?)</h4>\s*<h1[^>]*>(.*?)</h1>', page, re.S):
        values[_strip_tags(m.group(1))] = _strip_tags(m.group(2))
    events: list[dict[str, str]] = []
    block = re.search(r"Najnowsze zdarzenia.*?<tbody>(.*?)</tbody>", page, re.S)
    if block:
        for row in re.finditer(r"<tr>(.*?)</tr>", block.group(1), re.S):
            cells = [_strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.S)]
            if len(cells) >= 2:
                events.append({"data": cells[0], "opis": cells[1]})
    power = values.get("Moc umowna")
    return MeterDetails(
        number=values.get("Numer licznika"),
        model=values.get("Model licznika"),
        phases=values.get("Fazowość"),
        contracted_power=None if not power or power.startswith("-") else power,
        ppe=values.get("PPE"),
        events=events,
    )


def parse_inbox(page: str) -> Inbox:
    messages: list[InboxMessage] = []
    for m in re.finditer(r'<a href="/message/(\d+)" class="wrapper([^"]*)">(.*?)</a>', page, re.S):
        body = m.group(3)

        def part(cls: str, body: str = body) -> str:
            found = re.search(rf'<div class="{cls}[^"]*">(.*?)</div>', body, re.S)
            return _strip_tags(found.group(1)) if found else ""

        preview = re.sub(r"\s*Czytaj więcej\s*>\s*$", "", part("message")).strip()
        messages.append(
            InboxMessage(
                id=m.group(1),
                category=part("category"),
                date=part("date"),
                title=part("title"),
                preview=preview,
                unread="no-read" in m.group(2),
            )
        )
    unread = re.search(r'data-unread="(\d+)"', page)
    count = int(unread.group(1)) if unread else sum(1 for msg in messages if msg.unread)
    return Inbox(unread=count, messages=messages)


def _is_logged_in(page: str) -> bool:
    return 'name="site[client]"' in page or "const METER" in page


class TauronBusinessClient:
    """Asynchroniczny klient eLicznika (widok biznesowy WO)."""

    def __init__(self, username: str, password: str, session: aiohttp.ClientSession | None = None) -> None:
        self._username = username
        self._password = password
        self._own_session = session is None
        self._session = session or aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(), timeout=TIMEOUT)
        self._logged_in = False
        self._selected_meter: str | None = None
        self.meters: list[Meter] = []
        self.meter_info: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        if self._own_session:
            await self._session.close()

    # ------------------------------------------------------------------ logowanie
    async def login(self) -> list[Meter]:
        """Logowanie przez Keycloak (CAS) z wymuszoną usługą eLicznik."""
        self._logged_in = False
        self._selected_meter = None
        self._session.cookie_jar.clear()
        _LOGGER.debug("Logowanie do eLicznika")

        async with self._session.get(URL_LOGIN, headers=HEADERS, allow_redirects=True) as resp:
            page = await resp.text()
            final_url = str(resp.url)

        # Gdyby w ciasteczkach została aktywna sesja SSO, od razu lądujemy w eLiczniku.
        if not (final_url.startswith(URL_SERVICE) and _is_logged_in(page)):
            form = re.search(r'<form[^>]+id="kc-form-login"[^>]+action="([^"]+)"', page)
            if not form:
                raise TauronError(f"Nie znaleziono formularza logowania (status {resp.status}, {final_url})")
            action = html.unescape(form.group(1))
            payload = {"username": self._username, "password": self._password, "credentialId": ""}
            async with self._session.post(action, data=payload, headers=HEADERS, allow_redirects=True) as resp:
                page = await resp.text()
                final_url = str(resp.url)

        self._check_page_errors(page, final_url)
        if 'id="kc-form-login"' in page:
            raise TauronAuthError("Nieprawidłowy login lub hasło")
        if not final_url.startswith(URL_SERVICE):
            # Konto zalogowane, ale serwer przekierował do innej usługi - wymuś eLicznik.
            async with self._session.get(URL_SERVICE, headers=HEADERS, allow_redirects=True) as resp:
                page = await resp.text()
                final_url = str(resp.url)
            self._check_page_errors(page, final_url)
        if not _is_logged_in(page):
            raise TauronError(f"Logowanie nie powiodło się - nie otwarto eLicznika ({final_url})")

        self.meters = parse_meters(page)
        self.meter_info = parse_meter_info(page)
        self._logged_in = True
        _LOGGER.debug("Zalogowano, punkty: %s", self.meters)
        return self.meters

    @staticmethod
    def _check_page_errors(page: str, url: str) -> None:
        if url.startswith(URL_BLOCKED) or "Przekroczono maksymalną liczbę logowań" in page:
            raise TauronBlockedError("Konto czasowo zablokowane - zbyt wiele logowań")

    async def select_meter(self, meter_id: str) -> dict[str, str]:
        async with self._session.post(
            URL_SELECT_METER, data={"site[client]": meter_id}, headers=HEADERS, allow_redirects=True
        ) as resp:
            page = await resp.text()
            final_url = str(resp.url)
        self._check_page_errors(page, final_url)
        if not final_url.startswith(URL_SERVICE) or not _is_logged_in(page):
            raise TauronSessionExpired("Sesja wygasła przy wyborze punktu")
        info = parse_meter_info(page)
        if info:
            self.meter_info = info
        self._selected_meter = meter_id
        return self.meter_info

    async def ensure_ready(self, meter_id: str) -> None:
        if not self._logged_in:
            await self.login()
        if self._selected_meter != meter_id:
            try:
                await self.select_meter(meter_id)
            except TauronSessionExpired:
                await self.login()
                await self.select_meter(meter_id)

    # ------------------------------------------------------------------ zapytania
    async def _post_json(self, url: str, payload: dict[str, Any]) -> Any:
        async with self._session.post(url, data=payload, headers=AJAX_HEADERS, allow_redirects=False) as resp:
            text = await resp.text()
            status = resp.status
            location = resp.headers.get("Location", "")
        if status in (301, 302, 303, 307, 308):
            if URL_BLOCKED in location or location.endswith("/blokada"):
                raise TauronBlockedError("Konto czasowo zablokowane")
            raise TauronSessionExpired(f"Przekierowanie do {location}")
        try:
            data = json.loads(text)
        except ValueError as err:
            if "kc-form-login" in text or "logowanie.tauron" in text:
                raise TauronSessionExpired("Odpowiedź HTML zamiast JSON") from err
            raise TauronError(f"Niepoprawna odpowiedź {url} (HTTP {status}): {text[:200]}") from err
        if isinstance(data, dict) and data.get("data") == "RE_LOGIN":
            raise TauronSessionExpired("RE_LOGIN")
        if not isinstance(data, dict) or not data.get("success"):
            raise TauronError(f"Serwer zwrócił błąd dla {url}: {text[:200]}")
        return data.get("data")

    async def _get_html(self, url: str) -> str:
        async with self._session.get(url, headers=HEADERS, allow_redirects=False) as resp:
            text = await resp.text()
            status = resp.status
            location = resp.headers.get("Location", "")
        if status in (301, 302, 303, 307, 308):
            if location.endswith("/blokada"):
                raise TauronBlockedError("Konto czasowo zablokowane")
            raise TauronSessionExpired(f"Przekierowanie do {location}")
        if status != 200:
            raise TauronError(f"HTTP {status} dla {url}")
        if not _is_logged_in(text) and "kc-form-login" in text:
            raise TauronSessionExpired("Strona logowania zamiast treści")
        return text

    async def _with_relogin(self, meter_id: str, func, *args) -> Any:
        async with self._lock:
            await self.ensure_ready(meter_id)
            try:
                return await func(*args)
            except TauronSessionExpired:
                _LOGGER.debug("Sesja wygasła - ponowne logowanie")
                self._logged_in = False
                await self.ensure_ready(meter_id)
                return await func(*args)

    async def request(self, meter_id: str, url: str, payload: dict[str, Any]) -> Any:
        """Zapytanie JSON z automatycznym ponownym logowaniem po wygaśnięciu sesji."""
        return await self._with_relogin(meter_id, self._post_json, url, payload)

    async def get_page(self, meter_id: str, url: str) -> str:
        return await self._with_relogin(meter_id, self._get_html, url)

    async def get_energy(
        self, meter_id: str, energy_key: str, date_from: dt.date, date_to: dt.date, profile: str
    ) -> EnergyData:
        """profile: 'full time' (godzinowo, 1 dzień), 'month' (dziennie), 'year' (miesięcznie)."""
        spec = ENERGY_TYPES[energy_key]
        payload = {
            "from": date_from.strftime(DATE_FORMAT),
            "to": date_to.strftime(DATE_FORMAT),
            "profile": profile,
            "type": spec["type"],
            "energy": spec["energy"],
        }
        data = await self.request(meter_id, URL_ENERGY_WO, payload)
        return EnergyData.from_json(data or {})

    async def get_day(self, meter_id: str, energy_key: str, day: dt.date) -> EnergyData:
        return await self.get_energy(meter_id, energy_key, day, day, "full time")

    async def get_power(self, meter_id: str, date_from: dt.date, date_to: dt.date) -> PowerData:
        payload = {
            "from": date_from.strftime(DATE_FORMAT),
            "to": date_to.strftime(DATE_FORMAT),
            "profile": "full time",
            "type": "moc",
        }
        data = await self.request(meter_id, URL_POWER_WO, payload)
        return PowerData(entries=data if isinstance(data, list) else [])

    async def get_power_profile(self, meter_id: str, day: dt.date) -> PowerProfile:
        payload = {
            "from": day.strftime(DATE_FORMAT),
            "to": day.strftime(DATE_FORMAT),
            "profile": "full time",
            "type": "moc",
        }
        data = await self.request(meter_id, URL_POWER_PROFILE_WO, payload)
        return PowerProfile.from_json(day, data if isinstance(data, dict) else {})

    async def get_readings(
        self, meter_id: str, energy_key: str, date_from: dt.date, date_to: dt.date
    ) -> list[RegisterReading]:
        payload = {
            "from": date_from.strftime(DATE_FORMAT),
            "to": date_to.strftime(DATE_FORMAT),
            "type": READING_TYPES[energy_key]["type"],
        }
        try:
            data = await self.request(meter_id, URL_READINGS, payload)
        except TauronError as err:
            if isinstance(err, (TauronSessionExpired, TauronBlockedError, TauronAuthError)):
                raise
            # {"success": false, "data": []} - brak odczytów w okresie
            _LOGGER.debug("Brak odczytów %s: %s", energy_key, err)
            return []
        rows = [RegisterReading.from_json(r) for r in (data or []) if isinstance(r, dict)]
        return sorted((r for r in rows if r), key=lambda r: r.timestamp)

    async def get_capacity_fee(self, meter_id: str, date_from: dt.date, date_to: dt.date) -> CapacityFee:
        payload = {
            "from": date_from.strftime(DATE_FORMAT),
            "to": date_to.strftime(DATE_FORMAT),
            "profile": "month",
            "type": "oplata_moc",
        }
        data = await self.request(meter_id, URL_ENERGY_WO, payload)
        return CapacityFee.from_json(data if isinstance(data, dict) else {})

    async def get_meter_details(self, meter_id: str) -> MeterDetails:
        return parse_meter_details(await self.get_page(meter_id, URL_METER_PAGE))

    async def get_inbox(self, meter_id: str) -> Inbox:
        return parse_inbox(await self.get_page(meter_id, URL_INBOX))
