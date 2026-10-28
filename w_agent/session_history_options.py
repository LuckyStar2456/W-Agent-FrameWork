"""Pure shared options for built-in CLI/TUI history policies, without authority."""

from __future__ import annotations

from dataclasses import dataclass

from w_agent.session_context import RecordedSessionHistoryPolicy
from w_agent.session_message_fields import MessageFieldsSessionInputDecoder
from w_agent.session_context_templates import (
    ExtractiveSessionHistorySummarizer,
    RetrievedSessionHistoryPolicy,
    SessionHistoryLimits,
    SummarizedSessionHistoryPolicy,
)


@dataclass(frozen=True, slots=True)
class BuiltinSessionHistoryOptions:
    """Validate explicit built-in selection, never load custom code or grant consent.

    None means unspecified; settings for other modes are rejected, not ignored.
    Python hosts can bypass this convenience object and inject any history policy.
    """

    mode: str = "text"
    query: str | None = None
    recent_turns: int | None = None
    retrieved_turns: int | None = None
    summary_chars: int | None = None
    max_output_bytes: int | None = None
    include_name: bool = False
    include_metadata: bool = False

    def __post_init__(self) -> None:
        if type(self.include_name) is not bool or type(self.include_metadata) is not bool:
            raise ValueError("history field selections must be booleans")
        if (self.include_name or self.include_metadata) and self.mode != "recorded":
            raise ValueError("history field reuse requires recorded mode")
        if not isinstance(self.mode, str) or self.mode not in {"text", "recorded", "none", "retrieved", "summarized"}:
            raise ValueError("history must be text, recorded, none, retrieved, or summarized")
        template_values = (self.query, self.recent_turns, self.retrieved_turns,
                           self.summary_chars, self.max_output_bytes)
        if self.mode in {"text", "recorded", "none"}:
            if any(value is not None for value in template_values):
                raise ValueError("history template settings require retrieved or summarized mode")
            return
        if self.mode == "retrieved":
            if not isinstance(self.query, str) or not self.query.strip():
                raise ValueError("retrieved history requires an explicit nonempty query")
            if self.summary_chars is not None:
                raise ValueError("summary characters require summarized history")
        elif self.query is not None or self.retrieved_turns is not None:
            raise ValueError("query and retrieved turn count require retrieved history")
        # Constructors are pure. Validate before callers read inputs or load tools.
        try:
            self.runtime_options()
        except (TypeError, ValueError):
            raise ValueError("history template limits or query are invalid") from None

    def runtime_options(self) -> dict[str, object]:
        """Fresh Runtime kwargs; callers must independently authorize their use."""

        if self.mode == "none":
            return {"include_history": False}
        if self.mode == "text":
            return {}
        if self.mode == "recorded":
            decoder = MessageFieldsSessionInputDecoder(
                include_name=self.include_name, include_metadata=self.include_metadata,
            )
            return {"history_policy": RecordedSessionHistoryPolicy(
                decoder=decoder,
                fields_decoder=decoder if self.include_name or self.include_metadata else None,
            )}
        limits = SessionHistoryLimits(
            max_output_bytes=64 * 1024 if self.max_output_bytes is None else self.max_output_bytes,
        )
        recent = 2 if self.recent_turns is None else self.recent_turns
        if self.mode == "retrieved":
            assert self.query is not None  # Validated at construction.
            return {"history_policy": RetrievedSessionHistoryPolicy(
                query=self.query,
                recent_turns=recent,
                max_retrieved_turns=4 if self.retrieved_turns is None else self.retrieved_turns,
                limits=limits,
            )}
        return {"history_policy": SummarizedSessionHistoryPolicy(
            recent_turns=recent,
            summarizer=ExtractiveSessionHistorySummarizer(
                max_chars=4096 if self.summary_chars is None else self.summary_chars,
            ),
            limits=limits,
        )}
