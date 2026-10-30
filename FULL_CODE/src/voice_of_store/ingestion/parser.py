"""Extract text from uploaded unstructured documents (PDF, TXT, CSV) into chunked text."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DocumentChunk:
    chunk_index: int
    source_reference: str  # e.g., "Page 1", "Lines 1-50", "Rows 1-20"
    raw_text: str


def parse_txt(content: str | bytes) -> list[DocumentChunk]:
    if isinstance(content, bytes):
        text = content.decode("utf-8", errors="replace")
    else:
        text = content

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    chunks: list[DocumentChunk] = []
    current_lines: list[str] = []
    current_chars = 0
    start_line = 1

    for idx, line in enumerate(lines, 1):
        current_lines.append(line)
        current_chars += len(line) + 1
        if current_chars >= 2500 or idx == len(lines):
            ref = f"Lines {start_line}-{idx}" if start_line != idx else f"Line {start_line}"
            chunks.append(DocumentChunk(len(chunks) + 1, ref, "\n".join(current_lines)))
            current_lines = []
            current_chars = 0
            start_line = idx + 1

    return chunks


def parse_pdf(stream: io.BytesIO | bytes) -> list[DocumentChunk]:
    import pypdf

    if isinstance(stream, bytes):
        stream = io.BytesIO(stream)

    reader = pypdf.PdfReader(stream)
    chunks: list[DocumentChunk] = []

    for page_idx, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        text = text.strip()
        if text:
            # If page text is very large, split it
            lines = text.splitlines()
            current: list[str] = []
            c_len = 0
            sub_part = 1
            for line in lines:
                current.append(line)
                c_len += len(line) + 1
                if c_len >= 3000:
                    chunks.append(
                        DocumentChunk(
                            len(chunks) + 1,
                            f"Page {page_idx} (part {sub_part})",
                            "\n".join(current),
                        )
                    )
                    current = []
                    c_len = 0
                    sub_part += 1
            if current:
                ref = f"Page {page_idx}" if sub_part == 1 else f"Page {page_idx} (part {sub_part})"
                chunks.append(DocumentChunk(len(chunks) + 1, ref, "\n".join(current)))

    return chunks


def parse_unstructured_csv(content: str | bytes) -> list[DocumentChunk]:
    if isinstance(content, bytes):
        text = content.decode("utf-8", errors="replace")
    else:
        text = content

    f = io.StringIO(text)
    reader = csv.reader(f)
    rows = list(reader)
    if not rows:
        return []

    chunks: list[DocumentChunk] = []
    current_rows: list[str] = []
    start_row = 1
    header = rows[0] if len(rows) > 1 else []

    data_rows = rows[1:] if header else rows
    for idx, r in enumerate(data_rows, 1):
        row_str = " | ".join(r).strip()
        if row_str:
            current_rows.append(row_str)
        if len(current_rows) >= 30 or idx == len(data_rows):
            ref = f"Rows {start_row}-{idx}"
            chunks.append(DocumentChunk(len(chunks) + 1, ref, "\n".join(current_rows)))
            current_rows = []
            start_row = idx + 1

    return chunks


def parse_file(filename: str, file_bytes: bytes) -> list[DocumentChunk]:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return parse_pdf(file_bytes)
    elif ext == ".csv":
        return parse_unstructured_csv(file_bytes)
    else:
        # Defaults to plain text
        return parse_txt(file_bytes)
