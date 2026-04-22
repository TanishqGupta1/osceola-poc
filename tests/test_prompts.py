from poc.prompts import SYSTEM_PROMPT, TOOL_SCHEMA, USER_TURN_TEXT


def test_system_prompt_mentions_six_classes():
    for cls in [
        "student_cover", "student_test_sheet", "student_continuation",
        "roll_separator", "roll_leader", "unknown",
    ]:
        assert cls in SYSTEM_PROMPT


def test_system_prompt_mentions_both_separator_styles():
    assert "clapperboard" in SYSTEM_PROMPT.lower()
    assert "certificate" in SYSTEM_PROMPT.lower()


def test_system_prompt_handles_rotation():
    assert "rotat" in SYSTEM_PROMPT.lower()


def test_tool_schema_has_required_fields():
    props = TOOL_SCHEMA["input_schema"]["properties"]
    for f in ["page_class", "separator", "student", "roll_meta",
              "confidence_overall", "confidence_name"]:
        assert f in props


def test_user_turn_text_non_empty():
    assert len(USER_TURN_TEXT.strip()) > 0
