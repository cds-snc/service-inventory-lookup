"""Tests for download_service_inventory.py pipeline functions."""

import pandas as pd

from download_service_inventory import build_program_lookup, download_csv, filter_placeholder, filter_transferred


def _mock_urlopen(mocker, csv_bytes: bytes):
    mock = mocker.patch("download_service_inventory.urlopen")
    mock.return_value.__enter__.return_value.read.return_value = csv_bytes
    return mock


def test_download_csv_returns_dataframe(mocker):
    _mock_urlopen(mocker, b"col_a,col_b\nfoo,1\nbar,2\n")
    df = download_csv("https://example.com/data.csv")
    assert list(df.columns) == ["col_a", "col_b"]
    assert len(df) == 2


def test_download_csv_preserves_all_columns(mocker):
    _mock_urlopen(mocker, b"service_id,service_en,org_name_en\n1,Foo,Bar\n")
    df = download_csv("https://example.com/data.csv")
    assert list(df.columns) == ["service_id", "service_en", "org_name_en"]


def test_filter_transferred_drops_rows_with_date():
    df = pd.DataFrame(
        {
            "service_id": [1, 2, 3],
            "date_transferred": ["2023-01-01", "", float("nan")],
        }
    )
    result = filter_transferred(df)
    assert list(result["service_id"]) == [2, 3]


def test_filter_transferred_keeps_all_when_none_transferred():
    df = pd.DataFrame(
        {
            "service_id": [1, 2],
            "date_transferred": [float("nan"), float("nan")],
        }
    )
    result = filter_transferred(df)
    assert len(result) == 2


def test_filter_transferred_returns_empty_when_all_transferred():
    df = pd.DataFrame(
        {
            "service_id": [1, 2],
            "date_transferred": ["2022-01-01", "2023-06-15"],
        }
    )
    result = filter_transferred(df)
    assert len(result) == 0


def test_filter_placeholder_drops_id_not_used():
    df = pd.DataFrame(
        {
            "service_id": [1, 2, 3],
            "service_en": ["id not used", "Real Service", "id not used"],
        }
    )
    result = filter_placeholder(df)
    assert list(result["service_id"]) == [2]


def test_filter_placeholder_keeps_services_with_test_in_name():
    df = pd.DataFrame(
        {
            "service_id": [1],
            "service_en": ["Rapid Test Kit Provision"],
        }
    )
    result = filter_placeholder(df)
    assert len(result) == 1


def test_build_program_lookup_takes_most_recent_fiscal_year():
    df = pd.DataFrame({
        "service_id": [1, 1, 1],
        "fiscal_yr": ["2018-2019", "2022-2023", "2020-2021"],
        "program_id": ["OLD01", "NEW01", "MID01"],
    })
    result = build_program_lookup(df)
    assert result["1"] == "NEW01"


def test_build_program_lookup_handles_single_entry():
    df = pd.DataFrame({
        "service_id": [42],
        "fiscal_yr": ["2023-2024"],
        "program_id": ["ABC01"],
    })
    result = build_program_lookup(df)
    assert result["42"] == "ABC01"


def test_build_program_lookup_returns_string_keys():
    df = pd.DataFrame({
        "service_id": [7],
        "fiscal_yr": ["2023-2024"],
        "program_id": ["XYZ99"],
    })
    result = build_program_lookup(df)
    assert "7" in result
    assert 7 not in result


def test_build_program_lookup_handles_multiple_services():
    df = pd.DataFrame({
        "service_id": [1, 1, 2, 2],
        "fiscal_yr": ["2021-2022", "2023-2024", "2020-2021", "2022-2023"],
        "program_id": ["A01", "A02", "B01", "B02"],
    })
    result = build_program_lookup(df)
    assert result["1"] == "A02"
    assert result["2"] == "B02"
