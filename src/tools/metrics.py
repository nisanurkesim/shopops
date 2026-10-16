# Ops tools on the semantic layer (brief sections 5.3 and 5.4): list_metrics, run_metric
# run_metric builds the SQL from src/knowledge/metrics.yaml. Metric and dimension names
# must be in the YAML; filter values are always bound as parameters, never pasted into
# the SQL. The database is opened read-only.
from contextlib import closing
from functools import lru_cache
from pathlib import Path

import yaml

from config import DB_PATH, SIMULATED_TODAY
from src.tools.orders import connect_read_only

METRICS_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "metrics.yaml"
MAX_GROUP_BY = 2
MAX_ROWS = 1000


@lru_cache(maxsize=None)
def load_semantic_layer(path: Path = METRICS_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def list_metrics(path: Path = METRICS_PATH) -> dict:
    """Metric names, descriptions and allowed dimensions, for the agent to choose from."""
    layer = load_semantic_layer(path)
    return {
        "metrics": [{"name": name, "description": m["description"], "dimensions": m["dimensions"]}
                    for name, m in layer["metrics"].items()],
        "dimensions": {name: d["description"] for name, d in layer["dimensions"].items()},
    }


def dimension_join(dimension: dict, grain: str) -> str:
    join = dimension["join"]
    return join[grain] if isinstance(join, dict) else join


def build_metric_sql(name: str, filters: dict | None = None, group_by: list | None = None,
                     min_n: int | None = None, sort: str | None = None, limit: int | None = None,
                     path: Path = METRICS_PATH) -> tuple[str, dict] | dict:
    """SQL and parameters for one metric, or an error dict. Runs nothing.

    With group_by, min_n keeps the groups with at least that many orders (HAVING), sort
    ("desc" or "asc") orders the groups by the metric, and limit keeps the first rows. So
    "top 5 categories with at least 100 orders" uses the official definition too.
    """
    layer = load_semantic_layer(path)
    metric = layer["metrics"].get(name)
    if metric is None:
        return {"error": "UNKNOWN_METRIC", "message": f"There is no metric called '{name}'.",
                "metrics": list(layer["metrics"])}
    filters = dict(filters or {})
    group_by = list(group_by or [])
    if len(group_by) > MAX_GROUP_BY:
        return {"error": "TOO_MANY_GROUPS", "message": f"Group by at most {MAX_GROUP_BY} dimensions."}
    for dim in list(filters) + group_by:
        if dim not in metric["dimensions"]:
            return {"error": "UNKNOWN_DIMENSION",
                    "message": f"'{dim}' is not a dimension of {name}.", "dimensions": metric["dimensions"]}
    for dim, value in filters.items():
        if not isinstance(value, (str, int, float)):
            return {"error": "INVALID_FILTER", "message": f"The filter value for '{dim}' must be one value."}
    if (min_n is not None or sort is not None) and not group_by:
        return {"error": "NEEDS_GROUP_BY", "message": "min_n and sort only work together with group_by."}
    if sort is not None and sort not in ("desc", "asc"):
        return {"error": "INVALID_SORT", "message": "sort must be 'desc' or 'asc'."}
    try:
        min_n = None if min_n is None else int(min_n)
        limit = None if limit is None else int(limit)
    except (TypeError, ValueError):
        return {"error": "INVALID_NUMBER", "message": "min_n and limit must be whole numbers."}
    if (min_n is not None and min_n < 1) or (limit is not None and not 1 <= limit <= MAX_ROWS):
        return {"error": "INVALID_NUMBER", "message": f"min_n must be at least 1 and limit between 1 and {MAX_ROWS}."}

    grain = metric["grain"]
    from_sql = "FROM orders AS o" if grain == "order" else \
        "FROM order_items AS oi JOIN orders AS o ON o.order_id = oi.order_id"
    joins = [metric["join"]] if metric.get("join") else []
    for dim in dict.fromkeys(list(filters) + group_by):   # each dimension joined once
        join = dimension_join(layer["dimensions"][dim], grain)
        if join:
            joins.append(join)

    where = [f"({metric['base_filter']})"]
    params = {"simulated_today": SIMULATED_TODAY}
    for i, (dim, value) in enumerate(filters.items()):
        where.append(f"{layer['dimensions'][dim]['column']} = :f{i}")
        params[f"f{i}"] = str(value)

    if "value" in metric:
        raw_sql = metric["value"]
        n_sql = "COUNT(DISTINCT o.order_id)"
    else:
        raw_sql = f"1.0 * {metric['numerator']} / {metric['denominator']}"
        n_sql = metric["denominator"]
    decimals = metric.get("decimals", 0 if "value" in metric else 4)
    value_sql = f"ROUND({raw_sql}, {decimals})" if decimals else raw_sql

    group_cols = [f"{layer['dimensions'][dim]['column']} AS {dim}" for dim in group_by]
    select = group_cols + [f"{value_sql} AS {name}", f"{n_sql} AS n"]
    sql = f"SELECT {', '.join(select)}\n{from_sql}\n"
    if joins:
        sql += "\n".join(joins) + "\n"
    sql += "WHERE " + "\n  AND ".join(where)
    if group_by:
        sql += f"\nGROUP BY {', '.join(group_by)}"
        if min_n is not None:
            sql += f"\nHAVING {n_sql} >= :min_n"
            params["min_n"] = min_n
        # Sort on the unrounded value: two groups shown as 0.0805 are not a tie
        order = f"{raw_sql} {sort.upper()}, " if sort else ""
        sql += f"\nORDER BY {order}{', '.join(group_by)}"
    sql += f"\nLIMIT {limit or MAX_ROWS}"
    return sql, params


def run_metric(name: str, filters: dict | None = None, group_by: list | None = None,
               min_n: int | None = None, sort: str | None = None, limit: int | None = None,
               db_path: Path = DB_PATH, path: Path = METRICS_PATH) -> dict:
    """Run one metric. Returns the rows, the SQL that produced them and the metric's caveat."""
    built = build_metric_sql(name, filters, group_by, min_n, sort, limit, path)
    if isinstance(built, dict):
        return built
    sql, params = built
    with closing(connect_read_only(db_path)) as con:
        cursor = con.execute(sql, params)
        columns = [c[0] for c in cursor.description]
        rows = [list(r) for r in cursor.fetchall()]
    metric = load_semantic_layer(path)["metrics"][name]
    return {
        "metric": name, "description": metric["description"],
        "filters": filters or {}, "group_by": group_by or [],
        "columns": columns, "rows": rows, "row_count": len(rows),
        "sql": sql, "caveat": metric["caveat"],
    }
