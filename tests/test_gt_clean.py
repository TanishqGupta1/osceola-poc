from poc.gt_clean import clean_gt_filename, DROP_REASONS


def _call(fname: str):
    return clean_gt_filename(fname)


def test_clean_standard_uppercase():
    r = _call("SMITH, JOHN A.pdf")
    assert r == {"last": "SMITH", "first": "JOHN", "middle": "A"}


def test_clean_titlecase_normalizes_to_upper():
    r = _call("Smith, John Anthony.pdf")
    assert r == {"last": "SMITH", "first": "JOHN", "middle": "ANTHONY"}


def test_placeholder_drops():
    r, reason = clean_gt_filename("(LAST) Buston Jerry.pdf", return_reason=True)
    assert r is None
    assert reason == "placeholder"


def test_ocr_garbage_drops():
    r, reason = clean_gt_filename("(LAST) (FIRST) MIDDLE) COUNTY Barton, Virginia.pdf",
                                   return_reason=True)
    assert r is None
    assert reason in {"placeholder", "ocr_garbage"}


def test_numeric_only_drops():
    r, reason = clean_gt_filename("1959.pdf", return_reason=True)
    assert r is None
    assert reason == "numeric_only"


def test_too_short_drops():
    r, reason = clean_gt_filename("Smith.pdf", return_reason=True)
    assert r is None
    assert reason == "too_short"


def test_trailing_dup_suffix_stripped():
    r = _call("ALLEN, TAMMY_1.pdf")
    assert r == {"last": "ALLEN", "first": "TAMMY", "middle": ""}


def test_sham_merge_roll_prefix_drops():
    r, reason = clean_gt_filename("SMITH, JOHN.pdf", return_reason=True, source_roll="ROLL 003")
    assert r is None
    assert reason == "sham_merge"


def test_drop_reasons_enum_complete():
    assert DROP_REASONS == {
        "placeholder", "ocr_garbage", "numeric_only", "too_short", "sham_merge",
    }
