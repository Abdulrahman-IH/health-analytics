"""
Collect the figures the slide deck needs from results/*.csv (written by
scripts/run_queries.py) into presentation/deck_data.json, so every number on a
slide traces back to a SQL query.

Run:  python presentation/prepare_deck_data.py && node presentation/build_deck.js
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "results"


def csv(name: str) -> pd.DataFrame:
    return pd.read_csv(R / f"{name}.csv")


def main() -> None:
    con = sqlite3.connect(ROOT / "data" / "hospital_operations.db")
    d: dict = {}

    # ---- 01 occupancy
    occ = csv("01_daily_bed_occupancy_by_department")
    net = occ.groupby("census_date")[["occupied_beds", "staffed_beds"]].sum()
    net["occ"] = net.occupied_beds / net.staffed_beds
    weekly = net.occ.rolling(7).mean().iloc[6::7]
    med = occ[occ.department_code == "MED"]
    med_h = med.groupby("hospital_code").apply(lambda g: g.occupied_beds.sum() / g.staffed_beds.sum())
    d["occupancy"] = {
        "mean": net.occ.mean(), "peak": net.occ.max(),
        "peak_date": pd.Timestamp(net.occ.idxmax()).strftime("%d %b"),
        "ward_days_ge95": (occ.occupancy_rate >= 0.95).mean(),
        "ward_days_over100": (occ.occupancy_rate > 1).mean(),
        "med_mean": med.occupied_beds.sum() / med.staffed_beds.sum(),
        "med_hospitals_ge95": int((med_h >= 0.95).sum()),
        "weekly_labels": [pd.Timestamp(x).strftime("%d %b") for x in weekly.index],
        "weekly_values": [round(v * 100, 1) for v in weekly.values],
    }

    # ---- 02 department x month
    mo = csv("02_monthly_occupancy_by_department")
    piv = mo.pivot(index="department_code", columns="month", values="occupancy_rate")
    d["dept_month"] = {"icu_jan": piv.loc["ICU", "2025-01"], "med_apr": piv.loc["MED", "2025-04"],
                       "med_mar": piv.loc["MED", "2025-03"]}

    # ---- 03 LOS
    los = csv("03_length_of_stay_avg_p90")
    nl = los[los.hospital == "NETWORK"].sort_values("alos_days", ascending=False)
    names = pd.read_sql_query("SELECT department_code, department_name FROM departments", con) \
        .set_index("department_code").department_name
    excess = los[los.hospital != "NETWORK"].assign(e=lambda x: x.excess_bed_days.clip(lower=0)) \
        .groupby("hospital").e.sum().sort_values(ascending=False)
    alos_all = pd.read_sql_query(
        "SELECT (strftime('%s', discharge_ts) - strftime('%s', admit_ts)) / 86400.0 AS los FROM admissions "
        "WHERE discharge_ts >= '2025-01-01' AND discharge_ts < '2026-01-01'", con).los
    d["los"] = {
        "depts": [names[c] for c in nl.department_code],
        "alos": nl.alos_days.round(1).tolist(), "p90": nl.p90_los_days.round(1).tolist(),
        "network_alos": alos_all.mean(), "network_p90": alos_all.quantile(0.9),
        "excess_top": [{"hospital": h, "bed_days": int(v)} for h, v in excess.head(2).items()],
    }

    # ---- 04 stranded / weekend
    st = csv("04_stranded_patients_and_weekend_discharges")
    dow = pd.read_sql_query(
        "SELECT CAST(strftime('%w', discharge_ts) AS INTEGER) AS dow, COUNT(*) AS n FROM admissions "
        "WHERE discharge_ts >= '2025-01-01' AND discharge_ts < '2026-01-01' GROUP BY 1", con).set_index("dow").n
    days_in_2025 = {0: 52, 1: 52, 2: 52, 3: 53, 4: 52, 5: 52, 6: 52}
    order = [1, 2, 3, 4, 5, 6, 0]
    d["stranded"] = {
        "stranded_share": (st.stranded_share * st.discharges).sum() / st.discharges.sum(),
        "stranded_bed_day_share": st.stranded_bed_day_share.mean(),
        "weekend_ratio": st.weekend_discharge_ratio.mean(),
        "monday_surge": st.monday_surge_ratio.mean(),
        "dow_labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "dow_daily": [round(dow[i] / days_in_2025[i], 1) for i in order],
    }

    # ---- 05 ED trends
    ed = csv("05_er_wait_time_weekly_trends")
    net_w = ed.groupby("week_start").apply(lambda g: np.average(g.avg_door_to_provider_min, weights=g.attendances))
    hbv = ed[ed.hospital_code == "HBV"].set_index("week_start")
    ratio = hbv.avg_door_to_provider_min / net_w
    ed_h = ed.assign(w=ed.within_4h_rate * ed.attendances).groupby("hospital_code").agg(a=("attendances", "sum"), w=("w", "sum"))
    ed_h = (ed_h.w / ed_h.a).sort_values()
    d["ed"] = {
        "labels": [pd.Timestamp(x).strftime("%d %b") for x in hbv.index],
        "hbv_ma": hbv.avg_wait_4wk_moving_avg.round(1).tolist(),
        "network_ma": net_w.rolling(4, min_periods=1).mean().round(1).tolist(),
        "hbv_pre": ratio[ratio.index < "2025-06-02"].mean() - 1,
        "hbv_post": ratio[ratio.index >= "2025-06-02"].mean() - 1,
        "within4h_codes": ed_h.index.tolist(), "within4h": [round(v * 100, 1) for v in ed_h.values],
        "network_within4h": ed_h.pipe(lambda s: (ed.within_4h_rate * ed.attendances).sum() / ed.attendances.sum()),
    }
    hour = csv("06_er_wait_by_hour_and_triage")
    d["ed"]["worst_hour"] = int(hour[hour.triage_category.isin([3, 4, 5])].groupby("arrival_hour")
                                .avg_door_to_provider_min.mean().idxmax())

    # ---- 07 / 08 readmissions
    rd = csv("07_readmissions_within_30_days")
    hr = rd[rd.level == "Hospital"].sort_values("readmission_rate_30d", ascending=False)
    types = pd.read_sql_query("SELECT hospital_code, hospital_type FROM hospitals", con).set_index("hospital_code").hospital_type
    netr = rd[rd.level == "Network"].iloc[0]
    dr = csv("08_readmission_risk_drivers")
    top = dr[dr.factor.isin(["Diagnosis group", "Discharge destination", "Age band"])].nlargest(6, "relative_risk")
    d["readmit"] = {
        "network": netr.readmission_rate_30d, "elsewhere": netr.share_readmitted_elsewhere,
        "codes": hr.entity.tolist(), "rates": [round(v * 100, 1) for v in hr.readmission_rate_30d],
        "types": [types[c] for c in hr.entity],
        "drivers": [{"level": r.level_value, "factor": r.factor, "rr": r.relative_risk,
                     "rate": r.readmission_rate_30d} for r in top.itertuples()],
    }

    # ---- 09 bottlenecks
    b = csv("09_capacity_bottlenecks").head(6)
    board = pd.read_sql_query("""
        SELECT hospital_id, date(arrival_ts) AS day,
               AVG((strftime('%s', departure_ts) - strftime('%s', decision_to_admit_ts)) / 60.0) AS boarding_min
        FROM er_visits WHERE er_disposition = 'Admitted' AND arrival_ts >= '2025-01-01' GROUP BY 1, 2""", con)
    hid = pd.read_sql_query("SELECT hospital_id, hospital_code FROM hospitals", con)
    hd = occ.merge(hid).groupby(["hospital_id", "census_date"])[["occupied_beds", "staffed_beds"]].sum().reset_index()
    hd["occ"] = hd.occupied_beds / hd.staffed_beds
    link = hd.merge(board, left_on=["hospital_id", "census_date"], right_on=["hospital_id", "day"])
    link["band"] = pd.cut(link.occ, [0, 0.8, 0.85, 0.9, 0.95, 2], labels=["<80%", "80-85%", "85-90%", "90-95%", "95%+"])
    bb = link.groupby("band", observed=True).boarding_min.median()
    d["bottleneck"] = {
        "rows": [{"hospital": r.hospital_code, "dept": r.department_code, "occ": r.occupancy_rate,
                  "critical_days": int(r.critical_days), "longest": int(r.longest_run_days),
                  "board4h": r.share_boarding_over_4h, "trolley12": int(r.trolley_waits_over_12h)} for r in b.itertuples()],
        "band_labels": bb.index.astype(str).tolist(), "band_boarding": [round(v) for v in bb.values],
    }

    # ---- 10 scorecard
    sc = csv("10_staffing_pressure_scorecard")
    d["scorecard"] = {
        "top": sc.head(3).hospital_code.tolist(), "bottom": sc.tail(3).hospital_code.tolist(),
        "sdn_absence": sc.set_index("hospital_code").loc["SDN", "nurse_absence_rate"],
        "max_absence_code": sc.loc[sc.nurse_absence_rate.idxmax(), "hospital_code"],
        "corr_occ_breach": sc.occupancy_rate.corr(sc.share_night_shifts_breaching_ratio),
    }

    # ---- volumes
    q = lambda s: con.execute(s).fetchone()[0]
    d["volumes"] = {
        "admissions_2025": q("SELECT COUNT(*) FROM admissions WHERE admit_ts >= '2025-01-01'"),
        "er_2025": q("SELECT COUNT(*) FROM er_visits WHERE arrival_ts >= '2025-01-01'"),
        "beds": q("SELECT SUM(staffed_beds) FROM bed_capacity b JOIN departments d USING (department_id) "
                  "WHERE d.is_inpatient = 1 AND effective_from <= '2025-06-30' "
                  "AND (effective_to IS NULL OR effective_to >= '2025-06-30')"),
        "staff_shifts": q("SELECT COUNT(*) FROM staffing_shifts"),
    }

    out = ROOT / "presentation" / "deck_data.json"
    out.write_text(json.dumps(d, indent=1, default=float))
    print("wrote", out)


if __name__ == "__main__":
    main()
