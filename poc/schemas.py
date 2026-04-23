from typing import Literal
from pydantic import BaseModel, Field

PageClass = Literal[
    "student_cover",
    "student_test_sheet",
    "student_continuation",
    "student_records_index",
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


class IndexRow(BaseModel):
    last: str
    first: str
    middle: str = ""
    dob: str = ""
    source_frame: str = ""


class PageResult(BaseModel):
    frame: str
    roll_id: str
    page_class: PageClass
    separator: Separator
    student: Student
    roll_meta: RollMeta
    index_rows: list[IndexRow] = []
    confidence_overall: float = Field(ge=0.0, le=1.0)
    confidence_name: float = Field(ge=0.0, le=1.0)
    notes: str = ""
    model_version: str
    processed_at: str
    latency_ms: int
    tokens_in: int = 0
    tokens_out: int = 0
    usd_cost: float = 0.0


class StudentPacket(BaseModel):
    packet_id: str
    last_raw: str
    first_raw: str
    middle_raw: str
    last: str
    first: str
    middle: str
    frames: list[str]
    flagged: bool
    avg_confidence: float
    index_snap_applied: bool = False
    index_snap_distance: int | None = None


class EvalReport(BaseModel):
    roll_id: str
    pages_total: int
    pages_classified: int
    packets_predicted: int
    packets_ground_truth: int
    gt_rows_raw: int = 0
    gt_rows_usable: int = 0
    gt_rows_dropped_reasons: dict[str, int] = {}
    exact_matches_pre: int = 0
    partial_matches_pre: int = 0
    no_match_pre: int = 0
    accuracy_exact_pre: float = 0.0
    accuracy_partial_pre: float = 0.0
    exact_matches_post: int = 0
    partial_matches_post: int = 0
    no_match_post: int = 0
    accuracy_exact_post: float = 0.0
    accuracy_partial_post: float = 0.0
    index_frames_total: int = 0
    index_rows_total: int = 0
    packets_snapped: int = 0
    usd_total: float = 0.0
    tokens_in_total: int = 0
    tokens_out_total: int = 0
    unmatched_predictions: list[str] = []
    unmatched_ground_truth: list[str] = []
