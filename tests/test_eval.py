from poc.eval import evaluate
from poc.schemas import StudentPacket


def _pkt(last_raw, first_raw, last, first, middle="", pid="r001_001"):
    return StudentPacket(
        packet_id=pid,
        last_raw=last_raw, first_raw=first_raw, middle_raw=middle,
        last=last, first=first, middle=middle,
        frames=["00006"],
        flagged=False,
        avg_confidence=0.9,
    )


def test_evaluate_exact_match_both_passes():
    packets = [
        _pkt("SMITH", "JOHN", "SMITH", "JOHN", middle="A", pid="r001_001"),
        _pkt("JONES", "MARY", "JONES", "MARY", middle="", pid="r001_002"),
    ]
    gt = ["SMITH, JOHN A.pdf", "JONES, MARY.pdf"]
    report = evaluate(packets, gt, roll_id="ROLL 001")
    assert report.accuracy_exact_pre == 1.0
    assert report.accuracy_exact_post == 1.0
    assert report.gt_rows_raw == 2
    assert report.gt_rows_usable == 2
    assert report.gt_rows_dropped_reasons == {}


def test_evaluate_snap_lifts_accuracy():
    packets = [
        _pkt("SNITH", "JOHN", "SMITH", "JOHN", pid="r001_001"),
    ]
    gt = ["SMITH, JOHN.pdf"]
    report = evaluate(packets, gt, roll_id="ROLL 001")
    assert report.partial_matches_pre == 1
    assert report.exact_matches_pre == 0
    assert report.exact_matches_post == 1
    assert report.accuracy_exact_post == 1.0


def test_evaluate_drops_placeholder_from_gt():
    packets = [_pkt("SMITH", "JOHN", "SMITH", "JOHN", pid="r001_001")]
    gt = ["SMITH, JOHN.pdf", "(LAST) (FIRST) MIDDLE Burris, Tammy L.pdf"]
    report = evaluate(packets, gt, roll_id="ROLL 001")
    assert report.gt_rows_raw == 2
    assert report.gt_rows_usable == 1
    dropped = report.gt_rows_dropped_reasons
    assert sum(dropped.values()) == 1


def test_evaluate_reports_index_diagnostics():
    packets = [
        _pkt("SNITH", "JOHN", "SMITH", "JOHN", pid="r001_001"),
        _pkt("JONES", "MARY", "JONES", "MARY", pid="r001_002"),
    ]
    packets[0].index_snap_applied = True
    report = evaluate(packets, ["SMITH, JOHN.pdf", "JONES, MARY.pdf"],
                      roll_id="ROLL 001", index_frames_total=7, index_rows_total=165)
    assert report.packets_snapped == 1
    assert report.index_frames_total == 7
    assert report.index_rows_total == 165


def test_evaluate_sham_merge_roll_excluded():
    packets = [_pkt("SMITH", "JOHN", "SMITH", "JOHN")]
    gt = ["SMITH, JOHN.pdf"]
    report = evaluate(packets, gt, roll_id="ROLL 003")
    assert report.gt_rows_usable == 0
    assert report.gt_rows_dropped_reasons == {"sham_merge": 1}
