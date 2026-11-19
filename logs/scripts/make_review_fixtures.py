"""Create a small set of files for reviewing every Mitra app by hand.

    python logs/scripts/make_review_fixtures.py <output folder>

Writes: a two-page PDF with real text, a Markdown file that uses every construct the reader
claims to render, a Word file, a spreadsheet, a CSV, an HTML page and a meeting transcript.
Standard library only; nothing here is personal data.
"""
import sys
import zipfile
from pathlib import Path

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)


def pdf(path: Path, pages: list[list[str]]):
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        text = "BT /F1 14 Tf 72 740 Td 18 TL " + " ".join(f"({l.replace('(', '[').replace(')', ']')}) Tj T*" for l in lines) + " ET"
        objs.append(f"<< /Length {len(text)} >>\nstream\n{text}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {len(objs)} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    data, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(data))
        data += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(data)
    data += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    data += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(data)


pdf(out / "Quarterly review.pdf", [
    ["Quarterly review", "", "Revenue grew 12 percent against a plan of 9 percent.", "Churn held at 2.1 percent for the third quarter running.",
     "The export feature shipped in week 6 and is used by 340 accounts."],
    ["Risks", "", "The staging database is at 90 percent disk.", "Two enterprise renewals are due in November.", "Hiring for the data team is one month behind."]])

(out / "Everything Markdown.md").write_text("""---
title: Everything Markdown
tags: [review, sample]
---

# Everything Markdown

A paragraph with **bold**, *italic*, ~~struck~~, `inline code`, a [link](https://example.com) and a bare URL https://example.org/path.

## Lists

- First item
- Second item
  - Nested item with **bold**
  - Another nested item
- Third item

1. Step one
2. Step two
3. Step three

- [x] Done task
- [ ] Open task

## Table

| Model | RAM | Fits |
|---|---|---|
| Qwen3 0.6B | 748 MB | Yes |
| Whisper tiny | 150 MB | Yes |

## Code

```python
def hello(name):
    return f"Hello, {name}"
```

## Quote

> Decision then: release stays on the twentieth.
> With the twenty-fourth as fallback.

---

### A deeper heading

Line one with two trailing spaces
Line two after a hard break.

#### Level four heading

Text with <b>raw html</b> that should be shown as text, not run. <script>alert(1)</script>

[unsafe link](javascript:alert(1))
""", "utf-8")

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
with zipfile.ZipFile(out / "Project plan.docx", "w") as z:
    z.writestr("word/document.xml", f'<w:document {W}><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Project plan</w:t></w:r></w:p>'
               '<w:p><w:r><w:t>Ship the export fix before the release.</w:t></w:r></w:p>'
               '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Owner</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Due</w:t></w:r></w:p></w:tc></w:tr>'
               '<w:tr><w:tc><w:p><w:r><w:t>Sam</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Thursday</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')

(out / "Budget.csv").write_text("item,cost,owner\nLaptop,1200,Dana\nLicences,300,Sam\n", "utf-8")
(out / "Page.html").write_text("<html><head><title>T</title><script>x()</script></head><body><h1>Release notes</h1><p>Export is <b>faster</b>.</p><ul><li>CSV streaming</li><li>PDF export</li></ul></body></html>", "utf-8")
(out / "Standup transcript.txt").write_text("""Priya: Morning everyone. Quick standup. Let's start with the invoice export.
Sam: The export job is done for PDF. CSV still fails on invoices with more than two hundred line items, it times out after thirty seconds.
Priya: Okay. Sam, please fix the CSV timeout by Thursday.
Dana: The new onboarding screens are in review. Two comments from design about the colour contrast on the second screen. I will address them today.
Dana: If the CSV fix lands by Thursday we keep the twentieth. If not we slip to the twenty-fourth.
Priya: Decision then: release stays on the twentieth, with the twenty-fourth as fallback.
Sam: The staging database is at ninety percent disk. Someone needs to clear old snapshots.
Dana: I will clear snapshots older than thirty days this afternoon.
Priya: I will send the release note draft to marketing by Wednesday.
""", "utf-8")
print("wrote", ", ".join(sorted(p.name for p in out.iterdir())), "to", out)
