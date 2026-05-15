from __future__ import annotations

from .config import DateBatch
from .dimensions import get_dimensions


def build_spend_events_sql(
    *,
    dimension_names: tuple[str, ...],
    goal_type: str,
    include_country_code: bool,
    date_batch: DateBatch,
    total_campaign_batches: int,
    campaign_batch_index: int,
) -> str:
    dimensions = get_dimensions(dimension_names)

    select_dimensions = []
    group_positions = ["1"]
    next_group_position = 2

    if include_country_code:
        select_dimensions.append("element_at(imp.bid_request_info, 'ctry2') AS country_code")
        group_positions.append(str(next_group_position))
        next_group_position += 1

    for dimension in dimensions:
        select_dimensions.append(dimension.select_sql)
        group_positions.append(str(next_group_position))
        next_group_position += 1

    # campaign_id and app_id are always grouped after selected dimensions.
    group_positions.extend([str(next_group_position), str(next_group_position + 1)])

    select_dimensions_sql = ",\n                ".join(select_dimensions)
    predicates = [
        f"{dimension.sql_expression} IS NOT NULL"
        for dimension in dimensions
        if dimension.default_value is None
    ]
    source_not_null_predicate = " AND ".join(predicates) if predicates else "TRUE"

    if goal_type == "CPI":
        metric_cte = f"""
install_counts AS (
    SELECT
        ins.campaign_id,
        ins.trans_id,
        COUNT(*) AS install_total
    FROM dw.installs ins
    JOIN campaign_data cd ON ins.campaign_id = cd.campaign_id
    WHERE ins.dt BETWEEN '{date_batch.bid_start_dt}' AND '{date_batch.event_end_dt}'
        AND ins.install_created IS NOT NULL
    GROUP BY 1, 2
)""".strip()
        metric_join = "LEFT JOIN install_counts ins ON imp.trans_id = ins.trans_id"
        metric_select = "COALESCE(SUM(ins.install_total), 0) AS total_installs"
    else:
        metric_cte = f"""
event_counts AS (
    SELECT
        evs.campaign_id,
        evs.trans_id,
        SUM(element_at(cd.event_weights, evs.event_id)) AS event_total
    FROM dw.events evs
    JOIN campaign_data cd ON evs.campaign_id = cd.campaign_id
    WHERE evs.dt BETWEEN '{date_batch.bid_start_dt}' AND '{date_batch.event_end_dt}'
        AND element_at(cd.event_weights, evs.event_id) IS NOT NULL
    GROUP BY 1, 2
)""".strip()
        metric_join = "LEFT JOIN event_counts evs ON imp.trans_id = evs.trans_id"
        metric_select = "SUM(evs.event_total) AS goal_events"

    return f"""
WITH campaign_data AS (
    SELECT
        id AS campaign_id,
        application_id,
        MAP(
            TRANSFORM(CAST(goal_events AS ARRAY(JSON)), x -> CAST(JSON_EXTRACT(x, '$.event_id') AS INT)),
            TRANSFORM(CAST(goal_events AS ARRAY(JSON)), x -> CAST(JSON_EXTRACT(x, '$.weight') AS DOUBLE))
        ) AS event_weights
    FROM mysql.ruby3.campaigns c
    WHERE goal_type = '{goal_type}'
        AND MOD(c.id, {total_campaign_batches}) = {campaign_batch_index}
),
{metric_cte}
SELECT
    substring(imp.dt, 1, 10) AS day,
    {select_dimensions_sql},
    imp.campaign_id,
    imp.app_id,
    SUM(imp.impression_price * (1 + imp.fee) / 1000) AS spend,
    {metric_select},
    COUNT(imp.trans_id) AS impressions,
    COUNT(DISTINCT imp.device_id) AS imp_devices
FROM dw.enriched_impressions imp
{metric_join}
WHERE imp.dt BETWEEN '{date_batch.bid_start_dt}' AND '{date_batch.bid_end_dt}'
    AND imp.campaign_id IN (SELECT campaign_id FROM campaign_data)
    AND {source_not_null_predicate}
GROUP BY {", ".join(group_positions)}
ORDER BY 1, {next_group_position}, spend DESC
""".strip()
