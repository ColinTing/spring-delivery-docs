#!/usr/bin/env python3
"""Convert a requirement document to Markdown so it can be read in parts.

Prints where the Markdown went plus a short outline (headings with line numbers,
tables, images) instead of the content, so a long document does not flood the
session. Read the .md afterwards, using the line numbers to jump to sections, and
look at the extracted images: prototypes and flowcharts carry half the requirements.

Usage:
    python3 docx2md.py <file.docx|.odt|.rtf|.html|.epub|.md> [--out-dir DIR]
                       [--track-changes accept|all|reject]

--track-changes all  keeps insertions, deletions and comments visible, for a document
                     the business side sent back with review marks.
Requires pandoc: on PATH, or bundled via `pip install pypandoc_binary`.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

READERS = {".docx": "docx", ".odt": "odt", ".rtf": "rtf", ".html": "html", ".htm": "html",
           ".epub": "epub"}
ALREADY_TEXT = {".md", ".markdown", ".txt"}
HINTS = {
    ".doc": "old Word 97-2003 format: ask the user to open it in Word and save as .docx",
    ".wps": "WPS format: ask the user to save it as .docx",
    ".pdf": "PDF: read it directly with the Read tool",
    ".xls": "spreadsheet: read it with openpyxl/pandas, or ask for .xlsx/.csv",
    ".xlsx": "spreadsheet: read it with openpyxl/pandas, or ask for .csv",
    ".ppt": "slides: ask the user to save as PDF",
    ".pptx": "slides: ask the user to save as PDF",
}
UNVIEWABLE = (".emf", ".wmf")  # Office/Visio drawings: no image viewer can show them


def utf8_output():
    # Claude Code reads piped output as UTF-8; on Chinese Windows Python would emit GBK
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def find_pandoc():
    """pandoc on PATH, else the binary bundled with `pip install pypandoc_binary`."""
    found = shutil.which("pandoc")
    if found:
        return found
    try:
        import pypandoc
        return pypandoc.get_pandoc_path()
    except (ImportError, OSError):
        return None


def slash(path):
    # forward slashes work in Git Bash, PowerShell and Python strings alike
    return os.path.abspath(path).replace(os.sep, "/")


def outline(md_path):
    lines = open(md_path, encoding="utf-8", errors="replace").read().splitlines()
    heads, tables, images, in_code = [], 0, [], False
    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith(("```", "~~~")):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip()))
        if re.match(r"^\s*\|?\s*:?-{3,}", line) or "<table" in line:
            tables += 1
        images += re.findall(r"!\[[^\]]*\]\(([^)\s]+)", line)
        images += re.findall(r"<img[^>]+src=\"([^\"]+)\"", line)
    return lines, heads, tables, images


def main():
    utf8_output()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--out-dir", help="default: a folder in the system temp dir")
    ap.add_argument("--track-changes", choices=("accept", "all", "reject"), default="accept")
    args = ap.parse_args()

    src = args.input
    if not os.path.isfile(src):
        sys.exit(f"not found: {src}")
    ext = os.path.splitext(src)[1].lower()
    stem = os.path.splitext(os.path.basename(src))[0]

    if ext in ALREADY_TEXT:
        md_path = src
    elif ext in READERS:
        pandoc = find_pandoc()
        if not pandoc:
            sys.exit("pandoc not found. Install one of:\n"
                     f'  "{sys.executable}" -m pip install pypandoc_binary   (any OS, no admin rights; bundles pandoc)\n'
                     "  brew install pandoc                                  (macOS)\n"
                     "  https://github.com/jgm/pandoc/releases               (Windows .msi installer)\n"
                     "Or ask the user to save the document as PDF and read that instead.")
        out_dir = args.out_dir or os.path.join(tempfile.gettempdir(),
                                               "docx2md-" + re.sub(r"[^\w.-]", "_", stem))
        os.makedirs(out_dir, exist_ok=True)
        md_path = os.path.join(out_dir, stem + ".md")
        # review marks need pandoc's own Markdown: GFM cannot tell an insertion from a deletion
        fmt = "markdown" if args.track_changes == "all" else "gfm"
        cmd = [pandoc, src, "-f", READERS[ext], "-t", fmt, "--wrap=none",
               f"--extract-media={out_dir}", f"--track-changes={args.track_changes}", "-o", md_path]
        r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            sys.exit(f"pandoc failed: {r.stderr.strip()[:500]}")
    else:
        sys.exit(f"cannot convert {ext or 'this file'}: " + HINTS.get(ext, "save it as .docx or PDF"))

    try:
        report(md_path, args)
    except BrokenPipeError:  # output piped into `head`; the Markdown is already written
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())


def report(md_path, args):
    lines, heads, tables, images = outline(md_path)
    chars = sum(len(x) for x in lines)
    print(f"markdown: {slash(md_path)}  ({len(lines)} lines, {chars} chars, {len(heads)} headings, "
          f"{tables} tables, {len(images)} images)")
    if args.track_changes == "all":
        marks = sum(len(re.findall(r"\{\.(insertion|deletion|comment-start)", x)) for x in lines)
        print(f"review marks: {marks} (spans like [text]{{.insertion author=...}}, "
              "{.deletion ...} and {.comment-start ...})")
    if heads:
        print("outline (line: heading):")
        for i, level, text in heads[:60]:
            print(f"  L{i}: {'  ' * (level - 1)}{text[:80]}")
        if len(heads) > 60:
            print(f"  … {len(heads) - 60} more headings")
    if images:
        base = os.path.dirname(os.path.abspath(md_path))
        files = [p if os.path.isabs(p) else os.path.join(base, p) for p in images]
        bad = [f for f in files if f.lower().endswith(UNVIEWABLE)]
        print(f"images ({len(files)}):")
        for f in files[:20]:
            print(f"  {slash(f)}" + ("   [EMF/WMF: cannot be viewed]" if f.lower().endswith(UNVIEWABLE) else ""))
        if len(files) > 20:
            print(f"  … {len(files) - 20} more")
        if bad:
            print(f"note: {len(bad)} images are EMF/WMF drawings (often Visio flowcharts or prototypes). "
                  "Ask the user for screenshots or PNG exports if they matter.")
    if chars > 60000:
        print("note: long document, read it in parts (Read with offset/limit) using the outline")


if __name__ == "__main__":
    main()
