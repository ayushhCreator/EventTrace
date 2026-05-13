import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eventtrace.causelist.causelist_parser import parse_cases_from_block


def test_heading_wrapper_and_transitional_lines_do_not_create_sections() -> None:
    block = "\n".join(
        [
            "IN OFR JUDGMENT",
            "FOR JUDGMENT",
            "1",
            "WP.CT/63/2026",
            "(AT 2:00 P.M)",
            "ABINASH KUMAR",
            "VS",
            "THE UNION OF INDIA AND ORS",
            "MD. RAZIUDDIN",
            "AFTER THAT IN OLD CONTEMPT",
            "2",
            "CPAN/1623/2000",
            "NAMITA GHOSH",
            "VS",
            "MAHENDRA NATH DUTTA",
            "BHABANI PROSAD MONDAL",
        ]
    )

    cases = parse_cases_from_block(block)

    assert [c["case_ref"] for c in cases] == ["WP.CT/63/2026", "CPAN/1623/2000"]
    # 'IN OFR JUDGMENT' should not become its own section; 'FOR JUDGMENT' maps to 'JUDGMENT'
    assert cases[0]["section"] == "JUDGMENT"
    # 'AFTER THAT IN OLD CONTEMPT' should be normalised to 'OLD CONTEMPT' -> 'CONTEMPT'
    assert cases[1]["section"] == "CONTEMPT"
