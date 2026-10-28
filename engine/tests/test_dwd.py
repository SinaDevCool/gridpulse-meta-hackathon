from datetime import datetime, timezone
from io import BytesIO
from zipfile import ZipFile

from capacity_backtest.dwd import _parse_archive, _stations


def test_station_metadata_preserves_identity_and_coordinates():
    text = "header\n----\n00433 19470101 20251231 48 52.4675 13.4021 Berlin-Tempelhof                         Berlin Frei\n"
    stations = _stations(text)
    assert stations[0]["id"] == "00433"
    assert stations[0]["name"] == "Berlin-Tempelhof"
    assert stations[0]["latitude"] == 52.4675


def test_weather_archive_uses_utc_and_rejects_missing_sentinel():
    product = "STATIONS_ID;MESS_DATUM;QN_9;TT_TU;eor\n433;2021010100;3;2.5;eor\n433;2021010101;3;-999;eor\n"
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("produkt_tu.txt", product)
    values, rejected = _parse_archive(buffer.getvalue(), ("TT_TU",), 2021, 2021)
    assert values == {datetime(2021, 1, 1, tzinfo=timezone.utc): 2.5}
    assert rejected == 1


def test_weather_archive_can_quarantine_an_empty_requested_period():
    product = "STATIONS_ID;MESS_DATUM;QN_9;TT_TU;eor\n433;2020010100;3;2.5;eor\n"
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("produkt_tu.txt", product)
    values, rejected = _parse_archive(buffer.getvalue(), ("TT_TU",), 2021, 2021)
    assert values == {}
    assert rejected == 0
