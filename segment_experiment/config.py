from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
import re


RUN_REQUEST_FILENAME = "_run_request.json"


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Expected date in YYYY-MM-DD format, got {value!r}") from exc


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y"}:
        return True
    if normalized in {"0", "false", "f", "no", "n"}:
        return False
    raise ValueError(f"Expected boolean value, got {value!r}")


@dataclass(frozen=True)
class ThresholdConfig:
    min_campaign_spend: float = 100.0
    min_events_campaign: float = 1.0
    min_segment_spend: float = 5.0
    min_segment_imps: int = 100
    min_spend_share_pct: float = 1.0
    min_active_days: int = 3
    min_bad_days: int = 3
    min_bad_days_ratio: float = 0.67
    min_cpa_ratio: float = 3.0
    min_campaign_segments: int = 2
    max_smoothed_rate_ratio: float = 0.75
    max_event_to_spend_share_ratio: float = 0.60
    k_attr_imps: int = 100
    default_cut_pct: int = 25
    medium_cut_pct: int = 35
    high_cut_pct: int = 50
    max_event_loss_pct: float = 5.0

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


@dataclass(frozen=True)
class RunConfig:
    dimension_names: tuple[str, ...]
    goal_type: str
    include_country_code: bool
    start_date: date
    end_date: date
    run_spend_query_flag: bool
    attribution_buffer_for_events: int
    batch_days: int
    total_campaign_batches: int
    output_root: Path
    resolved_output_dir: Path | None
    log_dir: Path
    predex_path: Path
    presto_user: str
    presto_server: str
    save_visualizations: bool
    create_report: bool
    thresholds: ThresholdConfig

    @property
    def run_key(self) -> str:
        prefix = "country_" if self.include_country_code else ""
        return f"{prefix}{self.dimension_key}_{self.goal_type.lower()}_experiment"

    @property
    def dimension_key(self) -> str:
        return "_".join(self.dimension_names)

    @property
    def dimension_label(self) -> str:
        return " + ".join(self.dimension_names)

    @property
    def date_key(self) -> str:
        return f"{self.start_date}_{self.end_date}"

    @property
    def output_dir(self) -> Path:
        if self.resolved_output_dir is not None:
            return self.resolved_output_dir
        return self.base_output_dir

    @property
    def base_output_dir(self) -> Path:
        return self.output_root / self.run_key

    @property
    def file_prefix(self) -> str:
        return f"{self.goal_type.lower()}_{self.dimension_key}_{self.start_date}_{self.end_date}"

    def validate(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be greater than or equal to start_date")
        if self.attribution_buffer_for_events < 0:
            raise ValueError("attribution_buffer_for_events must be >= 0")
        if self.batch_days < 1:
            raise ValueError("batch_days must be >= 1")
        if self.total_campaign_batches < 1:
            raise ValueError("total_campaign_batches must be >= 1")
        if self.goal_type not in {"CPA", "CPI"}:
            raise ValueError("goal_type must be either CPA or CPI")


@dataclass(frozen=True)
class DateBatch:
    batch_number: int
    bid_start: date
    bid_end: date
    event_end: date

    @property
    def bid_start_dt(self) -> str:
        return f"{self.bid_start:%Y-%m-%d}-00"

    @property
    def bid_end_dt(self) -> str:
        return f"{self.bid_end:%Y-%m-%d}-23"

    @property
    def event_end_dt(self) -> str:
        return f"{self.event_end:%Y-%m-%d}-23"


def build_date_batches(start_date: date, end_date: date, batch_days: int, attribution_buffer_days: int) -> list[DateBatch]:
    batches: list[DateBatch] = []
    current = start_date
    batch_number = 0
    while current <= end_date:
        bid_end = min(current + timedelta(days=batch_days - 1), end_date)
        batches.append(
            DateBatch(
                batch_number=batch_number,
                bid_start=current,
                bid_end=bid_end,
                event_end=bid_end + timedelta(days=attribution_buffer_days),
            )
        )
        current = bid_end + timedelta(days=1)
        batch_number += 1
    return batches


def allocate_output_dir(config: RunConfig) -> RunConfig:
    base_dir = config.base_output_dir
    request_payload = build_run_request_payload(config)

    for candidate in iter_matching_output_dirs(base_dir):
        existing_payload = read_run_request_payload(candidate)
        if existing_payload == request_payload:
            return replace(config, resolved_output_dir=candidate)

    if not base_dir.exists():
        return replace(config, resolved_output_dir=base_dir)

    suffix = next_available_suffix(base_dir)
    return replace(config, resolved_output_dir=base_dir.with_name(f"{base_dir.name}_{suffix}"))


def build_run_request_payload(config: RunConfig) -> dict:
    return {
        "version": 1,
        "dimension_names": list(config.dimension_names),
        "goal_type": config.goal_type,
        "include_country_code": config.include_country_code,
        "start_date": str(config.start_date),
        "end_date": str(config.end_date),
        "run_spend_query_flag": config.run_spend_query_flag,
        "attribution_buffer_for_events": config.attribution_buffer_for_events,
        "batch_days": config.batch_days,
        "total_campaign_batches": config.total_campaign_batches,
        "save_visualizations": config.save_visualizations,
        "create_report": config.create_report,
        "thresholds": config.thresholds.to_dict(),
    }


def build_config_payload(config: RunConfig) -> dict:
    config_payload = asdict(config)
    config_payload["dimension_names"] = list(config.dimension_names)
    config_payload["start_date"] = str(config.start_date)
    config_payload["end_date"] = str(config.end_date)
    config_payload["output_root"] = str(config.output_root)
    config_payload["resolved_output_dir"] = str(config.resolved_output_dir) if config.resolved_output_dir else None
    config_payload["log_dir"] = str(config.log_dir)
    config_payload["predex_path"] = str(config.predex_path)
    config_payload["thresholds"] = config.thresholds.to_dict()
    return config_payload


def run_request_path(output_dir: Path) -> Path:
    return output_dir / RUN_REQUEST_FILENAME


def read_run_request_payload(output_dir: Path) -> dict | None:
    path = run_request_path(output_dir)
    if not path.exists():
        return None
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def iter_matching_output_dirs(base_dir: Path) -> list[Path]:
    parent = base_dir.parent
    if not parent.exists():
        return [base_dir]

    pattern = re.compile(rf"^{re.escape(base_dir.name)}(?:_(\d+))?$")
    matches: list[tuple[int, Path]] = []
    for child in parent.iterdir():
        if not child.is_dir():
            continue
        match = pattern.match(child.name)
        if not match:
            continue
        suffix = int(match.group(1) or "1")
        matches.append((suffix, child))
    if not matches:
        return [base_dir]
    return [path for _, path in sorted(matches, key=lambda item: item[0])]


def next_available_suffix(base_dir: Path) -> int:
    parent = base_dir.parent
    pattern = re.compile(rf"^{re.escape(base_dir.name)}_(\d+)$")
    max_suffix = 1
    if parent.exists():
        for child in parent.iterdir():
            if not child.is_dir():
                continue
            match = pattern.match(child.name)
            if match:
                max_suffix = max(max_suffix, int(match.group(1)))
    return max_suffix + 1
