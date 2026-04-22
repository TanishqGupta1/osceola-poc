SYSTEM_PROMPT = """You classify and extract data from scanned microfilm pages of Osceola County School District student records (circa 1991-92). Each page belongs to one of six classes:

1. `student_cover` — primary cumulative/guidance record, typically has student name top-left, demographics, school, DOB. Florida Cumulative Guidance Record 1-12, Osceola Progress Report, Elementary Record.
2. `student_test_sheet` — standardized test form with student name printed or typed. Stanford Achievement Test, H&R First Reader, SAT Profile Graph.
3. `student_continuation` — back pages, comments, family data, health records — student name at top. Comments page, MCH 304 health record, Elementary family data page.
4. `roll_separator` — START or END card that bookends each roll. TWO visually distinct styles both count as `roll_separator`:
     - Style A (clapperboard): diagonal-hatched rectangles + "START" or "END" in large block text + boxed handwritten "ROLL NO. N"
     - Style B (certificate): printed "CERTIFICATE OF RECORD" / "CERTIFICATE OF AUTHENTICITY" form with START or END heading, typed school name, handwritten date, filmer signature, reel number
5. `roll_leader` — non-student filler frames: blank page, vendor letterhead ("Total Information Management Systems" or "White's Microfilm Services"), microfilm resolution test target, district title page (Osceola County seal + "RECORDS DEPARTMENT"), filmer certification card without START/END marker, operator roll-identity card.
6. `unknown` — blank mid-roll, illegible, or unrecognized.

Images may be rotated 90°, 180°, or 270°; read orientation regardless. Images may be noisy, low-contrast, or partially missing — when in doubt use `unknown` with low confidence rather than guessing.

Extract student name from the TOP-LEFT of the form (per SOW). Only extract student fields when `page_class` is `student_*`. Leave them blank otherwise.

Extract separator fields (`marker`, `roll_no`) only when `page_class` is `roll_separator`.

Extract roll metadata (`filmer`, `date`, `school`, `reel_no_cert`) only from certification or operator leader cards — these appear once per roll near the start.

Self-report `confidence_overall` and `confidence_name` on a 0.0-1.0 scale based on legibility and certainty. Be honest — low confidence flags work for human review."""

USER_TURN_TEXT = "Classify this page and extract the fields. Respond only via the `classify_page` tool."

TOOL_SCHEMA = {
    "name": "classify_page",
    "description": "Return structured classification and extraction for one page.",
    "input_schema": {
        "type": "object",
        "required": [
            "page_class", "separator", "student", "roll_meta",
            "confidence_overall", "confidence_name",
        ],
        "properties": {
            "page_class": {
                "type": "string",
                "enum": [
                    "student_cover", "student_test_sheet", "student_continuation",
                    "roll_separator", "roll_leader", "unknown",
                ],
            },
            "separator": {
                "type": "object",
                "properties": {
                    "marker": {"type": ["string", "null"], "enum": ["START", "END", None]},
                    "roll_no": {"type": ["string", "null"]},
                },
            },
            "student": {
                "type": "object",
                "properties": {
                    "last": {"type": "string"},
                    "first": {"type": "string"},
                    "middle": {"type": "string"},
                    "dob": {"type": "string"},
                    "school": {"type": "string"},
                },
            },
            "roll_meta": {
                "type": "object",
                "properties": {
                    "filmer": {"type": "string"},
                    "date": {"type": "string"},
                    "school": {"type": "string"},
                    "reel_no_cert": {"type": "string"},
                },
            },
            "confidence_overall": {"type": "number", "minimum": 0, "maximum": 1},
            "confidence_name": {"type": "number", "minimum": 0, "maximum": 1},
            "notes": {"type": "string"},
        },
    },
}
