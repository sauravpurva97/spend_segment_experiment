from __future__ import annotations

import json

import pandas as pd

from .config import RunConfig, build_config_payload, build_run_request_payload, run_request_path


def write_outputs(outputs: dict[str, pd.DataFrame], config: RunConfig, logger) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)

    for name, df in outputs.items():
        path = config.output_dir / f"{config.file_prefix}_{name}.csv"
        df.to_csv(path, index=False)
        logger.info("Output written | name=%s | rows=%s | file=%s", name, len(df), path)

    config_payload = build_config_payload(config)
    path = config.output_dir / f"{config.file_prefix}_config.json"
    path.write_text(json.dumps(config_payload, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Config written | file=%s", path)


def write_run_request_manifest(config: RunConfig, logger) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    path = run_request_path(config.output_dir)
    path.write_text(json.dumps(build_run_request_payload(config), indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Run request manifest written | file=%s", path)
