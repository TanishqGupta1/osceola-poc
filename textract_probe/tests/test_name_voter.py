import pytest

from textract_probe.name_voter import NameVote, vote_on_name


def test_three_sources_agree_high_confidence():
    sources = [
        ("forms_name",      "Owen, Randall Horton", 87.0),
        ("queries_record",  "Owen, Randall Horton", 91.0),
        ("queries_top",     "Owen, Randall Horton", 79.0),
    ]
    r = vote_on_name(sources)
    assert r.name == "Owen, Randall Horton"
    assert r.agreement == 3
    assert r.confidence >= 0.85
    assert set(r.sources) == {"forms_name", "queries_record", "queries_top"}


def test_two_sources_agree_one_disagrees():
    sources = [
        ("forms_name",     "Bunt",  81.0),
        ("queries_record", "Bunt",  78.0),
        ("detect_first",   "Judy",  60.0),
    ]
    r = vote_on_name(sources)
    assert r.name == "Bunt"
    assert r.agreement == 2


def test_garbage_inputs_filtered_out():
    sources = [
        ("forms_name",      "BIRTH",                  95.0),
        ("queries_record",  "Markley, Jenelyn",       62.0),
        ("queries_top",     "Markley, Jenelyn",       72.0),
        ("detect_first",    "(LAST)",                  99.0),
    ]
    r = vote_on_name(sources)
    assert r.name == "Markley, Jenelyn"
    assert r.agreement == 2


def test_no_valid_sources_returns_empty():
    sources = [
        ("forms_name",      "BIRTH", 95.0),
        ("queries_record",  "1887", 92.0),
    ]
    r = vote_on_name(sources)
    assert r.name == ""
    assert r.agreement == 0
    assert r.confidence == 0.0


def test_single_high_confidence_source_keeps_low_confidence():
    sources = [
        ("queries_record", "Paulerson, Rebecca", 99.0),
    ]
    r = vote_on_name(sources)
    assert r.name == "Paulerson, Rebecca"
    assert r.agreement == 1
    assert 0.40 <= r.confidence <= 0.65


def test_name_normalization_for_agreement():
    sources = [
        ("queries_record", "Markley, Judith", 27.0),
        ("queries_top",    "MARKLEY, Judith,", 46.0),
    ]
    r = vote_on_name(sources)
    assert r.name in {"Markley, Judith", "MARKLEY, Judith"}
    assert r.agreement == 2
