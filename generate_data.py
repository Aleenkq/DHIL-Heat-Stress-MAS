"""
generate_data.py  --  builds the synthetic training set for the DHIL Health Agent
===============================================================================
Method (simulation-based, not random columns):
  1. Sample virtual pilgrims (profile) and a weather day (Makkah-like range).
  2. Simulate each pilgrim walking for up to 3 hours with the SAME dynamics the
     runtime Health Agent uses (health_model.step_state).
  3. Take random snapshots of the state -> features.
  4. Label each snapshot:
       risk_class  : from the reference risk score (+ small Gaussian noise)
       ttr_min     : minutes until the score reaches 'High' if the pilgrim keeps
                     walking, same weather, same shade, no water  (rollout).
                     Censored at 120 min.

Run:  python generate_data.py            (writes data/health_dataset.csv)
"""
import argparse
import numpy as np
import pandas as pd
import health_model as hm

TRIP_STEPS = 36            # 36 x 5 min = 3 hours
TTR_HORIZON_STEPS = 24     # 24 x 5 min = 120 minutes
LABEL_NOISE_SD = 3.5       # label noise (score points)

FEATURES = [
    "age", "sex", "bmi", "has_cardiac", "has_diabetes", "has_respiratory",
    "acclimatized", "fatigue", "minutes_since_water", "minutes_since_rest",
    "cumulative_heat_exposure", "heat_index_c", "in_shade",
]


# --------------------------------------------------------------- sampling
def sample_profiles(rng, n):
    """Pilgrim profiles. Distributions are assumptions (documented in report):
    skewed to older ages; comorbidity prevalence grows with age."""
    age = np.clip(rng.normal(55, 14, n), 18, 85).round()
    sex = rng.integers(0, 2, n)                              # 0 = female, 1 = male
    bmi = np.clip(rng.normal(27.5, 5.0, n), 17, 45).round(1)
    over30 = np.clip(age - 30, 0, None)
    cardiac = (rng.random(n) < np.clip(0.05 + 0.006 * over30, 0, 0.45)).astype(int)
    diabetes = (rng.random(n) < np.clip(0.04 + 0.004 * over30, 0, 0.30)).astype(int)
    respiratory = (rng.random(n) < 0.07).astype(int)
    acclimatized = (rng.random(n) < 0.35).astype(int)        # most pilgrims arrive from abroad
    return age, sex, bmi, cardiac, diabetes, respiratory, acclimatized


def sample_weather_day(rng, n):
    """Per-pilgrim day: Makkah-like range (cool season .. hot season)."""
    tmax = rng.uniform(28, 46, n)
    tmin = tmax - rng.uniform(8, 14, n)
    # hotter days are drier in Makkah-like climates (assumption)
    rh_day = np.clip(rng.uniform(10, 60, n) - 0.8 * (tmax - 30), 8, 60)
    start_hour = rng.uniform(6, 17, n)
    return tmax, tmin, rh_day, start_hour


def weather_at(hour, tmax, tmin, rh_day):
    """Diurnal curve: peak ~13:00, RH lower when hotter."""
    shape = np.clip(np.sin(np.pi * (hour - 6.0) / 14.0), 0, 1)
    temp = tmin + (tmax - tmin) * shape
    rh = np.clip(rh_day * (1.5 - 0.5 * shape), 5, 95)
    return temp, rh


# -------------------------------------------------------------- simulation
def simulate(n_pilgrims, seed):
    rng = np.random.default_rng(seed)
    age, sex, bmi, card, diab, resp, acc = sample_profiles(rng, n_pilgrims)
    tmax, tmin, rh_day, hour0 = sample_weather_day(rng, n_pilgrims)

    fatigue = rng.uniform(0, 35, n_pilgrims)
    msw = rng.uniform(0, 90, n_pilgrims)
    msr = rng.uniform(0, 60, n_pilgrims)
    expo = rng.uniform(0, 250, n_pilgrims)
    shade = (rng.random(n_pilgrims) < 0.3).astype(int)

    traj = {k: [] for k in ["fatigue", "msw", "msr", "expo", "shade", "temp", "rh", "hi_f"]}
    for s in range(TRIP_STEPS):
        hour = hour0 + s * hm.STEP_MIN / 60.0
        temp, rh = weather_at(hour, tmax, tmin, rh_day)
        hi_f = hm.heat_index_f(temp, rh)

        # behaviour of the virtual pilgrim this step
        p_walk = np.clip(0.85 - 0.50 * fatigue / 100.0, 0.25, 0.90)
        walking = rng.random(n_pilgrims) < p_walk
        # shade as a 2-state Markov chain (~30% of the route is shaded)
        flip_to_shade = (shade == 0) & (rng.random(n_pilgrims) < 0.10)
        flip_to_sun = (shade == 1) & (rng.random(n_pilgrims) < 0.25)
        shade = np.where(flip_to_shade, 1, np.where(flip_to_sun, 0, shade))
        # drinking: more likely once thirsty
        p_drink = np.where(msw > 90, 0.15, 0.03)
        msw = np.where(rng.random(n_pilgrims) < p_drink, 0.0, msw)

        fatigue, msw, msr, expo = hm.step_state(
            fatigue, msw, msr, expo, age, bmi, hi_f, shade, walking)

        for k, v in zip(traj.keys(), [fatigue, msw, msr, expo, shade, temp, rh, hi_f]):
            traj[k].append(np.array(v, copy=True))

    traj = {k: np.stack(v) for k, v in traj.items()}      # shape (steps, pilgrims)
    return dict(age=age, sex=sex, bmi=bmi, card=card, diab=diab, resp=resp,
                acc=acc), traj, rng


def time_to_high(prof, snap, hi_f):
    """Rollout: keep walking, same weather/shade, no water. Returns minutes
    until risk >= HIGH threshold (0 if already there), censored at horizon."""
    n = len(hi_f)
    fat, msw, msr, expo = snap["fatigue"].copy(), snap["msw"].copy(), snap["msr"].copy(), snap["expo"].copy()
    shade = snap["shade"]
    ttr = np.full(n, np.nan)

    def risk_now():
        return hm.latent_risk(prof["age"], prof["card"], prof["diab"], prof["resp"],
                              prof["acc"], prof["bmi"], fat, msw, msr, expo, hi_f, shade)

    ttr[risk_now() >= hm.HIGH_THRESHOLD] = 0.0
    for step in range(1, TTR_HORIZON_STEPS + 1):
        fat, msw, msr, expo = hm.step_state(
            fat, msw, msr, expo, prof["age"], prof["bmi"], hi_f, shade, np.ones(n, bool))
        crossed = np.isnan(ttr) & (risk_now() >= hm.HIGH_THRESHOLD)
        ttr[crossed] = step * hm.STEP_MIN
    censored = np.isnan(ttr)
    ttr[censored] = TTR_HORIZON_STEPS * hm.STEP_MIN
    return ttr, censored.astype(int)


def build_dataset(n_pilgrims=10000, snaps_per_pilgrim=2, seed=42):
    prof, traj, rng = simulate(n_pilgrims, seed)
    rows = []
    for j in range(snaps_per_pilgrim):
        idx = rng.integers(0, TRIP_STEPS, n_pilgrims)
        pil = np.arange(n_pilgrims)
        snap = {k: traj[k][idx, pil] for k in ["fatigue", "msw", "msr", "expo", "shade", "temp", "rh", "hi_f"]}

        score = hm.latent_risk(prof["age"], prof["card"], prof["diab"], prof["resp"],
                               prof["acc"], prof["bmi"], snap["fatigue"], snap["msw"],
                               snap["msr"], snap["expo"], snap["hi_f"], snap["shade"])
        noisy = np.clip(score + rng.normal(0, LABEL_NOISE_SD, n_pilgrims), 0, 100)
        ttr, cens = time_to_high(prof, snap, snap["hi_f"])

        df = pd.DataFrame({
            "pilgrim_id": pil,
            "age": prof["age"], "sex": prof["sex"], "bmi": prof["bmi"],
            "has_cardiac": prof["card"], "has_diabetes": prof["diab"],
            "has_respiratory": prof["resp"], "acclimatized": prof["acc"],
            "fatigue": snap["fatigue"].round(2),
            "minutes_since_water": snap["msw"].round(1),
            "minutes_since_rest": snap["msr"].round(1),
            "cumulative_heat_exposure": snap["expo"].round(2),
            "heat_index_c": ((snap["hi_f"] - 32) * 5 / 9).round(2),
            "in_shade": snap["shade"],
            "air_temp_c": snap["temp"].round(1), "humidity_pct": snap["rh"].round(1),
            "risk_score": noisy.round(2),
            "risk_class": hm.risk_to_class(noisy),
            "ttr_min": ttr, "ttr_censored": cens,
        })
        rows.append(df)
    out = pd.concat(rows, ignore_index=True)
    out["risk_class_name"] = out["risk_class"].map(dict(enumerate(hm.CLASS_NAMES)))
    out["ttr_bucket"] = pd.cut(out["ttr_min"], [-1, 0, 15, 30, 60, 1e9],
                               labels=["now", "<=15", "15-30", "30-60", ">60"]).astype(str)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilgrims", type=int, default=10000)
    ap.add_argument("--snaps", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/health_dataset.csv")
    a = ap.parse_args()
    df = build_dataset(a.pilgrims, a.snaps, a.seed)
    df.to_csv(a.out, index=False)
    print(f"saved {len(df)} rows -> {a.out}")
    print("\nrisk class distribution (%):")
    print((df["risk_class_name"].value_counts(normalize=True) * 100).round(1).reindex(hm.CLASS_NAMES))
    print("\ntime-to-High bucket distribution (%):")
    print((df["ttr_bucket"].value_counts(normalize=True) * 100).round(1))
