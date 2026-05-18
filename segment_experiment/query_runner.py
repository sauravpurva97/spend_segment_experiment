from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd

from .config import DateBatch, RunConfig
from .logging_utils import log_key_values, log_section, log_subsection
from .sql_builder import build_spend_events_sql


class QueryExecutionError(RuntimeError):
    pass


class WarehouseClient:
    def __init__(self, predex_path: Path, user: str, server: str):
        self.predex_path = predex_path
        self.user = user
        self.server = server
        self._query = None

    def connect(self) -> None:
        if self._query is not None:
            return
        if self.predex_path.exists():
            os.chdir(self.predex_path)
        try:
            from gcd import lab
            from gcd.lab import presto_engine, query
            from gcd.chronos import set_timezone
        except Exception as exc:  # pragma: no cover - depends on internal env
            raise QueryExecutionError(
                "Failed to import gcd warehouse dependencies. Run from the internal environment "
                "or set --run_spend_query_flag false to use cached CSVs."
            ) from exc

        set_timezone("UTC")
        lab.default_engine = presto_engine(user=self.user, server=self.server)
        self._query = query

    def query(self, sql: str) -> pd.DataFrame:
        self.connect()
        try:
            return self._query(sql)
        except Exception as exc:  # pragma: no cover - warehouse dependent
            raise QueryExecutionError(str(exc)) from exc


def raw_batch_path(output_dir: Path, prefix: str, campaign_batch_index: int, date_batch: DateBatch) -> Path:
    return output_dir / "raw_batches" / (
        f"{prefix}_campaign_batch_{campaign_batch_index}_date_batch_{date_batch.batch_number}_"
        f"{date_batch.bid_start}_{date_batch.bid_end}.csv"
    )


def run_or_load_raw_data(config: RunConfig, date_batches: list[DateBatch], logger) -> pd.DataFrame:
    log_section(logger, "RAW DATA COLLECTION")
    config.output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = config.output_dir / "raw_batches"
    raw_dir.mkdir(parents=True, exist_ok=True)
    sql_dir = config.output_dir / "sql"
    sql_dir.mkdir(parents=True, exist_ok=True)

    frames: list[pd.DataFrame] = []
    client = WarehouseClient(config.predex_path, config.presto_user, config.presto_server)

    for campaign_batch_index in range(config.total_campaign_batches):
        for date_batch in date_batches:
            path = raw_batch_path(config.output_dir, config.file_prefix, campaign_batch_index, date_batch)
            batch_title = (
                f"BATCH {campaign_batch_index + 1}/{config.total_campaign_batches} "
                f"| DATE BATCH {date_batch.batch_number + 1}/{len(date_batches)}"
            )
            log_key_values(
                logger,
                batch_title,
                {
                    "dimensions": config.dimension_label,
                    "goal_type": config.goal_type,
                    "include_country_code": config.include_country_code,
                    "bid_window": f"{date_batch.bid_start_dt} -> {date_batch.bid_end_dt}",
                    "event_window": f"{date_batch.bid_start_dt} -> {date_batch.event_end_dt}",
                    "output_csv": path,
                },
            )
            started_at = time.perf_counter()

            if config.run_spend_query_flag:
                if path.exists():
                    log_subsection(logger, "BATCH CACHE HIT")
                    logger.info("Existing raw batch CSV found. Skipping query execution and reusing %s", path)
                    df = pd.read_csv(path, dtype={name: str for name in config.dimension_names})
                    df = normalize_metric_columns(df, config.goal_type)
                    elapsed = time.perf_counter() - started_at
                    log_key_values(
                        logger,
                        "BATCH COMPLETE",
                        {
                            "rows": len(df),
                            "runtime_seconds": f"{elapsed:.2f}",
                            "output_csv": path,
                            "used_existing_csv": True,
                        },
                    )
                    frames.append(df)
                    continue

                sql = build_spend_events_sql(
                    dimension_names=config.dimension_names,
                    goal_type=config.goal_type,
                    include_country_code=config.include_country_code,
                    date_batch=date_batch,
                    total_campaign_batches=config.total_campaign_batches,
                    campaign_batch_index=campaign_batch_index,
                )
                sql_path = sql_dir / (
                    f"{config.file_prefix}_campaign_batch_{campaign_batch_index}_"
                    f"date_batch_{date_batch.batch_number}.sql"
                )
                sql_path.write_text(sql, encoding="utf-8")
                log_subsection(logger, f"SQL QUERY | saved_to={sql_path}")
                logger.info("\n%s", sql)
                log_subsection(logger, "QUERY EXECUTION START")
                try:
                    df = client.query(sql)
                    df = normalize_metric_columns(df, config.goal_type)
                    df.to_csv(path, index=False)
                except Exception:
                    logger.exception("Batch failed | output=%s", path)
                    raise
            else:
                if not path.exists():
                    raise FileNotFoundError(
                        f"Cached raw batch not found: {path}. Re-run with --run_spend_query_flag true "
                        "or place the expected raw CSV in raw_batches/."
                    )
                df = pd.read_csv(path, dtype={name: str for name in config.dimension_names})
                df = normalize_metric_columns(df, config.goal_type)

            elapsed = time.perf_counter() - started_at
            log_key_values(
                logger,
                "BATCH COMPLETE",
                {
                    "rows": len(df),
                    "runtime_seconds": f"{elapsed:.2f}",
                    "output_csv": path,
                    "used_existing_csv": False,
                },
            )
            frames.append(df)

    if not frames:
        raise ValueError("No raw data frames were produced.")

    raw = pd.concat(frames, ignore_index=True)
    raw_output = config.output_dir / f"{config.file_prefix}_raw.csv"
    raw.to_csv(raw_output, index=False)
    log_key_values(logger, "RAW DATA WRITTEN", {"rows": len(raw), "file": raw_output})
    return raw


def normalize_metric_columns(df: pd.DataFrame, goal_type: str) -> pd.DataFrame:
    if goal_type == "CPI" and "total_installs" in df.columns and "goal_events" not in df.columns:
        df = df.copy()
        df["goal_events"] = df["total_installs"]
    return df
