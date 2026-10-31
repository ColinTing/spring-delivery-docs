#!/usr/bin/env python3
"""Convert delivery / design Markdown into Word (.docx) ready for review meetings.

What it adds over a bare `pandoc x.md -o x.docx`:
  - Mermaid diagrams rendered to images (Word cannot render Mermaid)
  - bordered tables, shaded header row repeated across pages, 9pt table text
  - <br> inside table cells kept as real line breaks
  - Chinese layout: 宋体 body, 黑体 headings, A4, table of contents, page numbers
  - 【待确认…】 highlighted red, 【假设…】 highlighted orange, so reviewers see open points
  - --template company.docx to use the company's own styles instead

Usage:
    python3 md2docx.py <file.md|dir> [more ...] [--out-dir DIR] [--template ref.docx]
                       [--no-toc] [--mmdc CMD] [--chrome PATH] [--no-npx]

Requires: pandoc, python-docx (pip3 install python-docx).
Mermaid rendering uses, in order: --mmdc, `mmdc` on PATH, `npx -y @mermaid-js/mermaid-cli`.
Without any of them the diagram source is kept as a code block, with a note.
Nothing is sent to online services.
"""
import argparse
import copy
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor
    from docx.text.run import Run
except ImportError:
    sys.exit("python-docx is required:  pip3 install python-docx   (or: pip3 install --user python-docx)")

BR = "BR"  # private-use marker for <br> in table cells
MERMAID_RE = re.compile(r"^```mermaid[ \t]*\n(.*?)^```[ \t]*$", re.S | re.M)
MARKS = [(re.compile(r"【待确认[^】]*】"), RGBColor(0xC0, 0x00, 0x00)),
         (re.compile(r"【假设[^】]*】"), RGBColor(0xC5, 0x5A, 0x11))]
BODY_EA, HEAD_EA, LATIN = "宋体", "黑体", "Times New Roman"
DIAGRAM_ALT = "mermaid-diagram"
DIAGRAM_SCALE = 0.5  # diagrams are rendered at 2x for sharpness


# --------------------------------------------------------------------------- mermaid

def mermaid_cmd(args):
    if args.mmdc:
        return args.mmdc.split()
    if shutil.which("mmdc"):
        return ["mmdc"]
    if not args.no_npx and shutil.which("npx"):
        return ["npx", "-y", "@mermaid-js/mermaid-cli@11.4.2"]
    return None


def render_mermaid(md, workdir, args):
    blocks = list(MERMAID_RE.finditer(md))
    if not blocks:
        return md, 0, 0
    cmd = mermaid_cmd(args)
    if cmd is None:
        print("  ! no Mermaid renderer (install: npm i -g @mermaid-js/mermaid-cli); diagrams kept as code")
    pconf = os.path.join(workdir, "puppeteer.json")
    pp = {"args": ["--no-sandbox"]}
    if args.chrome:
        pp["executablePath"] = args.chrome
    json.dump(pp, open(pconf, "w"))
    cfg = os.path.join(workdir, "mermaid.json")
    json.dump({"theme": "default", "themeVariables": {
        "fontFamily": "PingFang SC, Microsoft YaHei, WenQuanYi Zen Hei, sans-serif"}}, open(cfg, "w"))

    ok = 0
    out, last = [], 0
    for i, m in enumerate(blocks):
        out.append(md[last:m.start()])
        last = m.end()
        src = os.path.join(workdir, f"diagram{i}.mmd")
        png = os.path.join(workdir, f"diagram{i}.png")
        open(src, "w", encoding="utf-8").write(m.group(1))
        done = False
        if cmd:
            try:
                r = subprocess.run(cmd + ["-i", src, "-o", png, "-s", "2", "-b", "white",
                                          "-p", pconf, "-c", cfg],
                                   capture_output=True, text=True, timeout=180)
                done = r.returncode == 0 and os.path.exists(png)
                if not done:
                    print(f"  ! diagram {i + 1} failed: {(r.stderr or r.stdout).strip().splitlines()[-1:]}")
            except (subprocess.TimeoutExpired, OSError) as e:
                print(f"  ! diagram {i + 1} failed: {e}")
        if done:
            ok += 1
            out.append(f"![{DIAGRAM_ALT}]({png})\n")
        else:
            out.append("> 【图未渲染，以下为 Mermaid 源码，可粘贴到 https://mermaid.live 查看】\n\n"
                       + m.group(0) + "\n")
    out.append(md[last:])
    return "".join(out), len(blocks), ok


# --------------------------------------------------------------------------- reference doc

def set_fonts(style, east_asia, latin=LATIN, size=None, bold=None, color=None):
    style.font.name = latin
    if size:
        style.font.size = Pt(size)
    if bold is not None:
        style.font.bold = bold
    if color is not None:
        style.font.color.rgb = color
    rpr = style.element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    for k in ("w:ascii", "w:hAnsi", "w:cs"):
        fonts.set(qn(k), latin)
    fonts.set(qn("w:eastAsia"), east_asia)
    for k in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        fonts.attrib.pop(qn(k), None)


def build_reference(path):
    data = subprocess.run(["pandoc", "--print-default-data-file", "reference.docx"],
                          capture_output=True, check=True).stdout
    open(path, "wb").write(data)
    d = Document(path)
    by_name = {s.name: s for s in d.styles}  # d.styles[...] mangles pandoc's "Heading 1" names
    names = set(by_name)
    black = RGBColor(0, 0, 0)
    for n in ("Normal", "Body Text", "First Paragraph", "Compact"):
        if n in names:
            set_fonts(by_name[n], BODY_EA, size=10.5)
    sizes = {1: 18, 2: 15, 3: 13, 4: 12, 5: 11, 6: 10.5}
    for lvl, sz in sizes.items():
        n = f"Heading {lvl}"
        if n in names:
            set_fonts(by_name[n], HEAD_EA, size=sz, bold=True, color=black)
            by_name[n].font.italic = False
            by_name[n].paragraph_format.space_before = Pt(12 if lvl <= 2 else 8)
            by_name[n].paragraph_format.space_after = Pt(6)
    for n in ("Title",):
        if n in names:
            set_fonts(by_name[n], HEAD_EA, size=22, bold=True, color=black)
    if "TOC Heading" in names:
        set_fonts(by_name["TOC Heading"], HEAD_EA, size=15, bold=True, color=black)
    if "Source Code" in names:
        set_fonts(by_name["Source Code"], BODY_EA, latin="Consolas", size=9)
        ppr = by_name["Source Code"].element.get_or_add_pPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), "F5F5F5")
        ppr.append(shd)
    if "Verbatim Char" in names:
        set_fonts(by_name["Verbatim Char"], BODY_EA, latin="Consolas", size=9.5)
    if "Block Text" in names:
        set_fonts(by_name["Block Text"], BODY_EA, size=10.5, color=RGBColor(0x40, 0x40, 0x40))
    d.save(path)


# --------------------------------------------------------------------------- post-processing

def shade(cell, fill):
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcpr.append(shd)


def style_table(t):
    tblpr = t._tbl.tblPr
    for old in tblpr.findall(qn("w:tblBorders")):
        tblpr.remove(old)
    borders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b = OxmlElement(f"w:{side}")
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), "4")
        b.set(qn("w:space"), "0")
        b.set(qn("w:color"), "808080")
        borders.append(b)
    tblpr.append(borders)
    for old in tblpr.findall(qn("w:tblW")):
        tblpr.remove(old)
    w = OxmlElement("w:tblW")
    w.set(qn("w:w"), "5000")
    w.set(qn("w:type"), "pct")
    tblpr.append(w)
    for ri, row in enumerate(t.rows):
        if ri == 0:
            trpr = row._tr.get_or_add_trPr()
            h = OxmlElement("w:tblHeader")
            trpr.append(h)
        for cell in row.cells:
            if ri == 0:
                shade(cell, "D9E2F3")
            for p in cell.paragraphs:
                p.paragraph_format.space_before = Pt(1)
                p.paragraph_format.space_after = Pt(1)
                for r in p.runs:
                    r.font.size = Pt(9)
                    if ri == 0:
                        r.font.bold = True


def text_width(s):
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)


def set_column_widths(t, total_twips):
    """Size columns by content.

    Each column first gets a minimum that keeps short values (ids, 是/否, status words,
    paths) on one line; the remaining width goes to the columns with long text.
    """
    rows = t.rows
    ncols = len(t.columns)
    if ncols < 2:
        return
    per_char, pad = 100, 300  # twips per half-width char at 9pt, cell padding
    mins, wants = [], []
    for ci in range(ncols):
        lens, tokens = [], [0]
        for ri, row in enumerate(rows):
            if ci >= len(row.cells):
                continue
            text = row.cells[ci].text.replace(BR, "\n")
            lines = text.splitlines() or [""]
            lens.append(max(text_width(x) for x in lines))
            tokens += [len(tok) for tok in re.findall(r"[\x21-\x7e]+", text)]
        lens.sort()
        longest = lens[-1] if lens else 4
        typical = lens[int(len(lens) * 0.8)] if lens else 4
        need = max(min(longest, 10), min(max(tokens), 22))  # short values never wrap
        mins.append(need * per_char + pad)
        wants.append(max(min(typical, 80) * per_char + pad, mins[-1]))
    if sum(mins) >= total_twips:
        widths = [int(total_twips * m / sum(mins)) for m in mins]
    elif sum(wants) <= total_twips:
        extra = total_twips - sum(wants)
        widths = [int(w + extra * w / sum(wants)) for w in wants]
    else:
        spare = total_twips - sum(mins)
        grow = [w - m for w, m in zip(wants, mins)]
        widths = [int(m + spare * g / sum(grow)) if sum(grow) else m for m, g in zip(mins, grow)]
    grid = t._tbl.tblGrid
    for gc, w in zip(grid.findall(qn("w:gridCol")), widths):
        gc.set(qn("w:w"), str(w))
    tblpr = t._tbl.tblPr
    for old in tblpr.findall(qn("w:tblLayout")):
        tblpr.remove(old)
    lay = OxmlElement("w:tblLayout")
    lay.set(qn("w:type"), "fixed")
    tblpr.append(lay)
    for row in rows:
        for ci, cell in enumerate(row.cells[:ncols]):
            tcpr = cell._tc.get_or_add_tcPr()
            for old in tcpr.findall(qn("w:tcW")):
                tcpr.remove(old)
            tcw = OxmlElement("w:tcW")
            tcw.set(qn("w:w"), str(widths[ci]))
            tcw.set(qn("w:type"), "dxa")
            tcpr.insert(0, tcw)


def iter_paragraphs(doc):
    yield from doc.paragraphs
    for t in doc.tables:
        yield from iter_table_paragraphs(t)


def iter_table_paragraphs(t):
    for row in t.rows:
        for cell in row.cells:
            yield from cell.paragraphs
            for inner in cell.tables:
                yield from iter_table_paragraphs(inner)


def split_run(run, start, end):
    """Split run so [start:end) of its text is its own run; return that run."""
    text = run.text
    parts = [text[:start], text[start:end], text[end:]]
    run.text = parts[0]
    mid = copy.deepcopy(run._r)
    run._r.addnext(mid)
    tail = copy.deepcopy(run._r)
    mid.addnext(tail)
    mid_run, tail_run = Run(mid, run._parent), Run(tail, run._parent)
    mid_run.text, tail_run.text = parts[1], parts[2]
    if not parts[0]:
        run._r.getparent().remove(run._r)
    if not parts[2]:
        tail.getparent().remove(tail)
    return mid_run


def fix_runs(p):
    # <br> markers → line breaks
    for r in list(p.runs):
        if BR in r.text:
            pieces = r.text.split(BR)
            r.text = pieces[0]
            anchor = r
            for piece in pieces[1:]:
                new = copy.deepcopy(anchor._r)
                anchor._r.addnext(new)
                nr = Run(new, anchor._parent)
                nr.text = piece
                br = OxmlElement("w:br")
                new.insert(1 if new.find(qn("w:rPr")) is not None else 0, br)
                anchor = nr
    # highlight review markers
    for rx, color in MARKS:
        changed = True
        while changed:
            changed = False
            for r in list(p.runs):
                if r.font.color is not None and r.font.color.rgb == color:
                    continue
                m = rx.search(r.text)
                if m:
                    mr = split_run(r, m.start(), m.end())
                    mr.font.color.rgb = color
                    mr.font.bold = True
                    changed = True
                    break


def add_field(run, instr):
    for tag, text in (("begin", None), ("instr", instr), ("separate", None), ("text", "1"), ("end", None)):
        if tag == "instr":
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        elif tag == "text":
            el = OxmlElement("w:t")
            el.text = text
        else:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), tag)
        run._r.append(el)


def page_setup(doc, title, own_template):
    for s in doc.sections:
        if not own_template or s.page_width is None:
            s.page_width, s.page_height = Cm(21), Cm(29.7)
            s.left_margin = s.right_margin = Cm(2.2)
            s.top_margin = s.bottom_margin = Cm(2.4)
        fp = s.footer.paragraphs[0] if s.footer.paragraphs else s.footer.add_paragraph()
        if not fp.text.strip():
            fp.alignment = 1
            fp.add_run("第 ")
            add_field(fp.add_run(), "PAGE")
            fp.add_run(" 页 / 共 ")
            add_field(fp.add_run(), "NUMPAGES")
            fp.add_run(" 页")
            for r in fp.runs:
                r.font.size = Pt(9)
        hp = s.header.paragraphs[0] if s.header.paragraphs else s.header.add_paragraph()
        if title and not hp.text.strip():
            hp.alignment = 2
            r = hp.add_run(title)
            r.font.size = Pt(9)
            r.font.color.rgb = RGBColor(0x80, 0x80, 0x80)


def fit_images(doc):
    sec = doc.sections[0]
    maxw = sec.page_width - sec.left_margin - sec.right_margin
    maxh = int((sec.page_height - sec.top_margin - sec.bottom_margin) * 0.8)
    for shp in doc.inline_shapes:
        w, h = shp.width, shp.height
        if shp._inline.docPr.get("descr") == DIAGRAM_ALT:
            # size from real pixels (rendered at 2x) instead of pandoc's DPI guess
            rid = shp._inline.graphic.graphicData.pic.blipFill.blip.embed
            img = doc.part.related_parts[rid].image
            target = int(img.px_width * DIAGRAM_SCALE * 9525)
            w, h = target, int(h * target / w) if w else h
            shp.width, shp.height = w, h
        scale = min(1.0, maxw / w if w else 1, maxh / h if h else 1)
        if scale < 1:
            shp.width, shp.height = int(w * scale), int(h * scale)


def enable_field_update(doc):
    settings = doc.settings.element
    if settings.find(qn("w:updateFields")) is None:
        u = OxmlElement("w:updateFields")
        u.set(qn("w:val"), "true")
        settings.append(u)


# --------------------------------------------------------------------------- main

def convert(md_path, out_path, ref, args, own_template):
    md = open(md_path, encoding="utf-8").read()
    title_m = re.search(r"^#\s+(.+)$", md, re.M)
    title = title_m.group(1).strip() if title_m else os.path.splitext(os.path.basename(md_path))[0]
    with tempfile.TemporaryDirectory() as wd:
        md, n_diag, n_ok = render_mermaid(md, wd, args)
        md = re.sub(r"<br\s*/?>", BR, md)
        src = os.path.join(wd, "in.md")
        open(src, "w", encoding="utf-8").write(md)
        cmd = ["pandoc", src, "-f", "gfm", "-o", out_path, "--reference-doc", ref,
               "--resource-path", os.pathsep.join([wd, os.path.dirname(os.path.abspath(md_path))])]
        if not args.no_toc:
            cmd += ["--toc", "--toc-depth=3", "-M", "toc-title=目录"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip())
    doc = Document(out_path)
    for t in doc.tables:
        style_table(t)
    for p in iter_paragraphs(doc):
        fix_runs(p)
    page_setup(doc, title, own_template)
    sec = doc.sections[0]
    usable = int((sec.page_width - sec.left_margin - sec.right_margin) / 635)  # EMU → twips
    for t in doc.tables:
        set_column_widths(t, usable)
    fit_images(doc)
    if not args.no_toc:
        enable_field_update(doc)
    doc.save(out_path)
    return n_diag, n_ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="Markdown files or directories")
    ap.add_argument("--out-dir", help="default: next to each .md")
    ap.add_argument("--template", help="company .docx whose styles to use (pandoc reference doc)")
    ap.add_argument("--no-toc", action="store_true")
    ap.add_argument("--mmdc", help="Mermaid CLI command, e.g. 'mmdc' or '/path/to/mmdc'")
    ap.add_argument("--chrome", help="Chrome/Chromium executable for the Mermaid CLI")
    ap.add_argument("--no-npx", action="store_true", help="do not fall back to npx to fetch mermaid-cli")
    args = ap.parse_args()
    if not shutil.which("pandoc"):
        sys.exit("pandoc is required:  brew install pandoc   (Windows: winget install pandoc)")

    files = []
    for i in args.inputs:
        if os.path.isdir(i):
            files += sorted(glob.glob(os.path.join(i, "**", "*.md"), recursive=True))
        else:
            files.append(i)
    if not files:
        sys.exit("no .md files found")

    with tempfile.TemporaryDirectory() as tmp:
        ref = args.template
        if not ref:
            ref = os.path.join(tmp, "reference.docx")
            build_reference(ref)
        for f in files:
            out_dir = args.out_dir or os.path.dirname(os.path.abspath(f))
            os.makedirs(out_dir, exist_ok=True)
            out = os.path.join(out_dir, os.path.splitext(os.path.basename(f))[0] + ".docx")
            try:
                n, ok = convert(f, out, ref, args, bool(args.template))
            except Exception as e:  # keep going with the other files
                print(f"FAIL {f}: {e}")
                continue
            diag = f", diagrams {ok}/{n}" if n else ""
            print(f"wrote {out}{diag}")


if __name__ == "__main__":
    main()
