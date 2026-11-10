"""Build docs/evaluation/Evaluation.pdf from RESULTS.md, and Slide_brief.pdf from SLIDE_BRIEF.md.

    python3 scripts/build-evaluation-pdf.py

Needs pandoc and Google Chrome (used headless, with a throwaway profile). The text of each PDF is the Markdown file
itself; only the title block of the report is changed. Re-run after editing either file.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "evaluation" / "RESULTS.md"
OUT = ROOT / "docs" / "evaluation" / "Evaluation.pdf"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OLD_HEAD = "# Evaluation results - Studyspace (Group 09, Track 4)\n\nDraft for `Evaluation.pdf`. Run on"
NEW_HEAD = ("# Evaluation\n\n<p class=\"subtitle\">Studyspace (Student Work Assistant) &middot; Group 09 &middot; "
            "Track 4, Student Productivity Agent</p>\n\nRun on")

CSS = """
@page { size: A4; margin: 16mm 15mm 17mm 15mm;
  @bottom-center { content: "Studyspace  \\00B7  Group 09  \\00B7  Evaluation        " counter(page) " / " counter(pages);
                   font: 7.5pt -apple-system, "Helvetica Neue", Arial, sans-serif; color: #6b7780; } }
html { font: 9.4pt/1.42 -apple-system, "Helvetica Neue", Arial, "PingFang SC", sans-serif; color: #1c2326; }
body { margin: 0 !important; padding: 0 !important; max-width: none !important; hyphens: manual !important;
       font-size: inherit !important; }
h1 { font-size: 21pt; margin: 0 0 1pt; letter-spacing: -0.2pt; }
.subtitle { color: #55626a; font-size: 10.5pt; margin: 0 0 9pt; }
h2 { font-size: 13pt; margin: 15pt 0 5pt; padding-bottom: 2pt; border-bottom: 0.8pt solid #c9d1d8; break-after: avoid; }
h3 { font-size: 10.8pt; margin: 11pt 0 4pt; break-after: avoid; }
p { margin: 0 0 6pt; orphans: 3; widows: 3; }
table { border-collapse: collapse; width: calc(100% - 1pt); margin: 5pt 0.5pt 9pt; font-size: 8.5pt; line-height: 1.34; }
blockquote { margin: 4pt 0 8pt; padding: 5pt 10pt; border-left: 2.5pt solid #9fb3c2; background: #f5f7f9; }
blockquote p { margin: 0; }
th, td { border: 0.5pt solid #c9d1d8; padding: 2.6pt 5pt; vertical-align: top; text-align: left; }
th { background: #eef2f6; font-weight: 600; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
table { break-inside: avoid; }                 /* a short table is not split across pages */
table:has(tr:nth-child(14)) { break-inside: auto; }  /* a long one may be, with its header repeated */
p:has(+ table), h3 + p { break-after: avoid; } /* the line that introduces a table stays with it */
code { font: 8pt "SF Mono", Menlo, Consolas, monospace; background: #f1f4f6; padding: 0 1.8pt; border-radius: 2pt;
       overflow-wrap: anywhere; }
ol, ul { margin: 0 0 6pt; padding-left: 15pt; }
li { margin-bottom: 4.5pt; }
li > p { margin-bottom: 3pt; }
strong { font-weight: 600; }
"""


def render(text: str, out: Path, title: str, footer: str) -> int:
    with tempfile.TemporaryDirectory(prefix="evalpdf-") as tmp:
        t = Path(tmp)
        (t / "report.md").write_text(text, encoding="utf-8")
        (t / "head.html").write_text(f"<style>{CSS.replace('Evaluation        ', footer + '        ')}</style>", encoding="utf-8")
        subprocess.run(["pandoc", str(t / "report.md"), "-f", "gfm", "-t", "html5", "--standalone", "--columns=100000", "-M", "document-css=false",
                        "--metadata", f"pagetitle={title}", "--metadata", "lang=en",
                        "-H", str(t / "head.html"), "-o", str(t / "report.html")], check=True)
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run",
                            f"--user-data-dir={t / 'profile'}", f"--print-to-pdf={out}", (t / "report.html").as_uri()],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0 or not out.is_file():
            print("Chrome failed:", r.stderr[-800:])
            return 1
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")
    return 0


def main() -> int:
    if not shutil.which("pandoc"):
        print("pandoc not found")
        return 1
    if not Path(CHROME).is_file():
        print("Google Chrome not found at", CHROME)
        return 1
    text = SRC.read_text(encoding="utf-8")
    if OLD_HEAD not in text:
        print("RESULTS.md no longer starts with the expected title block; update OLD_HEAD in this script")
        return 1
    rc = render(text.replace(OLD_HEAD, NEW_HEAD, 1), OUT, "Evaluation - Studyspace (Group 09, Track 4)", "Evaluation")
    brief = SRC.with_name("SLIDE_BRIEF.md")
    if rc == 0 and brief.is_file():
        rc = render(brief.read_text(encoding="utf-8"), SRC.with_name("Slide_brief.pdf"),
                    "Evaluation - brief for the slides (Group 09)", "Slide brief")
    return rc


if __name__ == "__main__":
    sys.exit(main())
