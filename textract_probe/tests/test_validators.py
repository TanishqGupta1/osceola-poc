import pytest

from textract_probe import validators as v


@pytest.mark.parametrize("name,ok", [
    ("Owen", True),
    ("Owen, Randall Horton", True),
    ("alexander, Earnestine", True),
    ("O'Brien", True),
    ("Markley-Smith", True),
    ("",                      False),
    ("BIRTH",                 False),
    ("PHOTOGRAPH",            False),
    ("STUDENT",               False),
    ("OSCEOLA",               False),
    ("1887",                  False),
    ("1925 Sept 11",          False),
    ("X",                     False),
    ("12345",                 False),
    ("Mrs. W. O. Janner",     False),
    ("FATHER's name",         False),
    ("MOTHER",                False),
    ("(LAST)",                False),
])
def test_is_valid_student_name(name, ok):
    assert v.is_valid_student_name(name) is ok


@pytest.mark.parametrize("text,expected", [
    ("Owen, Randall Horton with",     "Owen, Randall Horton"),
    ("MARKLEY, Judith,",              "MARKLEY, Judith"),
    ("  Bunt   ",                     "Bunt"),
    ("'arklev",                       "arklev"),
])
def test_clean_extracted_name(text, expected):
    assert v.clean_extracted_name(text) == expected


@pytest.mark.parametrize("dob,ok", [
    ("11/26/45",  True),
    ("6/10/60",   True),
    ("5-21-46",   True),
    ("1925",      False),
    ("1887",      False),
    ("",          False),
    ("19 / 19 / 19", False),
    ("9.5.59",    True),
])
def test_is_valid_dob(dob, ok):
    assert v.is_valid_dob(dob) is ok
