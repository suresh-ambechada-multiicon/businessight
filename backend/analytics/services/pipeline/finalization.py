from __future__ import annotations

import time
from typing import Generator

from analytics.services.logger import get_logger
from analytics.services.pipeline.serialization import deep_sanitize, sanitize_row
from analytics.services.tokens import count_tokens

logger = get_logger("pipeline")


class PipelineFinalizer:
    def __init__(self, *, history_entry, ctx):
        self.history_entry = history_entry
        self.ctx = ctx

    @staticmethod
    def merge_usage(*parts: dict | None) -> dict:
        merged = {
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
            "estimated_cost": 0.0,
        }
        for part in parts:
            if not isinstance(part, dict):
                continue
            merged["input_tokens"] += int(part.get("input_tokens") or 0)
            merged["output_tokens"] += int(part.get("output_tokens") or 0)
            merged["thinking_tokens"] += int(part.get("thinking_tokens") or 0)
            merged["estimated_cost"] += float(part.get("estimated_cost") or 0)
        return merged

    def finalize(
        self,
        *,
        result: dict,
        budget: dict,
        model_config,
        stream_data: dict,
    ) -> Generator[dict, None, None]:
        exec_time = time.time() - self.ctx.start_time
        usage = self._usage(result, budget, model_config, stream_data)
        self._save_result(result, exec_time, usage)

        yield {"event": "usage", "data": usage}
        yield {
            "event": "result",
            "data": {
                **result,
                "execution_time": exec_time,
                "usage": {
                    "input_tokens": usage["input_tokens"],
                    "output_tokens": usage["output_tokens"],
                    "thinking_tokens": usage["thinking_tokens"],
                },
                "done": True,
            },
        }
        logger.info(
            "Pipeline completed",
            extra={
                "data": {
                    **self.ctx.to_dict(),
                    "total_time_ms": round(exec_time * 1000, 2),
                }
            },
        )

    def cancel(self):
        if not self.history_entry:
            return
        self.history_entry.report = "_Analysis cancelled by user._"
        self.history_entry.execution_time = -1
        self.history_entry.save()

    def mark_error(self, error: Exception):
        if not self.history_entry:
            return
        err_msg = str(error)
        self.history_entry.report = f"Error: {err_msg}"
        self.history_entry.execution_time = self.history_entry.execution_time or 0.1
        self.history_entry.save()

    def _usage(self, result: dict, budget: dict, model_config, stream_data: dict) -> dict:
        actual_usage = result.pop("_actual_usage", None) if isinstance(result, dict) else None
        if not actual_usage and isinstance(stream_data, dict) and stream_data.get("usage"):
            actual_usage = self._usage_from_stream(stream_data["usage"], model_config)

        if self._has_usage(actual_usage):
            return {
                "input_tokens": int(actual_usage.get("input_tokens") or 0),
                "output_tokens": int(actual_usage.get("output_tokens") or 0),
                "thinking_tokens": int(actual_usage.get("thinking_tokens") or 0),
                "estimated_cost": round(float(actual_usage.get("estimated_cost") or 0), 6),
            }
        return self._estimated_usage(result, budget, model_config, stream_data)

    @staticmethod
    def _usage_from_stream(stream_usage: dict, model_config) -> dict | None:
        if not (stream_usage.get("input_tokens") or stream_usage.get("output_tokens")):
            return None
        input_tokens = stream_usage.get("input_tokens", 0)
        output_tokens = stream_usage.get("output_tokens", 0)
        thinking_tokens = stream_usage.get("thinking_tokens", 0)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "thinking_tokens": thinking_tokens,
            "estimated_cost": (input_tokens / 1_000_000) * model_config.cost_per_1m_input
            + ((output_tokens + thinking_tokens) / 1_000_000)
            * model_config.cost_per_1m_output,
        }

    @staticmethod
    def _has_usage(usage: dict | None) -> bool:
        return isinstance(usage, dict) and bool(
            usage.get("input_tokens")
            or usage.get("output_tokens")
            or usage.get("estimated_cost")
        )

    @staticmethod
    def _estimated_usage(result: dict, budget: dict, model_config, stream_data: dict) -> dict:
        out_tokens = int(
            (
                count_tokens(stream_data.get("full_content", ""))
                + count_tokens(stream_data.get("full_tool_args_str", ""))
                + count_tokens(result.get("report", ""))
            )
            * 1.05
        )
        initial_in = int(budget["total_used"])
        steps = int(stream_data.get("steps_count") or 0)
        in_tokens = int(
            (initial_in * (steps + 1))
            + (stream_data.get("history_tokens_acc", 0) * (steps / 2)) * 1.1
        )
        cost = (in_tokens / 1_000_000) * model_config.cost_per_1m_input + (
            out_tokens / 1_000_000
        ) * model_config.cost_per_1m_output
        return {
            "input_tokens": in_tokens,
            "output_tokens": out_tokens,
            "thinking_tokens": 0,
            "estimated_cost": round(cost, 6),
        }

    def _save_result(self, result: dict, exec_time: float, usage: dict) -> None:
        self.history_entry.report = result["report"]
        self.history_entry.chart_config = result["chart_config"]
        self.history_entry.raw_data = (
            [sanitize_row(row) for row in result["raw_data"]]
            if isinstance(result.get("raw_data"), list)
            else None
        )
        self.history_entry.sql_query = result["sql_query"]
        self.history_entry.execution_time = exec_time
        self.history_entry.input_tokens = usage["input_tokens"]
        self.history_entry.output_tokens = usage["output_tokens"]
        self.history_entry.thinking_tokens = usage["thinking_tokens"]
        self.history_entry.thinking_steps = result.get("thinking_steps")
        self.history_entry.estimated_cost = usage["estimated_cost"]
        self.history_entry.result_blocks = deep_sanitize(result.get("result_blocks"))
        self.history_entry.save()
