# Spend Segment Experiment CLI

The workflow evaluates CPA or CPI campaign underperformance for one selected
segment definition at a time. A segment definition can contain one or more
dimensions, optionally combined with `country_code`.

## Example

Single dimension with country:

```bash
python run.py \
  --dimension_name instl \
  --goal_type CPA \
  --include_country_code true \
  --start_date 2025-01-01 \
  --end_date 2025-01-31 \
  --run_spend_query_flag true \
  --attribution_buffer_for_events 7
```

Multiple dimensions with country:

```bash
python run.py \
  --dimension_name source_id,instl \
  --goal_type CPA \
  --include_country_code true \
  --start_date 2025-01-01 \
  --end_date 2025-01-31 \
  --run_spend_query_flag true \
  --attribution_buffer_for_events 7
```

The following forms are equivalent:

```bash
--dimension_name source_id,instl
--dimension_name source_id+instl
```

Standalone multi-dimension segment:

```bash
python run.py \
  --dimension_name rewarded,skippable,has_video \
  --goal_type CPI \
  --include_country_code false \
  --start_date 2025-01-01 \
  --end_date 2025-01-31 \
  --run_spend_query_flag true
```

## First-Time Run After Cloning

```bash
python /path/to/spend_segment_experiment/run.py \
  --dimension_name source_id,instl \
  --goal_type CPA \
  --include_country_code true \
  --start_date 2026-05-01 \
  --end_date 2026-05-07 \
  --run_spend_query_flag true \
  --predex_path /path/to/predex \
  --presto_user YourPrestoUser \
  --presto_server data \
  --output_root /path/to/experiment_outputs
```

If `--output_root` is not passed, outputs are created under
`<spend_segment_experiment>/../../result_files/spend_allocation_mvp`; directories
are created automatically when you have write permission.

Logs are created automatically under `<spend_segment_experiment>/logs`.

If a run stops midway and you rerun the exact same config with
`--run_spend_query_flag true`, the CLI reuses any raw batch CSVs that already
exist in that experiment directory and only executes the missing batches.

Parameters you usually need to change:

| Parameter | What to pass |
| --- | --- |
| `--dimension_name` | Segment dimension(s), for example `source_id`, `instl`, or `source_id,instl`. |
| `--goal_type` | `CPA` or `CPI`. |
| `--include_country_code` | `true` for `campaign_id + country_code + dimensions`; `false` for campaign + dimensions only. |
| `--start_date` / `--end_date` | Bid/spend date window to analyze. |
| `--run_spend_query_flag` | Use `true` on first run. |
| `--predex_path` | Their local path to the `predex` repo. |
| `--presto_user` | Their Presto username. |
| `--presto_server` | Presto server name, usually `data`. |
| `--output_root` | Root folder where experiment output directories should be created. |

You also need warehouse access to:

- `mysql.ruby3.campaigns`
- `dw.enriched_impressions`
- `dw.events` for CPA
- `dw.installs` for CPI

The output directory is created automatically if it does not exist, as long as
you have the write permission to the repo/output path.

## Available Dimensions

All dimensions are read from `dw.enriched_impressions`.

| Dimension | Source |
| --- | --- |
| `source_id` | `source_id` |
| `zip` | `element_at(bid_request_info, 'zip')` |
| `device_type` | `element_at(bid_request_info, 'device_type')` |
| `network_type` | `element_at(bid_request_info, 'network_type')` |
| `region_code` | `element_at(bid_request_info, 'region_code')` |
| `wait` | `element_at(impression_args, 'w')` |
| `instl` | `element_at(impression_args, 'instl')` |
| `rewarded` | `element_at(req_info, 'rewarded')` |
| `skippable` | `element_at(req_info, 'skippable')`, defaults to `'false'` when missing |
| `has_video` | `element_at(bid_imp_info, 'has_video')` |
| `has_banner` | `element_at(bid_imp_info, 'has_banner')` |
| `h` | `element_at(impression_args, 'h')` |
| `is_native` | `element_at(bid_imp_info, 'is_native')` |
| `tps` | `element_at(bid_imp_info, 'tps')` |
| `ask_sup` | `element_at(bid_imp_info, 'ask_sup')` |
| `pcta_sup` | `element_at(bid_imp_info, 'pcta_sup')` |


## Parameters

Required:

| Parameter | Description |
| --- | --- |
| `--dimension_name` | One dimension or comma/plus-separated dimensions. |
| `--goal_type` | `CPA` or `CPI`; controls the `mysql.ruby3.campaigns.goal_type` filter. |
| `--include_country_code` | `true` or `false`; adds `country_code` to the segment key. |
| `--start_date` | Bid/spend window start date, `YYYY-MM-DD`. |
| `--end_date` | Bid/spend window end date, `YYYY-MM-DD`. |
| `--run_spend_query_flag` | `true` to query Presto; `false` to read cached raw batch CSVs. |

Common optional:

| Parameter | Default | Description |
| --- | ---: | --- |
| `--attribution_buffer_for_events` | `7` | Extra days added to the event window. |
| `--batch_days` | `7` | Number of bid-window days per date batch. |
| `--total_campaign_batches` | `2` | Splits campaigns by `MOD(campaign_id, N)`. |
| `--output_root` | `../../result_files/spend_allocation_mvp` | Root directory for experiment output folders. |
| `--predex_path` | `/Users/saurav.purva/Desktop/jampp_dev/github_repos/predex` | Path used before importing internal `gcd` dependencies. |
| `--presto_user` | `Saurav` | Presto user passed to `presto_engine`. |
| `--presto_server` | `data` | Presto server passed to `presto_engine`. |
| `--save_visualizations` | `true` | Writes notebook-style PNG visualizations. |
| `--create_report` | `true` | Writes Markdown and HTML proposal reports. |

Threshold/config parameters:

| Parameter | Default |
| --- | ---: |
| `--MIN_CAMPAIGN_SPEND` | `100.0` |
| `--MIN_EVENTS_CAMPAIGN` | `1.0` |
| `--MIN_SEGMENT_SPEND` | `5.0` |
| `--MIN_SEGMENT_IMPS` | `100` |
| `--MIN_SPEND_SHARE_PCT` | `1.0` |
| `--MIN_ACTIVE_DAYS` | `3` |
| `--MIN_BAD_DAYS` | `3` |
| `--MIN_BAD_DAYS_RATIO` | `0.67` |
| `--MIN_CPA_RATIO` | `3.0` |
| `--MIN_CAMPAIGN_SEGMENTS` | `2` |
| `--MAX_SMOOTHED_RATE_RATIO` | `0.75` |
| `--MAX_EVENT_TO_SPEND_SHARE_RATIO` | `0.60` |
| `--K_ATTR_IMPS` | `100` |
| `--DEFAULT_CUT_PCT` | `25` |
| `--MEDIUM_CUT_PCT` | `35` |
| `--HIGH_CUT_PCT` | `50` |
| `--MAX_EVENT_LOSS_PCT` | `5.0` |

## Cached Mode

Set `--run_spend_query_flag false` to skip warehouse queries and analyze cached
raw batch CSVs from the run output directory.

```bash
python run.py \
  --dimension_name source_id \
  --goal_type CPA \
  --include_country_code true \
  --start_date 2026-04-08 \
  --end_date 2026-04-28 \
  --run_spend_query_flag false
```

## Outputs

Each run writes to:

```text
../../result_files/spend_allocation_mvp/[country_]<dimension_key>_<goal_type>_experiment/
```

Both CPA and CPI are explicit in the folder name:

```text
../../result_files/spend_allocation_mvp/country_source_id_cpa_experiment/
../../result_files/spend_allocation_mvp/country_source_id_cpi_experiment/
```

If that exact directory already exists, the CLI creates the next available
suffix instead:

```text
../../result_files/spend_allocation_mvp/country_source_id_cpa_experiment/
../../result_files/spend_allocation_mvp/country_source_id_cpa_experiment_2/
../../result_files/spend_allocation_mvp/country_source_id_cpa_experiment_3/
```

This prevents repeated runs for the same dimension from overwriting previous
results. Dates are still included in every output filename.

Main CSV outputs:

- `<goal_type>_<dimension>_<start>_<end>_raw.csv`
- `<goal_type>_<dimension>_<start>_<end>_segments.csv`
- `<goal_type>_<dimension>_<start>_<end>_experiment_segments.csv`
- `<goal_type>_<dimension>_<start>_<end>_experiment_campaigns.csv`
- `<goal_type>_<dimension>_<start>_<end>_threshold_backtest.csv`
- `<goal_type>_<dimension>_<start>_<end>_recommended_thresholds.csv`
- `<goal_type>_<dimension>_<start>_<end>_run_summary.csv`

Logs are written automatically under `<spend_segment_experiment>/logs`.

Visualizations are written under:

```text
../../result_files/spend_allocation_mvp/[country_]<dimension_key>_<goal_type>_experiment/visualizations/
```

Reports matching the source Google Doc proposal shape are written under:

```text
../../result_files/spend_allocation_mvp/[country_]<dimension_key>_<goal_type>_experiment/reports/
```

The report directory contains both Markdown and HTML. The HTML file is the best
source for native Google Docs import.

## Google Docs Creation

The CLI can generate the report source files locally. Creating a native Google
Doc requires a Google Drive/Docs connector or Drive API credentialed runtime.

In Codex, after a run completes, import:

```text
reports/<dimension>_<start>_<end>_experiment_report.html
```

as a native Google Docs document. The generated report follows the same
structure as the reference proposal:

- Proposal Summary
- Objective
- Approach
- Findings
- Proposed Experiment: Top 5 Campaigns
- Recommendation
