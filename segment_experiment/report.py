from __future__ import annotations

from html import escape
from datetime import timedelta

import pandas as pd

from .config import RunConfig


def write_experiment_report(outputs: dict[str, pd.DataFrame], config: RunConfig, logger) -> tuple[str, str]:
    report_dir = config.output_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    summary = _first_row(outputs.get("run_summary"))
    campaigns = outputs.get("experiment_campaigns", pd.DataFrame())
    thresholds = config.thresholds

    title = f"Proposal Summary: {config.goal_type} {config.dimension_label} Spend Reduction Experiment"
    segment_definition = "campaign_id + "
    if config.include_country_code:
        segment_definition += "country_code + "
    segment_definition += config.dimension_label

    top_campaigns = campaigns.head(5).copy() if campaigns is not None and not campaigns.empty else pd.DataFrame()

    markdown = _build_markdown(title, segment_definition, summary, top_campaigns, config)
    html = _build_html(title, segment_definition, summary, top_campaigns, config)

    md_path = report_dir / f"{config.file_prefix}_experiment_report.md"
    html_path = report_dir / f"{config.file_prefix}_experiment_report.html"
    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")

    logger.info("Experiment report written | markdown=%s | html=%s", md_path, html_path)
    logger.info(
        "Google Docs import source ready | use Google Drive native import on the HTML file for doc creation | file=%s",
        html_path,
    )
    return str(md_path), str(html_path)


def _first_row(df: pd.DataFrame | None) -> dict:
    if df is None or df.empty:
        return {}
    return df.iloc[0].to_dict()


def _fmt_int(value) -> str:
    try:
        return f"{int(round(float(value))):,}"
    except Exception:
        return "0"


def _fmt_money(value) -> str:
    try:
        return f"${float(value):,.0f}"
    except Exception:
        return "$0"


def _fmt_pct(value) -> str:
    try:
        return f"{float(value):.1f}%"
    except Exception:
        return "0.0%"


def _build_markdown(title: str, segment_definition: str, summary: dict, top_campaigns: pd.DataFrame, config: RunConfig) -> str:
    t = config.thresholds
    event_end = config.end_date + timedelta(days=config.attribution_buffer_for_events)
    lines = [
        f"# {title}",
        "",
        "## Objective",
        f"Improve campaign {config.goal_type} efficiency by reducing spend on {config.dimension_label} segments that consistently underperform within the same campaign.",
        "",
        "The hypothesis is that some segments receive meaningful spend but contribute disproportionately few attributed goal events. Reducing spend on those segments and reallocating budget to the rest of the campaign should improve CPA with limited event loss.",
        "",
        "---",
        "",
        "# Approach",
        "",
        "## Analysis Window",
        f"- Spend and impressions: {config.start_date} - {config.end_date}",
        f"- Attributed goal events: {config.start_date} - {event_end}",
        f"- Includes a {config.attribution_buffer_for_events}-day attribution lag after the spend window.",
        "",
        "## Segment Definition",
        f"- {segment_definition}",
        "- Each segment is evaluated against its own campaign baseline.",
        "",
        "## Campaign Eligibility",
        "- Campaigns included only if:",
        f"- At least {t.min_campaign_segments} segments",
        f"- Campaign spend >= ${t.min_campaign_spend:g}",
        f"- Campaign events >= {t.min_events_campaign:g}",
        "",
        "## Segment Eligibility",
        f"- Segment spend >= ${t.min_segment_spend:g}",
        f"- Segment impressions >= {t.min_segment_imps:,}",
        f"- Segment spend share >= {t.min_spend_share_pct:g}%",
        f"- Active days >= {t.min_active_days}",
        "",
        "## Bad Segment Criteria",
        "- A segment is recommended only if:",
        f"- Segment CPA >= {t.min_cpa_ratio:g}x campaign CPA",
        "- And at least one of:",
        f"- Smoothed event rate <= {100 * t.max_smoothed_rate_ratio:g}% of campaign average",
        f"- Event share / spend share <= {t.max_event_to_spend_share_ratio:g}",
        "- And consistency:",
        f"- Bad days >= {t.min_bad_days}",
        f"- Bad day share >= {100 * t.min_bad_days_ratio:g}%",
        "- And excess spend vs campaign CPA > 0",
        "",
        "## Action Sizing",
        f"- {t.default_cut_pct}% cut: default",
        f"- {t.medium_cut_pct}% cut: stronger underperformance",
        f"- {t.high_cut_pct}% cut: strongest underperformance",
        "",
        "---",
        "",
        "# Findings",
        "",
        "After applying the stricter criteria:",
        f"- {_fmt_int(summary.get('flagged_segments'))} {config.dimension_label} segments recommended",
        f"- {_fmt_int(summary.get('flagged_campaigns'))} campaigns affected",
        f"- {_fmt_money(summary.get('flagged_spend'))} targeted spend",
        f"- {_fmt_pct(summary.get('flagged_spend_pct'))} of spend vs {_fmt_pct(summary.get('flagged_event_pct'))} of events",
        "",
        "The strongest pattern observed:",
        "- Worst-performing segments consume meaningful spend share while contributing zero or near-zero event share.",
        "- Several top segments can have infinite CPA, meaning spend generated zero attributed goal events during the analysis window.",
        "",
        "---",
        "",
        "# Proposed Experiment: Top 5 Campaigns",
        "",
        _campaign_table_markdown(top_campaigns),
        "",
        "---",
        "",
        "# Recommendation",
        "",
        "Launch a controlled experiment on the top 5 campaigns first.",
        "",
        "These campaigns show the clearest evidence of inefficient spend allocation: high spend share, minimal or zero event share, and repeated bad-day behavior. If measured CPA improvements align with projections, expand the approach to the broader eligible segment set.",
        "",
    ]
    return "\n".join(lines)


def _build_html(title: str, segment_definition: str, summary: dict, top_campaigns: pd.DataFrame, config: RunConfig) -> str:
    markdown = _build_markdown(title, segment_definition, summary, top_campaigns, config)
    body = []
    in_ul = False
    for line in markdown.splitlines():
        if line.startswith("- "):
            if not in_ul:
                body.append("<ul>")
                in_ul = True
            body.append(f"<li>{escape(line[2:])}</li>")
            continue
        if in_ul:
            body.append("</ul>")
            in_ul = False
        if line.startswith("# "):
            body.append(f"<h1>{escape(line[2:])}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{escape(line[3:])}</h2>")
        elif line == "---":
            body.append("<hr>")
        elif line.strip().startswith("|"):
            continue
        elif line.strip():
            body.append(f"<p>{escape(line)}</p>")
    if in_ul:
        body.append("</ul>")
    body.append(_campaign_table_html(top_campaigns))
    return """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body { font-family: Arial, sans-serif; font-size: 11pt; line-height: 1.35; color: #202124; }
    h1 { font-size: 23pt; margin-top: 24pt; }
    h2 { font-size: 17pt; margin-bottom: 4pt; }
    table { border-collapse: collapse; width: 100%; margin-top: 12pt; margin-bottom: 12pt; }
    th, td { border: 1px solid #999; padding: 5pt; vertical-align: top; }
    th { font-weight: bold; text-align: center; background: #f1f3f4; }
  </style>
</head>
<body>
""" + "\n".join(body) + "\n</body>\n</html>\n"


def _campaign_table_markdown(df: pd.DataFrame) -> str:
    headers = ["Campaign", "Segments", "Action", "Targeted Spend", "Targeted Events", "Est. CPA Lift"]
    if df is None or df.empty:
        return "No campaigns met the experiment criteria."
    rows = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in df.head(5).itertuples(index=False):
        rows.append(
            "| "
            + " | ".join(
                [
                    str(getattr(row, "campaign_id")),
                    str(getattr(row, "segment_values", "")),
                    "Cut recommended segments",
                    _fmt_pct(getattr(row, "targeted_spend_pct", 0)),
                    _fmt_pct(getattr(row, "targeted_event_pct", 0)),
                    _fmt_pct(getattr(row, "cpa_improvement_pct_realloc", 0)),
                ]
            )
            + " |"
        )
    return "\n".join(rows)


def _campaign_table_html(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return ""
    rows = [
        "<h1>Proposed Experiment Table</h1>",
        "<table>",
        "<tr><th>Campaign</th><th>Segments</th><th>Action</th><th>Targeted Spend</th><th>Targeted Events</th><th>Est. CPA Lift</th></tr>",
    ]
    for row in df.head(5).itertuples(index=False):
        rows.append(
            "<tr>"
            f"<td>{escape(str(getattr(row, 'campaign_id')))}</td>"
            f"<td>{escape(str(getattr(row, 'segment_values', '')))}</td>"
            "<td>Cut recommended segments</td>"
            f"<td>{escape(_fmt_pct(getattr(row, 'targeted_spend_pct', 0)))}</td>"
            f"<td>{escape(_fmt_pct(getattr(row, 'targeted_event_pct', 0)))}</td>"
            f"<td>{escape(_fmt_pct(getattr(row, 'cpa_improvement_pct_realloc', 0)))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)
