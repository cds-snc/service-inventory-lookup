"""Tests for download_service_inventory.py pipeline functions."""

from download_service_inventory import download_csv


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
