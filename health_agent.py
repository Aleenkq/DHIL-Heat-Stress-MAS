"""health_agent.py -- Health Agent: ML risk classifier + rule-based fallback."""
import numpy as np
import pandas as pd
import joblib
import health_model as hm
import tracing
from messages import BaseAgent

DEFAULT_MIDPOINTS = np.array([15.0, 40.0, 60.0, 85.0])
LOW_CONFIDENCE = 0.50          # below this -> escalate conservatively
TTR_HORIZON_STEPS = 24         # 24 x 5 min = 120 minutes


class HealthAgent(BaseAgent):
    def __init__(self, bus, profile, model_path="health_model.joblib",
                 prevention_name="prevention"):
        super().__init__("health", bus)
        self.profile = dict(profile)
        self.prevention = prevention_name
        self.fatigue = float(profile.get("fatigue", 10))
        self.msw = float(profile.get("minutes_since_water", 20))
        self.msr = float(profile.get("minutes_since_rest", 20))
        self.exposure = float(profile.get("exposure", 0))

        self.model, self.features, self.midpoints = None, None, DEFAULT_MIDPOINTS
        self.force_ml_failure = False          # switch used by the failure scenario
        try:
            bundle = joblib.load(model_path)
            self.model = bundle["model"]
            self.features = bundle["features"]
            self.midpoints = np.array(bundle.get("class_midpoints", DEFAULT_MIDPOINTS))
            self.mode = "ML"
        except Exception:
            self.mode = "RULES"
        self.last = None                       # last assessment (dict)
        self._last_sent = (None, None)         # (risk_class, mode)

    # ---------------------------------------------------------------- helpers
    def _row(self, fatigue, msw, msr, exposure, hi_f, shade):
        p = self.profile
        return {"age": p["age"], "sex": p["sex"], "bmi": p["bmi"],
                "has_cardiac": p["has_cardiac"], "has_diabetes": p["has_diabetes"],
                "has_respiratory": p["has_respiratory"], "acclimatized": p["acclimatized"],
                "fatigue": fatigue, "minutes_since_water": msw, "minutes_since_rest": msr,
                "cumulative_heat_exposure": exposure,
                "heat_index_c": (hi_f - 32.0) * 5.0 / 9.0, "in_shade": int(shade)}

    def _rule_scores(self, rows):
        df = pd.DataFrame(rows)
        return np.asarray(hm.latent_risk(
            df.age, df.has_cardiac, df.has_diabetes, df.has_respiratory, df.acclimatized,
            df.bmi, df.fatigue, df.minutes_since_water, df.minutes_since_rest,
            df.cumulative_heat_exposure, df.heat_index_c * 9 / 5 + 32, df.in_shade))

    def _ml_ok(self):
        return self.model is not None and not self.force_ml_failure and not self.is_failed

    def _predict(self, rows):
        """Traced wrapper around the prediction."""
        with tracing.span("health.predict", "tool", inputs={"rows": len(rows), **tracing.plain(rows[0])}) as sp:
            out = self._predict_impl(rows)
            sp.set(mode=out[3], risk_class=hm.CLASS_NAMES[int(out[0][0])], score=round(float(out[1][0]), 1))
        return out

    def _predict_impl(self, rows):
        """-> (class_idx[], score[], confidence[], mode). Falls back to rules on failure."""
        rule_score = self._rule_scores(rows)
        rule_cls = hm.risk_to_class(rule_score)
        if self._ml_ok():
            try:
                proba = self.model.predict_proba(pd.DataFrame(rows)[self.features])
                cls = proba.argmax(axis=1)
                score = proba @ self.midpoints
                conf = proba.max(axis=1)
                low = conf < LOW_CONFIDENCE                   # conservative escalation
                cls = np.where(low, np.maximum(cls, rule_cls), cls)
                score = np.where(low, np.maximum(score, rule_score), score)
                self.mode = "ML"
                return cls, score, conf, "ML"
            except Exception:
                pass
        self.mode = "RULES"
        return rule_cls, rule_score, np.ones(len(rows)), "RULES"

    # ------------------------------------------------------------- assessment
    def assess(self, hi_f, in_shade):
        row = self._row(self.fatigue, self.msw, self.msr, self.exposure, hi_f, in_shade)
        cls, score, conf, mode = self._predict([row])
        ttr = self.time_to_high(hi_f, in_shade)
        self.last = {"risk_class": hm.CLASS_NAMES[int(cls[0])], "risk_class_idx": int(cls[0]),
                     "risk_score": round(float(score[0]), 1), "confidence": round(float(conf[0]), 2),
                     "time_to_high_min": ttr, "mode": mode,
                     "fatigue": round(self.fatigue, 1), "minutes_since_water": self.msw,
                     "minutes_since_rest": self.msr, "exposure": round(self.exposure, 1)}
        self.status = f"{self.last['risk_class']} ({self.last['risk_score']}) [{mode}]"
        return self.last

    def time_to_high(self, hi_f, in_shade):
        """Rollout: keep walking, same weather/shade, no water. Minutes until 'High'.
        Returns 0 if already High+, or None if not reached within 120 minutes."""
        f, w, r, x = self.fatigue, self.msw, self.msr, self.exposure
        rows = [self._row(f, w, r, x, hi_f, in_shade)]
        for _ in range(TTR_HORIZON_STEPS):
            f, w, r, x = hm.step_state(f, w, r, x, self.profile["age"], self.profile["bmi"],
                                       hi_f, in_shade, True)
            rows.append(self._row(float(f), float(w), float(r), float(x), hi_f, in_shade))
        cls, _, _, _ = self._predict(rows)                 # one batched prediction
        hit = np.where(cls >= 2)[0]
        return int(hit[0] * hm.STEP_MIN) if len(hit) else None

    # ------------------------------------------------------------------- loop
    def tick(self, hi_f, in_shade, walking):
        """One simulation step: process messages, update state, assess, report."""
        for m in self.read_inbox():
            self._handle(m, hi_f, in_shade)
        self.fatigue, self.msw, self.msr, self.exposure = [
            float(v) for v in hm.step_state(self.fatigue, self.msw, self.msr, self.exposure,
                                            self.profile["age"], self.profile["bmi"],
                                            hi_f, in_shade, walking)]
        a = self.assess(hi_f, in_shade)
        key = (a["risk_class"], a["mode"])
        if key != self._last_sent:                         # report only on change
            self.send(self.prevention, "INFORM", {"event": "risk_update", **a},
                      conversation_id="risk-monitoring")
            self._last_sent = key
        return a

    def _handle(self, m, hi_f, in_shade):
        ev = m.content.get("event") or m.content.get("action")
        if m.performative == "INFORM" and ev == "water_intake_completed":
            self.msw = 0.0
        elif m.performative == "INFORM" and ev == "rest_completed":
            self.msr = 0.0
        elif m.performative == "REQUEST" and ev == "risk_report":
            a = self.assess(hi_f, in_shade)
            self.send(m.sender, "INFORM", {"event": "risk_update", **a},
                      conversation_id=m.conversation_id, in_reply_to=m.msg_id)
