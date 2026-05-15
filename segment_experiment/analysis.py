from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from .config import RunConfig
from .dimensions import segment_columns


def _clean_raw(raw: pd.DataFrame, config: RunConfig, seg_cols: list[str]) -> pd.DataFrame:
    paid = raw.copy()
    paid["day"] = pd.to_datetime(paid["day"])
    paid["week"] = paid["day"].dt.to_period("W").apply(lambda r: r.start_time)
    for col in seg_cols:
        paid[col] = paid[col].astype(str).str.upper().str.strip() if col == "country_code" else paid[col].astype(str).str.strip()
    paid["spend"] = paid["spend"].fillna(0.0)
    paid["goal_events"] = paid["goal_events"].fillna(0.0)
    paid = paid[paid["spend"] > 0].copy()
    for col in seg_cols:
        paid = paid[(paid[col].notna()) & (paid[col] != "") & (paid[col].str.lower() != "nan")].copy()
    return paid


def analyze(raw: pd.DataFrame, config: RunConfig, logger) -> dict[str, pd.DataFrame]:
    t = config.thresholds
    seg_cols = segment_columns(config.dimension_names, config.include_country_code)
    paid = _clean_raw(raw, config, seg_cols)

    campaign_segment_counts = paid[["campaign_id", *seg_cols]].drop_duplicates().groupby("campaign_id").size()
    eligible_campaigns = campaign_segment_counts[campaign_segment_counts >= t.min_campaign_segments].index
    removed_campaigns = campaign_segment_counts[campaign_segment_counts < t.min_campaign_segments]
    paid = paid[paid["campaign_id"].isin(eligible_campaigns)].copy()
    logger.info("Removed single-segment campaigns | count=%s", len(removed_campaigns))

    camp = paid.groupby(["campaign_id"], as_index=False).agg(
        camp_spend=("spend", "sum"),
        camp_evs=("goal_events", "sum"),
        camp_imps=("impressions", "sum"),
        camp_devices=("imp_devices", "sum"),
        camp_active_days=("day", "nunique"),
    )
    camp = camp[(camp["camp_spend"] >= t.min_campaign_spend) & (camp["camp_evs"] >= t.min_events_campaign)].copy()
    camp["camp_cpa"] = camp["camp_spend"] / camp["camp_evs"].replace(0, np.nan)
    camp["camp_ev_rate"] = camp["camp_evs"] / camp["camp_imps"].replace(0, np.nan)

    seg_group_cols = ["campaign_id", "app_id", *seg_cols]
    seg = paid.groupby(seg_group_cols, as_index=False).agg(
        attr_spend=("spend", "sum"),
        attr_evs=("goal_events", "sum"),
        attr_imps=("impressions", "sum"),
        attr_devices=("imp_devices", "sum"),
        active_days=("day", "nunique"),
        active_weeks=("week", "nunique"),
    )
    seg = seg.merge(
        camp[["campaign_id", "camp_spend", "camp_evs", "camp_imps", "camp_cpa", "camp_ev_rate"]],
        on="campaign_id",
        how="inner",
    )

    seg["segment_cpa"] = seg["attr_spend"] / seg["attr_evs"].replace(0, np.nan)
    seg.loc[(seg["attr_evs"] == 0) & (seg["attr_spend"] > 0), "segment_cpa"] = np.inf
    seg["cpa_ratio"] = seg["segment_cpa"] / seg["camp_cpa"]
    seg["spend_share_pct"] = 100 * seg["attr_spend"] / seg["camp_spend"].replace(0, np.nan)
    seg["event_share_pct"] = 100 * seg["attr_evs"] / seg["camp_evs"].replace(0, np.nan)
    seg["event_to_spend_share_ratio"] = seg["event_share_pct"] / seg["spend_share_pct"].replace(0, np.nan)
    seg["raw_ev_rate"] = seg["attr_evs"] / seg["attr_imps"].replace(0, np.nan)
    seg["smoothed_ev_rate"] = (seg["attr_evs"] + t.k_attr_imps * seg["camp_ev_rate"]) / (seg["attr_imps"] + t.k_attr_imps)
    seg["smoothed_rate_ratio"] = seg["smoothed_ev_rate"] / seg["camp_ev_rate"].replace(0, np.nan)
    seg["expected_events_at_campaign_rate"] = seg["attr_imps"] * seg["camp_ev_rate"]
    seg["event_gap_vs_campaign_rate"] = seg["expected_events_at_campaign_rate"] - seg["attr_evs"]
    seg["excess_spend_vs_campaign_cpa"] = seg["attr_spend"] - (seg["attr_evs"] * seg["camp_cpa"])

    daily_seg = paid.groupby(["day", "campaign_id", *seg_cols], as_index=False).agg(
        day_spend=("spend", "sum"),
        day_evs=("goal_events", "sum"),
        day_imps=("impressions", "sum"),
    )
    daily_camp = paid.groupby(["day", "campaign_id"], as_index=False).agg(
        camp_day_spend=("spend", "sum"),
        camp_day_evs=("goal_events", "sum"),
        camp_day_imps=("impressions", "sum"),
    )
    daily_camp["camp_day_ev_rate"] = daily_camp["camp_day_evs"] / daily_camp["camp_day_imps"].replace(0, np.nan)
    daily = daily_seg.merge(daily_camp[["day", "campaign_id", "camp_day_ev_rate"]], on=["day", "campaign_id"], how="left")
    daily["day_smoothed_ev_rate"] = (daily["day_evs"] + t.k_attr_imps * daily["camp_day_ev_rate"]) / (
        daily["day_imps"] + t.k_attr_imps
    )
    daily["bad_day"] = (daily["day_imps"] >= 30) & (
        daily["day_smoothed_ev_rate"] < daily["camp_day_ev_rate"] * t.max_smoothed_rate_ratio
    )

    consistency = daily.groupby(["campaign_id", *seg_cols], as_index=False).agg(
        observed_days=("day", "nunique"),
        bad_days=("bad_day", "sum"),
        median_day_spend=("day_spend", "median"),
    )
    consistency["bad_day_share"] = consistency["bad_days"] / consistency["observed_days"].replace(0, np.nan)

    seg = seg.merge(consistency, on=["campaign_id", *seg_cols], how="left")
    seg[["observed_days", "bad_days", "bad_day_share"]] = seg[["observed_days", "bad_days", "bad_day_share"]].fillna(0)

    enough_volume = (
        (seg["attr_spend"] >= t.min_segment_spend)
        & (seg["attr_imps"] >= t.min_segment_imps)
        & (seg["spend_share_pct"] >= t.min_spend_share_pct)
        & (seg["active_days"] >= t.min_active_days)
    )
    cpa_bad = seg["cpa_ratio"] >= t.min_cpa_ratio
    rate_bad = seg["smoothed_rate_ratio"] <= t.max_smoothed_rate_ratio
    share_bad = (seg["event_to_spend_share_ratio"] <= t.max_event_to_spend_share_ratio) & (
        seg["spend_share_pct"] >= t.min_spend_share_pct
    )
    overall_bad = cpa_bad & (rate_bad | share_bad)
    repeated_bad = (seg["bad_days"] >= t.min_bad_days) & (seg["bad_day_share"] >= t.min_bad_days_ratio)
    seg["robust_underperf"] = enough_volume & overall_bad & repeated_bad & (seg["excess_spend_vs_campaign_cpa"] > 0)

    experiment_output, campaign_action = _build_experiment_outputs(seg, seg_cols, config)
    weekly_summary = _build_weekly_summary(paid, seg, seg_cols)
    worst_campaign_segment_summary = _build_worst_campaign_segment_summary(seg, campaign_action, seg_cols)
    threshold_backtest = _build_threshold_backtest(seg, config)
    recommended_thresholds = threshold_backtest[threshold_backtest["feasible"]].head(1).copy()
    summary = _build_summary(raw, paid, seg, experiment_output, config)

    logger.info(
        "Analysis complete | raw_rows=%s | paid_rows=%s | segments=%s | flagged_segments=%s | flagged_campaigns=%s",
        len(raw),
        len(paid),
        len(seg),
        int(seg["robust_underperf"].sum()),
        int(seg.loc[seg["robust_underperf"], "campaign_id"].nunique()),
    )

    return {
        "segments": seg,
        "experiment_segments": experiment_output,
        "experiment_campaigns": campaign_action,
        "weekly_summary": weekly_summary,
        "worst_campaign_segment_summary": worst_campaign_segment_summary,
        "threshold_backtest": threshold_backtest,
        "recommended_thresholds": recommended_thresholds,
        "run_summary": summary,
    }


def _build_experiment_outputs(seg: pd.DataFrame, seg_cols: list[str], config: RunConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    t = config.thresholds
    experiment = seg[seg["robust_underperf"]].copy()
    if experiment.empty:
        return experiment.copy(), pd.DataFrame()

    experiment["recommended_cut_pct"] = t.default_cut_pct
    medium_evidence = (
        (experiment["cpa_ratio"] >= 3.0)
        & (experiment["smoothed_rate_ratio"] <= 0.60)
        & (experiment["bad_days"] >= t.min_bad_days)
    )
    high_evidence = (
        (experiment["cpa_ratio"] >= 4.0)
        & (experiment["smoothed_rate_ratio"] <= 0.35)
        & (experiment["event_to_spend_share_ratio"] <= 0.30)
    )
    experiment.loc[medium_evidence, "recommended_cut_pct"] = t.medium_cut_pct
    experiment.loc[high_evidence, "recommended_cut_pct"] = t.high_cut_pct
    experiment["cut_ratio"] = experiment["recommended_cut_pct"] / 100.0
    experiment["saved_spend_cut_only"] = experiment["cut_ratio"] * experiment["attr_spend"]
    experiment["lost_events_cut_only"] = experiment["cut_ratio"] * experiment["attr_evs"]
    experiment["campaign_spend_after_cut_only"] = experiment["camp_spend"] - experiment["saved_spend_cut_only"]
    experiment["campaign_events_after_cut_only"] = experiment["camp_evs"] - experiment["lost_events_cut_only"]
    experiment["campaign_cpa_after_cut_only"] = experiment["campaign_spend_after_cut_only"] / experiment[
        "campaign_events_after_cut_only"
    ].replace(0, np.nan)
    experiment["good_spend"] = experiment["camp_spend"] - experiment["attr_spend"]
    experiment["good_events"] = experiment["camp_evs"] - experiment["attr_evs"]
    experiment["good_cpa"] = experiment["good_spend"] / experiment["good_events"].replace(0, np.nan)
    experiment["regained_events_if_reallocated"] = experiment["saved_spend_cut_only"] / experiment["good_cpa"].replace(0, np.nan)
    experiment["campaign_events_after_realloc"] = (
        experiment["camp_evs"] - experiment["lost_events_cut_only"] + experiment["regained_events_if_reallocated"].fillna(0)
    )
    experiment["campaign_cpa_after_realloc"] = experiment["camp_spend"] / experiment["campaign_events_after_realloc"].replace(
        0, np.nan
    )
    experiment["cpa_improvement_pct_realloc"] = (
        100 * (experiment["camp_cpa"] - experiment["campaign_cpa_after_realloc"]) / experiment["camp_cpa"].replace(0, np.nan)
    )

    experiment["proof"] = (
        "spend_share="
        + experiment["spend_share_pct"].round(1).astype(str)
        + "%, event_share="
        + experiment["event_share_pct"].round(1).astype(str)
        + "%, cpa_ratio="
        + experiment["cpa_ratio"].round(2).astype(str)
        + "x, smoothed_rate_ratio="
        + experiment["smoothed_rate_ratio"].round(2).astype(str)
        + "x, bad_days="
        + experiment["bad_days"].astype(int).astype(str)
        + "/"
        + experiment["observed_days"].astype(int).astype(str)
    )
    experiment["action"] = "Decrease segment spend by " + experiment["recommended_cut_pct"].astype(int).astype(str) + "%"

    cols = [
        "campaign_id",
        *seg_cols,
        "proof",
        "action",
        "attr_spend",
        "attr_evs",
        "segment_cpa",
        "camp_cpa",
        "cpa_ratio",
        "spend_share_pct",
        "event_share_pct",
        "bad_days",
        "observed_days",
        "saved_spend_cut_only",
        "lost_events_cut_only",
        "campaign_cpa_after_cut_only",
        "campaign_cpa_after_realloc",
        "cpa_improvement_pct_realloc",
    ]
    experiment_output = experiment[cols].sort_values(
        ["cpa_improvement_pct_realloc", "saved_spend_cut_only"], ascending=False
    )

    experiment["_segment_value"] = experiment[seg_cols].astype(str).agg(" + ".join, axis=1)
    campaign_action = experiment.groupby("campaign_id", as_index=False).agg(
        n_segments=("robust_underperf", "size"),
        segment_values=("_segment_value", lambda s: ", ".join(sorted(s.astype(str).unique())[:12])),
        total_spend=("camp_spend", "first"),
        total_events=("camp_evs", "first"),
        current_cpa=("camp_cpa", "first"),
        targeted_spend=("attr_spend", "sum"),
        targeted_events=("attr_evs", "sum"),
        saved_spend=("saved_spend_cut_only", "sum"),
        lost_events=("lost_events_cut_only", "sum"),
    )
    campaign_action["targeted_spend_pct"] = 100 * campaign_action["targeted_spend"] / campaign_action["total_spend"].replace(
        0, np.nan
    )
    campaign_action["targeted_event_pct"] = 100 * campaign_action["targeted_events"] / campaign_action["total_events"].replace(
        0, np.nan
    )
    campaign_action["spend_reduction_pct"] = 100 * campaign_action["saved_spend"] / campaign_action["total_spend"].replace(
        0, np.nan
    )
    campaign_action["event_loss_pct_cut_only"] = 100 * campaign_action["lost_events"] / campaign_action["total_events"].replace(
        0, np.nan
    )
    campaign_action["cpa_after_cut_only"] = (campaign_action["total_spend"] - campaign_action["saved_spend"]) / (
        campaign_action["total_events"] - campaign_action["lost_events"]
    ).replace(0, np.nan)
    campaign_action["remaining_spend"] = campaign_action["total_spend"] - campaign_action["targeted_spend"]
    campaign_action["remaining_events"] = campaign_action["total_events"] - campaign_action["targeted_events"]
    campaign_action["remaining_cpa"] = campaign_action["remaining_spend"] / campaign_action["remaining_events"].replace(0, np.nan)
    campaign_action["regained_events_if_reallocated"] = campaign_action["saved_spend"] / campaign_action["remaining_cpa"].replace(
        0, np.nan
    )
    campaign_action["events_after_realloc"] = (
        campaign_action["total_events"]
        - campaign_action["lost_events"]
        + campaign_action["regained_events_if_reallocated"].fillna(0)
    )
    campaign_action["cpa_after_realloc"] = campaign_action["total_spend"] / campaign_action["events_after_realloc"].replace(
        0, np.nan
    )
    campaign_action["cpa_improvement_pct_realloc"] = (
        100 * (campaign_action["current_cpa"] - campaign_action["cpa_after_realloc"]) / campaign_action["current_cpa"].replace(0, np.nan)
    )
    campaign_action = campaign_action.sort_values(["cpa_improvement_pct_realloc", "saved_spend"], ascending=False)
    return experiment_output, campaign_action


def _build_weekly_summary(paid: pd.DataFrame, seg: pd.DataFrame, seg_cols: list[str]) -> pd.DataFrame:
    if seg.empty:
        return pd.DataFrame()
    weekly_flagged = paid.merge(
        seg[["campaign_id", *seg_cols, "robust_underperf"]],
        on=["campaign_id", *seg_cols],
        how="left",
    )
    weekly_flagged["robust_underperf"] = weekly_flagged["robust_underperf"].fillna(False)
    wk = weekly_flagged.groupby(["week", "robust_underperf"], as_index=False).agg(
        spend=("spend", "sum"),
        goal_events=("goal_events", "sum"),
    )
    wk_total = weekly_flagged.groupby("week", as_index=False).agg(
        total_spend=("spend", "sum"),
        total_events=("goal_events", "sum"),
    )
    wk_under = wk[wk["robust_underperf"]].rename(columns={"spend": "under_spend", "goal_events": "under_events"})
    weekly_summary = wk_total.merge(wk_under[["week", "under_spend", "under_events"]], on="week", how="left").fillna(0)
    weekly_summary["pct_spend_under"] = (
        100 * weekly_summary["under_spend"] / weekly_summary["total_spend"].replace(0, np.nan)
    )
    weekly_summary["pct_events_under"] = (
        100 * weekly_summary["under_events"] / weekly_summary["total_events"].replace(0, np.nan)
    )
    return weekly_summary


def _build_worst_campaign_segment_summary(seg: pd.DataFrame, campaign_action: pd.DataFrame, seg_cols: list[str]) -> pd.DataFrame:
    if seg.empty or campaign_action.empty:
        return pd.DataFrame()
    top_campaigns = (
        campaign_action.sort_values(["cpa_improvement_pct_realloc", "saved_spend"], ascending=False)
        .head(15)["campaign_id"]
        .tolist()
    )
    out = seg[seg["campaign_id"].isin(top_campaigns)].copy()
    out["flag"] = np.where(out["robust_underperf"], "recommended_cut", "other_segment")
    ordered = [
        "campaign_id",
        *seg_cols,
        "app_id",
        "flag",
        "attr_spend",
        "attr_evs",
        "segment_cpa",
        "camp_cpa",
        "cpa_ratio",
        "spend_share_pct",
        "event_share_pct",
        "event_to_spend_share_ratio",
        "smoothed_rate_ratio",
        "bad_days",
        "observed_days",
        "bad_day_share",
    ]
    ordered = [c for c in ordered if c in out.columns]
    return out.sort_values(["robust_underperf", "campaign_id", "spend_share_pct"], ascending=[False, True, False])[
        ordered
    ]


def _build_threshold_backtest(seg: pd.DataFrame, config: RunConfig) -> pd.DataFrame:
    t = config.thresholds
    grid = {
        "min_cpa_ratio": [3.0, 4.0, 5.0, 6.0],
        "max_smoothed_rate_ratio": [0.50, 0.60, 0.75],
        "min_imps": [100, 200, 500],
        "min_spend_share_pct": [1.0, 2.0, 5.0],
        "min_bad_day_share": [0.67, 0.75],
    }
    rows = []
    for min_cpa_ratio, max_rate_ratio, min_imps, min_spend_share, min_bad_day_share in product(
        grid["min_cpa_ratio"],
        grid["max_smoothed_rate_ratio"],
        grid["min_imps"],
        grid["min_spend_share_pct"],
        grid["min_bad_day_share"],
    ):
        target = seg[
            (seg["attr_imps"] >= min_imps)
            & (seg["spend_share_pct"] >= min_spend_share)
            & (seg["bad_day_share"] >= min_bad_day_share)
            & (seg["excess_spend_vs_campaign_cpa"] > 0)
            & (seg["cpa_ratio"] >= min_cpa_ratio)
            & (
                (seg["smoothed_rate_ratio"] <= max_rate_ratio)
                | (seg["event_to_spend_share_ratio"] <= t.max_event_to_spend_share_ratio)
            )
        ].copy()
        saved_spend = 0.5 * target["attr_spend"].sum()
        lost_events = 0.5 * target["attr_evs"].sum()
        total_spend = seg["attr_spend"].sum()
        total_events = seg["attr_evs"].sum()
        event_loss_pct = 100 * lost_events / max(total_events, 1e-9)
        rows.append(
            {
                "min_cpa_ratio": min_cpa_ratio,
                "max_smoothed_rate_ratio": max_rate_ratio,
                "min_imps": min_imps,
                "min_spend_share_pct": min_spend_share,
                "min_bad_day_share": min_bad_day_share,
                "n_segments": len(target),
                "n_campaigns": target["campaign_id"].nunique(),
                "spend_saved_pct": 100 * saved_spend / max(total_spend, 1e-9),
                "event_loss_pct": event_loss_pct,
                "feasible": event_loss_pct <= t.max_event_loss_pct,
            }
        )
    return pd.DataFrame(rows).sort_values(["feasible", "spend_saved_pct"], ascending=[False, False])


def _build_summary(raw: pd.DataFrame, paid: pd.DataFrame, seg: pd.DataFrame, experiment: pd.DataFrame, config: RunConfig) -> pd.DataFrame:
    flagged = seg[seg["robust_underperf"]].copy()
    total_spend = seg["attr_spend"].sum()
    total_events = seg["attr_evs"].sum()
    return pd.DataFrame(
        [
            {
                "dimension_name": config.dimension_key,
                "dimension_label": config.dimension_label,
                "goal_type": config.goal_type,
                "include_country_code": config.include_country_code,
                "start_date": config.start_date,
                "end_date": config.end_date,
                "raw_rows": len(raw),
                "paid_rows_after_cleaning": len(paid),
                "campaigns": paid["campaign_id"].nunique(),
                "segments": len(seg),
                "flagged_segments": len(flagged),
                "flagged_campaigns": flagged["campaign_id"].nunique(),
                "total_spend": total_spend,
                "total_events": total_events,
                "flagged_spend": flagged["attr_spend"].sum(),
                "flagged_events": flagged["attr_evs"].sum(),
                "flagged_spend_pct": 100 * flagged["attr_spend"].sum() / total_spend if total_spend else np.nan,
                "flagged_event_pct": 100 * flagged["attr_evs"].sum() / total_events if total_events else np.nan,
                "experiment_rows": len(experiment),
            }
        ]
    )
