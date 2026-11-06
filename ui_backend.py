"""ui_backend.py -- thin layer between the Streamlit UI and the DHIL system (no Streamlit code here)."""
import pandas as pd
import health_model as hm
import system
from heat_agent import MAKKAH, FALLBACK_HOURS, FALLBACK_TEMP, FALLBACK_RH, band_name
from route_agent import KAABA, default_map, to_latlon
from train_model import ensure_model

STEP_MIN = 5
AGENTS = ["heat", "health", "prevention", "resource", "route"]
LEVEL_STYLE = {                     # (border / text colour, background colour)
    "OK": ("#2e7d32", "#e8f5e9"), "INFO": ("#1565c0", "#e3f2fd"),
    "ATTENTION": ("#9a6b00", "#fff8e1"), "WARNING": ("#e65100", "#fff3e0"),
    "URGENT": ("#c62828", "#ffebee"), "EMERGENCY": ("#ffffff", "#b71c1c"),
}
NEED_COLORS = {"water": "#1f77b4", "medical": "#d62728", "cooling": "#17becf", "rest": "#2ca02c"}
NEED_LABELS = {"water": "Drinking water", "medical": "Medical point",
               "cooling": "Cooling area (roofed)", "rest": "Rest point"}


class Session:
    """One simulated pilgrim plus the history shown on screen."""

    def __init__(self, profile=None, live=True, temp=40.0, rh=25.0, auto_follow=False, fetcher=None):
        ensure_model()
        self.profile = dict(system.DEFAULT_PROFILE)
        self.profile.update(profile or {})
        self.sim = system.DHILSystem(profile=self.profile, fetcher=fetcher)
        self.sim.obey = bool(auto_follow)
        self.weather_key = None
        self.history = []
        self.last = None
        self.set_weather(live, temp, rh)
        self.advance(1)                                  # first reading, so the screen is never empty

    # ------------------------------------------------------------------ time
    def _record(self, snap):
        r, a = snap["risk"] or {}, snap["advice"]
        hi_c = None
        if snap.get("heat"):
            hi_c = snap["heat"]["zones"][snap["zone"]]["hi_c"]
        return {"minute": self.sim.t * STEP_MIN, "risk_score": r.get("risk_score"),
                "risk_class": r.get("risk_class"), "level": a["level"], "code": a["code"],
                "need": a["need"], "station": a.get("station"), "zone": snap["zone"],
                "heat_index_c": hi_c, "health": "DOWN" if snap["health_stale"] else r.get("mode"),
                "medic": a["call_medic"]}

    def advance(self, n=1):
        for _ in range(n):
            self.last = self.sim.step()
            self.history.append(self._record(self.last))
        return self.last

    # --------------------------------------------------------------- weather
    def set_weather(self, live, temp, rh):
        key = (bool(live), None if live else float(temp), None if live else float(rh))
        if key == self.weather_key:
            return
        self.weather_key = key
        self.sim.heat.set_manual(None if live else temp, None if live else rh)
        if not self.sim.heat.is_failed:
            self.sim.heat.tick(self.sim.hour, refresh=True)

    # --------------------------------------------------------------- pilgrim
    def action(self, name):
        """water / rest / symptoms / recovered. Each action advances one step (5 simulated minutes)."""
        self.sim.user_action(name)
        return self.advance(1)

    def start_rest(self, minutes):
        """Start resting for a chosen time. Returns the minutes planned."""
        planned = self.sim.start_rest(minutes)
        self.advance(1)
        return planned

    def end_rest(self):
        """End the rest now. Returns (minutes rested, whether it counted)."""
        done = self.sim.end_rest()
        if done:
            self.advance(1)
        return done, done >= system.MIN_REST_CREDIT_MIN

    def follow(self):
        if not self.sim.follow_advice():
            return False
        self.advance(1)
        return True

    # -------------------------------------------------------------- failures
    def fail(self, name):
        self.sim.bus.fail(name)

    def recover(self, name):
        self.sim.bus.recover(name)

    def set_ml_failure(self, on):
        self.sim.health.force_ml_failure = bool(on)

    def set_api_failure(self, on):
        self.sim.heat.force_api_failure = bool(on)

    def set_station_closed(self, name, closed):
        for st in self.sim.stations:
            if st.name == name:
                st.closed = bool(closed)

    def restore_all(self):
        self.sim.bus.failed.clear()
        self.sim.health.force_ml_failure = False
        self.sim.heat.force_api_failure = False
        for st in self.sim.stations:
            st.closed = False

    def preset(self, name):
        if name == "heat_wave":
            self.set_weather(False, 44, 15)
            self.sim.obey = True
        elif name == "health_failure":
            self.fail("health")
        elif name == "rest_closed":
            self.set_weather(False, 44, 15)
            self.sim.obey = True
            for st in self.sim.stations:
                if st.need == "rest":
                    st.closed = True
        elif name == "restore":
            self.restore_all()

    # ----------------------------------------------------------------- tables
    def history_df(self):
        return pd.DataFrame(self.history)

    def agents_df(self):
        rows = []
        for name, status in (self.last or self.sim.snapshot())["agents"].items():
            rows.append({"agent": name, "state": "DOWN" if status == "FAILED" else "up", "status": status})
        return pd.DataFrame(rows)

    def stations_df(self):
        real = {t[0] for t in default_map().real_sites()}
        rows = [{"station": s.name, "need": s.need, "zone": s.zone, "free": s.capacity,
                 "wait_min": s.queue_min, "closed": s.closed,
                 "source": "OpenStreetMap" if s.name in real else "team assumption"}
                for s in self.sim.stations]
        return pd.DataFrame(rows)

    def messages_df(self, limit=60, performatives=None, text=""):
        rows = []
        for m in reversed(self.sim.bus.log):
            if performatives and m.performative not in performatives:
                continue
            line = f"{m.sender} {m.receiver} {m.conversation_id}"
            if text and text.lower() not in line.lower() and text.lower() not in str(m.content).lower():
                continue
            rows.append({"id": m.msg_id, "step": m.step, "performative": m.performative,
                         "from": m.sender, "to": m.receiver, "conversation": m.conversation_id,
                         "content": str(m.content)[:160], "delivered": "yes" if m.delivered else "NO"})
            if len(rows) >= limit:
                break
        return pd.DataFrame(rows)


# ------------------------------------------------------------------------ map
_LINES = {}


def _walkway_lines():
    if not _LINES:
        m = default_map()
        open_l, shaded_l = [], []
        for u in range(len(m.adj)):
            for v, e in m.adj[u].items():
                if u < v or u not in m.adj[v]:
                    line = [list(to_latlon(x, y)) for x, y in e["pts"]]
                    (shaded_l if e["shade"] >= 0.5 else open_l).append(line)
        _LINES["open"], _LINES["shaded"] = open_l, shaded_l
    return _LINES["open"], _LINES["shaded"]


def build_map_html(sim, lang="en"):
    from i18n import tr, station_name
    T = lambda text: tr(text, lang)
    import folium
    real = {t[0] for t in default_map().real_sites()}
    fmap = folium.Map(location=list(KAABA), zoom_start=17, tiles=None)
    folium.TileLayer(tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
                     attr="Tiles (c) Esri", name="Street map", max_zoom=19).add_to(fmap)
    folium.TileLayer(tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                     attr="Tiles (c) Esri, Maxar, Earthstar Geographics", name="Satellite",
                     max_zoom=19, show=False).add_to(fmap)
    open_l, shaded_l = _walkway_lines()
    folium.PolyLine(open_l, color="#e08a00", weight=3, opacity=0.7).add_to(fmap)
    folium.PolyLine(shaded_l, color="#6a5acd", weight=3, opacity=0.7).add_to(fmap)
    folium.Marker(list(KAABA), tooltip=T("Kaaba"), icon=folium.Icon(color="black", icon="star")).add_to(fmap)
    for s in sim.stations:
        folium.CircleMarker(
            location=list(to_latlon(*s.pos)), radius=8, color=NEED_COLORS[s.need], weight=3,
            fill=True, fill_color=NEED_COLORS[s.need], fill_opacity=0.9,
            tooltip=f"{station_name(s.name, lang)} | {T(s.need)} | {'OSM (real)' if s.name in real else 'ASSUMED'}"
                    f"{' | CLOSED' if s.closed else ''}").add_to(fmap)
    route = sim.prevention.advice.get("route")
    if route and route.get("path_latlon"):
        folium.PolyLine([list(p) for p in route["path_latlon"]], color="#00a000", weight=6, opacity=0.9,
                        tooltip=T("suggested route")).add_to(fmap)
    folium.Marker(list(to_latlon(*sim.pos)), tooltip=T("Pilgrim"),
                  icon=folium.Icon(color="darkblue", icon="user", prefix="fa")).add_to(fmap)
    legend = ('<div style="position: fixed; bottom: 28px; right: 8px; z-index: 9999; background: rgba(255,255,255,0.92);'
              'padding: 5px 8px; border: 1px solid #999; border-radius: 5px; font-size: 11px; line-height: 1.25;">'
              '<span style="color:#e08a00">&#9473;&#9473;</span> open walkway<br>'
              '<span style="color:#6a5acd">&#9473;&#9473;</span> shaded walkway (proxy)<br>'
              '<span style="color:#00a000">&#9473;&#9473;</span> suggested route<br>'
              '<span style="color:#1f77b4">&#9679;</span> water '
              '<span style="color:#d62728">&#9679;</span> medical<br>'
              '<span style="color:#17becf">&#9679;</span> cooling '
              '<span style="color:#2ca02c">&#9679;</span> rest<br>'
              '<span style="font-size:10px">(c) OpenStreetMap contributors</span></div>')
    if lang == "ar":
        for label in ("shaded walkway (proxy)", "open walkway", "suggested route", "medical", "cooling", "water", "rest"):
            legend = legend.replace(label, T(label))
    fmap.get_root().html.add_child(folium.Element(legend))
    folium.LayerControl(collapsed=True).add_to(fmap)
    return fmap.get_root().render()


# ------------------------------------------------------------- heat outlook
BAND_MESSAGE = {
    "Safe": "Comfortable heat level. Keep drinking water regularly.",
    "Caution": "Fatigue is possible with long activity. Drink often and rest in the shade.",
    "Extreme Caution": "Cramps and heat exhaustion are possible. Limit time in the sun and rest every 30 minutes.",
    "Danger": "Heat exhaustion is likely and heat stroke is possible. Stay in covered or cooled areas and avoid long walks.",
    "Extreme Danger": "Heat stroke is highly likely. Stay in a cooled indoor area.",
}
BAND_COLORS = {"Safe": "#2e7d32", "Caution": "#9a6b00", "Extreme Caution": "#e65100",
               "Danger": "#c62828", "Extreme Danger": "#7f0000"}


def _hour_row(label, hour, temp_c, rh):
    hi_f = float(hm.heat_index_f(float(temp_c), float(rh)))
    return {"label": label, "hour": hour, "temp_c": round(float(temp_c), 1), "rh": round(float(rh)),
            "hi_c": round((hi_f - 32.0) * 5.0 / 9.0, 1), "band": band_name(hi_f)}


def forecast_next_24h(timeout=8):
    """Hourly outlook for Makkah. Returns (rows, source). Live data from Open-Meteo, otherwise a
    typical summer day (team assumption) that is clearly labelled."""
    try:
        import requests
        r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=timeout, params={
            "latitude": MAKKAH[0], "longitude": MAKKAH[1], "timezone": "auto", "forecast_days": 2,
            "current": "temperature_2m,relative_humidity_2m",
            "hourly": "temperature_2m,relative_humidity_2m"})
        r.raise_for_status()
        d = r.json()
        times, temps, rhs = d["hourly"]["time"], d["hourly"]["temperature_2m"], d["hourly"]["relative_humidity_2m"]
        now = d["current"]["time"][:13]
        start = next(i for i, t in enumerate(times) if t[:13] >= now)
        rows = [_hour_row(times[i][11:16], int(times[i][11:13]), temps[i], rhs[i])
                for i in range(start, min(start + 24, len(times)))
                if temps[i] is not None and rhs[i] is not None]
        if not rows:
            raise ValueError("empty forecast")
        return rows, "Open-Meteo live forecast"
    except Exception:
        import numpy as np
        rows = [_hour_row(f"{h:02d}:00", h, np.interp(h, FALLBACK_HOURS, FALLBACK_TEMP),
                          np.interp(h, FALLBACK_HOURS, FALLBACK_RH)) for h in range(24)]
        return rows, "typical summer day (no live forecast available)"


def band_ranges(rows, bands):
    """Consecutive hours whose heat band is in `bands`, as a list of (first_label, last_label)."""
    out, cur = [], None
    for r in rows:
        if r["band"] in bands:
            cur = [r["label"], r["label"]] if cur is None else [cur[0], r["label"]]
        elif cur:
            out.append(tuple(cur))
            cur = None
    if cur:
        out.append(tuple(cur))
    return out


def outlook_figure(rows):
    from matplotlib.figure import Figure
    fig = Figure(figsize=(8, 3.2))
    ax = fig.subplots()
    for lo, hi, col in ((0, 26.7, "#d8f0d8"), (26.7, 32.2, "#fff4c2"), (32.2, 39.4, "#ffe0b3"),
                        (39.4, 51.7, "#ffc9c9"), (51.7, 70, "#f0a0a0")):
        ax.axhspan(lo, hi, color=col, alpha=0.7, lw=0)
    x = list(range(len(rows)))
    ax.plot(x, [r["hi_c"] for r in rows], color="#222222", lw=2, marker="o", ms=3)
    ax.set_xticks(x[::3])
    ax.set_xticklabels([rows[i]["label"] for i in x[::3]], fontsize=8)
    top = max(r["hi_c"] for r in rows)
    ax.set_ylim(15, max(45, top + 3))
    ax.set_ylabel("heat index (C)")
    ax.set_title("Next 24 hours: what the heat feels like", fontsize=10)
    fig.tight_layout()
    return fig
