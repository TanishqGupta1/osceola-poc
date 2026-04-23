from poc.prompts import SYSTEM_PROMPT, TOOL_SCHEMA, USER_TURN_TEXT, MAX_OUTPUT_TOKENS


def test_system_prompt_mentions_seven_classes():
    for cls in [
        "student_cover", "student_test_sheet", "student_continuation",
        "student_records_index",
        "roll_separator", "roll_leader", "unknown",
    ]:
        assert cls in SYSTEM_PROMPT


def test_system_prompt_mentions_both_separator_styles():
    assert "clapperboard" in SYSTEM_PROMPT.lower()
    assert "certificate" in SYSTEM_PROMPT.lower()


def test_system_prompt_handles_rotation():
    assert "rotat" in SYSTEM_PROMPT.lower()


def test_system_prompt_describes_index_rows_behavior():
    text = SYSTEM_PROMPT.lower()
    assert "index_rows" in text
    assert "student_records_index" in text
    assert "empty" in text


def test_tool_schema_has_required_fields():
    props = TOOL_SCHEMA["input_schema"]["properties"]
    for f in ["page_class", "separator", "student", "roll_meta",
              "confidence_overall", "confidence_name", "index_rows"]:
        assert f in props


def test_tool_schema_page_class_enum_has_seven():
    enum = TOOL_SCHEMA["input_schema"]["properties"]["page_class"]["enum"]
    assert set(enum) == {
        "student_cover", "student_test_sheet", "student_continuation",
        "student_records_index",
        "roll_separator", "roll_leader", "unknown",
    }


def test_tool_schema_index_rows_is_array_of_objects():
    spec = TOOL_SCHEMA["input_schema"]["properties"]["index_rows"]
    assert spec["type"] == "array"
    assert spec["items"]["type"] == "object"
    assert "last" in spec["items"]["required"]
    assert "first" in spec["items"]["required"]


def test_user_turn_text_non_empty():
    assert len(USER_TURN_TEXT.strip()) > 0


def test_max_output_tokens_is_1500():
    assert MAX_OUTPUT_TOKENS == 1500
