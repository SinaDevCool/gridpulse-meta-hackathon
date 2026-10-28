import pytest

from capacity_backtest.adapters.price import parse_price_csv


def test_negative_prices_are_valid_electricity_market_evidence():
    rows = parse_price_csv(b"timestamp,price_eur_per_mwh,market\n2026-01-01T00:00:00Z,-25,DE\n", source_id="test")
    assert rows[0].price_eur_per_mwh == -25


@pytest.mark.parametrize("prices", ["NaN", "inf", "-inf"])
def test_nonfinite_prices_are_rejected(prices):
    with pytest.raises(ValueError):
        parse_price_csv(f"timestamp,price_eur_per_mwh,market\n2026-01-01T00:00:00Z,{prices},DE\n".encode(), source_id="test")


def test_equivalent_price_timestamps_are_duplicate_evidence():
    with pytest.raises(ValueError):
        parse_price_csv(b"timestamp,price_eur_per_mwh,market\n2026-01-01T00:00:00Z,1,DE\n2026-01-01T01:00:00+01:00,2,DE\n", source_id="test")


def test_existing_entsoe_adapter_reads_quarter_hour_negative_prices():
    from capacity_backtest.entsoe import parse_timeseries
    xml = b"<Document><TimeSeries><currency_Unit.name>EUR</currency_Unit.name><price_Measure_Unit.name>MWH</price_Measure_Unit.name><Period><timeInterval><start>2026-01-01T00:00:00Z</start></timeInterval><resolution>PT15M</resolution><Point><position>1</position><price.amount>-12.5</price.amount></Point><Point><position>2</position><price.amount>8</price.amount></Point></Period></TimeSeries></Document>"
    series, = parse_timeseries(xml, "A44")
    assert series.unit == "EUR/MWh" and list(series.points.values()) == [-12.5, 8]
    with pytest.raises(ValueError, match="EUR/MWh"):
        parse_timeseries(xml.replace(b"EUR", b"USD"), "A44")
