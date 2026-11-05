#!/usr/bin/env python3
# Pure ASCII on purpose (Chinese text is written as \u escapes): the file then runs whatever
# encoding it is saved in after being copied or pasted onto another machine.
"""Markdown <-> Word for design and delivery docs. Needs only python-docx.

  python md2docx.py <doc.md> [--out-dir DIR] [--template \u516c\u53f8\u6a21\u677f.docx]
      Word with Chinese layout: \u5b8b\u4f53/\u9ed1\u4f53, A4, table of contents, page numbers, bordered
      tables with repeating header rows, \u3010\u5f85\u786e\u8ba4\u3011 red, \u3010\u5047\u8bbe\u3011 orange. Mermaid blocks become
      images when Node.js is available (mmdc, or npx using the installed Chrome/Edge),
      otherwise their source is kept. Design docs also get a traceability check.
  python md2docx.py --read <doc.docx> [--out-dir DIR]
      Markdown for reading or editing, with an outline printed instead of the content.
      Tracked changes become [+added+] / [-deleted-], comments [\u6279\u6ce8 author\uff1atext].
      Diagrams made by this script come back as Mermaid (the source is in the alt text).

Install: python -m pip install python-docx. Nothing is sent to online services.
Shared by both skills: edit skills/spring-delivery-docs/scripts/md2docx.py, then run
`python tools/sync_shared.py` to update the copy in spring-detailed-design.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:
    from docx import Document
    from docx.enum.style import WD_STYLE_TYPE
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.image.image import Image as DocxImage
    from docx.oxml import OxmlElement, parse_xml
    from docx.oxml.ns import qn
    from docx.shared import Cm, Emu, Pt, RGBColor
except ImportError:
    sys.exit(f'python-docx is required:  "{sys.executable}" -m pip install python-docx'
             "   (add --user on a permissions error)")

LATIN, BODY_EA, HEAD_EA, MONO = "Times New Roman", "\u5b8b\u4f53", "\u9ed1\u4f53", "Consolas"
MARKS = [(re.compile(r"\u3010\u5f85\u786e\u8ba4[^\u3011]*\u3011"), RGBColor(0xC0, 0x00, 0x00)),
         (re.compile(r"\u3010\u5047\u8bbe[^\u3011]*\u3011"), RGBColor(0xC5, 0x5A, 0x11))]
INLINE = re.compile(r"(`[^`]+`|\*\*.+?\*\*|<br\s*/?>|!?\[[^\]]*\]\([^)]*\)|\u3010\u5f85\u786e\u8ba4[^\u3011]*\u3011|\u3010\u5047\u8bbe[^\u3011]*\u3011)")
MERMAID_START = re.compile(r"^\s*(flowchart|graph|sequenceDiagram|stateDiagram|erDiagram|classDiagram|gantt|"
                           r"journey|pie|mindmap|timeline)\b")
MARK_HEX = {str(c).upper() for _, c in MARKS}
MERMAID_CLI = "@mermaid-js/mermaid-cli@11.4.2"
ALT = "mermaid:"  # alt-text prefix that carries a diagram's source
NOT_RENDERED = "\u3010\u56fe\u672a\u6e32\u67d3\uff1a\u9700\u8981 Node.js\uff0c\u4ee5\u4e0b\u4e3a Mermaid \u6e90\u7801\u3011"
ID = re.compile(r"(?<![\w-])(R|AC|Q|D|T)-\d{1,3}(?!\w)")
WNS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = {}  # styles of the document being written


def utf8_output():
    # Claude Code reads piped output as UTF-8; on Chinese Windows Python would emit GBK
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def slash(path):
    return os.path.abspath(path).replace(os.sep, "/")  # works in Git Bash, PowerShell and Python


# --------------------------------------------------------------------------- styles

def set_font(obj, east=BODY_EA, latin=LATIN, size=None, bold=None, color=None):
    """Font for a style or run, East Asian font included (python-docx only sets Latin)."""
    obj.font.name = latin
    if size:
        obj.font.size = Pt(size)
    if bold is not None:
        obj.font.bold = bold
    if color is not None:
        obj.font.color.rgb = color
    rpr = obj.element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.insert(0, rf)
    for k in ("w:ascii", "w:hAnsi", "w:cs"):
        rf.set(qn(k), latin)
    rf.set(qn("w:eastAsia"), east)
    for k in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        rf.attrib.pop(qn(k), None)


def get_style(doc, name, kind=None):
    for s in doc.styles:
        if s.name and s.name.lower() == name.lower():
            return s
    return doc.styles.add_style(name, kind) if kind is not None else None


def shading(ppr_or_tcpr, fill):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    ppr_or_tcpr.append(shd)


def setup_styles(doc, own_template):
    S["code"] = get_style(doc, "Code", WD_STYLE_TYPE.PARAGRAPH)
    set_font(S["code"], BODY_EA, MONO, 9)
    pf = S["code"].paragraph_format
    pf.space_before, pf.space_after, pf.line_spacing = Pt(2), Pt(6), 1.0
    ppr = S["code"].element.get_or_add_pPr()
    if ppr.find(qn("w:shd")) is None:
        shading(ppr, "F2F2F2")
    S["code_char"] = get_style(doc, "Code Char", WD_STYLE_TYPE.CHARACTER)
    set_font(S["code_char"], BODY_EA, MONO, 9.5)
    S["toc"] = get_style(doc, "TOC Heading", WD_STYLE_TYPE.PARAGRAPH)
    S["quote"] = get_style(doc, "Quote") or get_style(doc, "Normal")
    S["h"] = {n: get_style(doc, f"Heading {n}") for n in range(1, 7)}
    S["bullet"] = [get_style(doc, n) for n in ("List Bullet", "List Bullet 2", "List Bullet 3")]
    if own_template:
        return  # keep the company's fonts and headings
    set_font(get_style(doc, "Normal"), BODY_EA, LATIN, 10.5)
    for n, size in zip(range(1, 7), (18, 15, 13, 12, 11, 10.5)):
        h = S["h"][n]
        if h is not None:
            set_font(h, HEAD_EA, LATIN, size, bold=True, color=RGBColor(0, 0, 0))
            h.font.italic = False
            h.paragraph_format.space_before = Pt(12 if n <= 2 else 8)
            h.paragraph_format.space_after = Pt(6)
    set_font(S["toc"], HEAD_EA, LATIN, 15, bold=True, color=RGBColor(0, 0, 0))
    set_font(S["quote"], BODY_EA, LATIN, 10.5, color=RGBColor(0x40, 0x40, 0x40))
    S["quote"].font.italic = False


# --------------------------------------------------------------------------- markdown parsing

def cells(line):
    """Split a table row on | outside `code`, keeping escaped \\|."""
    s = line.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") and not s.endswith("\\|") else s
    out, buf, tick, i = [], "", False, 0
    while i < len(s):
        if s[i] == "\\" and s[i + 1:i + 2] == "|":
            buf, i = buf + "\\|", i + 2
            continue
        if s[i] == "`":
            tick = not tick
        if s[i] == "|" and not tick:
            out.append(buf.strip())
            buf = ""
        else:
            buf += s[i]
        i += 1
    return out + [buf.strip()]


def join_lines(lines):
    out = ""
    for ln in lines:
        cjk = out and (ord(out[-1]) > 0x2E80 or ord(ln[0]) > 0x2E80)
        out += ln if (not out or cjk) else " " + ln
    return out


def blocks(md):
    lines, out, para, i = md.splitlines(), [], [], 0

    def flush():
        if para:
            out.append(("p", join_lines(para)))
            para.clear()

    while i < len(lines):
        line, s = lines[i], lines[i].strip()
        fence = re.match(r"^\s*(```+|~~~+)\s*([\w-]*)", line)
        if fence:
            flush()
            buf, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith(fence.group(1)):
                buf.append(lines[i])
                i += 1
            out.append(("code", fence.group(2).lower(), "\n".join(buf)))
        elif not s:
            flush()
        elif s.startswith("<!--"):
            flush()
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
        elif re.match(r"^#{1,6}\s", s):
            flush()
            m = re.match(r"^(#{1,6})\s+(.*?)\s*#*$", s)
            out.append(("h", len(m.group(1)), m.group(2)))
        elif re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", s):
            flush()
            out.append(("hr",))
        elif s.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            flush()
            rows, i = [cells(line)], i + 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(cells(lines[i]))
                i += 1
            out.append(("table", rows))
            continue
        elif s.startswith(">"):
            flush()
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            out.append(("quote", join_lines([b for b in buf if b])))
            continue
        elif re.match(r"^(\s*)([-*+]|\d+[.)])\s+", line):
            flush()
            m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)", line)
            out.append(("li", len(m.group(1).expandtabs(4)) // 2, m.group(2), m.group(3)))
        elif re.fullmatch(r"!\[[^\]]*\]\([^)\s]+\)", s):
            flush()
            out.append(("img", re.fullmatch(r"!\[([^\]]*)\]\(([^)\s]+)\)", s).group(2)))
        else:
            para.append(s)
        i += 1
    flush()
    return out


def plain(text):
    """Markdown cell text as it will appear, for measuring column widths."""
    text = re.sub(r"<br\s*/?>", "\n", text)
    return re.sub(r"\*\*|`|\\(?=\|)", "", text)


# --------------------------------------------------------------------------- writing

def put(p, text, bold=False, size=None, code=False, color=None):
    r = p.add_run(re.sub(r"\\([\\`*_{}\[\]()#+\-.!|])", r"\1", text))
    if code:
        r.style = S["code_char"]
    if bold or color is not None:
        r.bold = True
    if color is not None:
        r.font.color.rgb = color
    if size:
        r.font.size = Pt(size)
    return r


def add_inline(p, text, bold=False, size=None):
    pos = 0
    for m in INLINE.finditer(text):
        if m.start() > pos:
            put(p, text[pos:m.start()], bold, size)
        tok = m.group(0)
        if tok.startswith("`"):
            put(p, tok[1:-1], bold, size, code=True)
        elif tok.startswith("**"):
            add_inline(p, tok[2:-2], True, size)
        elif tok.startswith("<br"):
            p.add_run().add_break()
        elif tok.startswith(("[", "!")):
            put(p, re.match(r"!?\[([^\]]*)\]", tok).group(1), bold, size)
        else:  # a review marker: colored, code spans inside still in code font
            color = next(c for rx, c in MARKS if rx.fullmatch(tok))
            for part in re.split(r"(`[^`]+`)", tok):
                if part:
                    put(p, part.strip("`") if part.startswith("`") else part, bold, size,
                        code=part.startswith("`"), color=color)
        pos = m.end()
    if pos < len(text):
        put(p, text[pos:], bold, size)


def add_field(run, instr, placeholder="1"):
    for kind, text in (("begin", None), ("instr", instr), ("separate", None), ("t", placeholder), ("end", None)):
        if kind == "instr":
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        elif kind == "t":
            el = OxmlElement("w:t")
            el.text = text
        else:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        run._r.append(el)


def text_width(s):
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in s)


def column_widths(rows, total):
    """Short values (ids, yes/no, statuses, paths) stay on one line; long text gets the rest."""
    ncols = max(len(r) for r in rows)
    mins, wants = [], []
    for ci in range(ncols):
        lens, tokens = [], [0]
        for row in rows:
            text = plain(row[ci]) if ci < len(row) else ""
            lens.append(max(text_width(x) for x in (text.splitlines() or [""])))
            tokens += [len(t) for t in re.findall(r"[\x21-\x7e]+", text)]
        lens.sort()
        need = max(min(lens[-1], 10), min(max(tokens), 22))
        mins.append(need * 100 + 300)  # twips: ~100 per half-width char at 9pt, plus padding
        wants.append(max(min(lens[int(len(lens) * 0.8)], 80) * 100 + 300, mins[-1]))
    if sum(mins) >= total:
        return [int(total * m / sum(mins)) for m in mins]
    if sum(wants) <= total:
        return [int(w + (total - sum(wants)) * w / sum(wants)) for w in wants]
    grow = [w - m for w, m in zip(wants, mins)]
    return [int(m + (total - sum(mins)) * g / sum(grow)) for m, g in zip(mins, grow)]


def add_table(doc, rows, total_twips):
    ncols = max(len(r) for r in rows)
    t = doc.add_table(rows=len(rows), cols=ncols)
    tblpr = t._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b = OxmlElement(f"w:{side}")
        for k, v in (("w:val", "single"), ("w:sz", "4"), ("w:space", "0"), ("w:color", "808080")):
            b.set(qn(k), v)
        borders.append(b)
    tblpr.append(borders)
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblpr.append(layout)
    widths = column_widths(rows, total_twips)
    for gc, w in zip(t._tbl.tblGrid.findall(qn("w:gridCol")), widths):
        gc.set(qn("w:w"), str(w))
    t.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))  # repeat on every page
    for ri, (row, row_obj) in enumerate(zip(rows, t.rows)):
        for ci, cell in enumerate(row_obj.cells):
            cell.width = Emu(widths[ci] * 635)
            if ri == 0:
                shading(cell._tc.get_or_add_tcPr(), "D9E2F3")
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = p.paragraph_format.space_after = Pt(1)
            add_inline(p, row[ci] if ci < len(row) else "", bold=ri == 0, size=9)


def add_picture(doc, path, alt, max_w, max_h, scale=1.0):
    img = DocxImage.from_file(path)
    w, h = img.px_width * scale * 9525, img.px_height * scale * 9525  # EMU at 96 dpi
    k = min(1.0, max_w / w, max_h / h)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    shape = p.add_run().add_picture(path, width=Emu(int(w * k)), height=Emu(int(h * k)))
    if alt:
        shape._inline.docPr.set("descr", alt)


class Mermaid:
    """Renders with mermaid-cli: an installed mmdc, else npx (installs into the user's npm
    cache, no admin rights), driving an installed Chrome/Edge so no browser is downloaded."""

    def __init__(self, args, workdir):
        self.dir, self.n, self.ok, self.noted, self.chrome = workdir, 0, 0, False, args.chrome
        self.cmd = self.find_cmd(args)
        local = None if args.chrome else self.local_browser()
        browsers = [args.chrome] if args.chrome else ([local, None] if local else [None])
        self.env = dict(os.environ, PUPPETEER_SKIP_DOWNLOAD="1") if browsers[0] else dict(os.environ)
        self.confs = []
        for k, b in enumerate(browsers):
            conf = os.path.join(workdir, f"puppeteer{k}.json")
            json.dump({"args": ["--no-sandbox"], **({"executablePath": b} if b else {})}, open(conf, "w"))
            self.confs.append(conf)
        self.cfg = os.path.join(workdir, "mermaid.json")
        json.dump({"theme": "default", "themeVariables": {
            "fontFamily": "PingFang SC, Microsoft YaHei, WenQuanYi Zen Hei, sans-serif"}}, open(self.cfg, "w"))

    @staticmethod
    def which(name):
        path = shutil.which(name)  # npm installs .cmd files on Windows; Python 3.12.0 may skip the .cmd
        if os.name == "nt" and path and not os.path.splitext(path)[1]:
            path = shutil.which(name + ".cmd") or path
        return path

    def find_cmd(self, args):
        if args.mmdc:
            return [self.which(args.mmdc) or args.mmdc]
        if self.which("mmdc"):
            return [self.which("mmdc")]
        if self.which("npx"):
            return [self.which("npx"), "-y", MERMAID_CLI]
        return None

    @staticmethod
    def local_browser():
        if os.name == "nt":
            cands = [os.path.join(os.environ.get(env, ""), *rest)
                     for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA") if os.environ.get(env)
                     for rest in (("Google", "Chrome", "Application", "chrome.exe"),
                                  ("Microsoft", "Edge", "Application", "msedge.exe"))]
        elif sys.platform == "darwin":
            cands = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                     "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
        else:
            cands = [shutil.which(x) for x in ("google-chrome", "google-chrome-stable", "chromium",
                                               "chromium-browser", "microsoft-edge")]
        return next((c for c in cands if c and os.path.exists(c)), None)

    def render(self, src):
        self.n += 1
        if not self.noted:
            self.noted = True
            if self.cmd is None:
                print("note: no Mermaid renderer (needs Node.js), diagrams are kept as source")
            elif MERMAID_CLI in self.cmd:
                print(f"note: rendering diagrams via npx {MERMAID_CLI}; the first run downloads ~300 MB")
        if self.cmd is None:
            return None
        mmd = os.path.join(self.dir, f"d{self.n}.mmd")
        png = mmd[:-4] + ".png"
        open(mmd, "w", encoding="utf-8").write(src)
        err = ""
        for conf in list(self.confs):
            try:
                r = subprocess.run(self.cmd + ["-i", mmd, "-o", png, "-s", "2", "-b", "white", "-p", conf,
                                               "-c", self.cfg], capture_output=True, encoding="utf-8",
                                   errors="replace", timeout=300, env=self.env)
                if r.returncode == 0 and os.path.exists(png):
                    self.confs[:] = [conf]  # stick with the browser that works
                    self.ok += 1
                    return png
                lines = (r.stderr or r.stdout).strip().splitlines() or ["(no output)"]
                err = next((x.strip() for x in lines if "Error" in x), lines[-1].strip())
            except (subprocess.TimeoutExpired, OSError) as e:
                err = str(e)
        print(f"  ! diagram {self.n} not rendered: {err[:300]}")
        if "Could not find" in err and not self.chrome:
            print("    no browser found: install Chrome or Edge, or pass --chrome <path to chrome/msedge>")
        return None


def write_docx(md_path, out_path, args):
    md = open(md_path, encoding="utf-8").read()
    title = next((m.group(1).strip() for m in re.finditer(r"^#\s+(.+)$", md, re.M)),
                 os.path.splitext(os.path.basename(md_path))[0])
    doc = Document(args.template) if args.template else Document()
    if args.template:  # keep the template's styles, header/footer and page setup; drop its body
        for el in list(doc.element.body):
            if el.tag != qn("w:sectPr"):
                doc.element.body.remove(el)
    setup_styles(doc, bool(args.template))
    for s in doc.sections:
        if not args.template:
            s.page_width, s.page_height = Cm(21), Cm(29.7)
            s.left_margin = s.right_margin = Cm(2.2)
            s.top_margin = s.bottom_margin = Cm(2.4)
        fp = s.footer.paragraphs[0]
        if not fp.text.strip():
            fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for part in ("\u7b2c ", "PAGE", " \u9875 / \u5171 ", "NUMPAGES", " \u9875"):
                r = fp.add_run() if part.isupper() else fp.add_run(part)
                if part.isupper():
                    add_field(r, part)
                r.font.size = Pt(9)
        hp = s.header.paragraphs[0]
        if not hp.text.strip():
            hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            r = hp.add_run(title)
            r.font.size = Pt(9)
            r.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
    sec = doc.sections[0]
    max_w = sec.page_width - sec.left_margin - sec.right_margin
    max_h = int((sec.page_height - sec.top_margin - sec.bottom_margin) * 0.8)
    base = os.path.dirname(os.path.abspath(md_path))
    toc_done = args.no_toc
    with tempfile.TemporaryDirectory() as wd:
        mer = Mermaid(args, wd)
        prev = None
        for b in blocks(md):
            kind = b[0]
            if prev == "table" and kind != "table":  # Word puts no gap under a table
                doc.add_paragraph().paragraph_format.space_after = Pt(0)
            prev = kind
            if kind == "h":
                p = doc.add_paragraph(style=S["h"].get(b[1]))
                add_inline(p, b[2])
                if b[1] == 1 and not toc_done:  # table of contents right after the title
                    toc_done = True
                    doc.add_paragraph("\u76ee\u5f55", style=S["toc"])
                    add_field(doc.add_paragraph().add_run(), 'TOC \\o "1-3" \\h \\z \\u',
                              "\uff08\u6253\u5f00\u6587\u6863\u65f6\u9009\u62e9\u201c\u662f\u201d\u66f4\u65b0\u57df\uff0c\u5373\u53ef\u751f\u6210\u76ee\u5f55\uff09")
            elif kind == "p":
                add_inline(doc.add_paragraph(), b[1])
            elif kind == "quote":
                add_inline(doc.add_paragraph(style=S["quote"]), b[1])
            elif kind == "li":
                _, level, marker, text = b
                if marker[0].isdigit():  # literal numbers: Word's list numbering would run on across lists
                    p = doc.add_paragraph()
                    p.paragraph_format.left_indent = Cm(0.75 * (level + 1))
                    p.paragraph_format.first_line_indent = Cm(-0.6)
                    add_inline(p, f"{marker} {text}")
                else:
                    add_inline(doc.add_paragraph(style=S["bullet"][min(level, 2)]), text)
            elif kind == "hr":
                doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            elif kind == "table":
                add_table(doc, b[1], int(max_w / 635))
            elif kind == "img":
                path = b[1] if os.path.isabs(b[1]) else os.path.join(base, b[1])
                if os.path.exists(path):
                    add_picture(doc, path, None, max_w, max_h)
            elif kind == "code":
                lang, src = b[1], b[2]
                png = mer.render(src) if lang == "mermaid" or (not lang and MERMAID_START.match(src)) else None
                if png:
                    alt = ALT + src.replace("\\", "\\\\").replace("\n", "\\n")
                    add_picture(doc, png, alt, max_w, max_h, scale=0.5)  # rendered at 2x
                    continue
                if lang == "mermaid":
                    doc.add_paragraph(NOT_RENDERED, style=S["quote"])
                p = doc.add_paragraph(style=S["code"])
                lines = src.replace("\t", "    ").split("\n")
                for k, line in enumerate(lines):
                    r = p.add_run(line)
                    if k < len(lines) - 1:
                        r.add_break()
    settings = doc.settings.element
    if not args.no_toc and settings.find(qn("w:updateFields")) is None:
        u = OxmlElement("w:updateFields")
        u.set(qn("w:val"), "true")
        settings.append(u)
    doc.save(out_path)
    return mer.n, mer.ok, md


def trace_check(md):
    """Design docs: every R has an AC and appears in the technical part; ids are defined;
    no \u3010\u5047\u8bbe\u3011 left for an answered question. Prints findings, never fails the conversion."""
    defined = {}
    for line in md.splitlines():
        if line.lstrip().startswith("|"):
            first = cells(line)[0].strip("* ")
            if ID.fullmatch(first):
                defined[first] = cells(line)
    if not any(k.startswith("R-") for k in defined):
        return
    refs = {m.group(0) for m in ID.finditer(md)}
    issues = [f"{i} is referenced but never defined" for i in sorted(refs - set(defined))]
    covered = {m.group(0) for k, row in defined.items() if k.startswith("AC-") for m in ID.finditer(" ".join(row[1:2]))}
    head = re.search(r"^#+ .*\u6280\u672f\u8bbe\u8ba1", md, re.M)
    tech = md[head.start():] if head else ""
    for r in (k for k in defined if k.startswith("R-")):
        if r not in covered:
            issues.append(f"{r} has no acceptance criterion (AC row with {r} in its 2nd column)")
        if tech and not re.search(rf"(?<![\w-]){r}(?!\d)", tech):
            issues.append(f"{r} is not referenced in the technical part")
    answered = {k for k, row in defined.items() if k.startswith("Q-") and re.search("\u5df2\u786e\u8ba4|\u5df2\u53d6\u6d88", row[-1])}
    for a in re.findall(r"\u3010\u5047\u8bbe[^\u3011]*\u3011", md):
        issues += [f"assumption left for answered {q}: {a}" for q in answered if re.search(rf"{q}(?!\d)", a)]
    open_q = [k for k, row in defined.items() if k.startswith("Q-") and k not in answered]
    blocking = [k for k in open_q if "\u963b\u585e" in " ".join(defined[k]).replace("\u975e\u963b\u585e", "")]
    count = lambda p: sum(k.startswith(p) for k in defined)
    assumptions = len(re.findall("\u3010\u5047\u8bbe", md))
    print(f"[check] R={count('R-')} AC={count('AC-')} Q={count('Q-')} (open {len(open_q)}, blocking "
          f"{len(blocking)}: {', '.join(blocking) or '-'}) \u3010\u5047\u8bbe\u3011={assumptions}" + ("" if issues else " -- ok"))
    for x in issues:
        print(f"  ! {x}")


# --------------------------------------------------------------------------- reading

def read_docx(path, out_dir):
    doc = Document(path)
    id2name = {s.style_id: (s.name or "").lower() for s in doc.styles}
    outline_of = {}
    for s in doc.styles:
        lvl = s.element.find(f"{WNS}pPr/{WNS}outlineLvl")
        if lvl is not None:
            outline_of[s.style_id] = int(lvl.get(qn("w:val")))
    code_char = next((s.style_id for s in doc.styles if (s.name or "").lower() == "code char"), None)
    comments = {}
    for rel in doc.part.rels.values():
        if rel.reltype.endswith("/comments") and not rel.is_external:
            for c in parse_xml(rel.target_part.blob).iter(f"{WNS}comment"):
                comments[c.get(qn("w:id"))] = (c.get(qn("w:author")) or "",
                                               "".join(t.text or "" for t in c.iter(f"{WNS}t")))
    media = os.path.join(out_dir, "media")
    images = []

    def save_image(rid):
        part = doc.part.related_parts.get(rid)
        if part is None:
            return None
        os.makedirs(media, exist_ok=True)
        name = f"image{len(images) + 1}{os.path.splitext(part.partname)[1]}"
        open(os.path.join(media, name), "wb").write(part.blob)
        images.append(os.path.join(media, name))
        return f"media/{name}"

    def inline(p, in_table=False, code=False):
        """Paragraph -> (markdown text, mermaid source or None, page break?)."""
        segs, mermaid, page = [], None, False
        for el in p.iter():
            tag = el.tag
            if tag in (f"{WNS}t", f"{WNS}delText"):
                r = el.getparent()
                rpr = r.find(f"{WNS}rPr")
                b = rpr.find(f"{WNS}b") if rpr is not None else None
                rs = rpr.find(f"{WNS}rStyle") if rpr is not None else None
                color = rpr.find(f"{WNS}color") if rpr is not None else None
                if color is not None and color.get(qn("w:val"), "").upper() in MARK_HEX:
                    b = None  # bold that comes with a marker's color is not **emphasis**
                ins = any(True for _ in el.iterancestors(f"{WNS}ins", f"{WNS}moveTo"))
                segs.append([el.text or "", b is not None and b.get(qn("w:val")) not in ("0", "false"),
                             rs is not None and rs.get(qn("w:val")) == code_char,
                             "+" if ins else "-" if tag.endswith("delText") else ""])
            elif tag == f"{WNS}tab":
                segs.append([" ", False, False, ""])
            elif tag == f"{WNS}br":
                if el.get(qn("w:type")) == "page":
                    page = True
                else:
                    segs.append(["\n" if code else "<br>", False, False, ""])
            elif tag == f"{WNS}commentRangeStart" and el.get(qn("w:id")) in comments:
                author, text = comments[el.get(qn("w:id"))]
                segs.append([f"[\u6279\u6ce8 {author}\uff1a{text}]", False, False, ""])
            elif tag.endswith("}docPr"):
                descr = el.get("descr") or ""
                if descr.startswith(ALT):
                    mermaid = re.sub(r"\\(\\|n)", lambda m: "\n" if m.group(1) == "n" else "\\", descr[len(ALT):])
            elif (tag.endswith("}blip") or tag.endswith("}imagedata")) and mermaid is None:  # DrawingML / old VML
                ref = save_image(el.get(qn("r:embed")) or el.get(qn("r:id")))
                if ref:
                    segs.append([f"![]({ref})", False, False, ""])
        merged = []
        for s in segs:  # merge neighbours with the same formatting before adding markup
            if merged and merged[-1][1:] == s[1:] and s[0] not in ("<br>", "\n"):
                merged[-1][0] += s[0]
            else:
                merged.append(list(s))
        out = ""
        for text, bold, is_code, change in merged:
            if in_table:
                text = text.replace("|", "\\|")
            if is_code and text.strip():
                text = f"`{text}`"
            elif bold and text.strip():
                text = f"**{text}**"
            out += f"[{change}{text}{change}]" if change else text
        return out, mermaid, page

    out, code_buf = [], []

    def flush_code():
        if code_buf:
            src = "\n".join(code_buf)
            lang = ("mermaid" if MERMAID_START.match(src) else
                    "json" if re.match(r"\s*[{\[]", src) else
                    "sql" if re.search(r"^\s*(CREATE|ALTER|SELECT|INSERT|UPDATE|DELETE)\s", src, re.M) else
                    "bash" if re.search(r"^\s*(mvn|java|docker|curl|nohup|cd|git|npm|npx|python3?|pip3?|kill|"
                                        r"systemctl|sudo|export|tail)\s", src, re.M) else "")
            out.append(f"```{lang}\n{src}\n```")
            code_buf.clear()

    def paragraph(p):
        sid = p.find(f"{WNS}pPr/{WNS}pStyle")
        sid = sid.get(qn("w:val")) if sid is not None else None
        name = id2name.get(sid, "normal")
        if name.startswith("toc") or p.find(f".//{WNS}instrText") is not None and "TOC" in "".join(
                t.text or "" for t in p.iter(f"{WNS}instrText")):
            return
        text, mermaid, page = inline(p, code=name == "code")
        if name == "code":
            code_buf.append(text)
            return
        flush_code()
        if mermaid is not None:
            out.append(f"```mermaid\n{mermaid}\n```")
        elif page and not text.strip():
            out.append("---")
        elif text.strip() == NOT_RENDERED:
            return
        elif text.strip():
            lvl = p.find(f"{WNS}pPr/{WNS}outlineLvl")
            lvl = int(lvl.get(qn("w:val"))) if lvl is not None else outline_of.get(sid)
            m = re.match(r"(heading|\u6807\u9898)\s*(\d)", name)
            if m or (lvl is not None and lvl < 6):
                out.append("#" * (int(m.group(2)) if m else lvl + 1) + " " + text.replace("**", "").strip())
            elif name.startswith("list bullet") or p.find(f"{WNS}pPr/{WNS}numPr") is not None:
                depth = int(name[-1]) - 1 if name[-1:].isdigit() else 0
                out.append("  " * depth + "- " + text.strip())
            elif name in ("quote", "intense quote"):
                out.append("> " + text.strip())
            else:
                out.append(text.strip())

    def table(tbl):
        flush_code()
        rows = []
        for tr in tbl.findall(f"{WNS}tr"):
            row = []
            for tc in tr.findall(f"{WNS}tc"):
                parts = [inline(p, in_table=True)[0].strip() for p in tc.iter(f"{WNS}p")]
                row.append("<br>".join(x for x in parts if x))
            rows.append(row)
        if rows:
            n = max(len(r) for r in rows)
            rows = [r + [""] * (n - len(r)) for r in rows]
            rows[0] = [re.sub(r"^\*\*(.*)\*\*$", r"\1", c) for c in rows[0]]
            out.append("\n".join(["| " + " | ".join(rows[0]) + " |", "|" + "---|" * n]
                                 + ["| " + " | ".join(r) + " |" for r in rows[1:]]))

    def walk(container):
        for el in container.iterchildren():
            if el.tag == f"{WNS}p":
                paragraph(el)
            elif el.tag == f"{WNS}tbl":
                table(el)
            elif el.tag == f"{WNS}sdt":  # content control; Word puts its own TOC in one
                content = el.find(f"{WNS}sdtContent")
                gallery = el.find(f".//{WNS}docPartGallery")
                if content is not None and not (gallery is not None and "Contents" in (gallery.get(qn("w:val")) or "")):
                    walk(content)
        flush_code()

    walk(doc.element.body)
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, os.path.splitext(os.path.basename(path))[0] + ".md")
    open(md_path, "w", encoding="utf-8").write("\n\n".join(out) + "\n")
    return md_path, images


def report(md_path, images):
    lines = open(md_path, encoding="utf-8").read().splitlines()
    heads = [(i, ln) for i, ln in enumerate(lines, 1) if re.match(r"^#{1,6}\s", ln)]
    joined = "\n".join(lines)
    marks = {k: len(re.findall(p, joined)) for k, p in (("added", r"\[\+"), ("deleted", r"\[-"), ("comments", r"\[\u6279\u6ce8 "))}
    print(f"markdown: {slash(md_path)}  ({len(lines)} lines, {len(joined)} chars, {len(heads)} headings, "
          f"{len(images)} images, {joined.count('```mermaid')} diagrams)")
    if any(marks.values()):
        print(f"review marks: {marks['added']} [+added+], {marks['deleted']} [-deleted-], {marks['comments']} [\u6279\u6ce8 \u2026]")
    for i, ln in heads[:60]:
        print(f"  L{i}: {ln[:90]}")
    if len(heads) > 60:
        print(f"  \u2026 {len(heads) - 60} more headings")
    for f in images[:20]:
        print(f"  image: {slash(f)}" + ("  [EMF/WMF: cannot be viewed, ask for a screenshot]"
                                        if f.lower().endswith((".emf", ".wmf")) else ""))
    if len(joined) > 60000:
        print("note: long document, read it in parts (offset/limit) using the line numbers above")


# --------------------------------------------------------------------------- main

def main():
    utf8_output()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help=".md files or folders to convert, or .docx files with --read")
    ap.add_argument("--read", action="store_true", help="convert .docx to Markdown instead")
    ap.add_argument("--out-dir", help="default: next to each .md (writing), system temp dir (--read)")
    ap.add_argument("--template", help="company .docx whose styles, header and footer to use")
    ap.add_argument("--no-toc", action="store_true")
    ap.add_argument("--mmdc", help="Mermaid CLI command or path")
    ap.add_argument("--chrome", help="Chrome/Edge executable for the Mermaid CLI")
    args = ap.parse_args()
    files, failed = [], False
    for i in args.inputs:
        if os.path.isdir(i):
            files += sorted(os.path.join(i, f) for f in os.listdir(i) if f.endswith(".md"))
        elif os.path.isfile(i):
            files.append(i)
        else:
            print(f"not found: {i}")
            failed = True
    try:
        for f in files:
            stem, ext = os.path.splitext(os.path.basename(f))
            if args.read:
                if ext.lower() != ".docx":
                    print(f"skip {f}: --read takes .docx (.pdf \u2192 read it directly, .doc/.wps \u2192 save as .docx)")
                    failed = True
                    continue
                out_dir = args.out_dir or os.path.join(tempfile.gettempdir(), "md2docx-" + re.sub(r"[^\w.-]", "_", stem))
                report(*read_docx(f, out_dir))
                continue
            out_dir = args.out_dir or os.path.dirname(os.path.abspath(f))
            os.makedirs(out_dir, exist_ok=True)
            out = os.path.join(out_dir, stem + ".docx")
            try:
                n, ok, md = write_docx(f, out, args)
            except PermissionError as e:
                print(f"FAIL {f}: cannot write {e.filename}: close it in Word first")
                failed = True
                continue
            trace_check(md)
            print(f"wrote {slash(out)}" + (f", diagrams {ok}/{n}" if n else ""))
    except BrokenPipeError:  # output piped into `head`; files are already written
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
