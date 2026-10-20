/*
 * Streckenwacht map card: the events of one or more observation areas with
 * their real geometry (lines and areas), coloured by type, on Home Assistant's
 * own map tile proxy (the browser only talks to Home Assistant).
 *
 * type: custom:streckenwacht-map-card
 * entities:                                     # any entity of each area
 *   - sensor.streckenwacht_<area>_events
 * (entity: <one entity> still works, from 0.6)
 * title: optional
 * height: 400                                   # pixels
 * show_planned: true                            # events starting within 14 days
 */

const BASE = new URL(".", import.meta.url).pathname;
const LEAFLET_JS = `${BASE}leaflet.js?v=1.9.4`;
const LEAFLET_CSS = `${BASE}leaflet.css?v=1.9.4`;
const TOKEN_REFRESH_MS = 20 * 60 * 1000;
const DATA_REFRESH_MS = 5 * 60 * 1000;

const COLORS = {
  closure: "#d32f2f",
  roadworks: "#f57c00",
  traffic_jam: "#8e0000",
  accident: "#7b1fa2",
  warning: "#fbc02d",
};

const TEXT = {
  de: {
    closure: "Sperrung",
    roadworks: "Baustelle",
    traffic_jam: "Stau",
    accident: "Unfall",
    warning: "Warnung",
    now: "aktuell",
    from: "ab",
    until: "bis",
    open: "Ende offen",
    planned: "geplant",
    noTiles:
      "Kartenhintergrund nicht verfügbar – er braucht Home Assistant 2026.9 oder neuer.",
    noArea: "Kein Streckenwacht-Bereich: bitte eine Entität eines Beobachtungsbereichs wählen.",
    entities: "Bereiche (je eine Entität eines Beobachtungsbereichs)",
    title: "Titel",
    height: "Höhe",
    show_planned: "Geplante Meldungen zeigen (nächste 14 Tage)",
  },
  en: {
    closure: "Closure",
    roadworks: "Roadworks",
    traffic_jam: "Traffic jam",
    accident: "Accident",
    warning: "Warning",
    now: "now",
    from: "from",
    until: "until",
    open: "open end",
    planned: "planned",
    noTiles: "Map background unavailable – it needs Home Assistant 2026.9 or later.",
    noArea: "Not a Streckenwacht area: please choose an entity of an observation area.",
    entities: "Areas (an entity of each observation area)",
    title: "Title",
    height: "Height",
    show_planned: "Show planned reports (next 14 days)",
  },
};

let leafletLoading;

function pageLanguage(hass) {
  const lang = hass?.locale?.language || document.documentElement.lang || navigator.language || "";
  return String(lang).toLowerCase().startsWith("de") ? "de" : "en";
}

function loadLeaflet() {
  if (window.L?.map) return Promise.resolve(window.L);
  if (!leafletLoading) {
    leafletLoading = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = LEAFLET_JS;
      script.onload = () => resolve(window.L);
      script.onerror = () => reject(new Error("Leaflet could not be loaded"));
      document.head.appendChild(script);
    });
  }
  return leafletLoading;
}

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}

class StreckenwachtMapCard extends HTMLElement {
  static getConfigForm() {
    return {
      schema: [
        {
          name: "entities",
          selector: { entity: { multiple: true, filter: { integration: "streckenwacht" } } },
        },
        { name: "title", selector: { text: {} } },
        {
          name: "height",
          selector: {
            number: { min: 150, max: 1200, step: 10, mode: "box", unit_of_measurement: "px" },
          },
        },
        { name: "show_planned", selector: { boolean: {} } },
      ],
      // The form passes no hass here: take the language of the page.
      computeLabel: (schema) => TEXT[pageLanguage()][schema.name],
    };
  }

  static getStubConfig(hass) {
    const ids = Object.keys(hass?.entities || {}).filter(
      (id) => hass.entities[id]?.platform === "streckenwacht" && id.startsWith("sensor."),
    );
    const events = ids.find((id) => hass.entities[id]?.translation_key === "events");
    const first = events || ids[0];
    return { entities: first ? [first] : [], height: 400, show_planned: true };
  }

  setConfig(config) {
    // "entity" (one area, 0.6) and "entities" (several) may both be given.
    const entities = [
      ...(Array.isArray(config.entities) ? config.entities : []),
      ...(config.entity ? [config.entity] : []),
    ].filter((id, i, all) => id && all.indexOf(id) === i);
    if (!entities.length) {
      throw new Error("entities is required");
    }
    const changed = entities.join() !== this._entities?.join();
    this._entities = entities;
    this._config = { height: 400, show_planned: true, ...config };
    if (changed) {
      this._lastUpdated = undefined;
      this._userMoved = false; // new areas: fit them again
    }
    if (this._map) {
      this._render();
      if (changed) this._refresh();
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) {
      this._build();
      return;
    }
    this._applyTheme();
    const updated = this._entities.map((id) => hass.states[id]?.last_updated).join();
    if (updated !== this._lastUpdated) {
      this._lastUpdated = updated;
      this._refresh();
    }
  }

  get _t() {
    return TEXT[pageLanguage(this._hass)];
  }

  getCardSize() {
    return Math.ceil((this._config?.height || 400) / 50) + 1;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 4, rows: "auto" };
  }

  connectedCallback() {
    if (this._map && !this._timers) {
      this._startTimers();
      this._resize?.observe(this._wrap);
      this._refresh();
    }
  }

  disconnectedCallback() {
    for (const timer of this._timers || []) clearInterval(timer);
    this._timers = undefined;
    this._resize?.disconnect();
  }

  async _build() {
    this._built = true;
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <link rel="stylesheet" href="${LEAFLET_CSS}">
      <style>
        ha-card { overflow: hidden; }
        .wrap { position: relative; }
        #map { height: 100%; width: 100%; background: var(--secondary-background-color); }
        .dark .leaflet-tile-pane { filter: invert(1) hue-rotate(180deg) brightness(.9) contrast(.9); }
        .legend { position: absolute; z-index: 500; bottom: 18px; left: 8px; display: flex;
          flex-wrap: wrap; gap: 4px; max-width: calc(100% - 16px); pointer-events: none; }
        .chip { background: var(--card-background-color); color: var(--primary-text-color);
          border-radius: 10px; padding: 1px 8px 1px 6px; font-size: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.3); }
        .chip i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px;
          vertical-align: -1px; }
        .notice { position: absolute; z-index: 600; top: 8px; left: 50px; right: 8px; padding: 6px 10px;
          font-size: 13px; background: var(--card-background-color); color: var(--primary-text-color);
          border-left: 4px solid var(--warning-color, #ffa600); border-radius: 4px; }
        .notice[hidden] { display: none; }
        .leaflet-popup-content-wrapper, .leaflet-popup-tip {
          background: var(--card-background-color, #fff); color: var(--primary-text-color, #212121); }
        .leaflet-popup-content { margin: 10px 12px; font-size: 13px; line-height: 1.4; }
        .leaflet-popup-content .meta { color: var(--secondary-text-color, #555); }
        .leaflet-popup-content .desc { white-space: pre-line; margin-top: 4px; }
        .leaflet-popup-content .src { color: var(--secondary-text-color, #777); font-size: 11px;
          margin-top: 6px; opacity: .8; }
      </style>
      <ha-card>
        <div class="wrap"><div id="map"></div><div class="legend"></div><div class="notice" hidden></div></div>
      </ha-card>`;
    this._card = root.querySelector("ha-card");
    this._wrap = root.querySelector(".wrap");
    this._legend = root.querySelector(".legend");
    this._notice = root.querySelector(".notice");
    this._render();
    try {
      const L = await loadLeaflet();
      this._L = L;
      // Half zoom steps let the area circle fill the card.
      this._map = L.map(root.querySelector("#map"), { zoomControl: true, zoomSnap: 0.5 });
      this._map.attributionControl.setPrefix("");
      this._tiles = L.tileLayer("", {
        maxZoom: 19,
        attribution:
          '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
      }).addTo(this._map);
      this._map.setView([51.2, 10.4], 6);
      // Until the user pans or zooms, the view follows the area circle
      // (registered after the first view, which fires zoomstart too).
      this._map.on("dragstart", () => (this._userMoved = true));
      this._map.on("zoomstart", () => {
        if (!this._fitting) this._userMoved = true;
      });
      this._resize = new ResizeObserver(() => {
        this._map.invalidateSize();
        if (!this._userMoved) this._fit();
      });
      this._resize.observe(this._wrap);
      this._applyTheme();
      await this._refreshToken();
      this._startTimers();
      await this._refresh();
    } catch (err) {
      this._showNotice(String(err.message || err));
    }
  }

  _render() {
    if (!this._wrap) return;
    this._wrap.style.height = `${this._config.height}px`;
    if (this._config.title) this._card.setAttribute("header", this._config.title);
    else this._card.removeAttribute("header");
    this._map?.invalidateSize();
    if (this._data) this._draw();
  }

  _applyTheme() {
    this._wrap?.classList.toggle("dark", Boolean(this._hass?.themes?.darkMode));
  }

  _startTimers() {
    this._timers = [
      setInterval(() => this._refreshToken(), TOKEN_REFRESH_MS),
      setInterval(() => this._refresh(), DATA_REFRESH_MS),
    ];
  }

  _showNotice(text) {
    this._notice.textContent = text;
    this._notice.hidden = !text;
  }

  async _refreshToken() {
    try {
      const { token } = await this._hass.callWS({ type: "map_tiles/access_token" });
      this._tiles.setUrl(
        `/api/map_tiles/raster/{z}/{x}/{y}.png?token=${encodeURIComponent(token)}`,
      );
      if (this._notice.textContent === this._t.noTiles) this._showNotice("");
    } catch (_err) {
      // Older Home Assistant: no proxy. Never fall back to OSM directly, that
      // would show the area to a third party.
      this._showNotice(this._t.noTiles);
    }
  }

  async _refresh() {
    if (!this._map || !this._hass || this._loading) return;
    this._loading = true;
    try {
      const results = await Promise.allSettled(
        this._entities.map((entity_id) =>
          this._hass.callWS({ type: "streckenwacht/map", entity_id }),
        ),
      );
      const loaded = results.filter((r) => r.status === "fulfilled").map((r) => r.value);
      // An event in two areas is drawn once.
      const seen = new Set();
      const features = [];
      for (const data of loaded) {
        for (const feature of data.features) {
          if (seen.has(feature.properties.id)) continue;
          seen.add(feature.properties.id);
          features.push(feature);
        }
      }
      this._data = { areas: loaded.map((d) => d.area), features };
      const failed = loaded.length < results.length;
      if (failed) this._showNotice(this._t.noArea);
      else if (this._notice.textContent === this._t.noArea) this._showNotice("");
      this._draw();
    } finally {
      this._loading = false;
    }
  }

  _draw() {
    const L = this._L;
    const t = this._t;
    const { areas, features } = this._data;
    this._layer?.remove();
    const group = L.featureGroup();
    // SVG attributes take no CSS variables: read the theme colour.
    const primary =
      getComputedStyle(this).getPropertyValue("--primary-color").trim() || "#03a9f4";
    const circles = areas.map((area) =>
      L.circle([area.latitude, area.longitude], {
        radius: area.radius_km * 1000,
        color: primary,
        weight: 1.5,
        dashArray: "6 6",
        fill: false,
        interactive: false,
      }).addTo(group),
    );

    const shown = features.filter((f) => f.properties.active || this._config.show_planned);
    for (const feature of shown) {
      const p = feature.properties;
      const color = COLORS[p.type] || "#607d8b";
      const style = {
        color,
        weight: p.active ? (p.type === "closure" ? 6 : 5) : 3,
        opacity: p.active ? 0.9 : 0.55,
        dashArray: p.active ? null : "6 6",
        fillColor: color,
        fillOpacity: p.active ? 0.3 : 0.12,
      };
      const popup = this._popup(p);
      L.geoJSON(feature, {
        style: () => style,
        pointToLayer: () => L.layerGroup(), // points get the marker below
      })
        .bindPopup(popup)
        .addTo(group);
      if (p.latitude != null && p.longitude != null) {
        L.circleMarker([p.latitude, p.longitude], {
          radius: p.active ? 7 : 5,
          color: "#fff",
          weight: 2,
          fillColor: color,
          fillOpacity: p.active ? 0.95 : 0.6,
        })
          .bindPopup(popup)
          .addTo(group);
      }
    }
    group.addTo(this._map);
    this._layer = group;
    // Circles know their bounds only once they are on the map.
    if (circles.length) {
      const bounds = circles[0].getBounds();
      for (const circle of circles.slice(1)) bounds.extend(circle.getBounds());
      this._circleBounds = bounds;
    }

    // The legend first: fitting leaves room for it.
    const types = [...new Set(shown.map((f) => f.properties.type))];
    this._legend.innerHTML = types
      .map((type) => `<span class="chip"><i style="background:${COLORS[type]}"></i>${t[type] || type}</span>`)
      .join("");
    if (!this._userMoved) this._fit();
  }

  _fit() {
    if (!this._circleBounds) return;
    this._fitting = true;
    // Keep the circles above the legend in the bottom left corner.
    const legend = this._legend.offsetHeight ? this._legend.offsetHeight + 18 : 10;
    this._map.fitBounds(this._circleBounds, {
      paddingTopLeft: [10, 10],
      paddingBottomRight: [10, legend],
      animate: false,
    });
    this._fitting = false;
  }

  _popup(p) {
    const t = this._t;
    const fmt = (iso) =>
      new Date(iso).toLocaleDateString(this._hass.locale?.language || "de", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      });
    const when = [
      p.active ? t.now : p.start ? `${t.planned}, ${t.from} ${fmt(p.start)}` : t.planned,
      p.end ? `${t.until} ${fmt(p.end)}` : t.open,
    ].join(" · ");
    const delay = p.delay_minutes ? ` · +${p.delay_minutes} min` : "";
    return `
      <b>${escapeHtml(p.title)}</b>
      <div class="meta">${escapeHtml(t[p.type] || p.type)}${delay} · ${escapeHtml(when)}</div>
      ${p.description ? `<div class="desc">${escapeHtml(p.description)}</div>` : ""}
      <div class="src">${escapeHtml(p.attribution)}</div>`;
  }
}

// The file can be loaded twice, e.g. under another version (?v=) from a
// dashboard resource added by hand: the first one wins.
if (!customElements.get("streckenwacht-map-card")) {
  customElements.define("streckenwacht-map-card", StreckenwachtMapCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "streckenwacht-map-card",
    name: "Streckenwacht",
    description: "Baustellen, Sperrungen und Staus eines Beobachtungsbereichs auf der Karte",
    documentationURL: "https://github.com/streckenwacht/integration",
  });
}
