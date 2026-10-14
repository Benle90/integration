<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/streckenwacht/integration/main/assets/github/readme-header-dark@2x.png">
  <img alt="Streckenwacht – wacht über deine Strecke." src="https://raw.githubusercontent.com/streckenwacht/integration/main/assets/github/readme-header-light@2x.png" width="640">
</picture>

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-005B8C.svg)](https://hacs.xyz/)
[![Release](https://img.shields.io/github/v/release/streckenwacht/integration?color=005B8C)](https://github.com/streckenwacht/integration/releases)
[![CI](https://github.com/streckenwacht/integration/actions/workflows/ci.yml/badge.svg)](https://github.com/streckenwacht/integration/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-F5A623.svg)](LICENSE)

🇩🇪 **Deutsch** · 🇬🇧 [English](https://github.com/streckenwacht/integration/blob/main/README.en.md)

> ℹ️ **Junges Projekt.** Version 0.2 – die Grundfunktionen laufen stabil, neue Datenquellen sind frisch dazugekommen. Rückmeldungen sind sehr willkommen – siehe [Fehler melden](#fehler-melden).

Streckenwacht wacht über deine Strecke – ob Autobahn, Bundesstraße oder dein täglicher Arbeitsweg. Baustellen, Sperrungen, Staus und Unfälle, direkt in deinem Home Assistant: als Kalender, Sensoren und Events für Automationen.

## Was Streckenwacht kann

- **Beobachtungsbereiche** frei festlegen: Kreis auf der Karte, z. B. „Zuhause“ oder „Arbeitsweg“.
- Pro Bereich wählbar: **Datenquellen**, **Autobahnen** und **Fahrtrichtungen** – etwa nur die A81 Richtung Stuttgart.
- Pro Bereich ein **Kalender** mit allen Baustellen und Sperrungen; Nachtbaustellen erscheinen als einzelne Termine pro Nacht.
- **„Störung aktiv“**, sobald im Bereich eine Sperrung, ein Unfall oder ein nennenswerter Stau aktiv ist – Dauerbaustellen, monatelange Sperrungen (nach ihrer ersten Woche) und kleine Verzögerungen lösen ihn bewusst nicht aus.
- **Reisezeitverlust** in Minuten (größter aktueller Wert im Bereich).
- **Event bei neuen und beendeten Meldungen** – ideal für Push-Nachrichten.
- **Karte:** alle aktuellen Meldungen als Punkte auf der Kartenkarte im Dashboard.
- Fällt eine Quelle aus, laufen die anderen weiter; nach wiederholten Fehlern erscheint ein Hinweis unter *Reparaturen*.

<img src="https://raw.githubusercontent.com/streckenwacht/integration/main/assets/screenshots/geraet.png" alt="Gerät eines Beobachtungsbereichs mit Kalender, Ereignissen, Reisezeitverlust, Störung aktiv und Ereignisänderung" width="720">

## Datenquellen

| Quelle | Abdeckung | Lizenz / Namensnennung |
|---|---|---|
| [Autobahn GmbH – Autobahn-API](https://verkehr.autobahn.de/o/autobahn) | Bundesautobahnen, bundesweit: Baustellen, Sperrungen, Warnungen inkl. Staus | Die Autobahn GmbH des Bundes |
| ↳ Staumeldungen darin | Verkehrslage aus Fahrzeugdaten | Verkehrslage: INRIX (abschaltbar, siehe [Optionen](#optionen)) |
| [MobiData BW](https://mobidata-bw.de/dataset/baustelleninformationen-baden-wurttemberg) | Bundes-, Landes- und Kreisstraßen in Baden-Württemberg, vereinzelt Gemeindestraßen | Datenlizenz Deutschland – Namensnennung 2.0 |
| [Stadt Stuttgart – Baustellenkalender](https://www.stuttgart.de/baustellenkalender) | Hauptverkehrsstraßen (Vorbehaltsstraßennetz) in Stuttgart | CC BY 4.0, © Landeshauptstadt Stuttgart |
| [Baustelleninformationen Norddeutschland (LBV.SH)](https://dienste.gdi-sh.de/WFS_SH_Baustelleninformationen?SERVICE=WFS&REQUEST=GetCapabilities) | Schleswig-Holstein (alle Straßenklassen, dazu aktuelle Verkehrsstörungen und Unfälle), Hamburg, Mecklenburg-Vorpommern, Bundesstraßen in Niedersachsen | CC BY 4.0, © Geokompetenz/LVermGeo SH |
| [VIZ Berlin](https://daten.berlin.de/datensaetze/baustellen-sperrungen-und-sonstige-storungen-von-besonderem-verkehrlichem-interesse) | Berliner Hauptstraßen: Baustellen, Sperrungen, Störungen (Autobahn-Baustellen kommen über die Autobahn GmbH) | Digitale Plattform Stadtverkehr Berlin, dl-de/by-2-0 |
| [Landesbetrieb Straßenwesen Brandenburg](https://isk.geobasis-bb.de/ows/baustelleninfo_wfs?SERVICE=WFS&REQUEST=GetCapabilities) | Bundes-, Landes- und Kreisstraßen in Brandenburg | © Landesbetrieb Straßenwesen Brandenburg, dl-de/by-2-0 |
| [Sperrinfo Sachsen-Anhalt](https://service.ifak.eu/sperrinfo/wfs?SERVICE=WFS&REQUEST=GetCapabilities) | Alle Straßenklassen in Sachsen-Anhalt inkl. Gemeindestraßen | Ministerium für Landesentwicklung und Verkehr; laut Dienst **nur nichtkommerzielle Nutzung** |
| [Baustelleninformationssystem Sachsen](https://www.baustellen.sachsen.de/baustellendaten-dienste-3997.html) | Alle Straßenklassen in Sachsen inkl. Gemeindestraßen (Autobahnen kommen über die Autobahn GmbH) | Baustelleninformationssystem Sachsen, CC BY 4.0 |
| [Mobilitätsatlas Rheinland-Pfalz](https://verkehr.rlp.de) | Alle Straßenklassen in Rheinland-Pfalz (Meldungen der Landes- und Kommunalbehörden) | Landesbetrieb Mobilität Rheinland-Pfalz; öffentlich bereitgestellt, ohne erklärte Lizenz |
| [Landeshauptstadt München](https://opendata.muenchen.de/dataset/baustellen_4_weeks_opendata) | Baustellen auf der Fahrbahn in München (nächste vier Wochen; reine Park- und Gehwegeinschränkungen ausgelassen) | dl-de/by-2-0: Landeshauptstadt München – opendata.muenchen.de |
| [Stadt Köln – Verkehrskalender](https://www.stadt-koeln.de/leben-in-koeln/verkehr/verkehrskalender/) | Verkehrsrelevante Baustellen, Sperrungen und Veranstaltungen im Kölner Hauptstraßennetz | Stadt Köln, dl-de/zero-2-0 |
| [Stadt Frankfurt am Main](https://geowebdienste.frankfurt.de/Baustellen?SERVICE=WFS&REQUEST=GetCapabilities) | Baustellen und Verkehrsmeldungen in Frankfurt | Stadt Frankfurt am Main; öffentlich bereitgestellt, ohne erklärte Lizenz |
| [Stadt Dortmund](https://open-data.dortmund.de/explore/dataset/fb66-baustellen-tagesaktuell/) | Baustellen in Dortmund (aktuell und geplant) | Stadt Dortmund, dl-de/zero-2-0 |

Alle Entitäten tragen die jeweilige Namensnennung im Attribut `attribution`.

## Was Streckenwacht nicht kann

Die Quellen sind nicht vollständig:

- Die Autobahn-API deckt nur Bundesautobahnen ab, nicht Landes-, Kreis- oder Kommunalstraßen.
- MobiData BW deckt Bundes-, Landes- und Kreisstraßen in Baden-Württemberg ab, kommunale Straßen nur vereinzelt.
- Der Stuttgarter Baustellenkalender deckt nur das „Vorbehaltsstraßennetz“ ab – Wohnstraßen, Notreparaturen und nicht verkehrsrelevante Arbeiten von Versorgern fehlen bewusst.
- Die norddeutschen Daten sind je Land unterschiedlich ausführlich: In Niedersachsen sind es nur Bundesstraßen, in Mecklenburg-Vorpommern fehlen oft Straßennamen.
- In Bayern, Hessen und Nordrhein-Westfalen gibt es bisher nur einzelne Städte (München, Frankfurt, Köln, Dortmund); in Thüringen, Bremen und dem Saarland nur die Autobahnen.
- Unfälle haben in keiner Quelle eine eigene Kategorie; Streckenwacht erkennt sie am Wort „Unfall“ in den Warnungen und Verkehrsstörungen.
- Keine der Quellen garantiert Vollständigkeit oder eine feste Aktualisierungsfrequenz; alle Angaben stammen ungefiltert von den jeweiligen Behörden und Betreibern.

Kurz: Streckenwacht eignet sich gut, um größere Störungen auf Hauptstrecken im Blick zu behalten – nicht, um jede kleine Baustelle in jeder Nebenstraße zu erfassen.

## Datenschutz

Dein Standort verlässt Home Assistant nicht. Streckenwacht lädt die Meldungen ganzer Autobahnen bzw. landes- oder stadtweite Dateien (z. B. MobiData BW, Sachsen, Berlin) herunter und filtert erst lokal auf deine Bereiche. Unveränderte Daten werden dank ETag nicht erneut übertragen.

Ausnahme sind große Landesquellen ohne ETag (Norddeutschland, Brandenburg): Sie sind zu groß, um bei jedem Abruf komplett geladen zu werden. Streckenwacht fragt dort deshalb einen groben Kartenausschnitt ab – auf ein Raster von etwa 55 × 35 km gerundet. Der Server erfährt so nur die ungefähre Region, nicht deinen Bereich.

Die Abrufe enthalten keine persönlichen Daten, nur eine Kennung der Integration (User-Agent).

## Installation (HACS, benutzerdefiniertes Repository)

Voraussetzung: Home Assistant **2026.3** oder neuer und [HACS](https://hacs.xyz/).

**Mit einem Klick:** [![In HACS öffnen](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=streckenwacht&repository=integration&category=integration) → herunterladen, Home Assistant neu starten → [![Integration hinzufügen](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=streckenwacht)

Oder von Hand:

1. HACS öffnen → Menü (⋮) → **Benutzerdefinierte Repositories**.
2. URL `https://github.com/streckenwacht/integration` eintragen, Typ **Integration**, hinzufügen.
3. **Streckenwacht** in HACS öffnen → **Herunterladen**.
4. Home Assistant neu starten.
5. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Streckenwacht**.

Hinweis: Im HACS-Dashboard fehlt das Icon derzeit ([HACS-Issue #5171](https://github.com/hacs/integration/issues/5171)); in den Home-Assistant-Einstellungen wird es angezeigt.

## Einrichtung

### Datenquellen und Optionen

Beim Hinzufügen fragt Streckenwacht nur nach Abrufintervall und Staumeldungen. Die Datenquellen wählst du pro Beobachtungsbereich (siehe unten); abgefragt wird, was irgendein Bereich nutzt.

<a id="optionen"></a>Später änderbar über **Geräte & Dienste → Streckenwacht → Konfigurieren**:

| Option | Standard | Bedeutung |
|---|---|---|
| Abrufintervall | 15 min | 10–60 Minuten |
| Staumeldungen einbeziehen (INRIX) | an | Staus und Reisezeitverlust aus der Autobahn-API |

<img src="https://raw.githubusercontent.com/streckenwacht/integration/main/assets/screenshots/optionen.png" alt="Optionen: Datenquellen, Abrufintervall, Staumeldungen" width="400">

### Beobachtungsbereiche

Auf der Streckenwacht-Seite **Beobachtungsbereich hinzufügen**. Der Dialog führt in bis zu vier Schritten durch die Einrichtung:

1. **Bereich** – Name (wird Teil der Entity-IDs, z. B. „Arbeitsweg“) und Kreis auf der Karte (max. 100 km).
2. **Datenquellen** – angeboten werden die Autobahn und alle Quellen, deren Gebiet den Kreis berührt, alle vorausgewählt. Abwählen, was du nicht brauchst, z. B. alles außer der Autobahn für einen Arbeitsweg. Gibt es nur die Autobahn, entfällt der Schritt.
3. **Autobahnen** – nur wenn „Autobahn GmbH“ gewählt ist. Angezeigt werden nur ihre Meldungen innerhalb des Kreises. Die Auswahl ist nötig, weil die Autobahn-API immer eine ganze Autobahn liefert und keine Umkreissuche kennt. Hier stellst du auch ein, **ab wie vielen Minuten Reisezeitverlust ein Stau als Störung zählt** (Standard 10, 0 = jeder Stau).
4. **Fahrtrichtungen** – zur Auswahl stehen die Richtungen, die auf den gewählten Autobahnen aktuell vorkommen. Leer lassen für alle Richtungen. Meldungen an Anschlussstellen und ohne Richtung werden immer angezeigt.

<table>
  <tr>
    <td valign="top"><img src="https://raw.githubusercontent.com/streckenwacht/integration/main/assets/screenshots/bereich_1_bereich.png" alt="Schritt 1: Name, Kreis auf der Karte, Datenquellen" width="260"></td>
    <td valign="top"><img src="https://raw.githubusercontent.com/streckenwacht/integration/main/assets/screenshots/bereich_2_autobahnen.png" alt="Schritt 2: Autobahnen und Stau-Schwelle" width="260"></td>
    <td valign="top"><img src="https://raw.githubusercontent.com/streckenwacht/integration/main/assets/screenshots/bereich_3_richtungen.png" alt="Schritt 3: Fahrtrichtungen" width="260"></td>
  </tr>
  <tr>
    <td>1. Bereich und Quellen</td>
    <td>2. Autobahnen</td>
    <td>3. Fahrtrichtungen</td>
  </tr>
</table>

> **Tipp für Arbeitswege über ein Autobahnkreuz:** Die Richtungsangabe wechselt am Kreuz. Wer z. B. auf der A81 von Böblingen nach Stuttgart-Feuerbach fährt, braucht „Singen -> Stuttgart“ **und** „Stuttgart -> Heilbronn“.

Bereiche lassen sich jederzeit über ⋮ → **Neu konfigurieren** ändern.

## Entitäten pro Beobachtungsbereich

Beispiel für den Bereich „Arbeitsweg“ (Gerät *Streckenwacht Arbeitsweg*). Die Entity-IDs sind englisch, die angezeigten Namen folgen der Sprache von Home Assistant.

| Entität | Anzeigename | Inhalt |
|---|---|---|
| `calendar.streckenwacht_arbeitsweg` | Streckenwacht Arbeitsweg | Alle Meldungen als Termine |
| `binary_sensor.streckenwacht_arbeitsweg_disruption_active` | Störung aktiv | An bei aktiver Sperrung, Unfall oder Stau ab der eingestellten Schwelle. Sperrungen, deren aktuelles Zeitfenster länger als 30 Tage ist, zählen nur in ihrer ersten Woche (danach bleiben sie im Kalender und unter „Ereignisse“). Attribute: `count`, `disruptions` |
| `sensor.streckenwacht_arbeitsweg_events` | Ereignisse | Anzahl aktiver Meldungen. Attribute: Anzahl je Typ, `by_source`, `events` (bis zu 20, schwerste zuerst) |
| `sensor.streckenwacht_arbeitsweg_travel_time_loss` | Reisezeitverlust | Größter aktueller Reisezeitverlust in Minuten (nur mit Staumeldungen) |
| `sensor.streckenwacht_arbeitsweg_next_closure` | Nächste Sperrung | Beginn der nächsten geplanten Sperrung (innerhalb von 14 Tagen) als Zeitstempel. Attribute: `title`, `road`, `direction`, `end`, `source` |
| `event.streckenwacht_arbeitsweg_event_change` | Ereignisänderung | Event-Typ `new` oder `ended` |

<img src="https://raw.githubusercontent.com/streckenwacht/integration/main/assets/screenshots/kalender.png" alt="Kalender in der Listenansicht: Nachtsperrungen als einzelne Termine, aktueller Stau" width="600">

**Typen** (`type`): `roadworks` (Baustelle), `closure` (Sperrung), `traffic_jam` (Stau), `accident` (Unfall), `warning` (sonstige Warnung).

Alle Entitäten haben das Attribut `unavailable_sources`: Ist eine Quelle gerade nicht erreichbar, steht sie dort – die angezeigten Daten sind dann der letzte bekannte Stand.

Ein `new`-Event enthält `id`, `title`, `type`, `source`, `road`, `direction`, `start`, `end`, `delay_minutes`, `latitude`, `longitude`; ein `ended`-Event `id`, `title`, `type` und `source`. Nach einem Neustart oder einer Bereichsänderung werden bekannte Meldungen nicht erneut als neu gemeldet. Staus werden erst ab der Stau-Schwelle des Bereichs als neu gemeldet (und nur dann auch als beendet); vergibt die Verkehrslage für einen Stau eine neue Kennung, wird das nicht als neuer Stau gemeldet.

## Was du damit bauen kannst

### Fertige Blueprints

Ohne YAML: Blueprint importieren, Bereich und Handy auswählen, fertig.

| Blueprint | Was sie tut | |
|---|---|---|
| **Stau-Benachrichtigung** | Push-Nachricht, sobald der Reisezeitverlust einen Schwellwert überschreitet; optional nur in einem Zeitfenster | [![Blueprint importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fstreckenwacht%2Fintegration%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fstreckenwacht%2Fstau_benachrichtigung.yaml) |
| **Vorwarnung vor geplanter Sperrung** | Push-Nachricht mit frei wählbarem Vorlauf (Standard 12 Stunden), bevor eine geplante Sperrung beginnt – etwa am Vorabend einer Nachtsperrung | [![Blueprint importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fstreckenwacht%2Fintegration%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fstreckenwacht%2Fvorwarnung_sperrung.yaml) |
| **Neue oder beendete Meldung** | Push-Nachricht bei neuen Meldungen der gewählten Arten (z. B. Sperrung, Unfall), auf Wunsch auch bei deren Ende | [![Blueprint importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fstreckenwacht%2Fintegration%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fstreckenwacht%2Fneue_meldung.yaml) |

Die Benachrichtigungen gehen an ein Handy mit der offiziellen Home-Assistant-App. Wer es anders braucht, findet unten die Beispiele als YAML zum Anpassen.

### Push-Nachricht bei Reisezeitverlust

```yaml
alias: Stau auf dem Arbeitsweg
triggers:
  - trigger: numeric_state
    entity_id: sensor.streckenwacht_arbeitsweg_travel_time_loss
    above: 15
actions:
  - action: notify.mobile_app_mein_telefon
    data:
      title: "Stau auf dem Arbeitsweg"
      message: >-
        +{{ states('sensor.streckenwacht_arbeitsweg_travel_time_loss') }} min:
        {{ state_attr('sensor.streckenwacht_arbeitsweg_travel_time_loss', 'title') }}
```

### Benachrichtigung bei neuer Sperrung oder neuem Unfall

```yaml
alias: Neue Sperrung auf dem Arbeitsweg
triggers:
  - trigger: state
    entity_id: event.streckenwacht_arbeitsweg_event_change
conditions:
  - condition: template
    value_template: >-
      {{ trigger.to_state.attributes.event_type == 'new'
         and trigger.to_state.attributes.type in ['closure', 'accident'] }}
actions:
  - action: notify.mobile_app_mein_telefon
    data:
      title: "Neu auf dem Arbeitsweg"
      message: "{{ trigger.to_state.attributes.title }}"
```

### Ansage beim Verlassen des Hauses

```yaml
alias: Störung auf dem Arbeitsweg ansagen
triggers:
  - trigger: state
    entity_id: person.ich
    from: home
conditions:
  - condition: state
    entity_id: binary_sensor.streckenwacht_arbeitsweg_disruption_active
    state: "on"
actions:
  - action: tts.speak
    target:
      entity_id: tts.home_assistant_cloud
    data:
      media_player_entity_id: media_player.flur
      message: >-
        Achtung, auf dem Arbeitsweg:
        {{ state_attr('binary_sensor.streckenwacht_arbeitsweg_disruption_active', 'disruptions')
           | map(attribute='title') | join(', ') }}
```

### Kalender im Dashboard

```yaml
type: calendar
initial_view: listWeek
entities:
  - calendar.streckenwacht_arbeitsweg
```

### Karte im Dashboard

Alle aktuellen Meldungen deiner Bereiche erscheinen als Punkte auf der Kartenkarte (je Meldung eine `geo_location`-Entität, höchstens 150, die schwersten und nächsten zuerst):

```yaml
type: map
geo_location_sources:
  - streckenwacht
entities:
  - zone.home
```

Die Punkte tragen Titel, Art, Straße, Zeitraum und die Namensnennung der Quelle. Sie kommen und gehen mit den Meldungen und landen nicht in der Entitätsliste.

## Fehlerbehebung

- **Reparaturen:** Ist eine Quelle dreimal in Folge nicht erreichbar, erscheint unter *Einstellungen → System → Reparaturen* ein Hinweis. Er verschwindet von selbst, sobald der Abruf wieder klappt.
- **Diagnose:** *Geräte & Dienste → Streckenwacht → ⋮ → Diagnose herunterladen*. Die Koordinaten deiner Bereiche sind darin geschwärzt.
- **Ausführliches Protokoll:**

  ```yaml
  logger:
    logs:
      custom_components.streckenwacht: debug
  ```

## Fehler melden

Fehler und Ideen bitte als [GitHub-Issue](https://github.com/streckenwacht/integration/issues), möglichst mit Diagnose-Datei und Home-Assistant-Version.

## Lizenz

Code: [MIT](LICENSE). Die angezeigten Daten unterliegen den Lizenzen der jeweiligen Quellen (siehe [Datenquellen](#datenquellen)).
