from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from .config import RunConfig, ThresholdConfig, allocate_output_dir, build_date_batches, parse_bool, parse_date
from .dimensions import DIMENSIONS, parse_dimension_names
from .logging_utils import log_key_values, log_section, setup_logging


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PACKAGE_ROOT.parent.parent / "result_files" / "spend_allocation_mvp"
DEFAULT_LOG_DIR = PACKAGE_ROOT / "logs"
DEFAULT_PREDEX_PATH = Path("/Users/saurav.purva/Desktop/jampp_dev/github_repos/predex")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run CPA segment underperformance experiment for a selected impression dimension.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--dimension_name",
        required=True,
        help="Dimension name or comma/plus-separated dimensions, e.g. instl or source_id,instl or source_id+instl.",
    )
    parser.add_argument("--include_country_code", required=True, type=parse_bool)
    parser.add_argument("--goal_type", default="CPA", choices=["CPA", "CPI"], type=lambda value: value.strip().upper())
    parser.add_argument("--start_date", required=True, type=parse_date)
    parser.add_argument("--end_date", required=True, type=parse_date)
    parser.add_argument("--run_spend_query_flag", required=True, type=parse_bool)
    parser.add_argument("--attribution_buffer_for_events", type=int, default=7)
    parser.add_argument("--batch_days", type=int, default=7)
    parser.add_argument("--total_campaign_batches", type=int, default=2)
    parser.add_argument("--output_root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--log_dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--predex_path", type=Path, default=DEFAULT_PREDEX_PATH)
    parser.add_argument("--presto_user", default="Saurav")
    parser.add_argument("--presto_server", default="data")
    parser.add_argument("--save_visualizations", type=parse_bool, default=True)
    parser.add_argument("--create_report", type=parse_bool, default=True)

    parser.add_argument("--MIN_CAMPAIGN_SPEND", dest="min_campaign_spend", type=float, default=100.0)
    parser.add_argument("--MIN_EVENTS_CAMPAIGN", dest="min_events_campaign", type=float, default=1.0)
    parser.add_argument("--MIN_SEGMENT_SPEND", dest="min_segment_spend", type=float, default=5.0)
    parser.add_argument("--MIN_SEGMENT_IMPS", dest="min_segment_imps", type=int, default=100)
    parser.add_argument("--MIN_SPEND_SHARE_PCT", dest="min_spend_share_pct", type=float, default=1.0)
    parser.add_argument("--MIN_ACTIVE_DAYS", dest="min_active_days", type=int, default=3)
    parser.add_argument("--MIN_BAD_DAYS", dest="min_bad_days", type=int, default=3)
    parser.add_argument("--MIN_BAD_DAYS_RATIO", dest="min_bad_days_ratio", type=float, default=0.67)
    parser.add_argument("--MIN_CPA_RATIO", dest="min_cpa_ratio", type=float, default=3.0)
    parser.add_argument("--MIN_CAMPAIGN_SEGMENTS", dest="min_campaign_segments", type=int, default=2)
    parser.add_argument("--MAX_SMOOTHED_RATE_RATIO", dest="max_smoothed_rate_ratio", type=float, default=0.75)
    parser.add_argument("--MAX_EVENT_TO_SPEND_SHARE_RATIO", dest="max_event_to_spend_share_ratio", type=float, default=0.60)
    parser.add_argument("--K_ATTR_IMPS", dest="k_attr_imps", type=int, default=100)
    parser.add_argument("--DEFAULT_CUT_PCT", dest="default_cut_pct", type=int, default=25)
    parser.add_argument("--MEDIUM_CUT_PCT", dest="medium_cut_pct", type=int, default=35)
    parser.add_argument("--HIGH_CUT_PCT", dest="high_cut_pct", type=int, default=50)
    parser.add_argument("--MAX_EVENT_LOSS_PCT", dest="max_event_loss_pct", type=float, default=5.0)
    return parser


def config_from_args(args: argparse.Namespace) -> RunConfig:
    dimension_names = parse_dimension_names(args.dimension_name)
    thresholds = ThresholdConfig(
        min_campaign_spend=args.min_campaign_spend,
        min_events_campaign=args.min_events_campaign,
        min_segment_spend=args.min_segment_spend,
        min_segment_imps=args.min_segment_imps,
        min_spend_share_pct=args.min_spend_share_pct,
        min_active_days=args.min_active_days,
        min_bad_days=args.min_bad_days,
        min_bad_days_ratio=args.min_bad_days_ratio,
        min_cpa_ratio=args.min_cpa_ratio,
        min_campaign_segments=args.min_campaign_segments,
        max_smoothed_rate_ratio=args.max_smoothed_rate_ratio,
        max_event_to_spend_share_ratio=args.max_event_to_spend_share_ratio,
        k_attr_imps=args.k_attr_imps,
        default_cut_pct=args.default_cut_pct,
        medium_cut_pct=args.medium_cut_pct,
        high_cut_pct=args.high_cut_pct,
        max_event_loss_pct=args.max_event_loss_pct,
    )
    config = RunConfig(
        dimension_names=dimension_names,
        goal_type=args.goal_type,
        include_country_code=args.include_country_code,
        start_date=args.start_date,
        end_date=args.end_date,
        run_spend_query_flag=args.run_spend_query_flag,
        attribution_buffer_for_events=args.attribution_buffer_for_events,
        batch_days=args.batch_days,
        total_campaign_batches=args.total_campaign_batches,
        output_root=args.output_root,
        resolved_output_dir=None,
        log_dir=args.log_dir,
        predex_path=args.predex_path,
        presto_user=args.presto_user,
        presto_server=args.presto_server,
        save_visualizations=args.save_visualizations,
        create_report=args.create_report,
        thresholds=thresholds,
    )
    config.validate()
    return config


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logger = None
    try:
        config = allocate_output_dir(config_from_args(args))
        logger = setup_logging(config.log_dir, f"{config.run_key}_{config.date_key}")
        log_section(logger, "SEGMENT EXPERIMENT RUN START")
        log_key_values(
            logger,
            "RUN CONFIG",
            {
                "dimensions": config.dimension_label,
                "goal_type": config.goal_type,
                "include_country_code": config.include_country_code,
                "start_date": config.start_date,
                "end_date": config.end_date,
                "run_spend_query": config.run_spend_query_flag,
                "attribution_buffer_days": config.attribution_buffer_for_events,
                "campaign_batches": config.total_campaign_batches,
                "date_batch_days": config.batch_days,
                "requested_output_dir": config.base_output_dir,
                "actual_output_dir": config.output_dir,
            },
        )
        date_batches = build_date_batches(
            config.start_date,
            config.end_date,
            config.batch_days,
            config.attribution_buffer_for_events,
        )
        log_key_values(logger, "DATE BATCH PLAN", {"count": len(date_batches), "batch_days": config.batch_days})

        from .analysis import analyze
        from .outputs import write_outputs
        from .query_runner import run_or_load_raw_data

        raw = run_or_load_raw_data(config, date_batches, logger)
        log_section(logger, "ANALYSIS")
        outputs = analyze(raw, config, logger)
        log_section(logger, "OUTPUT WRITES")
        write_outputs(outputs, config, logger)
        if config.save_visualizations:
            from .visualizations import save_visualizations

            log_section(logger, "VISUALIZATIONS")
            save_visualizations(outputs, config, logger)
        if config.create_report:
            from .report import write_experiment_report

            log_section(logger, "REPORT")
            write_experiment_report(outputs, config, logger)
        log_key_values(logger, "RUN COMPLETE", {"output_dir": config.output_dir})
        return 0
    except Exception as exc:
        if logger:
            logger.error("Run failed gracefully | error=%s", exc)
            logger.error("Traceback:\n%s", traceback.format_exc())
        else:
            print(f"Run failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
