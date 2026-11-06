"""route_agent.py -- Route Agent: heat-aware A* on the real OpenStreetMap walking network of Makkah.

Map:    data/makkah_walk.graphml (OSMnx walking graph around the Kaaba). (c) OpenStreetMap contributors, ODbL.
Coords: every position is local metres: origin = Kaaba (21.4225 N, 39.8262 E), x = east, y = south.
Cost:   edge cost = length * (1 + HEAT_WEIGHT * env_stress(zone heat index + sun penalty * (1 - shade)))
        The multiplier is always >= 1, so straight-line distance is an admissible heuristic.
Shade:  OSM has no shade data. We use a documented PROXY (see shade_of_edge): tunnel=yes is roofed,
        and walkways inside the Haram precinct are partly roofed. These shade values are TEAM ASSUMPTIONS.
Scope:  only pedestrian paths (footway / pedestrian / steps / path) within SCOPE_RADIUS_M of the Kaaba are used,
        i.e. the Haram precinct, not the city streets.
Zones:  4 compass quadrants around the Kaaba: A = north-west, B = north-east, C = south-east, D = south-west.
"""
import ast
import heapq
import math
import os
import numpy as np
import networkx as nx
import health_model as hm
import tracing
from messages import BaseAgent

KAABA = (21.4225, 39.8262)           # lat, lon (same point the Heat Agent queries)
GRAPH_FILE = "data/makkah_walk.graphml"
FEATURES_FILE = "data/haram_features.csv"
WALK_M_PER_MIN = 80.0                # slow pilgrim pace (assumption)
HEAT_WEIGHT = 2.0                    # how strongly heat penalises a step (team assumption)
DEFAULT_HI_F = 100.0                 # used for the cost only when no heat data was ever received
PRECINCT_RADIUS_M = 250.0            # walkways this close to the Kaaba count as the Haram precinct (assumption)
SHADE_TUNNEL = 1.0                   # OSM tunnel=yes -> roofed
SHADE_PRECINCT = 0.5                 # precinct walkways: galleries are roofed, the Mataf is open (assumption)
MAX_SNAP_M = 150.0                   # a point farther than this from any path is "outside the map"
SCOPE_RADIUS_M = 400.0               # only the Haram precinct (metres from the Kaaba)
PEDESTRIAN_ONLY = True               # drop streets used by vehicles
NO_WALK = {"motorway", "motorway_link", "trunk", "trunk_link"}
PED_TYPES = {"footway", "pedestrian", "steps", "path", "corridor"}

_M_LAT = 110574.0
_M_LON = 111320.0 * math.cos(math.radians(KAABA[0]))


def to_local(lat, lon):
    return ((lon - KAABA[1]) * _M_LON, -(lat - KAABA[0]) * _M_LAT)


def to_latlon(x, y):
    return (KAABA[0] - y / _M_LAT, KAABA[1] + x / _M_LON)


def zone_of_xy(xy):
    north, west = xy[1] < 0, xy[0] < 0
    return {(True, True): "Zone A", (True, False): "Zone B",
            (False, False): "Zone C", (False, True): "Zone D"}[(north, west)]


def _types(value):
    if isinstance(value, str) and value.startswith("["):
        try:
            return set(ast.literal_eval(value))
        except Exception:
            return {value}
    return {value}


def shade_of_edge(types, tunnel, mid_xy):
    """Shade fraction 0..1 for an edge (PROXY, see module docstring)."""
    if tunnel == "yes":
        return SHADE_TUNNEL
    if types & PED_TYPES and math.hypot(*mid_xy) <= PRECINCT_RADIUS_M:
        return SHADE_PRECINCT
    return 0.0


def _parse_wkt(wkt):
    """'LINESTRING (lon lat, lon lat, ...)' -> list of local (x, y)."""
    body = wkt[wkt.index("(") + 1: wkt.rindex(")")]
    pts = []
    for pair in body.split(","):
        lon, lat = pair.split()
        pts.append(to_local(float(lat), float(lon)))
    return pts


class OsmMap:
    """Walking network loaded from graphml. Nodes are indexed 0..N-1."""

    def __init__(self, path=GRAPH_FILE):
        G = nx.read_graphml(path)
        ids = list(G.nodes)
        self.index = {n: i for i, n in enumerate(ids)}
        self.xy = np.array([to_local(float(G.nodes[n]["y"]), float(G.nodes[n]["x"])) for n in ids])
        self.adj = [dict() for _ in ids]            # adj[u][v] = edge record (shortest parallel edge)
        for u, v, d in G.edges(data=True):
            types = _types(d.get("highway"))
            if types <= NO_WALK:
                continue                            # motorways / trunks are not pedestrian routes
            if PEDESTRIAN_ONLY and not (types & PED_TYPES):
                continue                            # vehicle streets are outside the Haram scope
            a, b = self.index[u], self.index[v]
            if math.hypot(*self.xy[a]) > SCOPE_RADIUS_M or math.hypot(*self.xy[b]) > SCOPE_RADIUS_M:
                continue                            # outside the Haram precinct
            length = float(d["length"])
            if b in self.adj[a] and self.adj[a][b]["length"] <= length:
                continue
            mid = ((self.xy[a][0] + self.xy[b][0]) / 2, (self.xy[a][1] + self.xy[b][1]) / 2)
            pts = _parse_wkt(d["geometry"]) if "geometry" in d else [tuple(self.xy[a]), tuple(self.xy[b])]
            pts = [(float(p[0]), float(p[1])) for p in pts]          # plain floats (JSON friendly)
            if math.hypot(pts[0][0] - self.xy[a][0], pts[0][1] - self.xy[a][1]) > \
               math.hypot(pts[-1][0] - self.xy[a][0], pts[-1][1] - self.xy[a][1]):
                pts = pts[::-1]
            self.adj[a][b] = {"length": length, "zone": zone_of_xy(mid), "types": types,
                              "shade": shade_of_edge(types, d.get("tunnel"), mid), "pts": pts}
        # keep only the largest strongly connected part, so every pair of kept nodes is reachable
        D = nx.DiGraph((u, v) for u in range(len(ids)) for v in self.adj[u])
        keep = max(nx.strongly_connected_components(D), key=len)
        self.adj = [{v: e for v, e in self.adj[u].items() if v in keep} if u in keep else {}
                    for u in range(len(ids))]
        # node-level shade (mean of incident edges), used for the pilgrim's own position
        self.node_shade = np.array([np.mean([e["shade"] for e in self.adj[i].values()]) if self.adj[i] else 0.0
                                    for i in range(len(ids))])
        self.walkable = np.array([bool(a) for a in self.adj])
        self.ped_node = np.array([any(e["types"] & PED_TYPES for e in self.adj[i].values())
                                  for i in range(len(ids))])

    def nearest(self, xy, pedestrian_only=False):
        mask = self.walkable & (self.ped_node if pedestrian_only else True)
        d = np.hypot(self.xy[:, 0] - xy[0], self.xy[:, 1] - xy[1])
        d = np.where(mask, d, np.inf)
        i = int(np.argmin(d))
        return i, float(d[i])

    def point_from_kaaba(self, bearing_deg, dist_m):
        """Walkway node `dist_m` from the Kaaba in a compass direction (0 = north, 90 = east)."""
        b = math.radians(bearing_deg)
        i, _ = self.nearest((dist_m * math.sin(b), -dist_m * math.cos(b)), pedestrian_only=True)
        return tuple(float(v) for v in self.xy[i])

    def zone_at(self, xy):
        return zone_of_xy(xy)

    def shade_at(self, xy):
        i, _ = self.nearest(xy)
        return float(self.node_shade[i])

    def real_sites(self, path=FEATURES_FILE):
        """Service points from real OpenStreetMap features (CSV), snapped to the nearest walkway node.
        Returns (name, need, xy, capacity, queue_min, snap_m, source) tuples."""
        import csv
        out = []
        if not os.path.exists(path):
            return out
        for r in csv.DictReader(open(path, encoding="utf-8")):
            amen, mm = r.get("amenity", ""), r.get("man_made", "")
            name = r.get("name:en") or r.get("name") or ""
            low = name.lower()
            if r["category"] == "water":
                ablution = "ablution" in low or "\u0648\u0636\u0648\u0621" in (r.get("name") or "")
                drinking = amen == "drinking_water" or mm == "water_well" or (amen == "water_point" and r.get("level"))
                if ablution or not drinking:
                    continue
                need, cap, q = "water", 10, 2.0
            elif r["category"] == "medical" and amen == "hospital":
                need, cap, q = "medical", 5, 3.0
            else:
                continue
            xy = to_local(float(r["lat"]), float(r["lon"]))
            i, d = self.nearest(xy, pedestrian_only=True)
            pos = tuple(float(v) for v in self.xy[i])
            out.append(((name or "osm_" + r["osm_id"]).replace(" ", "_"), need, pos, cap, q, d, "OSM"))
        return out

    def station_sites(self):
        """Stations: water and cooling points come from real OSM data when the CSV exists;
        rest points stay ILLUSTRATIVE (no real data found). Falls back to all-illustrative."""
        sites = [(n, need, pos, cap, q) for n, need, pos, cap, q, _d, _s in self.real_sites()]
        # ASSUMED roofed / air-conditioned galleries used as cooling areas (no coordinates found)
        spec = [("rest_A", "rest", 300, 150, 3, 0.0), ("rest_C", "rest", 150, 120, 15, 2.0),
                ("cool_A", "cooling", 330, 220, 12, 2.0), ("cool_B", "cooling", 60, 260, 10, 3.0),
                ("cool_C", "cooling", 140, 230, 15, 1.0), ("cool_D", "cooling", 235, 240, 12, 2.0)]
        if not sites:
            spec = [("water_A", "water", 315, 200, 20, 1.0), ("water_B", "water", 45, 250, 20, 3.0),
                    ("water_C", "water", 135, 250, 20, 0.0)] + spec + [("cool_B", "cooling", 60, 380, 10, 4.0)]
        return sites + [(n, need, self.point_from_kaaba(b, d), cap, q) for n, need, b, d, cap, q in spec]

    def start_xy(self):
        return self.point_from_kaaba(315, 330)


_MAP_CACHE = {}


def default_map(path=GRAPH_FILE):
    if path not in _MAP_CACHE:
        _MAP_CACHE[path] = OsmMap(path)
    return _MAP_CACHE[path]


class RouteAgent(BaseAgent):
    def __init__(self, bus, osm=None):
        super().__init__("route", bus)
        self.map = osm or default_map()
        self.zone_hi_f = {}                 # latest heat index per zone (from the Heat Agent)
        self.heat_source = None             # LIVE / CACHED / FALLBACK / MANUAL / None
        self.last_route = None

    # ------------------------------------------------------------ messaging
    def tick(self):
        for m in self.read_inbox():
            if m.performative == "INFORM" and m.content.get("event") == "heat_update":
                self.zone_hi_f = {z: v["hi_f"] for z, v in m.content["zones"].items()}
                self.heat_source = m.content.get("source")
            elif m.performative == "REQUEST":
                self._on_request(m)
        mode = "heat-aware" if self.zone_hi_f else "DEGRADED (shortest path)"
        self.status = f"{mode}; heat data: {self.heat_source or 'none'}"

    def _fail(self, m, reason):
        self.send(m.sender, "FAILURE", {"event": "route_failed", "reason": reason,
                                        "pilgrim_id": m.content.get("pilgrim_id")},
                  m.conversation_id, m.msg_id)

    def _on_request(self, m):
        c = m.content
        a, da = self.map.nearest(c["origin"])
        b, db = self.map.nearest(c["dest"])
        if da > MAX_SNAP_M or db > MAX_SNAP_M:
            self._fail(m, "invalid_endpoint")
            return
        best = self.plan(a, b, heat_aware=bool(self.zone_hi_f))
        short = self.plan(a, b, heat_aware=False)
        if best is None:
            self._fail(m, "no_path")
            return
        saved = 0.0
        if short["exposure"] > 0:
            saved = round(100.0 * (short["exposure"] - best["exposure"]) / short["exposure"], 1)
        result = {"event": "route_ready", "pilgrim_id": c.get("pilgrim_id"),
                  "mode": "heat-aware" if self.zone_hi_f else "shortest (no heat data)",
                  "heat_source": self.heat_source,
                  "path": best["xy"], "path_latlon": [to_latlon(*p) for p in best["xy"]],
                  "distance_m": best["distance_m"], "eta_min": best["eta_min"],
                  "shaded_pct": best["shaded_pct"], "exposure": best["exposure"],
                  "shortest": {"distance_m": short["distance_m"], "shaded_pct": short["shaded_pct"],
                               "exposure": short["exposure"], "path": short["xy"]},
                  "exposure_saved_pct": saved}
        self.last_route = result
        self.send(m.sender, "INFORM", result, m.conversation_id, m.msg_id)

    # ----------------------------------------------------------- cost model
    def _stress(self, e):
        hi = self.zone_hi_f.get(e["zone"], DEFAULT_HI_F)
        hi_eff = hi + hm.SUN_ADD_F * (1.0 - e["shade"])      # sun penalty shrinks with shade
        return float(hm.env_stress(hi_eff))

    def _edge_cost(self, e, heat_aware):
        if not heat_aware:
            return e["length"]
        return e["length"] * (1.0 + HEAT_WEIGHT * self._stress(e))

    # ------------------------------------------------------------------ A*
    def plan(self, a, b, heat_aware=True):
        """A* search, traced as one tool call."""
        ins = {"heat_aware": heat_aware, "from_x": round(float(self.map.xy[a][0]), 1),
               "from_y": round(float(self.map.xy[a][1]), 1), "to_x": round(float(self.map.xy[b][0]), 1),
               "to_y": round(float(self.map.xy[b][1]), 1)}
        with tracing.span("route.astar", "tool", inputs=ins) as sp:
            out = self._plan(a, b, heat_aware)
            if out is None:
                sp.set(result="no_path")
            else:
                sp.set(distance_m=out["distance_m"], eta_min=out["eta_min"], shaded_pct=out["shaded_pct"],
                       exposure=out["exposure"])
        return out

    def _plan(self, a, b, heat_aware=True):
        m = self.map
        goal = m.xy[b]
        open_heap = [(0.0, a)]
        best_cost = {a: 0.0}
        parent = {}
        while open_heap:
            _, cur = heapq.heappop(open_heap)
            if cur == b:
                break
            for nxt, e in m.adj[cur].items():
                new = best_cost[cur] + self._edge_cost(e, heat_aware)
                if new < best_cost.get(nxt, float("inf")):
                    best_cost[nxt] = new
                    parent[nxt] = cur
                    h = 0.99 * math.hypot(goal[0] - m.xy[nxt][0], goal[1] - m.xy[nxt][1])   # admissible
                    heapq.heappush(open_heap, (new + h, nxt))
        if b != a and b not in parent:
            return None
        nodes = [b]
        while nodes[-1] != a:
            nodes.append(parent[nodes[-1]])
        nodes.reverse()
        return self._summarise(nodes)

    def _summarise(self, nodes):
        dist = expo = shaded = 0.0
        xy = [tuple(float(v) for v in self.map.xy[nodes[0]])]
        for u, v in zip(nodes, nodes[1:]):
            e = self.map.adj[u][v]
            dist += e["length"]
            shaded += e["length"] * e["shade"]
            if self.zone_hi_f:
                expo += e["length"] * self._stress(e)
            xy.extend(e["pts"][1:])
        return {"nodes": nodes, "xy": xy, "distance_m": round(dist),
                "eta_min": round(dist / WALK_M_PER_MIN, 1),
                "shaded_pct": round(100.0 * shaded / dist) if dist else 0,
                "exposure": round(expo, 1)}
