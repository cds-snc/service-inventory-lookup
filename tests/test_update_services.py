"""Tests for update_services.py pipeline functions."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from update_services import (
    apply_org_corrections,
    build_program_lookup,
    build_records,
    download_csv,
    filter_placeholder,
    filter_transferred,
    resolve_orgs,
    update_generated_at,
    write_json,
)


def _mock_urlopen(mocker, csv_bytes: bytes):
    mock = mocker.patch("update_services.urlopen")
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


def test_apply_org_corrections_remaps_known_bad_name():
    df = pd.DataFrame(
        {
            "service_id": [1, 2],
            "org_name_en": [
                "Offices of the Information and Privacy Commissioners of Canada",
                "Canada Border Services Agency",
            ],
        }
    )
    result = apply_org_corrections(df)
    assert result["org_name_en"][0] == "Office of the Privacy Commissioner of Canada"
    assert result["org_name_en"][1] == "Canada Border Services Agency"


def test_apply_org_corrections_leaves_correct_names_unchanged():
    df = pd.DataFrame({"service_id": [1], "org_name_en": ["Natural Resources Canada"]})
    result = apply_org_corrections(df)
    assert result["org_name_en"][0] == "Natural Resources Canada"


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
    df = pd.DataFrame(
        {
            "service_id": [1, 1, 1],
            "fiscal_yr": ["2018-2019", "2022-2023", "2020-2021"],
            "program_id": ["OLD01", "NEW01", "MID01"],
        }
    )
    result = build_program_lookup(df)
    assert result["1"] == ["NEW01"]


def test_build_program_lookup_handles_single_entry():
    df = pd.DataFrame(
        {
            "service_id": [42],
            "fiscal_yr": ["2023-2024"],
            "program_id": ["ABC01"],
        }
    )
    result = build_program_lookup(df)
    assert result["42"] == ["ABC01"]


def test_build_program_lookup_returns_string_keys():
    df = pd.DataFrame(
        {
            "service_id": [7],
            "fiscal_yr": ["2023-2024"],
            "program_id": ["XYZ99"],
        }
    )
    result = build_program_lookup(df)
    assert "7" in result
    assert 7 not in result


def test_build_program_lookup_handles_multiple_services():
    df = pd.DataFrame(
        {
            "service_id": [1, 1, 2, 2],
            "fiscal_yr": ["2021-2022", "2023-2024", "2020-2021", "2022-2023"],
            "program_id": ["A01", "A02", "B01", "B02"],
        }
    )
    result = build_program_lookup(df)
    assert result["1"] == ["A02"]
    assert result["2"] == ["B02"]


def test_build_program_lookup_collects_multiple_programs_in_same_year():
    df = pd.DataFrame(
        {
            "service_id": [1, 1, 1],
            "fiscal_yr": ["2022-2023", "2022-2023", "2022-2023"],
            "program_id": ["BUH04", "BUH08", "BUH12"],
        }
    )
    result = build_program_lookup(df)
    assert sorted(result["1"]) == ["BUH04", "BUH08", "BUH12"]


def _mock_post(mocker, results: list[dict]):
    mock = MagicMock()
    mock.json.return_value = {"results": results}
    mock.raise_for_status = MagicMock()
    return mocker.patch("update_services.requests.post", return_value=mock)


def test_resolve_orgs_builds_lookup_from_matched_result(mocker):
    _mock_post(
        mocker,
        [
            {
                "input": "Canada Border Services Agency",
                "gc_orgID": 26,
                "harmonized_name": "Canada Border Services Agency",
                "nom_harmonise": "Agence des services frontaliers du Canada",
                "abbreviation": "CBSA",
                "abreviation": "ASFC",
                "matched": True,
            }
        ],
    )
    result = resolve_orgs(["Canada Border Services Agency"])
    assert result["Canada Border Services Agency"] == {
        "gc_orgID": 26,
        "org_name_en": "Canada Border Services Agency",
        "org_name_fr": "Agence des services frontaliers du Canada",
        "acronym_en": "CBSA",
        "acronym_fr": "ASFC",
    }


def test_resolve_orgs_acronyms_default_to_none_when_absent(mocker):
    _mock_post(
        mocker,
        [
            {
                "input": "Canada Border Services Agency",
                "gc_orgID": 26,
                "harmonized_name": "Canada Border Services Agency",
                "nom_harmonise": "Agence des services frontaliers du Canada",
                "matched": True,
            }
        ],
    )
    result = resolve_orgs(["Canada Border Services Agency"])
    assert result["Canada Border Services Agency"]["acronym_en"] is None
    assert result["Canada Border Services Agency"]["acronym_fr"] is None


def test_resolve_orgs_raises_on_unmatched_org(mocker):
    _mock_post(
        mocker,
        [
            {
                "input": "Unknown Dept",
                "gc_orgID": None,
                "harmonized_name": None,
                "nom_harmonise": None,
                "matched": False,
            }
        ],
    )
    with pytest.raises(ValueError, match="Unknown Dept"):
        resolve_orgs(["Unknown Dept"])


def test_resolve_orgs_passes_all_names_in_one_request(mocker):
    mock_post = _mock_post(mocker, [])
    resolve_orgs(["Org A", "Org B", "Org C"])
    assert mock_post.call_args[1]["json"]["names"] == ["Org A", "Org B", "Org C"]


def test_resolve_orgs_batches_when_over_limit(mocker):
    mock_post = _mock_post(mocker, [])
    org_names = [f"Org {i}" for i in range(1500)]
    resolve_orgs(org_names)
    assert mock_post.call_count == 2
    assert len(mock_post.call_args_list[0][1]["json"]["names"]) == 1000
    assert len(mock_post.call_args_list[1][1]["json"]["names"]) == 500


SAMPLE_SERVICES = pd.DataFrame(
    {
        "service_id": [4158, 4159],
        "service_en": ["Customs Brokers Professional Examination", "Customs Brokers Licensing"],
        "service_fr": [
            "Examen de compétences professionnelles",
            "Agrément des courtiers en douane",
        ],
        "org_name_en": ["Canada Border Services Agency", "Canada Border Services Agency"],
    }
)

SAMPLE_PROGRAM_LOOKUP = {"4158": ["BWM06"]}

SAMPLE_ORG_LOOKUP = {
    "Canada Border Services Agency": {
        "gc_orgID": 26,
        "org_name_en": "Canada Border Services Agency",
        "org_name_fr": "Agence des services frontaliers du Canada",
        "acronym_en": "CBSA",
        "acronym_fr": "ASFC",
    }
}


def test_build_records_produces_correct_schema():
    records = build_records(SAMPLE_SERVICES, SAMPLE_PROGRAM_LOOKUP, SAMPLE_ORG_LOOKUP)
    assert len(records) == 2
    first = records[0]
    assert first["service_id"] == "4158"
    assert first["service_en"] == "Customs Brokers Professional Examination"
    assert first["service_fr"] == "Examen de compétences professionnelles"
    assert first["gc_orgID"] == 26
    assert first["org_name_en"] == "Canada Border Services Agency"
    assert first["org_name_fr"] == "Agence des services frontaliers du Canada"
    assert first["acronym_en"] == "CBSA"
    assert first["acronym_fr"] == "ASFC"
    assert first["program_id"] == ["BWM06"]


def test_build_records_program_id_is_none_when_missing():
    records = build_records(SAMPLE_SERVICES, SAMPLE_PROGRAM_LOOKUP, SAMPLE_ORG_LOOKUP)
    assert records[1]["service_id"] == "4159"
    assert records[1]["program_id"] is None


def test_build_records_service_id_is_string():
    records = build_records(SAMPLE_SERVICES, SAMPLE_PROGRAM_LOOKUP, SAMPLE_ORG_LOOKUP)
    for record in records:
        assert isinstance(record["service_id"], str)


def test_build_records_strips_whitespace_from_names():
    services = pd.DataFrame(
        {
            "service_id": [4158],
            "service_en": ["  Customs Brokers Professional Examination "],
            "service_fr": [" Examen de compétences professionnelles  "],
            "org_name_en": ["Canada Border Services Agency"],
        }
    )
    records = build_records(services, SAMPLE_PROGRAM_LOOKUP, SAMPLE_ORG_LOOKUP)
    assert records[0]["service_en"] == "Customs Brokers Professional Examination"
    assert records[0]["service_fr"] == "Examen de compétences professionnelles"


def test_write_json_produces_valid_json_file():
    records = [{"service_id": "1", "service_en": "Test"}]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "services.json"
        write_json(records, out_path)
        loaded = json.loads(out_path.read_text())
        assert loaded["services"] == records
        assert "generated_at" in loaded


def test_write_json_prints_record_count(capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        write_json([{"a": 1}, {"a": 2}], Path(tmpdir) / "services.json")
    assert "2" in capsys.readouterr().out


def test_update_generated_at_new_timestamp_when_file_absent():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "services.json"
        assert update_generated_at([{"service_id": "1"}], out_path)


def test_update_generated_at_reuses_timestamp_when_records_unchanged():
    records = [{"service_id": "1", "service_en": "Test"}]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "services.json"
        out_path.write_text(
            json.dumps({"generated_at": "2020-01-01T00:00:00+00:00", "services": records}),
            encoding="utf-8",
        )
        assert update_generated_at(records, out_path) == "2020-01-01T00:00:00+00:00"


def test_update_generated_at_bumps_timestamp_when_records_change():
    old_records = [{"service_id": "1", "service_en": "Old"}]
    new_records = [{"service_id": "1", "service_en": "New"}]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "services.json"
        out_path.write_text(
            json.dumps({"generated_at": "2020-01-01T00:00:00+00:00", "services": old_records}),
            encoding="utf-8",
        )
        assert update_generated_at(new_records, out_path) != "2020-01-01T00:00:00+00:00"


def test_update_generated_at_bumps_timestamp_when_existing_file_corrupt():
    records = [{"service_id": "1"}]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "services.json"
        out_path.write_text("{ not valid json", encoding="utf-8")
        assert update_generated_at(records, out_path)


def test_write_json_is_idempotent_when_data_unchanged():
    records = [{"service_id": "1", "service_en": "Test"}]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "services.json"
        write_json(records, out_path)
        first = out_path.read_text()
        write_json(records, out_path)
        assert out_path.read_text() == first
