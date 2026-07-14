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
    fetch_code_labels,
    filter_fiscal_year,
    label_codes,
    parse_list_cell,
    parse_programs,
    parse_uri,
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


def test_parse_list_cell_returns_single_value_as_list():
    assert parse_list_cell("BWM06") == ["BWM06"]


def test_parse_list_cell_splits_comma_separated_values():
    assert parse_list_cell("BED01,BED02,BED03") == ["BED01", "BED02", "BED03"]


def test_parse_list_cell_strips_whitespace_around_values():
    assert parse_list_cell(" BED01 , BED02 ") == ["BED01", "BED02"]


def test_parse_list_cell_strips_quotes_from_quoted_values():
    assert parse_list_cell('"Business Growth", "Internal services"') == [
        "Business Growth",
        "Internal services",
    ]


def test_parse_list_cell_keeps_commas_inside_quoted_values():
    # program_name_en quotes each value and 103 names contain a comma; splitting
    # on "," instead of parsing as CSV misaligns them against program_id.
    assert parse_list_cell('"Care, Education, Recreation", "Business Growth"') == [
        "Care, Education, Recreation",
        "Business Growth",
    ]


@pytest.mark.parametrize("value", [float("nan"), "", "   ", ","])
def test_parse_list_cell_returns_empty_list_when_no_values(value):
    assert parse_list_cell(value) == []


def _program_row(program_id, name_en, name_fr, service_id="1"):
    return pd.Series(
        {
            "service_id": service_id,
            "program_id": program_id,
            "program_name_en": name_en,
            "program_name_fr": name_fr,
        }
    )


def test_parse_programs_pairs_single_program_with_its_names():
    row = _program_row("ISS00", '"Internal services"', '"Services internes"')
    assert parse_programs(row) == [
        {
            "program_id": "ISS00",
            "program_name_en": "Internal services",
            "program_name_fr": "Services internes",
        }
    ]


def test_parse_programs_pairs_each_id_with_its_own_name():
    row = _program_row(
        "BED01,BED02",
        '"Inclusive Communities", "Business Growth"',
        '"Collectivités inclusives", "Croissance des entreprises"',
    )
    programs = parse_programs(row)
    assert [p["program_id"] for p in programs] == ["BED01", "BED02"]
    assert [p["program_name_en"] for p in programs] == ["Inclusive Communities", "Business Growth"]
    assert [p["program_name_fr"] for p in programs] == [
        "Collectivités inclusives",
        "Croissance des entreprises",
    ]


def test_parse_programs_keeps_pairing_when_a_name_contains_a_comma():
    row = _program_row(
        "CER01,BED01",
        '"Care, Education, Recreation", "Business Growth"',
        '"Soins, éducation, loisirs", "Croissance des entreprises"',
    )
    programs = parse_programs(row)
    assert programs[0] == {
        "program_id": "CER01",
        "program_name_en": "Care, Education, Recreation",
        "program_name_fr": "Soins, éducation, loisirs",
    }
    assert programs[1]["program_id"] == "BED01"


def test_parse_programs_returns_none_when_service_has_no_programs():
    assert parse_programs(_program_row(float("nan"), float("nan"), float("nan"))) is None


def test_parse_programs_raises_when_ids_and_names_do_not_line_up():
    row = _program_row("BED01,BED02", '"Only One Name"', '"Un seul nom"')
    with pytest.raises(ValueError, match="2 program IDs"):
        parse_programs(row)


def test_parse_uri_returns_url_when_present():
    assert parse_uri("https://example.gc.ca/service") == "https://example.gc.ca/service"


def test_parse_uri_strips_surrounding_whitespace():
    assert parse_uri("  https://example.gc.ca/service  ") == "https://example.gc.ca/service"


@pytest.mark.parametrize("value", [float("nan"), "", "   "])
def test_parse_uri_returns_none_when_blank(value):
    assert parse_uri(value) is None


SAMPLE_CODE_LABELS = {
    "service_type": {
        "INFO": {"en": "Information", "fr": "Information"},
        "CER": {"en": "Care, Education, Recreation", "fr": "Soins, éducation, loisirs"},
    },
    "service_scope": {"EXTERN": {"en": "External Service", "fr": "Service externe"}},
    "client_target_groups": {"PERSON": {"en": "Persons", "fr": "Personnes"}},
    "service_recipient_type": {
        "SOCIETY": {"en": "Untargeted, Societal-based service", "fr": "Service non-ciblé"}
    },
}


def test_label_codes_expands_a_single_code():
    assert label_codes("EXTERN", "service_scope", SAMPLE_CODE_LABELS) == [
        {"code": "EXTERN", "name_en": "External Service", "name_fr": "Service externe"}
    ]


def test_label_codes_expands_each_code_in_a_multi_valued_cell():
    labelled = label_codes("INFO,CER", "service_type", SAMPLE_CODE_LABELS)
    assert [c["code"] for c in labelled] == ["INFO", "CER"]
    assert labelled[1]["name_en"] == "Care, Education, Recreation"


def test_label_codes_returns_empty_list_when_cell_is_blank():
    assert label_codes(float("nan"), "service_scope", SAMPLE_CODE_LABELS) == []


def test_label_codes_raises_on_code_missing_from_schema():
    with pytest.raises(ValueError, match="NEWCODE"):
        label_codes("NEWCODE", "service_scope", SAMPLE_CODE_LABELS)


def test_fetch_code_labels_reads_choices_for_each_classification_field(mocker):
    schema = {
        "resources": [
            {
                "fields": [
                    {"id": field, "choices": choices}
                    for field, choices in SAMPLE_CODE_LABELS.items()
                ]
                + [{"id": "service_name_en"}]
            }
        ]
    }
    _mock_urlopen(mocker, json.dumps(schema).encode())
    labels = fetch_code_labels("https://example.com/schema.json")
    assert labels["service_scope"]["EXTERN"]["en"] == "External Service"
    assert "service_name_en" not in labels


def test_fetch_code_labels_raises_when_a_field_has_no_choices(mocker):
    schema = {"resources": [{"fields": [{"id": "service_scope", "choices": {}}]}]}
    _mock_urlopen(mocker, json.dumps(schema).encode())
    with pytest.raises(ValueError, match="service_type"):
        fetch_code_labels("https://example.com/schema.json")


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
        "program_name_en": ['"Border Management"', float("nan")],
        "program_name_fr": ['"Gestion de la frontière"', float("nan")],
        "service_uri_en": ["https://example.gc.ca/exam", float("nan")],
        "service_uri_fr": ["https://example.gc.ca/examen", float("nan")],
        "service_type": ["INFO", "INFO"],
        "service_scope": ["EXTERN", "EXTERN"],
        "client_target_groups": ["PERSON", "PERSON"],
        "service_recipient_type": ["SOCIETY", "SOCIETY"],
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
    records = build_records(SAMPLE_SERVICES, SAMPLE_ORG_LOOKUP, SAMPLE_CODE_LABELS)
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
    assert first["programs"] == [
        {
            "program_id": "BWM06",
            "program_name_en": "Border Management",
            "program_name_fr": "Gestion de la frontière",
        }
    ]


def test_build_records_programs_is_none_when_missing():
    records = build_records(SAMPLE_SERVICES, SAMPLE_ORG_LOOKUP, SAMPLE_CODE_LABELS)
    assert records[1]["service_id"] == "4159"
    assert records[1]["programs"] is None


def test_build_records_pairs_multiple_programs_with_their_names():
    services = SAMPLE_SERVICES.assign(
        program_id=["BED01,BED02", float("nan")],
        program_name_en=['"Inclusive Communities", "Business Growth"', float("nan")],
        program_name_fr=['"Collectivités inclusives", "Croissance"', float("nan")],
    )
    records = build_records(services, SAMPLE_ORG_LOOKUP, SAMPLE_CODE_LABELS)
    assert records[0]["programs"] == [
        {
            "program_id": "BED01",
            "program_name_en": "Inclusive Communities",
            "program_name_fr": "Collectivités inclusives",
        },
        {
            "program_id": "BED02",
            "program_name_en": "Business Growth",
            "program_name_fr": "Croissance",
        },
    ]


def test_build_records_includes_service_uris():
    records = build_records(SAMPLE_SERVICES, SAMPLE_ORG_LOOKUP, SAMPLE_CODE_LABELS)
    assert records[0]["service_uri_en"] == "https://example.gc.ca/exam"
    assert records[0]["service_uri_fr"] == "https://example.gc.ca/examen"


def test_build_records_service_uris_are_none_when_blank():
    records = build_records(SAMPLE_SERVICES, SAMPLE_ORG_LOOKUP, SAMPLE_CODE_LABELS)
    assert records[1]["service_uri_en"] is None
    assert records[1]["service_uri_fr"] is None


def test_build_records_labels_each_classification_field():
    records = build_records(SAMPLE_SERVICES, SAMPLE_ORG_LOOKUP, SAMPLE_CODE_LABELS)
    first = records[0]
    assert first["service_type"] == [
        {"code": "INFO", "name_en": "Information", "name_fr": "Information"}
    ]
    assert first["service_scope"] == [
        {"code": "EXTERN", "name_en": "External Service", "name_fr": "Service externe"}
    ]
    assert first["client_target_groups"] == [
        {"code": "PERSON", "name_en": "Persons", "name_fr": "Personnes"}
    ]
    assert first["service_recipient_type"][0]["code"] == "SOCIETY"


def test_build_records_resolves_org_from_english_half_of_title():
    records = build_records(SAMPLE_SERVICES, SAMPLE_ORG_LOOKUP, SAMPLE_CODE_LABELS)
    assert records[0]["gc_orgID"] == 26


def test_build_records_service_id_is_string():
    records = build_records(SAMPLE_SERVICES, SAMPLE_ORG_LOOKUP, SAMPLE_CODE_LABELS)
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
    records = build_records(services, SAMPLE_ORG_LOOKUP, SAMPLE_CODE_LABELS)
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
