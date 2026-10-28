from datetime import datetime, timezone

from capacity_backtest.entsoe import aggregate_generation_hourly, aggregate_hourly, parse_timeseries
from capacity_backtest.profiling import profile_entsoe


def test_parse_and_hourly_aggregate_entsoe_points():
    payload = b'''<GL_MarketDocument xmlns="urn:test"><TimeSeries><businessType>A04</businessType><objectAggregation>A01</objectAggregation><quantity_Measure_Unit.name>MAW</quantity_Measure_Unit.name><Period><timeInterval><start>2025-01-01T00:00Z</start></timeInterval><resolution>PT30M</resolution><Point><position>1</position><quantity>100</quantity></Point><Point><position>2</position><quantity>120</quantity></Point></Period></TimeSeries></GL_MarketDocument>'''
    series = parse_timeseries(payload, "A65")
    result = aggregate_hourly(series)
    assert result[datetime(2025, 1, 1, tzinfo=timezone.utc)] == 110
    profile = profile_entsoe(series, "A65")
    assert profile.accepted


def test_generation_profile_rejects_unclassified_or_duplicate_series():
    payload = b'''<GL_MarketDocument xmlns="urn:test"><TimeSeries><mRID>1</mRID><businessType>A01</businessType><quantity_Measure_Unit.name>MAW</quantity_Measure_Unit.name><Period><timeInterval><start>2025-01-01T00:00Z</start></timeInterval><resolution>PT60M</resolution><Point><position>1</position><quantity>10</quantity></Point></Period></TimeSeries></GL_MarketDocument>'''
    assert not profile_entsoe(parse_timeseries(payload, "A75"), "A75").accepted


def test_generation_aggregation_preserves_technology_and_direction():
    payload = b'''<GL_MarketDocument xmlns="urn:test"><TimeSeries><mRID>1</mRID><businessType>A01</businessType><objectAggregation>A08</objectAggregation><inBiddingZone_Domain.mRID>x</inBiddingZone_Domain.mRID><quantity_Measure_Unit.name>MAW</quantity_Measure_Unit.name><psrType>B16</psrType><Period><timeInterval><start>2025-01-01T00:00Z</start></timeInterval><resolution>PT60M</resolution><Point><position>1</position><quantity>10</quantity></Point></Period></TimeSeries><TimeSeries><mRID>2</mRID><businessType>A01</businessType><objectAggregation>A08</objectAggregation><outBiddingZone_Domain.mRID>x</outBiddingZone_Domain.mRID><quantity_Measure_Unit.name>MAW</quantity_Measure_Unit.name><psrType>B10</psrType><Period><timeInterval><start>2025-01-01T00:00Z</start></timeInterval><resolution>PT60M</resolution><Point><position>1</position><quantity>3</quantity></Point></Period></TimeSeries></GL_MarketDocument>'''
    result = aggregate_generation_hourly(parse_timeseries(payload, "A75"))
    values = result[datetime(2025, 1, 1, tzinfo=timezone.utc)]
    assert values == {"B16_generation": 10, "B10_consumption": 3}
    assert profile_entsoe(parse_timeseries(payload, "A75"), "A75").duplicate_points == 0
