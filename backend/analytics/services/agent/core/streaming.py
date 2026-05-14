"""Streaming loop for the deep analytics agent."""

import json
import time
from typing import Any, Dict, Generator, List, Optional

from django.core.cache import cache
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.utils.json import parse_partial_json

from analytics.services.agent.core.state import StreamResult
from analytics.services.logger import get_logger

logger = get_logger("agent")


def _is_transient_llm_error(exc: Exception) -> bool:
    """Return True for provider errors that are usually fixed by retrying."""
    err = str(exc).lower()
    return any(
        marker in err
        for marker in (
            "503",
            "unavailable",
            "service unavailable",
            "high demand",
            "temporarily unavailable",
            "try again later",
            "rate limit",
            "timeout",
            "timed out",
        )
    )


def _is_agent_budget_error(exc: Exception) -> bool:
    """Return True for local graph/time budget errors, not provider rate limits."""
    err = str(exc).lower()
    name = type(exc).__name__.lower()
    return any(
        marker in err or marker in name
        for marker in (
            "recursion",
            "graphrecursion",
            "recursion_limit",
            "time budget",
            "token budget",
        )
    )


class StreamProcessor:
    """Manages the state and logic for processing an agent stream."""

    def __init__(self, result_holder: StreamResult, ctx: Optional[Any] = None):
        self.result_holder = result_holder
        self.ctx = ctx
        self._ctx_dict = ctx.to_dict() if ctx else {}
        self.start_time = time.time()

        # Accumulators
        self.full_content = ""
        self.full_tool_args_str = ""
        self.last_tool_args: Dict[str, Any] = {}
        self.last_non_empty_report = ""
        self.last_yielded_report = ""
        self.usage = {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0}
        self.steps_count = 0
        self.history_tokens_acc = 0

    def handle_ai_message(
        self, msg: AIMessage
    ) -> Generator[Dict[str, Any], None, None]:
        """Process content and tool chunks from an AIMessage."""
        # 1. Accumulate text content
        if msg.content:
            if isinstance(msg.content, list):
                for part in msg.content:
                    if isinstance(part, dict) and "text" in part:
                        self.full_content += part["text"]
                    elif isinstance(part, str):
                        self.full_content += part
            else:
                self.full_content += msg.content

        # 1.5. Accumulate usage metadata
        if hasattr(msg, "usage_metadata") and msg.usage_metadata:
            u = msg.usage_metadata
            self.usage["input_tokens"] += u.get("input_tokens") or 0
            self.usage["output_tokens"] += u.get("output_tokens") or 0
            # Some providers use specific fields for thinking/reasoning tokens
            self.usage["thinking_tokens"] += (
                u.get("thinking_tokens") 
                or u.get("reasoning_tokens") 
                or 0
            )

        # 2. Process tool call chunks (for partial reports)
        if hasattr(msg, "tool_call_chunks") and msg.tool_call_chunks:
            for chunk in msg.tool_call_chunks:
                self.full_tool_args_str += chunk.get("args", "")
                yield from self._extract_partial_report(self.full_tool_args_str)

        # 3. Process completed tool calls
        if msg.tool_calls:
            for tc in msg.tool_calls:
                if tc["name"] in ["AnalyticsResponse", "structured_response"]:
                    self.last_tool_args = tc.get("args", {})
                    if isinstance(
                        self.last_tool_args, dict
                    ) and self.last_tool_args.get("report"):
                        self.last_non_empty_report = self.last_tool_args["report"]
                        yield from self._yield_report_if_changed()

        # 4. Extract report from accumulated JSON content
        if self.full_content:
            yield from self._extract_partial_report(self.full_content)

    def handle_tool_execution(self, msg: Any) -> Generator[Dict[str, Any], None, None]:
        """Track and yield events for tool execution chunks."""
        if isinstance(msg, ToolMessage):
            # Accumulate tool result tokens for estimation
            from analytics.services.tokens import count_tokens
            # Tool results are often large, we cap the estimation impact slightly to be conservative
            self.history_tokens_acc += count_tokens(str(msg.content))
            return

        if not (hasattr(msg, "tool_calls") and msg.tool_calls):
            return

        # For manual token estimation if provider metadata is missing
        # Each AIMessage with tool_calls represents ONE LLM turn
        self.steps_count += 1

        for tc in msg.tool_calls:
            raw_args = tc.get("args") or {}
            args = self._parse_args(raw_args)
            name = tc["name"]

            if name in ["AnalyticsResponse", "structured_response"]:
                continue

            # Trace and yield execution event
            self.result_holder.trace.append(
                {
                    "t": time.time(),
                    "name": name,
                    "sql_preview": args.get("query", "")[:500]
                    if name.endswith("sql")
                    else None,
                }
            )

            yield {
                "event": "tool",
                "data": {"name": name, "args": args if name.endswith("sql") else None},
            }
            
            # Roughly estimate the tokens of this tool call overhead
            from analytics.services.tokens import count_tokens
            self.history_tokens_acc += count_tokens(json.dumps(args)) + 50 

    def _parse_args(self, raw_args: Any) -> Dict[str, Any]:
        if isinstance(raw_args, str):
            try:
                return json.loads(raw_args) if raw_args.strip() else {}
            except:
                return {}
        return raw_args if isinstance(raw_args, dict) else {}

    def _extract_partial_report(
        self, json_str: str
    ) -> Generator[Dict[str, Any], None, None]:
        try:
            data = parse_partial_json(json_str)
            if isinstance(data, dict) and data.get("report"):
                self.last_non_empty_report = data["report"]
                yield from self._yield_report_if_changed()
        except:
            pass

    def _yield_report_if_changed(self) -> Generator[Dict[str, Any], None, None]:
        if self.last_non_empty_report != self.last_yielded_report:
            self.last_yielded_report = self.last_non_empty_report
            yield {
                "event": "report",
                "data": {"content": self.last_yielded_report, "partial": True},
            }

    def finalize(self):
        """Store final state in result_holder."""
        self.result_holder.data = {
            "full_content": self.full_content,
            "full_tool_args_str": self.full_tool_args_str,
            "last_tool_args": self.last_tool_args,
            "last_non_empty_report": self.last_non_empty_report,
            "trace": list(getattr(self.result_holder, "trace", []) or []),
            "usage": self.usage,
            "steps_count": self.steps_count,
            "history_tokens_acc": self.history_tokens_acc,
        }


def stream_agent(
    agent,
    messages,
    session_id,
    result_holder: StreamResult,
    ctx=None,
    attempt=0,
    processor=None,
):
    """
    Generator that streams agent execution recursively to handle retries efficiently.
    """
    if processor is None:
        processor = StreamProcessor(result_holder, ctx)

    max_retries = 10

    try:
        for msg, _ in agent.stream(
            {"messages": messages},
            stream_mode="messages",
            config={"recursion_limit": 20},
        ):
            # Check time budget & cancellation
            if ctx and ctx.elapsed_ms() > 330_000:
                yield {
                    "event": "status",
                    "data": {"message": "Time budget reached. Finalizing..."},
                }
                break
            if cache.get(f"cancel_{session_id}"):
                result_holder.cancelled = True
                yield {"event": "status", "data": {"message": "Cancelled by user."}}
                cache.delete(f"cancel_{session_id}")
                return

            # Process message content
            if isinstance(msg, AIMessage):
                yield from processor.handle_ai_message(msg)

            # Process tool execution
            yield from processor.handle_tool_execution(msg)

    except (GeneratorExit, StopIteration):
        return
    except Exception as e:
        err_name = type(e).__name__
        err_msg = str(e)

        # Provider 429/rate-limit/timeouts are transient. Handle these before
        # local graph budget errors because provider messages often contain
        # the word "limit".
        if _is_transient_llm_error(e) and attempt < max_retries:
            delay = 2 * (attempt + 1)
            logger.warning(
                f"Transient error, retrying in {delay}s (Attempt {attempt + 1})",
                extra={"data": {**(ctx.to_dict() if ctx else {}), "error": err_msg[:300]}},
            )
            yield {
                "event": "retry",
                "data": {
                    "message": f"Retrying {attempt + 1}/{max_retries}...",
                    "delay": delay,
                },
            }
            time.sleep(delay)
            # RECURSIVE CALL for retry
            yield from stream_agent(
                agent, messages, session_id, result_holder, ctx, attempt + 1, processor
            )
            return

        if _is_transient_llm_error(e):
            result_holder.has_error = True
            logger.error(
                "Transient LLM error retries exhausted",
                exc_info=True,
                extra={"data": {**(ctx.to_dict() if ctx else {}), "error": err_msg[:300]}},
            )
            yield {
                "event": "error",
                "data": {
                    "message": (
                        "The model provider is rate-limiting or temporarily unavailable. "
                        "Please retry in a moment or choose another model."
                    )
                },
            }

        # Handle local agent recursion/time budget errors gracefully.
        elif _is_agent_budget_error(e):
            logger.warning(
                f"Agent hit execution budget: {err_name}",
                extra={"data": {**(ctx.to_dict() if ctx else {}), "error": err_msg[:300]}},
            )

        # Fatal Errors
        else:
            result_holder.has_error = True
            logger.error(f"Stream error: {err_msg}", exc_info=True)
            yield {"event": "error", "data": {"message": f"Error: {err_msg}"}}

    processor.finalize()
