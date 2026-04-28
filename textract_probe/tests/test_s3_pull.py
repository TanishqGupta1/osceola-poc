from unittest.mock import MagicMock, patch

import pytest

from textract_probe import s3_pull


def test_build_keys_test_input_for_d1():
    keys = s3_pull.build_keys(
        district=1, roll="001", frame_start=100, frame_end=299
    )
    assert keys[0].endswith("Test Input/ROLL 001/00100.tif")
    assert keys[-1].endswith("Test Input/ROLL 001/00299.tif")
    assert len(keys) == 200


def test_build_keys_input_for_d4():
    keys = s3_pull.build_keys(
        district=4, roll="047", frame_start=100, frame_end=299
    )
    assert "OSCEOLA SCHOOL DISTRICT-4/ROLL 047" in keys[0]
    assert keys[0].endswith("00100.tif")


def test_build_keys_zero_padded():
    keys = s3_pull.build_keys(
        district=2, roll="020", frame_start=5, frame_end=7
    )
    assert keys == [
        "Osceola Co School District/Input/OSCEOLA SCHOOL DISTRICT-2/ROLL 020/00005.tif",
        "Osceola Co School District/Input/OSCEOLA SCHOOL DISTRICT-2/ROLL 020/00006.tif",
        "Osceola Co School District/Input/OSCEOLA SCHOOL DISTRICT-2/ROLL 020/00007.tif",
    ]


@patch("textract_probe.s3_pull.s3_client")
def test_pull_skips_existing_files(mock_factory, tmp_path):
    fake_client = MagicMock()
    mock_factory.return_value = fake_client

    out_dir = tmp_path / "samples/d1r001"
    out_dir.mkdir(parents=True)
    (out_dir / "00100.tif").write_bytes(b"existing")

    n = s3_pull.pull_frames(
        bucket="bucket-x",
        keys=["prefix/00100.tif", "prefix/00101.tif"],
        out_dir=out_dir,
    )
    assert n == 1
    fake_client.download_file.assert_called_once_with(
        "bucket-x", "prefix/00101.tif", str(out_dir / "00101.tif")
    )
