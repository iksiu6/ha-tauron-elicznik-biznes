"""Stałe integracji Tauron eLicznik Biznes."""
from __future__ import annotations

from zoneinfo import ZoneInfo

DOMAIN = "tauron_elicznik_biznes"
NAME = "Tauron eLicznik Biznes"
MANUFACTURER = "TAURON Dystrybucja"

TZ = ZoneInfo("Europe/Warsaw")

# --- Konfiguracja ---
CONF_METER_ID = "meter_id"          # wartość z <select name="site[client]">, np. 11111_22222_11111
CONF_METER_NAME = "meter_name"      # numer PPE wyświetlany w eLiczniku
CONF_SCAN_INTERVAL = "scan_interval"  # w minutach
CONF_STATISTICS = "import_statistics"
CONF_HISTORY_DAYS = "history_days"
CONF_REGISTER_MULTIPLIER = "register_multiplier"  # przekładnia liczydła, 0 = automatycznie

DEFAULT_SCAN_INTERVAL = 60   # min
MIN_SCAN_INTERVAL = 15       # min - częstsze logowania grożą blokadą konta
MAX_SCAN_INTERVAL = 1440     # min
DEFAULT_HISTORY_DAYS = 30
MAX_HISTORY_DAYS = 365
DEFAULT_REGISTER_MULTIPLIER = 0

# --- Adresy ---
URL_SERVICE = "https://elicznik.tauron-dystrybucja.pl"
# Parametr service wymusza usługę eLicznik niezależnie od domyślnego serwisu konta.
URL_LOGIN = f"https://logowanie.tauron-dystrybucja.pl/login?service={URL_SERVICE}"
URL_SELECT_METER = f"{URL_SERVICE}/ustaw_punkt"
URL_ENERGY_WO = f"{URL_SERVICE}/energia/wo/api"
URL_POWER_WO = f"{URL_SERVICE}/index/wo/api"
URL_BLOCKED = f"{URL_SERVICE}/blokada"
URL_POWER_PROFILE_WO = f"{URL_SERVICE}/moc/wo/api"   # moc 15-min
URL_READINGS = f"{URL_SERVICE}/odczyty/api"          # stany liczydeł
URL_METER_PAGE = f"{URL_SERVICE}/licznik"             # dane licznika + zdarzenia (HTML)
URL_INBOX = f"{URL_SERVICE}/inbox"                    # wiadomości (HTML)

DATE_FORMAT = "%d.%m.%Y"

# --- Rodzaje energii (payload dla /energia/wo/api, jak w index-wo.js eLicznika) ---
ENERGY_CONSUMED = "consumed"
ENERGY_RETURNED = "returned"
ENERGY_REACTIVE_IND = "reactive_inductive"
ENERGY_REACTIVE_CAP = "reactive_capacitive"

ENERGY_TYPES: dict[str, dict] = {
    ENERGY_CONSUMED: {"type": "consum", "energy": 1, "unit": "kWh"},
    ENERGY_RETURNED: {"type": "consum", "energy": 2, "unit": "kWh"},
    ENERGY_REACTIVE_IND: {"type": "indukcyjna", "energy": 3, "unit": "kvarh"},
    ENERGY_REACTIVE_CAP: {"type": "pojemnosciowa", "energy": 6, "unit": "kvarh"},
}

PERIOD_TODAY = "today"
PERIOD_YESTERDAY = "yesterday"
PERIOD_MONTH = "month"
PERIOD_YEAR = "year"
PERIODS = [PERIOD_TODAY, PERIOD_YESTERDAY, PERIOD_MONTH, PERIOD_YEAR]

ZONES = ["1", "2", "3"]  # T1, T2, T3

# --- Stany liczydeł (/odczyty/api, parametr type) ---
READING_TYPES: dict[str, dict] = {
    ENERGY_CONSUMED: {"type": "energia-pobrana", "unit": "kWh"},
    ENERGY_RETURNED: {"type": "energia-oddana", "unit": "kWh"},
    ENERGY_REACTIVE_IND: {"type": "bierna-indukcyjna-pobrana", "unit": "kvarh"},
    ENERGY_REACTIVE_CAP: {"type": "bierna-pojemnosciowa-pobrana", "unit": "kvarh"},
}

EVENT_METER = f"{DOMAIN}_meter_event"      # nowe zdarzenie licznika
EVENT_MESSAGE = f"{DOMAIN}_new_message"    # nowa wiadomość w skrzynce eLicznika
