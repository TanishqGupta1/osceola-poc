from poc.eval import parse_pdf_filename, evaluate
from poc.schemas import StudentPacket


def test_parse_clean_filename():
    got = parse_pdf_filename("ACKLEY, CALVIN CHARLES.pdf")
    assert got == {"last": "ACKLEY", "first": "CALVIN", "middle": "CHARLES"}


def test_parse_partial_filename_drops_placeholders():
    got = parse_pdf_filename("(LAST) Buston Jerry.pdf")
    assert got is None


def test_parse_with_underscore_dup():
    got = parse_pdf_filename("ALLEN, TAMMY_1.pdf")
    assert got == {"last": "ALLEN", "first": "TAMMY", "middle": ""}


def test_evaluate_exact_match():
    packets = [
        StudentPacket(packet_id="r001_001", last="SMITH", first="JOHN",
                      middle="A", frames=["00006"], flagged=False, avg_confidence=0.9),
        StudentPacket(packet_id="r001_002", last="JONES", first="MARY",
                      middle="", frames=["00010"], flagged=False, avg_confidence=0.9),
    ]
    gt = ["SMITH, JOHN A.pdf", "JONES, MARY.pdf"]
    report = evaluate(packets, gt, roll_id="ROLL 001")
    assert report.exact_name_matches == 2
    assert report.accuracy_exact == 1.0


def test_evaluate_partial_match_levenshtein():
    packets = [
        StudentPacket(packet_id="r001_001", last="SNITH", first="JOHN",
                      middle="A", frames=["00006"], flagged=False, avg_confidence=0.9),
    ]
    gt = ["SMITH, JOHN A.pdf"]
    report = evaluate(packets, gt, roll_id="ROLL 001", max_levenshtein=2)
    assert report.partial_name_matches >= 1
