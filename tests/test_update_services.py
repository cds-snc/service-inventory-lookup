"""Tests for update_services.py pipeline functions."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from update_services import (
    SOURCE_FISCAL_YEAR,
    build_records,
    download_csv,
    filter_fiscal_year,
    parse_program_ids,
    resolve_orgs,
    split_org_title,
    update_generated_at,
    validate_names_present,
    validate_unique_service_ids,
    write_json,
)

OTHER_FISCAL_YEAR = "2023-2024"


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
    _mock_urlopen(mocker, b"service_id,service_name_en,owner_org_title\n1,Foo,Bar | Baz\n")
    df = download_csv("https://example.com/data.csv")
    assert list(df.columns) == ["service_id", "service_name_en", "owner_org_title"]


def test_download_csv_reads_bom_encoded_header(mocker):
    _mock_urlopen(mocker, "﻿fiscal_yr,service_id\n2024-2025,1\n".encode("utf-8"))
    df = download_csv("https://example.com/data.csv")
    assert list(df.columns) == ["fiscal_yr", "service_id"]


def test_download_csv_keeps_service_ids_as_strings(mocker):
    _mock_urlopen(mocker, b"service_id,service_name_en\n0042,Foo\n")
    df = download_csv("https://example.com/data.csv")
    assert df["service_id"][0] == "0042"


def _fiscal_year_frame():
    return pd.DataFrame(
        {
            "fiscal_yr": [OTHER_FISCAL_YEAR, SOURCE_FISCAL_YEAR, OTHER_FISCAL_YEAR],
            "service_id": ["1", "2", "3"],
        }
    )


def test_filter_fiscal_year_keeps_only_pinned_year():
    result = filter_fiscal_year(_fiscal_year_frame())
    assert list(result["service_id"]) == ["2"]


def test_filter_fiscal_year_reindexes_result():
    result = filter_fiscal_year(_fiscal_year_frame())
    assert list(result.index) == [0]


def test_filter_fiscal_year_raises_when_pinned_year_absent():
    df = pd.DataFrame({"fiscal_yr": [OTHER_FISCAL_YEAR], "service_id": ["1"]})
    with pytest.raises(ValueError, match=SOURCE_FISCAL_YEAR):
        filter_fiscal_year(df)


def test_filter_fiscal_year_error_lists_years_present():
    df = pd.DataFrame({"fiscal_yr": ["2019-2020", OTHER_FISCAL_YEAR], "service_id": ["1", "2"]})
    with pytest.raises(ValueError, match="2019-2020"):
        filter_fiscal_year(df)


def test_validate_unique_service_ids_passes_when_unique():
    df = pd.DataFrame({"service_id": ["1", "2", "3"]})
    validate_unique_service_ids(df)


def test_validate_unique_service_ids_raises_on_duplicate():
    df = pd.DataFrame({"service_id": ["1", "2", "1"]})
    with pytest.raises(ValueError, match="Duplicate service_id"):
        validate_unique_service_ids(df)


def test_validate_names_present_passes_when_both_names_present():
    df = pd.DataFrame(
        {
            "service_id": ["1"],
            "service_name_en": ["Foo"],
            "service_name_fr": ["Machin"],
        }
    )
    validate_names_present(df)


def test_validate_names_present_raises_on_missing_english_name():
    df = pd.DataFrame(
        {
            "service_id": ["7"],
            "service_name_en": [float("nan")],
            "service_name_fr": ["Machin"],
        }
    )
    with pytest.raises(ValueError, match="7"):
        validate_names_present(df)


def test_validate_names_present_raises_on_missing_french_name():
    df = pd.DataFrame(
        {
            "service_id": ["8"],
            "service_name_en": ["Foo"],
            "service_name_fr": [float("nan")],
        }
    )
    with pytest.raises(ValueError, match="8"):
        validate_names_present(df)


def test_split_org_title_returns_both_halves():
    assert split_org_title(
        "Canada Border Services Agency | Agence des services frontaliers du Canada"
    ) == ("Canada Border Services Agency", "Agence des services frontaliers du Canada")


def test_split_org_title_strips_surrounding_whitespace():
    assert split_org_title("  Foo  |  Machin  ") == ("Foo", "Machin")


@pytest.mark.parametrize(
    "title",
    [
        "No separator here",
        "Foo | Machin | Extra",
        " | Machin",
        "Foo | ",
    ],
)
def test_split_org_title_raises_on_malformed_title(title):
    with pytest.raises(ValueError, match="Malformed owner_org_title"):
        split_org_title(title)


def test_parse_program_ids_returns_single_id_as_list():
    assert parse_program_ids("BWM06") == ["BWM06"]


def test_parse_program_ids_splits_comma_separated_ids():
    assert parse_program_ids("BED01,BED02,BED03") == ["BED01", "BED02", "BED03"]


def test_parse_program_ids_strips_whitespace_around_ids():
    assert parse_program_ids(" BED01 , BED02 ") == ["BED01", "BED02"]


@pytest.mark.parametrize("value", [float("nan"), "", "   ", ","])
def test_parse_program_ids_returns_none_when_no_ids(value):
    assert parse_program_ids(value) is None


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


CBSA_TITLE = "Canada Border Services Agency | Agence des services frontaliers du Canada"

SAMPLE_SERVICES = pd.DataFrame(
    {
        "service_id": ["4158", "4159"],
        "service_name_en": [
            "Customs Brokers Professional Examination",
            "Customs Brokers Licensing",
        ],
        "service_name_fr": [
            "Examen de compétences professionnelles",
            "Agrément des courtiers en douane",
        ],
        "program_id": ["BWM06", float("nan")],
        "owner_org_title": [CBSA_TITLE, CBSA_TITLE],
    }
)

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
    records = build_records(SAMPLE_SERVICES, SAMPLE_ORG_LOOKUP)
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
    records = build_records(SAMPLE_SERVICES, SAMPLE_ORG_LOOKUP)
    assert records[1]["service_id"] == "4159"
    assert records[1]["program_id"] is None


def test_build_records_collects_multiple_program_ids():
    services = SAMPLE_SERVICES.assign(program_id=["BED01,BED02", float("nan")])
    records = build_records(services, SAMPLE_ORG_LOOKUP)
    assert records[0]["program_id"] == ["BED01", "BED02"]


def test_build_records_resolves_org_from_english_half_of_title():
    records = build_records(SAMPLE_SERVICES, SAMPLE_ORG_LOOKUP)
    assert records[0]["gc_orgID"] == 26


def test_build_records_service_id_is_string():
    records = build_records(SAMPLE_SERVICES, SAMPLE_ORG_LOOKUP)
    for record in records:
        assert isinstance(record["service_id"], str)


def test_build_records_strips_whitespace_from_names():
    services = SAMPLE_SERVICES.assign(
        service_name_en=[
            "  Customs Brokers Professional Examination ",
            "Customs Brokers Licensing",
        ],
        service_name_fr=[" Examen de compétences professionnelles  ", "Agrément des courtiers"],
    )
    records = build_records(services, SAMPLE_ORG_LOOKUP)
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


def test_write_json_includes_source_block():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "services.json"
        write_json([{"service_id": "1"}], out_path)
        source = json.loads(out_path.read_text())["source"]
        assert source["fiscal_year"] == SOURCE_FISCAL_YEAR
        assert source["dataset_url"].startswith("https://open.canada.ca/")
        assert source["csv"].endswith(".csv")


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
