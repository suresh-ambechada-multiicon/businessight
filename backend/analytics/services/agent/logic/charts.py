"""Chart validation and fallback chart generation."""

from decimal import Decimal

from analytics.services.logger import get_logger

logger = get_logger("agent")


def _is_flag_or_boolean_column(key: str, sample_values: list) -> bool:
    """Check if a column is a boolean flag that shouldn't be charted."""
    flag_prefixes = ("is_", "has_", "can_", "should_", "was_", "did_")
    flag_names = (
        "active",
        "blocked",
        "deleted",
        "enabled",
        "archived",
        "verified",
        "status",
    )
    key_lower = key.lower()

    if any(key_lower.startswith(p) for p in flag_prefixes):
        return True
    if key_lower in flag_names:
        return True

    # Check if all values are 0/1 or True/False
    unique_vals = set(sample_values)
    if unique_vals <= {0, 1, 0.0, 1.0, True, False, None}:
        return True

    return False


def _is_id_or_key_column(key: str) -> bool:
    """Check if a column is an ID/key that shouldn't be charted."""
    key_lower = key.lower()
    if key_lower == "id" or key_lower.endswith("_id") or key_lower.endswith("_pk"):
        return True
    if key_lower in ("pk", "key", "uuid", "guid"):
        return True
    return False


def _validate_chart_config(
    chart_config: dict | None, raw_data: list | None
) -> dict | None:
    """
    Validate and clean a chart config (AI-generated or auto-generated).
    Removes useless datasets (no variance, boolean flags) and returns None
    if no valid datasets remain.
    """
    if not chart_config or not isinstance(chart_config, dict):
        return chart_config

    data_obj = chart_config.get("data", {})
    if not data_obj:
        return None

    datasets = data_obj.get("datasets", [])
    labels = data_obj.get("labels", [])

    if not datasets or not labels:
        return None

    # Get sample values from raw_data for flag detection
    sample_values_map = {}
    if raw_data and isinstance(raw_data, list) and len(raw_data) > 0:
        for key in raw_data[0]:
            sample_values_map[key] = [row.get(key) for row in raw_data[:50]]

    # Filter out useless datasets
    valid_datasets = []
    for ds in datasets:
        label = ds.get("label", "")
        data_points = ds.get("data", [])

        # Skip if no data
        if not data_points:
            continue

        # Skip if no variance (all same value)
        numeric_points = [p for p in data_points if isinstance(p, (int, float))]
        if numeric_points and len(set(numeric_points)) <= 1:
            continue

        # Skip boolean/flag columns
        original_key = label.lower().replace(" ", "_")
        sample = sample_values_map.get(original_key, numeric_points)
        if _is_flag_or_boolean_column(original_key, sample):
            continue

        # Skip ID columns
        if _is_id_or_key_column(original_key):
            continue

        valid_datasets.append(ds)

    if not valid_datasets:
        return None

    chart_config["data"]["datasets"] = valid_datasets
    return chart_config


def auto_generate_chart(chart_config, raw_data, query="") -> dict | list | None:
    """
    Fallback chart generation when the AI doesn't produce one.
    Accepts a single chart dict, a list of chart dicts (multi-chart reports), or None.

    KEY PRINCIPLE: Only auto-generate charts from AGGREGATED data (few rows
    with clear categories + numeric values). NEVER chart raw individual records
    (e.g. 1000 agent rows) — that data belongs in the data grid, not a chart.

    The AI should generate chart_config itself for analytical queries since
    only the AI understands what the user asked for.
    """
    if isinstance(chart_config, list):
        out: list[dict] = []
        for item in chart_config:
            if not isinstance(item, dict):
                continue
            one = _auto_generate_single_chart(item, raw_data, query)
            if one:
                out.append(one)
        if len(out) > 1:
            return out
        if len(out) == 1:
            return out[0]
        return None
    return _auto_generate_single_chart(chart_config, raw_data, query)


def _auto_generate_single_chart(chart_config, raw_data, query="") -> dict | None:
    """Validate or synthesize one chart from ``raw_data``."""
    allowed_types = {
        "bar",
        "stacked-bar",
        "line",
        "area",
        "stacked-area",
        "pie",
        "radar",
        "radial",
        "scatter",
        "composed",
    }
    requested_type = ""
    requested_x_label = ""
    requested_y_label = ""
    if chart_config and isinstance(chart_config, dict):
        requested_type = str(chart_config.get("type") or "").strip().lower()
        if requested_type not in allowed_types:
            requested_type = ""
        requested_x_label = str(chart_config.get("x_label") or "").strip()
        requested_y_label = str(chart_config.get("y_label") or "").strip()

    # First validate any AI-generated chart
    if chart_config and isinstance(chart_config, dict):
        data_obj = chart_config.get("data", {})
        has_content = data_obj.get("labels") and data_obj.get("datasets")
        if has_content:
            # AI generated a chart — validate it (remove flag/boolean datasets)
            return _validate_chart_config(chart_config, raw_data)

    if not raw_data or not isinstance(raw_data, list) or len(raw_data) < 2:
        return None

    try:
        all_keys = list(raw_data[0].keys())

        # Prefer time-series + category multi-series when shape looks like:
        # (time/month/date) + (category/company/supplier) + (numeric metric)
        def _is_time_key(k: str) -> bool:
            kl = k.lower()
            return any(
                x in kl for x in ("month", "date", "time", "day", "year", "week")
            )

        def _is_time_val(v) -> bool:
            if v is None:
                return False
            if hasattr(v, "isoformat"):
                return True
            if isinstance(v, str):
                s = v.strip()
                return len(s) >= 7 and (s[4] == "-" or "t" in s.lower())
            return False

        time_key = next((k for k in all_keys if _is_time_key(k)), None)
        if not time_key:
            for k in all_keys:
                if _is_id_or_key_column(k):
                    continue
                if _is_time_val(raw_data[0].get(k)):
                    time_key = k
                    break

        # Category key: prefer human-readable string columns. If none, allow id-like ints
        # (e.g. supplier_id) so we still plot multi-series by supplier.
        cat_key = next(
            (
                k
                for k in all_keys
                if k != time_key
                and not _is_id_or_key_column(k)
                and isinstance(raw_data[0].get(k), str)
            ),
            None,
        )
        if not cat_key:
            cat_key = next(
                (
                    k
                    for k in all_keys
                    if k != time_key
                    and k.lower().endswith("_id")
                    and isinstance(raw_data[0].get(k), (int, float))
                ),
                None,
            )

        value_key = next(
            (
                k
                for k in all_keys
                if k not in (time_key, cat_key)
                and not _is_id_or_key_column(k)
                and isinstance(raw_data[0].get(k), (int, float, Decimal))
                and not _is_flag_or_boolean_column(
                    k, [row.get(k) for row in raw_data[:50]]
                )
            ),
            None,
        )

        if time_key and cat_key and value_key:
            # Build labels by time, datasets by top categories
            def _time_str(v) -> str:
                if v is None:
                    return ""
                if hasattr(v, "isoformat"):
                    return v.isoformat()
                return str(v)

            times = sorted(
                {
                    _time_str(r.get(time_key))
                    for r in raw_data
                    if r.get(time_key) is not None
                }
            )
            times = [t for t in times if t][:30]
            if len(times) >= 2:
                totals: dict[str, float] = {}
                for r in raw_data:
                    c = str(r.get(cat_key, "") or "")
                    if not c:
                        continue
                    totals[c] = totals.get(c, 0.0) + float(r.get(value_key, 0) or 0)
                top_cats = [
                    k
                    for k, _ in sorted(
                        totals.items(), key=lambda x: x[1], reverse=True
                    )[:6]
                ]

                # map (time, cat) -> value
                grid: dict[tuple[str, str], float] = {}
                for r in raw_data:
                    t = _time_str(r.get(time_key))
                    c = str(r.get(cat_key, "") or "")
                    if t in times and c in top_cats:
                        grid[(t, c)] = grid.get((t, c), 0.0) + float(
                            r.get(value_key, 0) or 0
                        )

                datasets = []
                for c in top_cats:
                    pts = [grid.get((t, c), 0.0) for t in times]
                    if len(set(pts)) > 1:
                        datasets.append({"label": c, "data": pts})

                if datasets:
                    return {
                        "type": requested_type or "line",
                        "x_label": requested_x_label or time_key.replace("_", " ").title(),
                        "y_label": requested_y_label or value_key.replace("_", " ").title(),
                        "data": {"labels": times, "datasets": datasets},
                    }

        # Find label key (first non-ID string column)
        label_key = None
        for k in all_keys:
            if _is_id_or_key_column(k):
                continue
            sample_val = raw_data[0].get(k)
            if isinstance(sample_val, str):
                label_key = k
                break
        if not label_key:
            label_key = next(
                (k for k in all_keys if not _is_id_or_key_column(k)), all_keys[0]
            )

        # Find chartable numeric columns
        value_keys = []
        for k in all_keys:
            if _is_id_or_key_column(k) or k == label_key:
                continue
            sample_val = raw_data[0].get(k)
            if not isinstance(sample_val, (int, float, Decimal)):
                continue
            sample_values = [row.get(k) for row in raw_data[:50]]
            if _is_flag_or_boolean_column(k, sample_values):
                continue
            value_keys.append(k)

        if not value_keys:
            return None

        # Aggregate data: sum numeric values for duplicate labels
        from collections import OrderedDict

        agg: dict[str, dict[str, float]] = OrderedDict()
        for row in raw_data:
            lbl = str(row.get(label_key, ""))
            if lbl not in agg:
                agg[lbl] = {vk: 0.0 for vk in value_keys}
            for vk in value_keys:
                agg[lbl][vk] += float(row.get(vk, 0) or 0)

        labels = list(agg.keys())[:30]
        datasets = []
        for vk in value_keys[:5]:
            data_points = [agg[lbl][vk] for lbl in labels]
            if len(set(data_points)) > 1:
                datasets.append(
                    {
                        "label": vk.replace("_", " ").title(),
                        "data": data_points,
                    }
                )

        if not datasets:
            return None

        chart_type = requested_type or (
            "line"
            if any(
                k.lower() in label_key.lower()
                for k in ["date", "time", "month", "year"]
            )
            else "bar"
        )
        y_label = requested_y_label or (
            value_keys[0].replace("_", " ").title()
            if len(value_keys) == 1
            else "Value"
        )
        chart_config = {
            "type": chart_type,
            "x_label": requested_x_label or label_key.replace("_", " ").title(),
            "y_label": y_label,
            "data": {"labels": labels, "datasets": datasets},
        }

        logger.info(
            "Auto-generated chart",
            extra={
                "data": {
                    "chart_type": chart_type,
                    "data_points": len(labels),
                    "datasets": len(datasets),
                }
            },
        )

    except Exception:
        pass

    # Final cleanup
    if chart_config and isinstance(chart_config, dict) and not chart_config.get("data"):
        chart_config = None

    return chart_config
