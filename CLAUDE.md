# Streckenwacht – Projektkontext für Claude

Home-Assistant-Custom-Integration (HACS), Domain `streckenwacht`. Zeigt Baustellen, Sperrungen, Staus und Unfälle für vom Nutzer definierte Beobachtungsbereiche – aus offenen Datenquellen: **Autobahn-API** (Autobahn GmbH), **MobiData BW** (GeoJSON), **Stadt Stuttgart** (WFS, als GeoJSON abgerufen), **Norddeutschland** (WFS des LBV.SH: SH, HH, MV, NI), **Berlin** (VIZ), **Brandenburg**, **Sachsen-Anhalt** (WFS), **Sachsen** (ZIP, UTM), **Rheinland-Pfalz** (WFS Mobilitätsatlas), Städte **München**, **Köln**, **Frankfurt**, **Dortmund** (ab 0.2.0), **Aachen**, **Duisburg**, **Münster** (ab 0.3.0), **Luxemburg** (DATEX II), **Karlsruhe**, **Rostock**, **Kiel**, **Ingolstadt** (ab 0.4.0), **Freiburg**, **Landesmeldestelle BW** (Verkehrsmeldungen, DATEX II, ab 0.5.0).

## Dokumentation

- **`docs/ENTWICKLUNG.md`** – Architektur, verifizierte Eigenheiten der Datenquellen, Entscheidungen, Risiken, Release-Ablauf, Backlog. Vor größeren Arbeiten lesen.
- **`docs/DATENQUELLEN.md`** – Planungsgrundlage für neue Datenquellen (Länder, Städte, Endpunkte).
- **`docs/BRAND.md`** – Bilder, Farben, Regenerierung.

Stand (2026-10-18): **v0.5.0 veröffentlicht** (Freiburg, Verkehrsmeldungen der Landesmeldestelle BW; Städte-Sweep und TomTom-Prüfung in `docs/DATENQUELLEN.md`: offene Stadtquellen weitgehend ausgeschöpft, TomTom-Freikontingent ungeeignet). v0.4.0: (Luxemburg, Karlsruhe, Rostock, Kiel, Ingolstadt; Stuttgart auf neuen WFS-Endpunkt umgestellt, dort ohne Sperrungsangabe). v0.3.0: (Sensor „Nächste Sperrung“ + Blueprint Vorwarnung, Kartenansicht per geo_location, Aachen/Duisburg/Münster, Meldungsarten-Filter pro Bereich). README-Screenshots erneuert (2026-10-18, ohne Kartenbild: das Kartenpanel zeigt Heimzone und Personen); Update-Beitrag zu 0.3–0.5 im Forum gepostet (2026-10-18), README hat ein Dashboard-Beispiel (Statuskarte, Meldungsliste, Verlauf). v0.2.1: (Datenquellen pro Bereich, passend zur Lage des Kreises; Migration der alten globalen Quellenliste). v0.2.0: zehn neue Quellen (Norddeutschland, Berlin, Brandenburg, Sachsen-Anhalt, Sachsen, Rheinland-Pfalz, München, Köln, Frankfurt, Dortmund) und „Störung aktiv“ ignoriert langlaufende Sperrungen nach einer Woche. v0.1.0 vorgestellt in der simon42 Community (Showroom, [Thema 93623](https://community.simon42.com/t/streckenwacht-baustellen-sperrungen-und-staus-auf-der-eigenen-strecke-hacs-integration/93623)); Update-Beitrag zu 0.2.0 dort entworfen. HA Community (englisch) als Nächstes möglich. **Nächste Schritte:** Rückmeldungen aus dem Forum einarbeiten; danach Backlog (`docs/ENTWICKLUNG.md` Abschnitt 6) und weitere Städte aus `docs/DATENQUELLEN.md`.

## Verbindliche Entscheidungen (nicht neu diskutieren)

- **Eine** Integration mit Provider-Muster (`providers/autobahn.py`, `mobidata_bw.py`, `stuttgart.py`, `norddeutschland.py` auf Basis von `wfs.py`), gemeinsames Datenmodell `StreckenwachtEvent`.
- Ein Config-Entry + **Config-Subentries** je Beobachtungsbereich; **ein Coordinator pro Provider**, Bereiche filtern lokal. Autobahnen wählt der Nutzer aus (die API kann keine Umkreissuche).
- Nur UI-Config-Flow, kein YAML. `DataUpdateCoordinator`, durchgängig async, `async_get_clientsession(hass)`.
- Plattformen: `calendar`, `binary_sensor`, `sensor`, `event`, `geo_location` (Kartenpunkte, seit 0.3.0, auf Wunsch des Projektinhabers). **Keine Webcams.** Keine Deduplizierung zwischen Quellen (vorerst).
- Lizenz MIT. Repo: `github.com/streckenwacht/integration`. `codeowners`: `@n42net`.
- Deployment auf die produktive HA-OS-Instanz über HACS aus GitHub.

## Arbeitsregeln

1. **Feldnamen nie raten.** Fixtures mit `uv run --python 3.13 --no-project tools/fetch_fixtures.py` aktualisieren; die Dateien in `tests/fixtures/` sind die Wahrheit über Formate. Weicht die Live-API von `docs/ENTWICKLUNG.md` ab, gilt die API – und die Abweichung wird dort nachgetragen.
2. **Entwickelt wird gegen eine produktive Home-Assistant-Instanz.** Provider-Logik (HTTP + Parsing) erst als reines Python außerhalb von HA testen. Ein fehlerhafter Provider darf nie die ganze Integration oder HA blockieren: Fehler pro Provider fangen und über die Repairs/Issue-Registry melden.
3. Alle HTTP-Requests mit User-Agent `Streckenwacht/<version> (+https://github.com/streckenwacht/integration)`. Polling konservativ (Default 15 min).
4. Attribution pro Quelle mitführen (Stuttgart CC BY 4.0, MobiData BW DL-DE-BY-2.0, Norddeutschland CC BY 4.0, Berlin/Brandenburg DL-DE-BY-2.0, Sachsen CC BY 4.0, Sachsen-Anhalt nur nichtkommerziell, Rheinland-Pfalz Landesbetrieb Mobilität, München dl-de-by-2.0, Köln/Dortmund dl-de-zero, Frankfurt Stadt Frankfurt, Aachen/Münster dl-de-by-2.0, Duisburg CC BY 3.0 DE, Luxemburg/Rostock CC0, Karlsruhe/Kiel/Ingolstadt CC BY 4.0, Freiburg/LMS BW dl-de-by-2.0, Autobahn GmbH, Verkehrslage INRIX). Abfragen dürfen keine genauen Bereichskoordinaten enthalten (WFS: nur grobes 0,5°-Raster).
5. Code, Kommentare, Entity-IDs auf Englisch; UI-Texte über `strings.json` + `translations/de.json` und `en.json`. Reine Logik (Provider, `model`, `geo`, `summary`, `changes`) ohne HA-Importe, damit sie lokal testbar bleibt.
6. Tests gegen Fixtures, nicht gegen Live-APIs. Logik- und Provider-Tests lokal; HA-Tests (`tests/ha/`, `pytest-homeassistant-custom-component`) nur in GitHub Actions.
7. **Branches:** Entwickelt wird auf `dev` (CI läuft dort). `main` erhält nur freigegebene Stände (Fast-Forward von `dev` + Versions-Bump in `manifest.json` und `const.py` + GitHub-Release), weil die produktive HACS-Installation daran hängt. Ausnahmen nur nach Rücksprache.
8. **Werkzeuge:** `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`. Rechnerspezifisches (z. B. Pfad der virtuellen Umgebung) steht in `CLAUDE.local.md` (nicht im Repo). Die HA-Testbibliothek (`--group ha-tests`) läuft unter Windows nicht (`fcntl`). Ihre Version muss dieselbe `homeassistant`-Version pinnen wie die `dev`-Gruppe.
9. **Live-Check außerhalb von HA:** `uv run tools/live_check.py --lat 48.7758 --lon 9.1829 --radius 15 --roads A8 A81`. Unter Windows findet `aiodns` (kommt mit HA) keine DNS-Server – lokale Live-Skripte brauchen `aiohttp.ThreadedResolver()` (im Skript bereits drin).
10. **Warnungs-Fixtures (echte INRIX-Daten) nur lokal, nie committen.**

## Brand-Bilder

Fertig in `custom_components/streckenwacht/brand/` (HA ≥ 2026.3 lädt sie von dort). Nicht verändern oder neu erzeugen, außer auf ausdrücklichen Wunsch – Details in `docs/BRAND.md`.

## Zurückgestellt

Impressumspflicht und Anfrage bei der Autobahn GmbH zu INRIX sind **auf Wunsch zurückgestellt** (2026-10-02) – nicht von sich aus erneut vorschlagen, erst beim breiteren öffentlichen Bewerben wieder aufgreifen. Die INRIX-Frage selbst ist entschieden (`docs/ENTWICKLUNG.md` Abschnitt 4).
