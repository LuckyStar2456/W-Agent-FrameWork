"""Draft input-manifest tests; execution awaits separate authorization."""

import base64
import json

import pytest

from w_agent import InputManifestError, InputManifestLimits, input_manifest_from_mapping, load_input_manifest


def _manifest():
    return {"schema_version": 1, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "PRIVATE_TEXT"},
        {"type": "image", "url": "https://example.test/PRIVATE_IMAGE"},
        {"type": "audio", "data_base64": base64.b64encode(b"PRIVATE_AUDIO").decode(), "media_type": "audio/wav"},
    ]}]}


def test_ordered_blocks_and_utf8_bom_roundtrip(tmp_path):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8-sig")
    messages = load_input_manifest(path)
    assert [block.type for block in messages[0].content] == ["text", "image", "audio"]
    assert messages[0].content[2].data == b"PRIVATE_AUDIO"
    assert input_manifest_from_mapping(_manifest()) == messages


@pytest.mark.parametrize("change", ["schema", "role", "authority", "path", "tool", "mixed", "base64", "empty"])
def test_unknown_and_unsafe_fields_are_rejected(change):
    data = _manifest()
    if change == "schema":
        data["schema_version"] = True
    elif change == "role":
        data["messages"][0]["role"] = "system"
    elif change == "authority":
        data["permissions"] = ["execute"]
    elif change == "path":
        data["messages"][0]["content"][1] = {"type": "image", "path": "PRIVATE_FILE"}
    elif change == "tool":
        data["messages"][0]["content"][0]["type"] = "tool-call"
    elif change == "mixed":
        data["messages"][0]["content"][1]["data_base64"] = "AA=="
    elif change == "base64":
        data["messages"][0]["content"][2]["data_base64"] = "!PRIVATE"
    else:
        data["messages"] = []
    with pytest.raises(InputManifestError) as error:
        input_manifest_from_mapping(data)
    assert "PRIVATE" not in str(error.value)


@pytest.mark.parametrize("url", ["file:///private.png", "data:image/png;base64,AA==", "https://u:p@example.test/x", "https:///missing", "https://example.test/\nPRIVATE", "https://example.test:invalid/x"])
def test_builtin_urls_reject_file_data_userinfo_and_controls(url):
    data = _manifest()
    data["messages"][0]["content"][1]["url"] = url
    with pytest.raises(InputManifestError):
        input_manifest_from_mapping(data)


@pytest.mark.parametrize("options", [dict(max_blocks_per_message=1), dict(max_text_chars=1), dict(max_inline_bytes=1),
                                      dict(max_reference_chars=1), dict(max_content_bytes=1)])
def test_content_limits(options):
    with pytest.raises(InputManifestError):
        input_manifest_from_mapping(_manifest(), limits=InputManifestLimits(**options))


@pytest.mark.parametrize("content", ['{"schema_version":1,"schema_version":1,"messages":[]}', '{"PRIVATE":NaN}', 'PRIVATE_NOT_JSON'])
def test_invalid_json_and_duplicate_keys_are_sanitized(tmp_path, content):
    path = tmp_path / "input.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(InputManifestError) as error:
        load_input_manifest(path)
    assert "PRIVATE" not in str(error.value)


def test_file_size_and_message_limit(tmp_path):
    path = tmp_path / "input.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")
    with pytest.raises(InputManifestError):
        load_input_manifest(path, limits=InputManifestLimits(max_file_bytes=8))
    data = _manifest()
    data["messages"] *= 2
    with pytest.raises(InputManifestError):
        input_manifest_from_mapping(data, limits=InputManifestLimits(max_messages=1))


@pytest.mark.parametrize("value", [True, 0, -1, 1.5])
def test_limits_are_strict_positive_integers(value):
    with pytest.raises(ValueError):
        InputManifestLimits(max_inline_bytes=value)
