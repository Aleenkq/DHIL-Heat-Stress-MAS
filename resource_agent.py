"""resource_agent.py -- Resource Agent + service stations (Contract-Net negotiation).

Flow (FIPA Contract-Net style):
  requester --REQUEST--> resource
  resource  --CFP------> every station that offers the need
  station   --PROPOSE / REFUSE--> resource
  resource  --ACCEPT---> best proposal (lowest cost = walk time + queue time)
  station   --INFORM (reserved) / REFUSE (taken meanwhile)--> resource
  resource  --INFORM (assigned) / FAILURE (nothing available)--> requester
"""
import itertools
import math
import tracing
from messages import BaseAgent

WALK_M_PER_MIN = 80.0          # ~4.8 km/h, slow pilgrim pace (assumption)
NEEDS = ("water", "rest", "cooling")
_conv = itertools.count(1)


def dist_m(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


class StationAgent(BaseAgent):
    """A physical service point: water point, shaded rest area, cooling/misting tent."""

    def __init__(self, bus, name, need, pos, zone, capacity=10, queue_min=0.0):
        super().__init__(name, bus)
        self.need, self.pos, self.zone = need, pos, zone
        self.capacity = capacity          # free places / units right now
        self.queue_min = queue_min        # current waiting time (min)
        self.closed = False
        self.status = f"{need}: {capacity} free"

    def tick(self):
        for m in self.read_inbox():
            if m.performative == "CFP":
                self._on_cfp(m)
            elif m.performative == "ACCEPT":
                self._on_accept(m)
        self.status = "CLOSED" if self.closed else f"{self.need}: {self.capacity} free, wait {self.queue_min:.0f} min"

    def _on_cfp(self, m):
        c = m.content
        if self.closed:
            self.send(m.sender, "REFUSE", {"reason": "closed"}, m.conversation_id, m.msg_id)
        elif self.capacity <= 0:
            self.send(m.sender, "REFUSE", {"reason": "full"}, m.conversation_id, m.msg_id)
        else:
            d = dist_m(self.pos, c["location"])
            self.send(m.sender, "PROPOSE",
                      {"station": self.name, "need": self.need, "distance_m": round(d),
                       "queue_min": self.queue_min, "free": self.capacity},
                      m.conversation_id, m.msg_id)

    def _on_accept(self, m):
        if not self.closed and self.capacity > 0:
            self.capacity -= 1
            self.send(m.sender, "INFORM", {"event": "reserved", "station": self.name},
                      m.conversation_id, m.msg_id)
        else:      # somebody else took the last place meanwhile -> conflict
            self.send(m.sender, "REFUSE", {"reason": "taken_meanwhile", "station": self.name},
                      m.conversation_id, m.msg_id)


class ResourceAgent(BaseAgent):
    def __init__(self, bus):
        super().__init__("resource", bus)
        self.stations = {}        # name -> StationAgent (registry only: knowledge of who exists)
        self.pending = {}         # conv_id -> negotiation state
        self.done = []            # finished negotiations (for the UI / report)

    def add_station(self, st):
        self.stations[st.name] = st

    def tick(self):
        for m in self.read_inbox():
            if m.performative == "REQUEST":
                self._start(m)
            elif m.performative in ("PROPOSE", "REFUSE", "INFORM"):
                self._on_station_reply(m)
        self.status = f"{len(self.pending)} negotiation(s) open"

    # ---- start a negotiation
    def _start(self, m):
        c = m.content
        need = c.get("need")
        conv = f"neg-{next(_conv)}"
        targets = [s for s in self.stations.values() if s.need == need]
        self.pending[conv] = {"requester": m.sender, "request_id": m.msg_id, "need": need,
                              "location": c["location"], "pilgrim": c.get("pilgrim_id"),
                              "expected": {s.name for s in targets}, "proposals": [],
                              "refusals": {}, "chosen": None, "ranked": [], "accepted": False}
        if not targets:
            self._fail(conv, "no_station_for_need")
            return
        for s in targets:
            self.send(s.name, "CFP", {"need": need, "location": c["location"]}, conv)

    # ---- collect replies
    def _on_station_reply(self, m):
        st = self.pending.get(m.conversation_id)
        if st is None:
            return
        who = m.sender
        if st["chosen"] is None:                      # still in the bidding phase
            st["expected"].discard(who)
            if m.performative == "PROPOSE":
                st["proposals"].append(m.content)
            elif m.performative == "REFUSE":
                st["refusals"][who] = m.content.get("reason")
            if not st["expected"]:
                self._decide(m.conversation_id)
        else:                                          # answer to our ACCEPT
            if m.performative == "INFORM" and m.content.get("event") == "reserved":
                self._assign(m.conversation_id, who)
            elif m.performative == "REFUSE":
                st["refusals"][who] = m.content.get("reason")
                self._next_best(m.conversation_id)

    def on_idle(self):
        """Called when the bus is quiet: stations that never answered (down) are
        treated as 'no reply' and the negotiation goes on without them."""
        for conv, st in list(self.pending.items()):
            if st["chosen"] is None and st["expected"]:
                for who in st["expected"]:
                    st["refusals"][who] = "no_reply"
                st["expected"] = set()
                self._decide(conv)

    @staticmethod
    def _cost(p):
        return p["distance_m"] / WALK_M_PER_MIN + p["queue_min"]    # minutes

    def _decide(self, conv):
        st = self.pending[conv]
        ins = {"need": st["need"], "proposals": ", ".join(f"{p['station']}({self._cost(p):.1f} min)" for p in st["proposals"]),
               "refusals": ", ".join(f"{k}:{v}" for k, v in st["refusals"].items())}
        with tracing.span("resource.contract_net_decide", "chain", inputs=ins) as sp:
            st["ranked"] = sorted(st["proposals"], key=self._cost)
            self._next_best(conv)
            sp.set(chosen=st["chosen"], fallback_order=", ".join(p["station"] for p in st["ranked"]))

    def _next_best(self, conv):
        st = self.pending[conv]
        if not st["ranked"]:
            self._fail(conv, "all_stations_unavailable")
            return
        best = st["ranked"].pop(0)
        st["chosen"] = best["station"]
        st["chosen_proposal"] = best
        self.send(best["station"], "ACCEPT", {"need": st["need"]}, conv)

    def _assign(self, conv, station):
        st = self.pending.pop(conv)
        p = st["chosen_proposal"]
        result = {"event": "resource_assigned", "need": st["need"], "station": station,
                  "distance_m": p["distance_m"], "eta_min": round(self._cost(p), 1),
                  "pilgrim_id": st["pilgrim"], "refusals": st["refusals"]}
        self.done.append(result)
        self.send(st["requester"], "INFORM", result, conv, st["request_id"])

    def _fail(self, conv, reason):
        st = self.pending.pop(conv)
        result = {"event": "resource_unavailable", "need": st["need"], "reason": reason,
                  "pilgrim_id": st["pilgrim"], "refusals": st["refusals"]}
        self.done.append(result)
        self.send(st["requester"], "FAILURE", result, conv, st["request_id"])


def settle(agents, max_rounds=30):
    """Run agents until the bus is quiet (stand-in for the real-time loop)."""
    for _ in range(max_rounds):
        for a in agents:
            a.tick()
        if any(a.inbox for a in agents):
            continue
        for a in agents:
            if hasattr(a, "on_idle"):
                a.on_idle()
        if not any(a.inbox for a in agents):
            return


def default_stations(bus, resource):
    """Station layout on the schematic Haram map (meters). Team assumption, not surveyed data.
    water_* = Zamzam / water points, rest_* = shaded rest areas, cool_B = misting tent."""
    spec = [("water_A", "water", (425, 175), "Zone A", 20, 1.0),
            ("water_B", "water", (725, 175), "Zone B", 20, 3.0),
            ("water_C", "water", (725, 675), "Zone C", 20, 0.0),
            ("rest_A", "rest", (325, 325), "Zone A", 3, 0.0),
            ("rest_C", "rest", (775, 575), "Zone C", 15, 2.0),
            ("cool_B", "cooling", (875, 275), "Zone B", 10, 4.0)]
    out = []
    for name, need, pos, zone, cap, q in spec:
        s = StationAgent(bus, name, need, pos, zone, cap, q)
        resource.add_station(s)
        out.append(s)
    return out
