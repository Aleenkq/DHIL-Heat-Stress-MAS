"""prevention_agent.py -- Prevention Agent: rule-based advisor and coordinator.

It turns the Health Agent's risk assessment into one clear action for the pilgrim and
coordinates the other agents to make that action possible:
    risk -> RULE -> need (water / rest / cooling)
         -> REQUEST resource   (Contract Net inside the Resource Agent)
         -> REQUEST route      (heat-aware A* inside the Route Agent)
         -> advice for the pilgrim

The rules are kept in ONE table (RULES) so health specialists can review them, as
stated in the Business Model Canvas. Thresholds are team assumptions, not clinical values.
If the Health Agent is unreachable the agent degrades to heat-band-only rules.
"""
import tracing
from messages import BaseAgent, Message

LEVELS = ["OK", "INFO", "ATTENTION", "WARNING", "URGENT", "EMERGENCY"]
WATER_DUE_MIN = 45             # minutes without water that trigger a reminder (assumption)
WATER_OVERDUE_MIN = 90         # reminder even at low risk (assumption)
EARLY_WARNING_MIN = 30         # predicted minutes to "High" that trigger an early warning (assumption)

# (code, level, need, text, condition(ctx)). The FIRST matching rule wins.
RECOVER_AFTER_MIN = 30        # minutes a symptom alert stays on before "I feel better" can clear it

RULES = [
    ("SYMPTOMS", "EMERGENCY", "medical",
     "You reported symptoms. Stop now, go to the nearest medical point to be checked, and call a medic.",
     lambda c: c["symptoms"]),
    ("CRITICAL", "URGENT", "cooling",
     "Heat-stress risk is critical. Stop walking and go to the nearest cooling point.",
     lambda c: c["health_up"] and c["cls"] == "Critical"),
    ("HIGH", "WARNING", "rest",
     "Heat-stress risk is high. Rest in the shade and drink water.",
     lambda c: c["health_up"] and c["cls"] == "High"),
    ("EARLY", "ATTENTION", "rest",
     "Your risk is rising. Take a shaded rest soon.",
     lambda c: c["health_up"] and c["ttr"] is not None and c["ttr"] <= EARLY_WARNING_MIN),
    ("WATER", "ATTENTION", "water",
     "Time to drink water.",
     lambda c: c["health_up"] and ((c["cls"] != "Low" and c["msw"] >= WATER_DUE_MIN)
                                   or c["msw"] >= WATER_OVERDUE_MIN)),
    ("MODERATE", "INFO", None,
     "Moderate risk. Keep drinking regularly and prefer shaded paths.",
     lambda c: c["health_up"] and c["cls"] == "Moderate"),
    # degraded mode: Health Agent unavailable -> use the heat band only
    ("DEGRADED_DANGER", "WARNING", "rest",
     "Health monitoring is unavailable and the heat is dangerous. Rest in the shade and drink water.",
     lambda c: (not c["health_up"]) and c["band"] in ("Danger", "Extreme Danger")),
    ("DEGRADED_HOT", "ATTENTION", "water",
     "Health monitoring is unavailable and it is hot. Drink water and avoid direct sun.",
     lambda c: (not c["health_up"]) and c["band"] == "Extreme Caution"),
    ("DEGRADED", "INFO", None,
     "Health monitoring is unavailable. Follow general heat precautions.",
     lambda c: not c["health_up"]),
    ("OK", "OK", None, "You are doing fine. Keep hydrated.", lambda c: True),
]


class PreventionAgent(BaseAgent):
    def __init__(self, bus, directory, pilgrim_id="P1", location=(100.0, 100.0)):
        super().__init__("prevention", bus)
        self.directory = dict(directory)      # station name -> (x, y)
        self.pilgrim_id = pilgrim_id
        self.location = tuple(location)
        self.risk = None                      # last risk_update content
        self.heat = None                      # last heat_update content
        self.health_up = True
        self.symptoms = False
        self.symptoms_step = None             # simulation step when symptoms were reported
        self.recovery_note = None             # why "I feel better" was not accepted yet
        self.rule_code = None
        self.open_reqs = {}                   # request msg_id -> ("resource"|"route", need)
        self.assigned = None                  # resource_assigned content
        self.route = None                     # route_ready content
        self.fail_note = None
        self.advice = {"level": "OK", "code": "OK", "text": "Waiting for data.", "need": None}
        self.history = []

    # ---------------------------------------------------------------- public API
    def poll_health(self):
        """Ask the Health Agent for a fresh report; an undelivered message = Health Agent down."""
        m = self.send("health", "REQUEST", {"event": "risk_report"}, "risk-poll")
        if not m.delivered and self.health_up:
            self.health_up = False
            self._evaluate()                  # switch to degraded rules immediately
        return m.delivered

    def set_location(self, xy):
        self.location = tuple(xy)

    def user_action(self, action):
        """Pilgrim actions coming from the UI: water / rest / symptoms / recovered."""
        self.bus.send(Message("ui", self.name, "INFORM",
                              {"event": "user_action", "action": action}))

    # ---------------------------------------------------------------------- loop
    def tick(self):
        changed = False
        for m in self.read_inbox():
            ev = m.content.get("event")
            if m.performative == "INFORM" and ev == "risk_update":
                self.risk, self.health_up, changed = m.content, True, True
            elif m.performative == "INFORM" and ev == "heat_update":
                self.heat, changed = m.content, True
            elif m.performative == "INFORM" and ev == "user_action":
                changed |= self._on_user_action(m.content["action"])
            elif m.performative == "INFORM" and ev == "resource_assigned":
                self.open_reqs.pop(m.in_reply_to, None)
                self.assigned, self.fail_note, changed = m.content, None, True
                self._request_route(m.content["station"])
            elif m.performative == "FAILURE" and ev == "resource_unavailable":
                self.open_reqs.pop(m.in_reply_to, None)
                self.fail_note, changed = f"no {m.content['need']} point available", True
            elif m.performative == "INFORM" and ev == "route_ready":
                self.open_reqs.pop(m.in_reply_to, None)
                self.route, changed = m.content, True
            elif m.performative == "FAILURE" and ev == "route_failed":
                self.open_reqs.pop(m.in_reply_to, None)
                self.route, changed = None, True
        if changed:
            self._evaluate()
        self.status = f"{self.advice['level']} / {self.advice['code']}"

    # ------------------------------------------------------------------- internals
    def _recovery_blocker(self):
        """None when "I feel better" may clear the symptom alert, otherwise the reason it cannot yet."""
        waited = (self.bus.step - (self.symptoms_step or 0)) * 5
        cls = (self.risk or {}).get("risk_class")
        if waited < RECOVER_AFTER_MIN:
            return (f"Your symptom alert stays on. Go to a medical point to be checked, or wait until "
                    f"{RECOVER_AFTER_MIN} minutes after the report ({RECOVER_AFTER_MIN - waited} min left).")
        if not (self.health_up and self.risk is not None):
            return "Your symptom alert stays on: the risk estimate is not available, so please get checked."
        if cls in ("High", "Critical"):
            return f"Your symptom alert stays on: your estimated heat risk is still {cls}. Go to a medical point."
        return None

    def _on_user_action(self, action):
        if action == "symptoms":
            self.symptoms, self.symptoms_step, self.recovery_note = True, self.bus.step, None
        elif action == "checked":              # the pilgrim was seen at a medical point
            self.symptoms, self.symptoms_step, self.recovery_note = False, None, None
        elif action == "recovered":
            if self.symptoms:
                reason = self._recovery_blocker()
                if reason:                     # a serious alert is not cancelled by one button press
                    self.recovery_note = reason
                    return True
                self.symptoms, self.symptoms_step = False, None
            self.recovery_note = None
        elif action == "water":
            self.send("health", "INFORM", {"event": "water_intake_completed"}, "user-action")
        elif action == "rest":
            self.send("health", "INFORM", {"event": "rest_completed"}, "user-action")
        self.assigned = self.route = self.fail_note = None
        self.rule_code = None                  # start a fresh episode
        return True

    def _context(self):
        r = self.risk or {}
        return {"symptoms": self.symptoms, "health_up": self.health_up and self.risk is not None,
                "cls": r.get("risk_class"), "ttr": r.get("time_to_high_min"),
                "msw": r.get("minutes_since_water", 0.0),
                "band": (self.heat or {}).get("worst_band", "Safe")}

    def _evaluate(self):
        with tracing.span("prevention.rules", "chain", inputs=tracing.plain(self._context())) as sp:
            self._evaluate_rules()
            a = self.advice
            sp.set(rule=a["code"], level=a["level"], need=a["need"], station=a.get("station"),
                   call_medic=a["call_medic"])

    def _evaluate_rules(self):
        ctx = self._context()
        code, level, need, text = next((c, l, n, t) for c, l, n, t, cond in RULES if cond(ctx))
        if code != self.rule_code:             # new situation -> forget the old plan
            self.rule_code = code
            self.assigned = self.route = self.fail_note = None
            self.open_reqs = {}
            if need:
                m = self.send("resource", "REQUEST",
                              {"need": need, "location": self.location, "pilgrim_id": self.pilgrim_id},
                              "prevention-plan")
                self.open_reqs[m.msg_id] = ("resource", need)
                if not m.delivered:
                    self.fail_note = "resource service unreachable"
        if self.fail_note and LEVELS.index(level) < LEVELS.index("URGENT") and need:
            level = LEVELS[LEVELS.index(level) + 1]      # conservative: escalate one level
        self.advice = {"level": level, "code": code, "text": text, "need": need,
                       "station": (self.assigned or {}).get("station"),
                       "eta_min": (self.assigned or {}).get("eta_min"),
                       "at_station": bool(self.assigned) and self.assigned.get("distance_m", 999) <= 100,
                       "route": self.route, "note": self.fail_note,
                       "health_up": ctx["health_up"], "recovery_note": self.recovery_note,
                       "call_medic": level in ("URGENT", "EMERGENCY") or
                                     (bool(self.fail_note) and level in ("WARNING", "URGENT", "EMERGENCY"))}
        self.history.append((self.bus.step, code, level))

    def _request_route(self, station):
        dest = self.directory.get(station)
        if dest is None:
            return
        m = self.send("route", "REQUEST",
                      {"origin": self.location, "dest": dest, "pilgrim_id": self.pilgrim_id},
                      "prevention-plan")
        self.open_reqs[m.msg_id] = ("route", station)
