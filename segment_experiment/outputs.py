from __future__ import annotations

import json
from dataclasses import asdict

import pandas as pd

from .config import RunConfig


def write_outputs(outputs: dict[str, pd.DataFrame], config: RunConfig, logger) -> None:
    config.output_dir.mkdir(parents=True, exist_ok=True)

    for name, df in outputs.items():
        path = config.output_dir / f"{config.file_prefix}_{name}.csv"
        df.to_csv(path, index=False)
        logger.info("Output written | name=%s | rows=%s | file=%s", name, len(df), path)

    config_payload = asdict(config)
    config_payload["start_date"] = str(config.start_date)
    config_payload["end_date"] = str(config.end_date)
    config_payload["output_root"] = str(config.output_root)
    config_payload["resolved_output_dir"] = str(config.resolved_output_dir) if config.resolved_output_dir else None
    config_payload["log_dir"] = str(config.log_dir)
    config_payload["predex_path"] = str(config.predex_path)
    config_payload["thresholds"] = config.thresholds.to_dict()
    path = config.output_dir / f"{config.file_prefix}_config.json"
    path.write_text(json.dumps(config_payload, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("Config written | file=%s", path)
