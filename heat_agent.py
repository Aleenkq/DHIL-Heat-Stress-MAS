"""heat_agent.py -- Heat Agent: live Makkah weather (Open-Meteo) with fallbacks."""
import json
import numpy as np
import health_model as hm
import tracing
from messages import BaseAgent

MAKKAH = (21.4225, 39.8262)                      # latitude, longitude
CACHE_FILE = "heat_cache.json"

# ASSUMPTION (team-defined): typical summer day in Makkah, used ONLY when there is
# no live data and no cached reading.
FALLBACK_HOURS = [0, 3, 6, 9, 12, 15, 18, 21, 24]
FALLBACK_TEMP = [33, 31, 31, 36, 42, 43, 40, 36, 33]
FALLBACK_RH = [30, 33, 33, 25, 15, 14, 18, 25, 30]

# NWS heat-index bands (deg F)
BANDS = [(80, "Safe"), (90, "Caution"), (103, "Extreme Caution"), (125, "Danger")]


def band_name(hi_f):
    for limit, name in BANDS:
        if hi_f < limit:
            return name
    return "Extreme Danger"


def open_meteo_fetch(lat=MAKKAH[0], lon=MAKKAH[1], timeout=6):
    """Current temperature (C) and relative humidity (%). Raises on any failure."""
    import requests
    r = requests.get("https://api.open-meteo.com/v1/forecast",
                     params={"latitude": lat, "longitude": lon,
                             "current": "temperature_2m,relative_humidity_2m",
                             "timezone": "auto"}, timeout=timeout)
    r.raise_for_status()
    cur = r.json()["current"]
    return float(cur["temperature_2m"]), float(cur["relative_humidity_2m"])


class HeatAgent(BaseAgent):
    # temperature offset per map zone in C (adjustable from the UI)
    DEFAULT_ZONES = {"Zone A": 0.0, "Zone B": 1.0, "Zone C": 2.0, "Zone D": -1.0}

    def __init__(self, bus, zones=None, receivers=("health", "route"), fetcher=None,
                 cache_file=CACHE_FILE):
        super().__init__("heat", bus)
        self.zones = dict(zones or self.DEFAULT_ZONES)
        self.receivers = list(receivers)
        self.fetcher = fetcher or open_meteo_fetch
        self.cache_file = cache_file
        self.mode = "LIVE"                  # LIVE | CACHED | FALLBACK | MANUAL
        self.force_api_failure = False      # switch for the failure scenario
        self.manual = None                  # (temp_c, rh) when the user overrides
        self.base = (None, None)
        self._last_sent = None
        self.last = None

    def set_manual(self, temp_c=None, rh=None):
        """Slider mode: the user decides the weather (needed for test scenarios)."""
        self.manual = None if temp_c is None else (float(temp_c), float(rh))

    def set_zone_offset(self, zone, delta_c):
        self.zones[zone] = float(delta_c)

    def _save_cache(self, t, rh):
        try:
            with open(self.cache_file, "w") as f:
                json.dump({"temp_c": t, "rh": rh}, f)
        except Exception:
            pass

    def _load_cache(self):
        try:
            with open(self.cache_file) as f:
                d = json.load(f)
            return float(d["temp_c"]), float(d["rh"])
        except Exception:
            return None

    def _read_base(self, hour):
        if self.manual is not None:
            self.mode = "MANUAL"
            return self.manual
        if not self.force_api_failure and not self.is_failed:
            try:
                t, rh = self.fetcher()
                self._save_cache(t, rh)
                self.mode = "LIVE"
                return t, rh
            except Exception:
                pass
        cached = self._load_cache()
        if cached is not None:
            self.mode = "CACHED"
            return cached
        self.mode = "FALLBACK"
        h = 12 if hour is None else hour % 24
        return (float(np.interp(h, FALLBACK_HOURS, FALLBACK_TEMP)),
                float(np.interp(h, FALLBACK_HOURS, FALLBACK_RH)))

    def zone_conditions(self, zone=None):
        t0, rh = self.base
        def one(offset):
            t = t0 + offset
            hi_f = float(hm.heat_index_f(t, rh))
            return {"temp_c": round(t, 1), "rh": round(rh, 1), "hi_f": round(hi_f, 1),
                    "hi_c": round((hi_f - 32) * 5 / 9, 1), "band": band_name(hi_f)}
        if zone is not None:
            return one(self.zones[zone])
        return {z: one(o) for z, o in self.zones.items()}

    def tick(self, hour=None, refresh=True):
        """Traced wrapper: read weather (if refresh), compute zone conditions, report on change."""
        with tracing.span("heat.weather", "tool", inputs={"refresh": refresh, "manual": self.manual is not None}) as sp:
            out = self._tick(hour, refresh)
            sp.set(source=out["source"], temp_c=out["base_temp_c"], rh=out["rh"], worst_band=out["worst_band"])
        return out

    def _tick(self, hour=None, refresh=True):
        """Read weather (if refresh), compute zone conditions, report on change."""
        if refresh or self.base[0] is None:
            self.base = self._read_base(hour)
        zones = self.zone_conditions()
        worst = max(zones.values(), key=lambda z: z["hi_f"])
        self.last = {"event": "heat_update", "source": self.mode,
                     "base_temp_c": round(self.base[0], 1), "rh": round(self.base[1], 1),
                     "worst_band": worst["band"], "zones": zones}
        self.status = f"{self.mode}: {self.last['base_temp_c']}C / {self.last['rh']}% ({worst['band']})"

        key = (worst["band"], self.mode)
        prev = self._last_sent
        changed = (prev is None or key != prev[:2] or abs(worst["hi_c"] - prev[2]) >= 2.0)
        if changed:
            for r in self.receivers:
                self.send(r, "INFORM", self.last, conversation_id="heat-monitoring")
            self._last_sent = (worst["band"], self.mode, worst["hi_c"])
        return self.last
