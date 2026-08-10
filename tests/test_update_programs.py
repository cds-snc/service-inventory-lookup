"""Tests for update_programs.py pipeline functions."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from update_programs import (
    DEPT_COL_EN,
    NAME_COLS,
    PROG_CODE_COL,
    PROGRAM_CODES_URL,
    SOURCE_DATASET_URL,
    SOURCE_FISCAL_YEAR,
    build_records,
    filter_program_rows,
    resolve_orgs,
    update_generated_at,
    validate_names_present,
    validate_prog_codes,
    write_json,
)

PROG_NAME_EN = NAME_COLS["program_name_en"]
PROG_NAME_FR = NAME_COLS["program_name_fr"]
CR_NAME_EN = NAME_COLS["core_responsibility_en"]
CR_NAME_FR = NAME_COLS["core_responsibility_fr"]


def _mock_post(mocker, results: list[dict]):
    mock = MagicMock()
    mock.json.return_value = {"results": results}
    mock.raise_for_status = MagicMock()
    return mocker.patch("update_programs.requests.post", return_value=mock)


def test_filter_program_rows_drops_core_responsibility_rows():
    # Core-responsibility rows carry a CR code (e.g. BWN00) but have no
    # Program Inventory code of their own - that column is blank.
    df = pd.DataFrame(
        {
            PROG_CODE_COL: ["", "BWN01"],
            PROG_NAME_EN: ["", "Trade and Market Expansion"],
        }
    )
    result = filter_program_rows(df)
    assert list(result[PROG_CODE_COL]) == ["BWN01"]


def test_filter_program_rows_drops_blank_code_rows():
    df = pd.DataFrame(
        {
            PROG_CODE_COL: ["BWN01", float("nan"), "  "],
            PROG_NAME_EN: ["Trade and Market Expansion", "", ""],
        }
    )
    result = filter_program_rows(df)
    assert len(result) == 1
    assert result[PROG_CODE_COL].iloc[0] == "BWN01"


def test_filter_program_rows_keeps_all_program_rows():
    df = pd.DataFrame({PROG_CODE_COL: ["BWN01", "ISS0Z"], PROG_NAME_EN: ["A", "B"]})
    result = filter_program_rows(df)
    assert len(result) == 2


def test_validate_prog_codes_accepts_iss0z_and_iss1z():
    df = pd.DataFrame({PROG_CODE_COL: ["BWN01", "ISS0Z", "ISS1Z"]})
    validate_prog_codes(df)  # should not raise


def test_validate_prog_codes_rejects_wrong_length():
    df = pd.DataFrame({PROG_CODE_COL: ["BW01"]})
    with pytest.raises(ValueError, match="BW01"):
        validate_prog_codes(df)


def test_validate_prog_codes_rejects_lowercase():
    df = pd.DataFrame({PROG_CODE_COL: ["bwn01"]})
    with pytest.raises(ValueError, match="bwn01"):
        validate_prog_codes(df)


def _names_df(**overrides) -> pd.DataFrame:
    columns = {
        PROG_CODE_COL: ["BWN01"],
        PROG_NAME_EN: ["Trade and Market Expansion"],
        PROG_NAME_FR: ["Commerce et expansion des marchés"],
        CR_NAME_EN: ["Domestic and International Markets"],
        CR_NAME_FR: ["Marchés nationaux et internationaux"],
    }
    columns.update(overrides)
    return pd.DataFrame(columns)


def test_validate_names_present_passes_when_names_complete():
    validate_names_present(_names_df())  # should not raise


def test_validate_names_present_raises_on_missing_english_name():
    df = _names_df(
        **{
            PROG_CODE_COL: ["BWN01", "BWN02"],
            PROG_NAME_EN: ["Trade and Market Expansion", float("nan")],
            PROG_NAME_FR: ["Commerce", "Commerce"],
            CR_NAME_EN: ["Domestic Markets", "Domestic Markets"],
            CR_NAME_FR: ["Marchés nationaux", "Marchés nationaux"],
        }
    )
    with pytest.raises(ValueError, match="BWN02"):
        validate_names_present(df)


def test_validate_names_present_raises_on_missing_french_name():
    # The French columns are new to the bilingual file - a row complete in
    # English must still fail if its French name is missing.
    df = _names_df(**{PROG_NAME_FR: [float("nan")]})
    with pytest.raises(ValueError, match="BWN01"):
        validate_names_present(df)


def test_resolve_orgs_builds_lookup_from_matched_result(mocker):
    _mock_post(
        mocker,
        [
            {
                "input": "Agriculture and Agri-Food (Department of)",
                "gc_orgID": 2222,
                "harmonized_name": "Agriculture and Agri-Food Canada",
                "nom_harmonise": "Agriculture et Agroalimentaire Canada",
                "abbreviation": "AAFC",
                "abreviation": "AAC",
                "matched": True,
            }
        ],
    )
    result = resolve_orgs(["Agriculture and Agri-Food (Department of)"])
    assert result["Agriculture and Agri-Food (Department of)"] == {
        "gc_orgID": 2222,
        "org_name_en": "Agriculture and Agri-Food Canada",
        "org_name_fr": "Agriculture et Agroalimentaire Canada",
        "acronym_en": "AAFC",
        "acronym_fr": "AAC",
    }


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


def test_resolve_orgs_batches_when_over_limit(mocker):
    mock_post = _mock_post(mocker, [])
    org_names = [f"Org {i}" for i in range(1500)]
    resolve_orgs(org_names)
    assert mock_post.call_count == 2
    assert len(mock_post.call_args_list[0][1]["json"]["names"]) == 1000
    assert len(mock_post.call_args_list[1][1]["json"]["names"]) == 500


ORG_LOOKUP = {
    "Agriculture and Agri-Food (Department of)": {
        "gc_orgID": 2222,
        "org_name_en": "Agriculture and Agri-Food Canada",
        "org_name_fr": "Agriculture et Agroalimentaire Canada",
        "acronym_en": "AAFC",
        "acronym_fr": "AAC",
    },
    "Health (Department of)": {
        "gc_orgID": 1111,
        "org_name_en": "Health Canada",
        "org_name_fr": "Santé Canada",
        "acronym_en": "HC",
        "acronym_fr": "SC",
    },
}


def _program_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


PROGRAM_ROW = {
    DEPT_COL_EN: "Agriculture and Agri-Food (Department of)",
    PROG_CODE_COL: "BWN01",
    PROG_NAME_EN: "Trade and Market Expansion",
    PROG_NAME_FR: "Commerce et expansion des marchés",
    CR_NAME_EN: "Domestic and International Markets",
    CR_NAME_FR: "Marchés nationaux et internationaux",
}


def test_build_records_composes_program_code_id():
    records = build_records(_program_df([PROGRAM_ROW]), ORG_LOOKUP)
    assert len(records) == 1
    record = records[0]
    assert record["program_code_id"] == "2222-BWN01"
    assert record["prog_code"] == "BWN01"
    assert record["gc_orgID"] == 2222
    assert record["program_name_en"] == "Trade and Market Expansion"
    assert record["program_name_fr"] == "Commerce et expansion des marchés"
    assert record["core_responsibility_en"] == "Domestic and International Markets"
    assert record["core_responsibility_fr"] == "Marchés nationaux et internationaux"
    assert record["org_name_en"] == "Agriculture and Agri-Food Canada"
    assert record["org_name_fr"] == "Agriculture et Agroalimentaire Canada"
    assert record["acronym_en"] == "AAFC"
    assert record["acronym_fr"] == "AAC"


def test_build_records_raises_on_duplicate_key():
    df = _program_df([PROGRAM_ROW, {**PROGRAM_ROW, PROG_NAME_EN: "A different name"}])
    with pytest.raises(ValueError, match="Duplicate"):
        build_records(df, ORG_LOOKUP)


def test_build_records_strips_whitespace_from_names():
    df = _program_df(
        [
            {
                **PROGRAM_ROW,
                PROG_NAME_EN: "  Trade and Market Expansion ",
                CR_NAME_FR: " Marchés nationaux et internationaux  ",
            }
        ]
    )
    record = build_records(df, ORG_LOOKUP)[0]
    assert record["program_name_en"] == "Trade and Market Expansion"
    assert record["core_responsibility_fr"] == "Marchés nationaux et internationaux"


def test_build_records_sorts_by_org_then_code():
    df = _program_df(
        [
            PROGRAM_ROW,
            {**PROGRAM_ROW, PROG_CODE_COL: "BWN02"},
            {**PROGRAM_ROW, DEPT_COL_EN: "Health (Department of)", PROG_CODE_COL: "HHH01"},
        ]
    )
    records = build_records(df, ORG_LOOKUP)
    assert [r["program_code_id"] for r in records] == ["1111-HHH01", "2222-BWN01", "2222-BWN02"]


def test_update_generated_at_new_timestamp_when_file_absent():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "program_codes.json"
        assert update_generated_at([{"program_code_id": "2222-BWN01"}], out_path)


def test_update_generated_at_reuses_timestamp_when_programs_unchanged():
    records = [{"program_code_id": "2222-BWN01"}]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "program_codes.json"
        out_path.write_text(
            json.dumps(
                {
                    "generated_at": "2020-01-01T00:00:00+00:00",
                    "source": {"fiscal_year": "2025-26"},
                    "programs": records,
                }
            ),
            encoding="utf-8",
        )
        assert update_generated_at(records, out_path) == "2020-01-01T00:00:00+00:00"


def test_update_generated_at_bumps_timestamp_when_programs_change():
    old_records = [{"program_code_id": "2222-BWN01", "program_name_en": "Old"}]
    new_records = [{"program_code_id": "2222-BWN01", "program_name_en": "New"}]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "program_codes.json"
        out_path.write_text(
            json.dumps(
                {"generated_at": "2020-01-01T00:00:00+00:00", "source": {}, "programs": old_records}
            ),
            encoding="utf-8",
        )
        assert update_generated_at(new_records, out_path) != "2020-01-01T00:00:00+00:00"


def test_update_generated_at_bumps_timestamp_when_existing_file_corrupt():
    records = [{"program_code_id": "2222-BWN01"}]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "program_codes.json"
        out_path.write_text("{ not valid json", encoding="utf-8")
        assert update_generated_at(records, out_path)


def test_write_json_produces_valid_json_file():
    records = [{"program_code_id": "2222-BWN01"}]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "program_codes.json"
        write_json(records, out_path)
        loaded = json.loads(out_path.read_text())
        assert loaded["programs"] == records
        assert "generated_at" in loaded
        assert loaded["source"] == {
            "fiscal_year": SOURCE_FISCAL_YEAR,
            "dataset_url": SOURCE_DATASET_URL,
            "csv": PROGRAM_CODES_URL,
        }


def test_write_json_prints_record_count(capsys):
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "program_codes.json"
        write_json([{"program_code_id": "a"}, {"program_code_id": "b"}], out_path)
    assert "2" in capsys.readouterr().out


def test_write_json_is_idempotent_when_data_unchanged():
    records = [{"program_code_id": "2222-BWN01"}]
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "program_codes.json"
        write_json(records, out_path)
        first = out_path.read_text()
        write_json(records, out_path)
        assert out_path.read_text() == first
