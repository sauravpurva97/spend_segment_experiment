from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Dimension:
    name: str
    sql_expression: str
    default_value: str | None = None

    @property
    def select_sql(self) -> str:
        expr = self.sql_expression
        if self.default_value is not None:
            expr = f"COALESCE(CAST({expr} AS varchar), '{self.default_value}')"
        else:
            expr = f"CAST({expr} AS varchar)"
        return f"{expr} AS {self.name}"


DIMENSIONS: dict[str, Dimension] = {
    "source_id": Dimension("source_id", "imp.source_id"),
    "zip": Dimension("zip", "element_at(imp.bid_request_info, 'zip')"),
    "device_type": Dimension("device_type", "element_at(imp.bid_request_info, 'device_type')"),
    "network_type": Dimension("network_type", "element_at(imp.bid_request_info, 'network_type')"),
    "region_code": Dimension("region_code", "element_at(imp.bid_request_info, 'region_code')"),
    "wait": Dimension("wait", "element_at(imp.impression_args, 'w')"),
    "instl": Dimension("instl", "element_at(imp.impression_args, 'instl')"),
    "rewarded": Dimension("rewarded", "element_at(imp.req_info, 'rewarded')"),
    "skippable": Dimension("skippable", "element_at(imp.req_info, 'skippable')", default_value="false"),
    "has_video": Dimension("has_video", "element_at(imp.bid_imp_info, 'has_video')"),
    "has_banner": Dimension("has_banner", "element_at(imp.bid_imp_info, 'has_banner')"),
    "h": Dimension("h", "element_at(imp.impression_args, 'h')"),
    "is_native": Dimension("is_native", "element_at(imp.bid_imp_info, 'is_native')"),
    "tps": Dimension("tps", "element_at(imp.bid_imp_info, 'tps')"),
    "ask_sup": Dimension("ask_sup", "element_at(imp.bid_imp_info, 'ask_sup')"),
    "pcta_sup": Dimension("pcta_sup", "element_at(imp.bid_imp_info, 'pcta_sup')"),
}


def get_dimension(name: str) -> Dimension:
    normalized = name.strip().lower()
    if normalized not in DIMENSIONS:
        allowed = ", ".join(sorted(DIMENSIONS))
        raise ValueError(f"Unsupported dimension_name={name!r}. Allowed values: {allowed}")
    return DIMENSIONS[normalized]


def parse_dimension_names(value: str | list[str] | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        raw_names = []
        for item in value:
            raw_names.extend(str(item).replace("+", ",").split(","))
    else:
        raw_names = str(value).replace("+", ",").split(",")

    names = tuple(name.strip().lower() for name in raw_names if name.strip())
    if not names:
        raise ValueError("At least one dimension name is required.")

    seen = set()
    deduped = []
    for name in names:
        if name in seen:
            continue
        get_dimension(name)
        seen.add(name)
        deduped.append(name)
    return tuple(deduped)


def get_dimensions(names: str | list[str] | tuple[str, ...]) -> list[Dimension]:
    return [get_dimension(name) for name in parse_dimension_names(names)]


def dimension_key(names: str | list[str] | tuple[str, ...]) -> str:
    return "_".join(parse_dimension_names(names))


def segment_columns(dimension_names: str | list[str] | tuple[str, ...], include_country_code: bool) -> list[str]:
    cols: list[str] = []
    if include_country_code:
        cols.append("country_code")
    cols.extend(dim.name for dim in get_dimensions(dimension_names))
    return cols
