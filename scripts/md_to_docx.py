#!/usr/bin/env python3
import argparse
import datetime as dt
import io
import os
import re
import zipfile


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _rpr(*, bold: bool = False, italic: bool = False, code: bool = False) -> str:
    parts: list[str] = []
    if bold:
        parts.append("<w:b/>")
    if italic:
        parts.append("<w:i/>")
    if code:
        parts.append(
            "<w:rFonts w:ascii=\"Consolas\" w:hAnsi=\"Consolas\" w:eastAsia=\"Consolas\" w:cs=\"Consolas\"/>"
        )
    if not parts:
        return ""
    return f"<w:rPr>{''.join(parts)}</w:rPr>"


def _run(text: str, *, bold: bool = False, italic: bool = False, code: bool = False) -> str:
    if text == "":
        return ""
    return f"<w:r>{_rpr(bold=bold, italic=italic, code=code)}<w:t xml:space=\"preserve\">{_xml_escape(text)}</w:t></w:r>"


_INLINE_RE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)")


def _runs_from_inline(md_text: str) -> list[str]:
    """
    Very small inline subset:
    - **bold**
    - *italic*
    - `code`
    """
    runs: list[str] = []
    pos = 0
    for m in _INLINE_RE.finditer(md_text):
        if m.start() > pos:
            runs.append(_run(md_text[pos : m.start()]))
        token = m.group(0)
        if token.startswith("**") and token.endswith("**"):
            runs.append(_run(token[2:-2], bold=True))
        elif token.startswith("`") and token.endswith("`"):
            runs.append(_run(token[1:-1], code=True))
        elif token.startswith("*") and token.endswith("*"):
            runs.append(_run(token[1:-1], italic=True))
        else:
            runs.append(_run(token))
        pos = m.end()
    if pos < len(md_text):
        runs.append(_run(md_text[pos:]))
    return [r for r in runs if r]


def _paragraph(
    text: str | None = None,
    *,
    style: str | None = None,
    num_id: int | None = None,
    ilvl: int | None = None,
    indent_left_twips: int | None = None,
    runs: list[str] | None = None,
) -> str:
    ppr_parts: list[str] = []
    if style:
        ppr_parts.append(f"<w:pStyle w:val=\"{style}\"/>")
    if num_id is not None and ilvl is not None:
        ppr_parts.append(
            f"<w:numPr><w:ilvl w:val=\"{ilvl}\"/><w:numId w:val=\"{num_id}\"/></w:numPr>"
        )
    if indent_left_twips is not None:
        ppr_parts.append(f"<w:ind w:left=\"{indent_left_twips}\"/>")
    ppr = f"<w:pPr>{''.join(ppr_parts)}</w:pPr>" if ppr_parts else ""

    if runs is None:
        runs = _runs_from_inline(text or "")
    return f"<w:p>{ppr}{''.join(runs)}</w:p>"


def _code_block(code: str) -> list[str]:
    # Represent as a sequence of paragraphs with monospace font.
    out: list[str] = []
    for line in code.splitlines():
        out.append(_paragraph(runs=[_run(line, code=True)], style="CodeBlock"))
    if not code.strip():
        out.append(_paragraph("", style="CodeBlock"))
    return out


def _table(rows: list[list[str]]) -> str:
    # Basic, no rowspans/colspans.
    if not rows:
        return ""
    col_count = max(len(r) for r in rows)
    tbl_grid = "".join("<w:gridCol w:w=\"2400\"/>" for _ in range(col_count))

    def tc(cell_text: str, *, header: bool) -> str:
        # Bold header cells (simple, no inline formatting in header).
        if header:
            cell_runs = [_run(cell_text.strip(), bold=True)]
        else:
            cell_runs = _runs_from_inline(cell_text.strip())
        para = _paragraph(runs=cell_runs)
        return (
            "<w:tc>"
            "<w:tcPr><w:tcW w:w=\"0\" w:type=\"auto\"/></w:tcPr>"
            f"{para}"
            "</w:tc>"
        )

    trs: list[str] = []
    for idx, row in enumerate(rows):
        header = idx == 0
        padded = row + [""] * (col_count - len(row))
        tcs = "".join(tc(c, header=header) for c in padded)
        trs.append(f"<w:tr>{tcs}</w:tr>")

    return (
        "<w:tbl>"
        "<w:tblPr>"
        "<w:tblW w:w=\"0\" w:type=\"auto\"/>"
        "<w:tblBorders>"
        "<w:top w:val=\"single\" w:sz=\"8\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:left w:val=\"single\" w:sz=\"8\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:bottom w:val=\"single\" w:sz=\"8\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:right w:val=\"single\" w:sz=\"8\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:insideH w:val=\"single\" w:sz=\"8\" w:space=\"0\" w:color=\"auto\"/>"
        "<w:insideV w:val=\"single\" w:sz=\"8\" w:space=\"0\" w:color=\"auto\"/>"
        "</w:tblBorders>"
        "</w:tblPr>"
        f"<w:tblGrid>{tbl_grid}</w:tblGrid>"
        f"{''.join(trs)}"
        "</w:tbl>"
    )


def _parse_table(lines: list[str], start: int) -> tuple[int, list[list[str]]]:
    def is_table_line(s: str) -> bool:
        s = s.strip()
        return s.startswith("|") and s.count("|") >= 2

    def is_sep_line(s: str) -> bool:
        s = s.strip()
        if not is_table_line(s):
            return False
        cells = [c.strip() for c in s.strip("|").split("|")]
        return all(re.fullmatch(r":?-{3,}:?", c) is not None for c in cells)

    if start + 1 >= len(lines):
        return start, []
    if not is_table_line(lines[start]) or not is_sep_line(lines[start + 1]):
        return start, []

    rows: list[list[str]] = []
    i = start
    while i < len(lines) and is_table_line(lines[i]):
        row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        rows.append(row)
        i += 1

    # drop separator row
    if len(rows) >= 2:
        rows.pop(1)
    return i, rows


def md_to_docx(md: str) -> bytes:
    blocks: list[str] = []
    lines = md.splitlines()
    i = 0
    in_code = False
    code_lines: list[str] = []

    def flush_paragraph(buf: list[str]) -> None:
        text = " ".join(s.strip() for s in buf).strip()
        if text:
            blocks.append(_paragraph(text))
        buf.clear()

    paragraph_buf: list[str] = []
    def current_ilvl(indent_spaces: int) -> int:
        return min(8, indent_spaces // 2)

    while i < len(lines):
        line = lines[i]

        if in_code:
            if line.strip().startswith("```"):
                blocks.extend(_code_block("\n".join(code_lines)))
                code_lines = []
                in_code = False
                i += 1
                continue
            code_lines.append(line.rstrip("\n"))
            i += 1
            continue

        if line.strip().startswith("```"):
            flush_paragraph(paragraph_buf)
            in_code = True
            code_lines = []
            i += 1
            continue

        # Horizontal rule
        if re.fullmatch(r"\s*-{3,}\s*", line or ""):
            flush_paragraph(paragraph_buf)
            blocks.append(_paragraph(""))
            i += 1
            continue

        # Tables (GFM pipe tables)
        next_i, rows = _parse_table(lines, i)
        if rows:
            flush_paragraph(paragraph_buf)
            blocks.append(_table(rows))
            i = next_i
            continue

        # Headings
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush_paragraph(paragraph_buf)
            level = len(m.group(1))
            text = m.group(2).strip()
            style = {1: "Heading1", 2: "Heading2", 3: "Heading3"}.get(level, "Heading3")
            blocks.append(_paragraph(text, style=style))
            i += 1
            continue

        # Blockquote (single-level)
        if line.lstrip().startswith(">"):
            flush_paragraph(paragraph_buf)
            quote_lines: list[str] = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                q = lines[i].lstrip()[1:]
                if q.startswith(" "):
                    q = q[1:]
                quote_lines.append(q.rstrip())
                i += 1
            quote_text = "\n".join(quote_lines).strip()
            for qline in quote_text.splitlines():
                blocks.append(_paragraph(qline, style="Quote", indent_left_twips=720))
            continue

        # Lists
        m = re.match(r"^(\s*)([-*])\s+(.*)$", line)
        if m:
            flush_paragraph(paragraph_buf)
            indent = len(m.group(1).replace("\t", "  "))
            ilvl = current_ilvl(indent)
            text = m.group(3).strip()
            blocks.append(_paragraph(text, num_id=1, ilvl=ilvl))
            i += 1
            continue

        # Blank line => flush paragraph
        if line.strip() == "":
            flush_paragraph(paragraph_buf)
            i += 1
            continue

        paragraph_buf.append(line)
        i += 1

    flush_paragraph(paragraph_buf)
    if in_code:
        blocks.extend(_code_block("\n".join(code_lines)))

    document_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">"
        "<w:body>"
        f"{''.join(blocks)}"
        "<w:sectPr>"
        "<w:pgSz w:w=\"12240\" w:h=\"15840\"/>"
        "<w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\" w:header=\"720\" w:footer=\"720\" w:gutter=\"0\"/>"
        "</w:sectPr>"
        "</w:body>"
        "</w:document>"
    )

    styles_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:styles xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
        "<w:style w:type=\"paragraph\" w:default=\"1\" w:styleId=\"Normal\">"
        "<w:name w:val=\"Normal\"/>"
        "<w:qFormat/>"
        "</w:style>"
        "<w:style w:type=\"paragraph\" w:styleId=\"Heading1\">"
        "<w:name w:val=\"heading 1\"/>"
        "<w:basedOn w:val=\"Normal\"/>"
        "<w:qFormat/>"
        "<w:rPr><w:b/><w:sz w:val=\"36\"/></w:rPr>"
        "</w:style>"
        "<w:style w:type=\"paragraph\" w:styleId=\"Heading2\">"
        "<w:name w:val=\"heading 2\"/>"
        "<w:basedOn w:val=\"Normal\"/>"
        "<w:qFormat/>"
        "<w:rPr><w:b/><w:sz w:val=\"28\"/></w:rPr>"
        "</w:style>"
        "<w:style w:type=\"paragraph\" w:styleId=\"Heading3\">"
        "<w:name w:val=\"heading 3\"/>"
        "<w:basedOn w:val=\"Normal\"/>"
        "<w:qFormat/>"
        "<w:rPr><w:b/><w:sz w:val=\"24\"/></w:rPr>"
        "</w:style>"
        "<w:style w:type=\"paragraph\" w:styleId=\"Quote\">"
        "<w:name w:val=\"Quote\"/>"
        "<w:basedOn w:val=\"Normal\"/>"
        "<w:qFormat/>"
        "<w:pPr><w:ind w:left=\"720\"/></w:pPr>"
        "<w:rPr><w:i/></w:rPr>"
        "</w:style>"
        "<w:style w:type=\"paragraph\" w:styleId=\"CodeBlock\">"
        "<w:name w:val=\"Code Block\"/>"
        "<w:basedOn w:val=\"Normal\"/>"
        "<w:qFormat/>"
        "<w:pPr><w:spacing w:before=\"120\" w:after=\"120\"/></w:pPr>"
        "<w:rPr>"
        "<w:rFonts w:ascii=\"Consolas\" w:hAnsi=\"Consolas\" w:eastAsia=\"Consolas\" w:cs=\"Consolas\"/>"
        "<w:sz w:val=\"20\"/>"
        "</w:rPr>"
        "</w:style>"
        "</w:styles>"
    )

    numbering_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:numbering xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
        "<w:abstractNum w:abstractNumId=\"1\">"
        "<w:multiLevelType w:val=\"hybridMultilevel\"/>"
        + "".join(
            f"<w:lvl w:ilvl=\"{lvl}\">"
            "<w:start w:val=\"1\"/>"
            "<w:numFmt w:val=\"bullet\"/>"
            "<w:lvlText w:val=\"•\"/>"
            "<w:lvlJc w:val=\"left\"/>"
            f"<w:pPr><w:ind w:left=\"{720 + (lvl * 360)}\" w:hanging=\"360\"/></w:pPr>"
            "</w:lvl>"
            for lvl in range(0, 9)
        )
        + "</w:abstractNum>"
        "<w:num w:numId=\"1\"><w:abstractNumId w:val=\"1\"/></w:num>"
        "</w:numbering>"
    )

    content_types = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
        "<Override PartName=\"/word/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml\"/>"
        "<Override PartName=\"/word/numbering.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml\"/>"
        "</Types>"
    )

    rels = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>"
        "<Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties\" Target=\"docProps/core.xml\"/>"
        "<Relationship Id=\"rId3\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties\" Target=\"docProps/app.xml\"/>"
        "</Relationships>"
    )

    doc_rels = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/>"
        "<Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering\" Target=\"numbering.xml\"/>"
        "</Relationships>"
    )

    core_props = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<cp:coreProperties xmlns:cp=\"http://schemas.openxmlformats.org/package/2006/metadata/core-properties\" "
        "xmlns:dc=\"http://purl.org/dc/elements/1.1/\" xmlns:dcterms=\"http://purl.org/dc/terms/\" "
        "xmlns:dcmitype=\"http://purl.org/dc/dcmitype/\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\">"
        "<dc:title>Converted Markdown</dc:title>"
        "<dc:creator>md_to_docx.py</dc:creator>"
        f"<dcterms:created xsi:type=\"dcterms:W3CDTF\">{dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace('+00:00','Z')}</dcterms:created>"
        "</cp:coreProperties>"
    )

    app_props = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Properties xmlns=\"http://schemas.openxmlformats.org/officeDocument/2006/extended-properties\" "
        "xmlns:vt=\"http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes\">"
        "<Application>md_to_docx.py</Application>"
        "</Properties>"
    )

    out = io.BytesIO()
    with zipfile.ZipFile(out, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/styles.xml", styles_xml)
        zf.writestr("word/numbering.xml", numbering_xml)
        zf.writestr("word/_rels/document.xml.rels", doc_rels)
        zf.writestr("docProps/core.xml", core_props)
        zf.writestr("docProps/app.xml", app_props)
    return out.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a small subset of Markdown to .docx (no external deps).")
    parser.add_argument("input_md", help="Path to input .md file")
    parser.add_argument("output_docx", help="Path to output .docx file")
    args = parser.parse_args()

    with open(args.input_md, "r", encoding="utf-8") as f:
        md = f.read()
    docx_bytes = md_to_docx(md)
    os.makedirs(os.path.dirname(os.path.abspath(args.output_docx)), exist_ok=True)
    with open(args.output_docx, "wb") as f:
        f.write(docx_bytes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
