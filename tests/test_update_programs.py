"""Tests for update_programs.py pipeline functions."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from update_programs import (
    CR_NAME_COL,
    DEPT_COL_EN,
    DEPT_COL_FR,
    PROG_CODE_COL,
    PROG_NAME_COL,
    SOURCE_DATASET_URL,
    SOURCE_FISCAL_YEAR,
    build_keyed_records,
    combine_records,
    filter_program_rows,
    resolve_orgs,
    update_generated_at,
    validate_prog_codes,
    write_json,
)


def _mock_post(mocker, results: list[dict]):
    mock = MagicMock()
    mock.json.return_value = {"results": results}
    mock.raise_for_status = MagicMock()
    return mocker.patch("update_programs.requests.post", return_value=mock)


def test_filter_program_rows_drops_core_responsibility_rows():
    # Core-responsibility rows carry a CR code (e.g. BWN00) but have no
    # ProgramInventory code of their own - that column is blank.
    df = pd.DataFrame(
        {
            PROG_CODE_COL: ["", "BWN01"],
            PROG_NAME_COL: ["", "Trade and Market Expansion"],
        }
    )
    result = filter_program_rows(df)
    assert list(result[PROG_CODE_COL]) == ["BWN01"]


def test_filter_program_rows_drops_blank_code_rows():
    df = pd.DataFrame(
        {
            PROG_CODE_COL: ["BWN01", float("nan"), "  "],
            PROG_NAME_COL: ["Trade and Market Expansion", "", ""],
        }
    )
    result = filter_program_rows(df)
    assert len(result) == 1
    assert result[PROG_CODE_COL].iloc[0] == "BWN01"


def test_filter_program_rows_keeps_all_program_rows():
    df = pd.DataFrame({PROG_CODE_COL: ["BWN01", "ISS0Z"], PROG_NAME_COL: ["A", "B"]})
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


def test_resolve_orgs_builds_lookup_from_matched_result(mocker):
    _mock_post(
        mocker,
        [
            {
                "input": "Agriculture and Agri-Food Canada",
                "gc_orgID": 2222,
                "harmonized_name": "Agriculture and Agri-Food Canada",
                "nom_harmonise": "Agriculture et Agroalimentaire Canada",
                "abbreviation": "AAFC",
                "abreviation": "AAC",
                "matched": True,
            }
        ],
    )
    result = resolve_orgs(["Agriculture and Agri-Food Canada"])
    assert result["Agriculture and Agri-Food Canada"] == {
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
    "Agriculture and Agri-Food Canada": {
        "gc_orgID": 2222,
        "org_name_en": "Agriculture and Agri-Food Canada",
        "org_name_fr": "Agriculture et Agroalimentaire Canada",
        "acronym_en": "AAFC",
        "acronym_fr": "AAC",
    }
}

EN_DF = pd.DataFrame(
    {
        DEPT_COL_EN: ["Agriculture and Agri-Food Canada"],
        PROG_CODE_COL: ["BWN01"],
        PROG_NAME_COL: ["Trade and Market Expansion"],
        CR_NAME_COL: ["Domestic and International Markets"],
    }
)

FR_DF = pd.DataFrame(
    {
        DEPT_COL_FR: ["Agriculture et Agroalimentaire Canada"],
        PROG_CODE_COL: ["BWN01"],
        PROG_NAME_COL: ["Commerce et expansion des marchés"],
        CR_NAME_COL: ["Marchés nationaux et internationaux"],
    }
)

ORG_LOOKUP_FR = {
    "Agriculture et Agroalimentaire Canada": ORG_LOOKUP["Agriculture and Agri-Food Canada"],
}


def test_build_keyed_records_raises_on_duplicate_key_within_file():
    df = pd.DataFrame(
        {
            DEPT_COL_EN: ["Agriculture and Agri-Food Canada", "Agriculture and Agri-Food Canada"],
            PROG_CODE_COL: ["BWN01", "BWN01"],
            PROG_NAME_COL: ["A", "B"],
            CR_NAME_COL: ["C", "D"],
        }
    )
    with pytest.raises(ValueError, match="Duplicate"):
        build_keyed_records(df, DEPT_COL_EN, ORG_LOOKUP, lang="en")


def test_combine_records_composes_program_code_id():
    en_records = build_keyed_records(EN_DF, DEPT_COL_EN, ORG_LOOKUP, lang="en")
    fr_records = build_keyed_records(FR_DF, DEPT_COL_FR, ORG_LOOKUP_FR, lang="fr")
    records = combine_records(en_records, fr_records)
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


def test_combine_records_raises_on_key_mismatch():
    en_records = build_keyed_records(EN_DF, DEPT_COL_EN, ORG_LOOKUP, lang="en")
    fr_records = {}
    with pytest.raises(ValueError, match=r"Only in EN.*2222.*BWN01"):
        combine_records(en_records, fr_records)


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


def test_update_generated_at_ignores_source_block_changes():
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
        # write_json would now be called with a different (newer) fiscal year source
        # block but identical programs; the timestamp must not bump.
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
            "csv_en": loaded["source"]["csv_en"],
            "csv_fr": loaded["source"]["csv_fr"],
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
