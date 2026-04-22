from typing import Literal
from pydantic import BaseModel, Field

PageClass = Literal[
    "student_cover",
    "student_test_sheet",
    "student_continuation",
    "roll_separator",
    "roll_leader",
    "unknown",
]


class Separator(BaseModel):
    marker: Literal["START", "END"] | None = None
    roll_no: str | None = None


class Student(BaseModel):
    last: str = ""
    first: str = ""
    middle: str = ""
    dob: str = ""
    school: str = ""


class RollMeta(BaseModel):
    filmer: str = ""
    date: str = ""
    school: str = ""
    reel_no_cert: str = ""


class PageResult(BaseModel):
    frame: str
    roll_id: str
    page_class: PageClass
    separator: Separator
    student: Student
    roll_meta: RollMeta
    confidence_overall: float = Field(ge=0.0, le=1.0)
    confidence_name: float = Field(ge=0.0, le=1.0)
    notes: str = ""
    model_version: str
    processed_at: str
    latency_ms: int


class StudentPacket(BaseModel):
    packet_id: str
    last: str
    first: str
    middle: str
    frames: list[str]
    flagged: bool
    avg_confidence: float


class EvalReport(BaseModel):
    roll_id: str
    pages_total: int
    pages_classified: int
    packets_predicted: int
    packets_ground_truth: int
    exact_name_matches: int
    partial_name_matches: int
    no_match: int
    accuracy_exact: float
    accuracy_partial: float
    unmatched_predictions: list[str]
    unmatched_ground_truth: list[str]
