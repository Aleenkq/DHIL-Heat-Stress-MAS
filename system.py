"""system.py -- DHIL orchestrator: builds the agents, runs the simulation loop, exposes state for the UI."""
import math
import health_model as hm
import tracing
from messages import MessageBus
from heat_agent import HeatAgent
from health_agent import HealthAgent
from resource_agent import ResourceAgent, StationAgent, settle
from route_agent import RouteAgent, WALK_M_PER_MIN
from prevention_agent import PreventionAgent

REFRESH_EVERY = 6          # steps between live weather refreshes (6 x 5 min = 30 min)
POLL_EVERY = 2             # steps between Prevention -> Health risk polls (2 x 5 min)
REST_STEPS = 3             # steps a pilgrim stays at a rest / cooling point (15 min)
COOLING_DROP_F = 20.0      # apparent-heat reduction inside a misting / cooling tent (assumption)
MIN_REST_CREDIT_MIN = 10   # a rest ended early only counts when it lasted at least this long
OBEY_FROM = ("WARNING", "URGENT", "EMERGENCY")

DEFAULT_PROFILE = {"age": 62, "sex": 1, "bmi": 29.0, "has_cardiac": 0, "has_diabetes": 1,
                   "has_respiratory": 0, "acclimatized": 0,
                   "fatigue": 15, "minutes_since_water": 30, "minutes_since_rest": 30, "exposure": 0}


class DHILSystem:
    def __init__(self, profile=None, start=None, hour=13.0, fetcher=None,
                 model_path="health_model.joblib", cache_file="heat_cache.json"):
        self.bus = MessageBus()
        self.route = RouteAgent(self.bus)
        start = start or self.route.map.start_xy()
        self.heat = HeatAgent(self.bus, receivers=("route", "prevention"), fetcher=fetcher,
                              cache_file=cache_file)
        self.resource = ResourceAgent(self.bus)
        self.stations = []
        for name, need, pos, cap, queue in self.route.map.station_sites():
            st = StationAgent(self.bus, name, need, pos, self.route.map.zone_at(pos), cap, queue)
            self.resource.add_station(st)
            self.stations.append(st)
        directory = {s.name: s.pos for s in self.stations}
        self.prevention = PreventionAgent(self.bus, directory, location=start)
        self.health = HealthAgent(self.bus, profile or DEFAULT_PROFILE, model_path=model_path)
        # agents that react to messages only (ticked inside settle); heat and health are
        # ticked explicitly because they need the environment as input
        self.reactive = [self.prevention, self.resource, self.route] + self.stations
        self.pos = tuple(start)
        self.hour = hour
        self.t = 0
        self.walking = True
        self.following = False
        self.path = []
        self.target_need = None
        self.rest_left = 0
        self.rest_total = 0
        self.rest_credit = False     # True while a rest is running that will reset the rest counter
        self.obey = False            # True = the simulated pilgrim follows serious advice automatically

    # ----------------------------------------------------------------- helpers
    @property
    def zone(self):
        return self.route.map.zone_at(self.pos)

    def in_shade(self):
        return self.route.map.shade_at(self.pos) >= 0.5 or self.rest_left > 0

    # -------------------------------------------------------------- user actions
    def follow_advice(self):
        """The pilgrim decides to follow the current advice (walk to the suggested point)."""
        adv = self.prevention.advice
        if adv.get("route") and adv.get("station"):
            self.path = list(adv["route"]["path"])
            self.target_need = adv["need"]
            self.following = True
            return True
        return False

    def user_action(self, action):
        self.prevention.user_action(action)

    # ------------------------------------------------------------------- resting
    def start_rest(self, minutes):
        """The pilgrim rests where they are for a chosen time. The rest counter resets only when it ends."""
        steps = max(1, round(minutes / hm.STEP_MIN))
        self.following, self.path, self.target_need = False, [], "rest"
        self.rest_left = self.rest_total = steps
        self.rest_credit = True
        return steps * hm.STEP_MIN

    def end_rest(self):
        """End a rest early. It counts only if it lasted at least MIN_REST_CREDIT_MIN. Returns minutes rested."""
        if self.rest_left <= 0:
            return 0
        done = (self.rest_total - self.rest_left) * hm.STEP_MIN
        self.rest_left = 0
        self.following = False
        self._finish_rest(done >= MIN_REST_CREDIT_MIN)
        return done

    def _finish_rest(self, credited):
        if self.rest_credit and credited:
            self.user_action("rest")
            if self.target_need == "medical":
                self.user_action("checked")
        self.rest_credit = False

    # --------------------------------------------------------------------- step
    def step(self):
        """One simulated step (5 minutes). One LangSmith trace per step when tracing is on."""
        inputs = {"minute": (self.t + 1) * hm.STEP_MIN, "zone": self.zone, "follows_advice": self.obey,
                  "weather": "manual" if self.heat.manual else "live", "pilgrim_age": self.health.profile["age"]}
        with tracing.span("dhil_step", "chain", inputs=inputs, root=True) as sp:
            snap = self._step()
            a, r = snap["advice"], snap["risk"] or {}
            msgs = [f"{m.performative} {m.sender}->{m.receiver}" + ("" if m.delivered else " [UNDELIVERED]")
                    for m in self.bus.log if m.step == snap["t"]][:40]
            sp.set(advice_level=a["level"], advice_code=a["code"], station=a.get("station"),
                   call_medic=a["call_medic"], risk_class=r.get("risk_class"), risk_score=r.get("risk_score"),
                   health_mode=r.get("mode"), agents_down=", ".join(n for n, s in snap["agents"].items() if s == "FAILED"),
                   messages=" | ".join(msgs))
        return snap

    def _step(self):
        self.t += 1
        self.bus.step = self.t
        if not self.heat.is_failed:
            self.heat.tick(self.hour, refresh=(self.t == 1 or self.t % REFRESH_EVERY == 0))
        cond = self.heat.zone_conditions(self.zone) if self.heat.base[0] is not None else None
        if cond is None:
            self.heat.tick(self.hour)
            cond = self.heat.zone_conditions(self.zone)
        if self.obey and not self.following and self.rest_left == 0 \
                and self.prevention.advice["level"] in OBEY_FROM:
            self.follow_advice()
        self._move()
        walking = self.walking and self.rest_left == 0
        hi_f = cond["hi_f"]
        if self.rest_left > 0 and self.target_need in ("cooling", "medical"):
            hi_f -= COOLING_DROP_F
        if not self.health.is_failed:
            self.health.tick(hi_f, self.in_shade(), walking)
        if self.t % POLL_EVERY == 0:
            self.prevention.poll_health()
        settle(self.reactive)
        self.hour += hm.STEP_MIN / 60.0
        return self.snapshot()

    def _move(self):
        if self.rest_left > 0:
            self.rest_left -= 1
            if self.rest_left == 0:
                self.following = False
                self._finish_rest(True)
            return
        if not self.following or not self.path:
            return
        budget = WALK_M_PER_MIN * hm.STEP_MIN
        while budget > 0 and self.path:
            nxt = self.path[0]
            d = math.hypot(nxt[0] - self.pos[0], nxt[1] - self.pos[1])
            if d <= budget:
                self.pos = tuple(nxt)
                self.path.pop(0)
                budget -= d
            else:
                break
        self.prevention.set_location(self.pos)
        if not self.path:                      # arrived
            need = self.target_need
            if need in ("water", "cooling", "medical"):
                self.user_action("water")           # drinking is instant; cooling and medical points give water
            if need in ("rest", "cooling", "medical"):
                self.rest_left = self.rest_total = REST_STEPS       # the rest counter resets when the rest ends
                self.rest_credit = True
            else:
                self.following = False

    # ----------------------------------------------------------------- snapshot
    def snapshot(self):
        h = self.health.last or {}
        return {"t": self.t, "hour": round(self.hour % 24, 2), "pos": self.pos, "zone": self.zone,
                "rest_left_min": self.rest_left * hm.STEP_MIN, "risk": h, "health_stale": self.health.is_failed, "advice": self.prevention.advice,
                "heat": self.heat.last, "heat_mode": self.heat.mode,
                "agents": {a.name: ("FAILED" if a.is_failed else a.status)
                           for a in [self.heat, self.health, self.prevention, self.resource, self.route] + self.stations}}
