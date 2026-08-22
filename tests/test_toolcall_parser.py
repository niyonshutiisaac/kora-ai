"""Tests for the text-based tool-call parser."""

from kora.models.toolcall_parser import extract_text_tool_calls


class TestTagFormat:
    def test_single_tagged_call(self):
        text = 'Let me read that.\n<tool_call>{"name": "read_file", "arguments": {"path": "a.py"}}</tool_call>'
        remainder, calls = extract_text_tool_calls(text)
        assert len(calls) == 1
        assert calls[0][0] == "read_file"
        assert calls[0][1] == {"path": "a.py"}
        assert "tool_call" not in remainder
        assert "Let me read that." in remainder

    def test_multiple_tagged_calls(self):
        text = (
            '<tool_call>{"name": "a", "arguments": {}}</tool_call>'
            '<tool_call>{"name": "b", "arguments": {"x": 1}}</tool_call>'
        )
        _, calls = extract_text_tool_calls(text)
        assert [c[0] for c in calls] == ["a", "b"]

    def test_malformed_tag_dropped(self):
        text = "<tool_call>not json at all</tool_call>"
        remainder, calls = extract_text_tool_calls(text)
        assert calls == []
        assert "not json" not in remainder


class TestFencedFormat:
    def test_fenced_json_object(self):
        text = '```json\n{"name": "search_code", "arguments": {"query": "TODO"}}\n```'
        remainder, calls = extract_text_tool_calls(text)
        assert calls == [("search_code", {"query": "TODO"})]
        assert remainder == ""

    def test_fenced_json_list(self):
        text = '```json\n[{"name": "a", "arguments": {}}, {"name": "b", "arguments": {}}]\n```'
        _, calls = extract_text_tool_calls(text)
        assert len(calls) == 2


class TestBareJson:
    def test_bare_object(self):
        text = '{"name": "git_status", "arguments": {}}'
        _, calls = extract_text_tool_calls(text)
        assert calls == [("git_status", {})]

    def test_plain_prose_untouched(self):
        text = "The answer is 42 and here is why..."
        remainder, calls = extract_text_tool_calls(text)
        assert calls == []
        assert remainder == text


class TestNestedFunction:
    def test_openai_style_wrapper(self):
        text = '<tool_call>{"function": {"name": "ls", "parameters": {"path": "."}}}</tool_call>'
        _, calls = extract_text_tool_calls(text)
        assert calls == [("ls", {"path": "."})]
