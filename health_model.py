"""
health_model.py -- DHIL shared heat-stress model (single source of truth for
data generation AND the runtime Health Agent).

NOTE: the structure follows Hajj heat-illness literature and NWS heat-index bands;
the numeric weights are team ASSUMPTIONS, not fitted to real patient data.
Output is a simulated preventive-alert indicator, NOT a clinical diagnosis.
"""
import numpy as np

STEP_MIN = 5
SUN_ADD_F = 12.5              # sun adds ~10-15 F on top of the shade-based heat index
EXPOSURE_THRESHOLD_C = 32.2   # 90 F: NWS "Extreme Caution" starts
EXPOSURE_TAU_MIN = 60.0
EXPOSURE_NORM = 600.0
WATER_CAP_MIN = 240
REST_CAP_MIN = 240

# ASSUMPTION (team-defined): class cut-offs on the 0-100 risk score are our own design
# choice for the simulation. They are NOT official NWS categories.
CLASS_CUTS = (30.0, 50.0, 70.0)          # Low | Moderate | High | Critical
SATURATION_K = 1.6                       # smooth saturation (avoids hard clipping at 100)
CLASS_NAMES = ["Low", "Moderate", "High", "Critical"]
HIGH_THRESHOLD = CLASS_CUTS[1]


def heat_index_f(temp_c, rh):
    """NWS heat index (F) -- Rothfusz regression + NWS adjustments."""
    t = np.asarray(temp_c, dtype=float) * 9.0 / 5.0 + 32.0
    r = np.asarray(rh, dtype=float)

    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + r * 0.094)
    avg = 0.5 * (simple + t)

    hi = (-42.379 + 2.04901523 * t + 10.14333127 * r - 0.22475541 * t * r
          - 0.00683783 * t * t - 0.05481717 * r * r + 0.00122874 * t * t * r
          + 0.00085282 * t * r * r - 0.00000199 * t * t * r * r)

    adj_dry = ((13.0 - r) / 4.0) * np.sqrt(np.clip((17.0 - np.abs(t - 95.0)) / 17.0, 0, None))
    hi = np.where((r < 13) & (t >= 80) & (t <= 112), hi - adj_dry, hi)
    adj_wet = ((r - 85.0) / 10.0) * ((87.0 - t) / 5.0)
    hi = np.where((r > 85) & (t >= 80) & (t <= 87), hi + adj_wet, hi)

    # regression is not valid beyond Steadman's range -> cap at 140 F
    return np.minimum(np.where(avg >= 80.0, hi, simple), 140.0)


def heat_index_c(temp_c, rh):
    return (heat_index_f(temp_c, rh) - 32.0) * 5.0 / 9.0


def effective_heat_f(hi_f, in_shade):
    return hi_f + np.where(np.asarray(in_shade) >= 1, 0.0, SUN_ADD_F)


def env_stress(hi_f_eff):
    """0 at 80 F (start of NWS 'Caution') .. 1 at 125 F ('Extreme Danger')."""
    return np.clip((hi_f_eff - 80.0) / 45.0, 0.0, 1.5)


def vulnerability(age, cardiac, diabetes, respiratory, acclimatized, bmi):
    age = np.asarray(age, dtype=float)
    bmi = np.asarray(bmi, dtype=float)
    return (1.0
            + 0.012 * np.clip(age - 40.0, 0, None)
            + 0.15 * np.asarray(cardiac)
            + 0.12 * np.asarray(diabetes)
            + 0.10 * np.asarray(respiratory)
            + 0.10 * (1 - np.asarray(acclimatized))
            + 0.08 * (bmi >= 30)
            + 0.05 * (bmi >= 35))


def step_state(fatigue, minutes_since_water, minutes_since_rest, exposure,
               age, bmi, hi_f, in_shade, walking):
    """Advance the dynamic pilgrim state by one step (5 minutes)."""
    walking = np.asarray(walking).astype(bool)
    shade = np.asarray(in_shade) >= 1
    hi_eff = effective_heat_f(hi_f, in_shade)
    e = env_stress(hi_eff)

    age_factor = 1.0 + np.clip(age - 40.0, 0, None) / 100.0
    obesity_factor = 1.0 + 0.10 * (np.asarray(bmi) >= 30)
    gain = 1.2 * (1.0 + e) * age_factor * obesity_factor
    recovery = np.where(shade, 4.0, 2.0)
    fatigue = np.clip(fatigue + np.where(walking, gain, -recovery), 0.0, 100.0)

    minutes_since_water = np.minimum(WATER_CAP_MIN, minutes_since_water + STEP_MIN)
    minutes_since_rest = np.where(
        walking, np.minimum(REST_CAP_MIN, minutes_since_rest + STEP_MIN),
        np.where(shade, 0.0, minutes_since_rest))

    hi_eff_c = (hi_eff - 32.0) * 5.0 / 9.0
    excess = np.clip(hi_eff_c - EXPOSURE_THRESHOLD_C, 0.0, None)
    exposure = exposure * np.exp(-STEP_MIN / EXPOSURE_TAU_MIN) + excess * STEP_MIN

    return fatigue, minutes_since_water, minutes_since_rest, exposure


def latent_risk(age, cardiac, diabetes, respiratory, acclimatized, bmi,
                fatigue, minutes_since_water, minutes_since_rest, exposure,
                hi_f, in_shade):
    """Reference risk score 0..100 (also the rule-based fallback of the Health Agent)."""
    e = env_stress(effective_heat_f(hi_f, in_shade))
    f = np.asarray(fatigue) / 100.0
    d = np.clip(np.asarray(minutes_since_water) / 180.0, 0, 1)
    x = np.clip(np.asarray(exposure) / EXPOSURE_NORM, 0, 1)
    r = np.clip(np.asarray(minutes_since_rest) / 120.0, 0, 1)
    inner = 0.30 + 0.30 * f + 0.25 * d + 0.25 * x + 0.10 * r
    v = vulnerability(age, cardiac, diabetes, respiratory, acclimatized, bmi)
    raw = e * inner * v
    # smooth saturation: in extreme heat the score keeps responding to
    # shade / water / rest instead of being stuck at 100
    return 100.0 * (1.0 - np.exp(-SATURATION_K * raw))

def risk_to_class(score):
    return np.digitize(score, CLASS_CUTS)
