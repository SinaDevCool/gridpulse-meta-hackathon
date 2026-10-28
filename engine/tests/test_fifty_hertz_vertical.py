from capacity_backtest.fifty_hertz_vertical import parse_file_list, profile_vertical_load


def test_file_listing_and_utf16_profile_preserve_local_dst_ambiguity() -> None:
    assert parse_file_list('(["2025.csv","2024.csv"])') == ["2024.csv", "2025.csv"]
    text = (
        ";Datum;von;bis;MW\r\n"
        "Datum;von;bis;MW\r\n"
        "27.10.2024;02:00;02:15;100\r\n"
        "27.10.2024;02:00;02:15;101\r\n"
        "27.10.2024;02:15;02:30;n/a\r\n"
    )
    report = profile_vertical_load(text.encode("utf-16"), snapshot_hash="a" * 64)
    assert report["record_count"] == 3
    assert report["duplicate_local_timestamps"] == 1
    assert report["missing_values"] == 1
    assert report["training_admitted"] is False
