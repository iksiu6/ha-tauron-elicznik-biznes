# Tauron eLicznik Biznes – integracja Home Assistant (HACS)

Odczyt danych z serwisu [eLicznik TAURON Dystrybucja](https://elicznik.tauron-dystrybucja.pl) dla **klientów biznesowych** (taryfy B/C, widok „WO”).

> Integracja dla klientów indywidualnych (taryfy G) będzie osobnym repozytorium.

## Instalacja (HACS)

1. HACS → menu ⋮ → **Niestandardowe repozytoria** → adres `https://github.com/iksiu6/ha-tauron-elicznik-biznes`, typ **Integracja**.
2. Wyszukaj **Tauron eLicznik Biznes** → Pobierz → zrestartuj Home Assistanta.
3. **Ustawienia → Urządzenia i usługi → Dodaj integrację → Tauron eLicznik Biznes**.
4. Podaj e-mail i hasło do TAURON Dystrybucja, wybierz punkt poboru (PPE) i interwał odczytów.

### Ustawienia (można zmienić później)

**Ustawienia → Urządzenia i usługi → Tauron eLicznik Biznes → Konfiguruj**:

| Opcja | Opis |
|---|---|
| Interwał odczytów | 15–1440 min (domyślnie 60). Dane w eLiczniku pojawiają się z kilkugodzinnym opóźnieniem. |
| Import statystyk | Godzinowe dane energii i mocy do statystyk długoterminowych (panel **Energia**, karty statystyk). |
| Dni historii | Ile dni wstecz zaimportować przy pierwszym uruchomieniu. |
| Przekładnia liczydła | Mnożnik dla stanów liczydeł (przekładniki prądowe/napięciowe). `0` = wykryj automatycznie. |

Zmiana loginu/hasła: menu ⋮ przy wpisie → **Zmień konfigurację**.

## Encje

Wszystkie encje należą do urządzenia **Tauron PPE &lt;numer PPE&gt;**. W tabelach `<PPE>` oznacza numer punktu poboru (18 cyfr), np. `sensor.tauron_ppe_590000000000000001_energia_pobrana_wczoraj`.
Kolumna „eLicznik” wskazuje, skąd pochodzi wartość w serwisie.

### Energia i Tg φ (Strona główna / zakładka Energia)

Dla każdej encji z tabeli istnieją też encje stref z przyrostkiem **`_t1`, `_t2`, `_t3`** (np. `sensor.tauron_ppe_<PPE>_energia_pobrana_wczoraj_t1`).
Encje stref dla okresu **dziś** są domyślnie wyłączone – można je włączyć w ustawieniach encji.

| Encja | eLicznik | Okres | Jednostka |
|---|---|---|---|
| `sensor.tauron_ppe_<PPE>_energia_pobrana_dzis` | Suma energii pobranej | Dzień – dziś | kWh |
| `sensor.tauron_ppe_<PPE>_energia_pobrana_wczoraj` | Suma energii pobranej | Dzień – wczoraj | kWh |
| `sensor.tauron_ppe_<PPE>_energia_pobrana_biezacy_miesiac` | Suma energii pobranej | Miesiąc – bieżący | kWh |
| `sensor.tauron_ppe_<PPE>_energia_pobrana_biezacy_rok` | Suma energii pobranej | Rok – bieżący | kWh |
| `sensor.tauron_ppe_<PPE>_energia_oddana_dzis` | Suma energii oddanej | Dzień – dziś | kWh |
| `sensor.tauron_ppe_<PPE>_energia_oddana_wczoraj` | Suma energii oddanej | Dzień – wczoraj | kWh |
| `sensor.tauron_ppe_<PPE>_energia_oddana_biezacy_miesiac` | Suma energii oddanej | Miesiąc – bieżący | kWh |
| `sensor.tauron_ppe_<PPE>_energia_oddana_biezacy_rok` | Suma energii oddanej | Rok – bieżący | kWh |
| `sensor.tauron_ppe_<PPE>_energia_bierna_indukcyjna_dzis` | Energia bierna indukcyjna | Dzień – dziś | kvarh |
| `sensor.tauron_ppe_<PPE>_energia_bierna_indukcyjna_wczoraj` | Energia bierna indukcyjna | Dzień – wczoraj | kvarh |
| `sensor.tauron_ppe_<PPE>_energia_bierna_indukcyjna_biezacy_miesiac` | Energia bierna indukcyjna | Miesiąc – bieżący | kvarh |
| `sensor.tauron_ppe_<PPE>_energia_bierna_indukcyjna_biezacy_rok` | Energia bierna indukcyjna | Rok – bieżący | kvarh |
| `sensor.tauron_ppe_<PPE>_energia_bierna_pojemnosciowa_dzis` | Energia bierna pojemnościowa | Dzień – dziś | kvarh |
| `sensor.tauron_ppe_<PPE>_energia_bierna_pojemnosciowa_wczoraj` | Energia bierna pojemnościowa | Dzień – wczoraj | kvarh |
| `sensor.tauron_ppe_<PPE>_energia_bierna_pojemnosciowa_biezacy_miesiac` | Energia bierna pojemnościowa | Miesiąc – bieżący | kvarh |
| `sensor.tauron_ppe_<PPE>_energia_bierna_pojemnosciowa_biezacy_rok` | Energia bierna pojemnościowa | Rok – bieżący | kvarh |
| `sensor.tauron_ppe_<PPE>_tg_fi_dzis` | Tg φ | Dzień – dziś | – |
| `sensor.tauron_ppe_<PPE>_tg_fi_wczoraj` | Tg φ | Dzień – wczoraj | – |
| `sensor.tauron_ppe_<PPE>_tg_fi_biezacy_miesiac` | Tg φ | Miesiąc – bieżący | – |
| `sensor.tauron_ppe_<PPE>_tg_fi_biezacy_rok` | Tg φ | Rok – bieżący | – |

Tg φ = energia bierna indukcyjna / energia czynna pobrana (tak samo liczy eLicznik).

### Moc (Strona główna / zakładka Moc)

| Encja | eLicznik | Jednostka |
|---|---|---|
| `sensor.tauron_ppe_<PPE>_moc_15_min_ostatnia` | Moc → wykres dzienny, ostatni dostępny punkt 15-min (atrybuty: `koniec_przedzialu`, `values` – 96 wartości dnia, `moc_umowna`) | kW |
| `sensor.tauron_ppe_<PPE>_moc_maksymalna_dzis` | Moc → Dzień (dziś) → Moc maksymalna (atrybut `czas`) | kW |
| `sensor.tauron_ppe_<PPE>_moc_maksymalna_wczoraj` | Moc → Dzień (wczoraj) → Moc maksymalna (atrybut `czas`) | kW |
| `sensor.tauron_ppe_<PPE>_moc_maksymalna_biezacy_miesiac` | Strona główna → Moc maksymalna (atrybuty: `data_pomiaru`, `najwyzsze_moce`) | kW |
| `sensor.tauron_ppe_<PPE>_srednia_z_mocy_maksymalnych_biezacy_miesiac` | Strona główna → Moc średnia → Średnia z mocy maksymalnych | kW |
| `sensor.tauron_ppe_<PPE>_przekroczenie_mocy_umownej_biezacy_miesiac` | Strona główna → Przekroczenia mocy umownej | kW |
| `sensor.tauron_ppe_<PPE>_moc_umowna` | Strona główna → Moc umowna *(diagnostyczny)* | kW |

### Stany liczydeł (zakładka Odczyty)

eLicznik pokazuje wskazania liczydła **bez przekładni przekładników**. Integracja mnoży je przez przekładnię (wykrytą automatycznie z porównania dobowego zużycia z przyrostem liczydła albo podaną w ustawieniach), więc encje pokazują rzeczywiste kWh/kvarh i mają `state_class: total_increasing` – nadają się do panelu Energia. Surowe wskazanie jest w atrybucie `wskazanie_liczydla`.

| Encja | eLicznik | Jednostka |
|---|---|---|
| `sensor.tauron_ppe_<PPE>_stan_licznika_energia_pobrana` | Odczyty → Energia pobrana – odczyt licznika energii pobranej (suma) | kWh |
| `sensor.tauron_ppe_<PPE>_stan_licznika_energia_pobrana_t1` … `_t3` | Odczyty → Energia pobrana – odczyt licznika energii pobranej (strefy T1, T2, T3) | kWh |
| `sensor.tauron_ppe_<PPE>_stan_licznika_energia_oddana` | Odczyty → Energia oddana – odczyt licznika energii oddanej (suma) | kWh |
| `sensor.tauron_ppe_<PPE>_stan_licznika_energia_oddana_t1` … `_t3` | Odczyty → Energia oddana – odczyt licznika energii oddanej (strefy T1, T2, T3) | kWh |
| `sensor.tauron_ppe_<PPE>_stan_licznika_energia_bierna_indukcyjna` | Odczyty → Bierna indukcyjna pobrana (suma) | kvarh |
| `sensor.tauron_ppe_<PPE>_stan_licznika_energia_bierna_indukcyjna_t1` … `_t3` | Odczyty → Bierna indukcyjna pobrana (strefy T1, T2, T3) | kvarh |
| `sensor.tauron_ppe_<PPE>_stan_licznika_energia_bierna_pojemnosciowa` | Odczyty → Bierna poj. pobrana (suma) | kvarh |
| `sensor.tauron_ppe_<PPE>_stan_licznika_energia_bierna_pojemnosciowa_t1` … `_t3` | Odczyty → Bierna poj. pobrana (strefy T1, T2, T3) | kvarh |
| `sensor.tauron_ppe_<PPE>_przekladnia_liczydla` | Mnożnik liczydła – wykryty automatycznie lub z ustawień (atrybut `zrodlo`: auto/manual) *(diagnostyczny)* | – |
| `sensor.tauron_ppe_<PPE>_data_odczytu_liczydla` | Odczyty → data i godzina ostatniego odczytu *(diagnostyczny)* | – |

### Opłata mocowa (Strona główna → Opłata mocowa)

| Encja | eLicznik | Jednostka |
|---|---|---|
| `sensor.tauron_ppe_<PPE>_oplata_mocowa_energia_szczytowego_zapotrzebowania_poprzedni_miesiac` | Opłata mocowa → Energia szczytowego zapotrzebowania – poprzedni (zamknięty) miesiąc | kWh |
| `sensor.tauron_ppe_<PPE>_oplata_mocowa_godziny_szczytowego_zapotrzebowania_poprzedni_miesiac` | Opłata mocowa → Ilość godzin (szczyt) – poprzedni (zamknięty) miesiąc | h |
| `sensor.tauron_ppe_<PPE>_oplata_mocowa_energia_pozostala_z_dni_roboczych_poprzedni_miesiac` | Opłata mocowa → Energia pozostała z dni roboczych – poprzedni (zamknięty) miesiąc | kWh |
| `sensor.tauron_ppe_<PPE>_oplata_mocowa_godziny_pozostale_z_dni_roboczych_poprzedni_miesiac` | Opłata mocowa → Ilość godzin (pozostałe) – poprzedni (zamknięty) miesiąc | h |
| `sensor.tauron_ppe_<PPE>_oplata_mocowa_energia_szczytowego_zapotrzebowania_biezacy_miesiac` | Opłata mocowa → Energia szczytowego zapotrzebowania – bieżący miesiąc | kWh |
| `sensor.tauron_ppe_<PPE>_oplata_mocowa_godziny_szczytowego_zapotrzebowania_biezacy_miesiac` | Opłata mocowa → Ilość godzin (szczyt) – bieżący miesiąc | h |
| `sensor.tauron_ppe_<PPE>_oplata_mocowa_energia_pozostala_z_dni_roboczych_biezacy_miesiac` | Opłata mocowa → Energia pozostała z dni roboczych – bieżący miesiąc | kWh |
| `sensor.tauron_ppe_<PPE>_oplata_mocowa_godziny_pozostale_z_dni_roboczych_biezacy_miesiac` | Opłata mocowa → Ilość godzin (pozostałe) – bieżący miesiąc | h |

### Licznik i informacje (zakładka Licznik, diagnostyczne)

| Encja | eLicznik | Jednostka |
|---|---|---|
| `sensor.tauron_ppe_<PPE>_numer_licznika` | Licznik → Numer licznika | – |
| `sensor.tauron_ppe_<PPE>_model_licznika` | Licznik → Model licznika | – |
| `sensor.tauron_ppe_<PPE>_fazowosc` | Licznik → Fazowość | – |
| `sensor.tauron_ppe_<PPE>_ostatnie_zdarzenie_licznika` | Licznik → Najnowsze zdarzenia (stan: opis ostatniego; atrybuty `data`, `zdarzenia`) | – |
| `sensor.tauron_ppe_<PPE>_taryfa` | Nagłówek → Taryfa | – |
| `sensor.tauron_ppe_<PPE>_dane_dostepne_do` | Koniec ostatniej godziny z danymi w eLiczniku | – |
| `sensor.tauron_ppe_<PPE>_ostatnia_aktualizacja` | Czas ostatniego pobrania danych przez integrację | – |

Numer i model licznika są też widoczne w karcie urządzenia.

### Wiadomości (skrzynka eLicznika)

| Encja | eLicznik | Jednostka |
|---|---|---|
| `sensor.tauron_ppe_<PPE>_nieprzeczytane_wiadomosci` | Wiadomości → liczba nieprzeczytanych (atrybuty: `ostatnia`, `wiadomosci` – 10 najnowszych) | szt. |

Integracja nie oznacza wiadomości jako przeczytanych.

### Zdarzenia Home Assistanta (do automatyzacji)

| Zdarzenie | Kiedy | Dane |
|---|---|---|
| `tauron_elicznik_biznes_meter_event` | nowe zdarzenie w zakładce Licznik | `meter_id`, `data`, `opis` |
| `tauron_elicznik_biznes_new_message` | nowa wiadomość w skrzynce | `meter_id`, `id`, `kategoria`, `data`, `tytul`, `tresc` |

Przykład – powiadomienie o nowej wiadomości:

```yaml
automation:
  - alias: Tauron – nowa wiadomość w eLiczniku
    triggers:
      - trigger: event
        event_type: tauron_elicznik_biznes_new_message
    actions:
      - action: notify.notify
        data:
          title: "eLicznik: {{ trigger.event.data.kategoria }}"
          message: "{{ trigger.event.data.tytul or trigger.event.data.tresc }}"
```

### Statystyki długoterminowe

| Statystyka | Zawartość |
|---|---|
| `tauron_elicznik_biznes:<PPE>_consumed` | energia pobrana, godzinowo (kWh) – do panelu Energia jako pobór z sieci |
| `tauron_elicznik_biznes:<PPE>_returned` | energia oddana, godzinowo (kWh) – do panelu Energia jako oddanie do sieci |
| `tauron_elicznik_biznes:<PPE>_reactive_inductive` | energia bierna indukcyjna, godzinowo (kvarh) |
| `tauron_elicznik_biznes:<PPE>_reactive_capacitive` | energia bierna pojemnościowa, godzinowo (kvarh) |
| `tauron_elicznik_biznes:<PPE>_power` | moc z profilu 15-min: średnia / min / max w każdej godzinie (kW) |

## Logowanie

TAURON używa wspólnego logowania (Keycloak) dla wielu usług i konto może mieć ustawiony inny serwis domyślny.
Integracja zawsze otwiera logowanie z parametrem `service=https://elicznik.tauron-dystrybucja.pl`, więc trafia bezpośrednio do eLicznika. Sesja jest utrzymywana między odczytami, a ponowne logowanie następuje dopiero po jej wygaśnięciu – zbyt częste logowania mogą skutkować czasową blokadą konta.

## Diagnostyka

Logi debug:

```yaml
logger:
  logs:
    custom_components.tauron_elicznik_biznes: debug
```

Surowe dane: **Urządzenie → Pobierz diagnostykę** (login i hasło są ukryte).

## Historia zmian

- **0.2.0** – moc 15-min (sensory + statystyka godzinowa), stany liczydeł z automatyczną przekładnią, opłata mocowa, dane i zdarzenia licznika, wiadomości ze skrzynki eLicznika, zdarzenia HA dla automatyzacji.
- **0.1.0** – pierwsza wersja: energia pobrana/oddana/bierna, Tg φ, strefy T1–T3, moc maksymalna, statystyki.

## Licencja

MIT
