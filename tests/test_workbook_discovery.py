from pathlib import Path

from stock_research.workbook_discovery import discover_workbooks, find_workbook_for_ticker


def test_discover_workbooks_chooses_one_excel_file_per_ticker_folder(tmp_path: Path) -> None:
    aapl = tmp_path / "AAPL"
    aapl.mkdir()
    old_file = aapl / "notes.xlsx"
    best_file = aapl / "ZP Quarterly matrix (AAPL).xlsx"
    pdf_file = aapl / "notes.pdf"
    temp_file = aapl / "~$ZP Quarterly matrix (AAPL).xlsx"
    old_file.write_text("old", encoding="utf-8")
    best_file.write_text("best", encoding="utf-8")
    pdf_file.write_text("ignore", encoding="utf-8")
    temp_file.write_text("ignore", encoding="utf-8")

    msft = tmp_path / "MSFT"
    msft.mkdir()
    msft_workbook = msft / "workbook.xlsm"
    msft_workbook.write_text("macro", encoding="utf-8")

    candidates = discover_workbooks(tmp_path)

    assert [candidate.ticker_hint for candidate in candidates] == ["AAPL", "MSFT"]
    assert candidates[0].path == best_file
    assert candidates[1].path == msft_workbook


def test_discover_workbooks_ignores_cache_and_build_folders(tmp_path: Path) -> None:
    ignored = tmp_path / "build" / "AAPL"
    ignored.mkdir(parents=True)
    (ignored / "ZP Quarterly matrix (AAPL).xlsx").write_text("ignore", encoding="utf-8")

    assert discover_workbooks(tmp_path) == ()


def test_discover_workbooks_ignores_root_level_workbooks(tmp_path: Path) -> None:
    first = tmp_path / "AAPL.xlsx"
    second = tmp_path / "MSFT.xlsx"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")

    assert discover_workbooks(tmp_path) == ()


def test_discover_workbooks_ignores_archive_folders_and_numbered_matrix_files(tmp_path: Path) -> None:
    ignored_archive = tmp_path / "1 - Old"
    ignored_archive.mkdir()
    (ignored_archive / "ZP Quarterly Matrix (OLD).xlsx").write_text("ignore", encoding="utf-8")

    ignored_zzz = tmp_path / "ZZZ Archive"
    ignored_zzz.mkdir()
    (ignored_zzz / "ZP Quarterly Matrix (ZZZ).xlsx").write_text("ignore", encoding="utf-8")

    aapl = tmp_path / "AAPL"
    aapl.mkdir()
    old_numbered = aapl / "1 - ZP Quarterly matrix (AAPL).xlsx"
    preferred = aapl / "ZP Quarterly Matrix (AAPL).xlsx"
    old_numbered.write_text("ignore", encoding="utf-8")
    preferred.write_text("use", encoding="utf-8")

    candidates = discover_workbooks(tmp_path)

    assert len(candidates) == 1
    assert candidates[0].ticker_hint == "AAPL"
    assert candidates[0].path == preferred


def test_find_workbook_for_ticker_searches_only_requested_ticker_folder(tmp_path: Path) -> None:
    archive = tmp_path / "1 - AAPL Archive"
    archive.mkdir()
    (archive / "ZP Quarterly Matrix (AAPL).xlsx").write_text("ignore", encoding="utf-8")

    aapl = tmp_path / "AAPL Apple Inc"
    aapl.mkdir()
    (aapl / "1 - ZP Quarterly matrix (AAPL).xlsx").write_text("old", encoding="utf-8")
    preferred = aapl / "ZP Quarterly Matrix (AAPL)- Rev, CE, Actual.xlsx"
    preferred.write_text("use", encoding="utf-8")
    (aapl / "other spreadsheet.xlsx").write_text("ignore", encoding="utf-8")

    wmt = tmp_path / "WMT"
    wmt.mkdir()
    wmt_file = wmt / "ZP Quarterly Matrix (WMT).xlsx"
    wmt_file.write_text("wmt", encoding="utf-8")

    candidate = find_workbook_for_ticker(tmp_path, "AAPL")

    assert candidate is not None
    assert candidate.ticker_hint == "AAPL"
    assert candidate.path == preferred
