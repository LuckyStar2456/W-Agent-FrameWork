import base64
import hashlib
import json

import pytest

from w_agent import (
    FieldPolicyRunEventProjector,
    MediaProjectionMode,
    MultimodalRunEventProjector,
    NestedFieldRunEventProjector,
    ProjectedRunEventPage,
    RunEvent,
    RunEventCursor,
    RunEventFieldPolicy,
    RunEventPathAction,
    RunEventPathRule,
    RunEventReplay,
    RunEventType,
    RunStoreError,
    SafeRunEventProjector,
)


class PagedSource:
    def __init__(self, events):
        self.recorded = tuple(events)
        self.requests = []

    async def events(self, run_id):
        raise AssertionError("bounded source should not read the whole log")

    async def events_page(self, run_id, after_sequence, limit):
        self.requests.append((run_id, after_sequence, limit))
        selected = self.recorded[after_sequence : after_sequence + limit]
        return selected, after_sequence + len(selected) < len(self.recorded)


class ApplicationProjector:
    def project(self, event):
        return {
            "position": event.sequence,
            "view": (event.type.value, {"approved": True}),
        }


class InvalidProjector:
    def project(self, event):
        return {"event": event}


@pytest.mark.asyncio
async def test_projected_page_defaults_to_content_free_bounded_view():
    events = (
        RunEvent(
            1,
            RunEventType.MODEL_TOOL_CALL_DELTA,
            "run-1",
            {
                "step": 1,
                "block_index": 0,
                "call_id": "secret-call",
                "name": "private-tool",
                "arguments_delta": '{"password":"hidden"}',
            },
        ),
        RunEvent(
            2,
            RunEventType.RUN_COMPLETED,
            "run-1",
            {"stop_reason": "completed", "text": "hidden output"},
        ),
    )
    source = PagedSource(events)

    page = await RunEventReplay(source).projected_page("run-1", limit=1)

    assert isinstance(page, ProjectedRunEventPage)
    assert source.requests == [("run-1", 0, 1)]
    assert page.events[0]["data"] == {"step": 1, "block_index": 0}
    serialized = json.dumps(page.events)
    assert "password" not in serialized
    assert "private-tool" not in serialized
    assert page.next_cursor == RunEventCursor("run-1", 1)
    assert page.has_more is True


@pytest.mark.asyncio
async def test_projected_page_accepts_explicit_application_projector():
    source = PagedSource(
        (RunEvent(1, RunEventType.RUN_STARTED, "run-1", {"agent": "writer"}),)
    )

    page = await RunEventReplay(source).projected_page(
        "run-1",
        projector=ApplicationProjector(),
    )

    assert page.events == (
        {"position": 1, "view": ["run-started", {"approved": True}]},
    )
    assert page.has_more is False


@pytest.mark.asyncio
async def test_field_policy_projector_is_default_deny_and_event_specific():
    events = (
        RunEvent(
            1,
            RunEventType.MODEL_TOOL_CALL_DELTA,
            "run-1",
            {
                "step": 1,
                "name": "lookup",
                "arguments_delta": '{"password":"hidden"}',
                "unlisted": "must-not-pass",
            },
        ),
        RunEvent(
            2,
            RunEventType.RUN_COMPLETED,
            "run-1",
            {"stop_reason": "completed", "output": "must-not-pass"},
        ),
    )
    projector = FieldPolicyRunEventProjector(
        {
            RunEventType.MODEL_TOOL_CALL_DELTA: RunEventFieldPolicy(
                include=("step", "name"),
                mask=("arguments_delta",),
                mask_value="***",
            ),
            "*": RunEventFieldPolicy(include=("stop_reason",)),
        }
    )

    page = await RunEventReplay(PagedSource(events)).projected_page(
        "run-1",
        projector=projector,
        limit=2,
    )

    assert page.events[0]["data"] == {
        "step": 1,
        "name": "lookup",
        "arguments_delta": "***",
    }
    assert page.events[1]["data"] == {"stop_reason": "completed"}
    serialized = json.dumps(page.events)
    assert "password" not in serialized
    assert "must-not-pass" not in serialized


def test_field_policy_rejects_ambiguous_or_unknown_rules():
    denied = FieldPolicyRunEventProjector({}).project(
        RunEvent(
            1,
            RunEventType.MODEL_TEXT_DELTA,
            "run-1",
            {"text": "must-not-pass"},
        )
    )
    assert denied["data"] == {}
    with pytest.raises(ValueError, match="included and masked"):
        RunEventFieldPolicy(include=("text",), mask=("text",))
    with pytest.raises(ValueError, match="invalid event type"):
        FieldPolicyRunEventProjector(
            {"unknown-event": RunEventFieldPolicy(include=("step",))}
        )


def test_nested_projector_copies_masks_and_renames_selected_paths():
    event = RunEvent(
        1,
        RunEventType.MODEL_COMPLETED,
        "run-1",
        {
            "response": {
                "items": [
                    {
                        "label": "visible",
                        "credential": "must-not-pass",
                    }
                ],
                "private": "must-not-pass",
            },
        },
    )
    projector = NestedFieldRunEventProjector(
        {
            RunEventType.MODEL_COMPLETED: (
                RunEventPathRule(
                    ("response", "items", 0, "label"),
                    ("result", "name"),
                ),
                RunEventPathRule(
                    ("response", "items", 0, "credential"),
                    ("result", "credential"),
                    RunEventPathAction.MASK,
                    "***",
                ),
                RunEventPathRule(
                    ("response", "missing"),
                    ("result", "missing"),
                ),
            )
        }
    )

    projected = projector.project(event)

    assert projected["data"] == {
        "result": {"name": "visible", "credential": "***"}
    }
    serialized = json.dumps(projected)
    assert "must-not-pass" not in serialized
    assert "private" not in serialized


def test_nested_projector_rejects_ambiguous_target_paths():
    with pytest.raises(ValueError, match="target paths collide"):
        NestedFieldRunEventProjector(
            {
                "*": (
                    RunEventPathRule(("source",), ("result",)),
                    RunEventPathRule(
                        ("other",),
                        ("result", "child"),
                    ),
                )
            }
        )


def test_multimodal_projector_requires_explicit_content_disclosure():
    payload = b"png"
    event = RunEvent(
        1,
        RunEventType.MODEL_OUTPUT_BLOCK,
        "run-1",
        {
            "step": 1,
            "block_index": 0,
            "block": {
                "kind": "image",
                "source": "inline",
                "media_type": "image/png",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "data_base64": base64.b64encode(payload).decode("ascii"),
            },
        },
    )

    metadata = MultimodalRunEventProjector().project(event)
    content = MultimodalRunEventProjector(
        MediaProjectionMode.CONTENT
    ).project(event)

    assert metadata["data"]["block"] == {
        "kind": "image",
        "source": "inline",
        "media_type": "image/png",
        "size_bytes": 3,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    assert "data_base64" not in metadata["data"]["block"]
    assert content["data"]["block"]["data_base64"] == "cG5n"


def test_multimodal_reference_mode_discloses_urls_but_not_other_events():
    media = RunEvent(
        1,
        RunEventType.MODEL_OUTPUT_BLOCK,
        "run-1",
        {
            "step": 1,
            "block_index": 2,
            "block": {
                "kind": "audio",
                "source": "url",
                "media_type": "audio/wav",
                "url": "https://media.test/reply.wav",
            },
        },
    )
    text = RunEvent(
        2,
        RunEventType.MODEL_TEXT_DELTA,
        "run-1",
        {"step": 1, "text": "must-not-pass"},
    )
    projector = MultimodalRunEventProjector("references")

    assert projector.project(media)["data"]["block"]["url"] == (
        "https://media.test/reply.wav"
    )
    assert projector.project(text)["data"] == {"step": 1}


@pytest.mark.asyncio
async def test_projected_page_fails_closed_for_non_json_view():
    source = PagedSource(
        (RunEvent(1, RunEventType.RUN_STARTED, "run-1"),)
    )

    with pytest.raises(RunStoreError, match="non-JSON-compatible"):
        await RunEventReplay(source).projected_page(
            "run-1",
            projector=InvalidProjector(),
        )


def test_safe_projector_is_public_and_rejects_non_events():
    projector = SafeRunEventProjector()

    with pytest.raises(TypeError, match="RunEvent"):
        projector.project(object())
