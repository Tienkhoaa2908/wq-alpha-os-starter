from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OperatorSpec:
    minimum_args: int
    maximum_args: int | None
    allowed_kwargs: frozenset[str] = frozenset()
    group_positions: tuple[int, ...] = ()


def spec(
    minimum: int,
    maximum: int | None = None,
    kwargs: tuple[str, ...] = (),
    group_positions: tuple[int, ...] = (),
) -> OperatorSpec:
    return OperatorSpec(minimum, maximum if maximum is not None else minimum, frozenset(kwargs), group_positions)


SPECS: dict[str, OperatorSpec] = {
    "abs": spec(1),
    "add": spec(2, 99, ("filter",)),
    "subtract": spec(2, 99, ("filter",)),
    "multiply": spec(2, 99, ("filter",)),
    "divide": spec(2),
    "inverse": spec(1),
    "log": spec(1),
    "max": spec(2, 99),
    "min": spec(2, 99),
    "power": spec(2),
    "reverse": spec(1),
    "sign": spec(1),
    "signed_power": spec(2),
    "sqrt": spec(1),
    "std": spec(1),
    "normalize": spec(1, 1, ("usestd", "limit")),
    "quantile": spec(1, 1, ("driver", "sigma")),
    "rank": spec(1, 1, ("rate",)),
    "scale": spec(1, 1, ("scale", "longscale", "shortscale")),
    "winsorize": spec(1, 1, ("std",)),
    "zscore": spec(1),
    "densify": spec(1),
    "group_backfill": spec(3, 3, ("std",), (1,)),
    "group_mean": spec(3, 3, (), (2,)),
    "group_neutralize": spec(2, 2, (), (1,)),
    "group_rank": spec(2, 2, (), (1,)),
    "group_scale": spec(2, 2, (), (1,)),
    "group_zscore": spec(2, 2, (), (1,)),
    "bucket": spec(1, 1, ("buckets", "range", "skipboth", "nangroup")),
    "trade_when": spec(3),
    "if_else": spec(3),
    "and": spec(2),
    "or": spec(2),
    "not": spec(1),
    "is_nan": spec(1),
    "hump": spec(1, 1, ("hump",)),
    "days_from_last_change": spec(1),
    "kth_element": spec(3, 3, ("ignore",)),
    "last_diff_value": spec(2),
    "ts_arg_max": spec(2),
    "ts_arg_min": spec(2),
    "ts_av_diff": spec(2),
    "ts_backfill": spec(1, 2, ("lookback", "d", "k")),
    "ts_corr": spec(3),
    "ts_count_nans": spec(2),
    "ts_covariance": spec(3),
    "ts_decay_linear": spec(2, 2, ("dense",)),
    "ts_delay": spec(2),
    "ts_delta": spec(2),
    "ts_mean": spec(2),
    "ts_product": spec(2),
    "ts_quantile": spec(2, 2, ("driver",)),
    "ts_rank": spec(2, 2, ("constant",)),
    "ts_regression": spec(3, 3, ("lag", "rettype")),
    "ts_scale": spec(2, 2, ("constant",)),
    "ts_std_dev": spec(2),
    "ts_step": spec(1),
    "ts_sum": spec(2),
    "ts_zscore": spec(2),
    "vec_avg": spec(1),
    "vec_sum": spec(1),
}


GROUP_IDENTIFIERS = {
    "market",
    "sector",
    "industry",
    "subindustry",
    "country",
    "exchange",
    "currency",
}

LITERALS = {
    "true",
    "false",
    "nan",
    "gaussian",
    "uniform",
    "cauchy",
}
