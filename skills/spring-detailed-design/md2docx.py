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
  python md2docx.py <design.docx | design.md> --openapi [--out-dir DIR]
      Design docs: writes <name>.openapi.json (OpenAPI 3.0) from section 2.3 for Apifox or Postman,
      next to the input unless --out-dir is given. Converting a design doc always checks that
      section and prints an [api] line; every "! api" finding is a table the export cannot read.

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
        return False
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
    return True


# --------------------------------------------------------------------------- OpenAPI export

API_HEAD = re.compile(r"^(.*?)\s*`(GET|POST|PUT|DELETE|PATCH)\s+(/[^`\s]*)`(.*)$", re.I)
API_DECL = re.compile(r"\**`?(GET|POST|PUT|DELETE|PATCH)\s+(/[^`\s\uff08(\uff1a:\uff0c,\uff1b;]*)`?\**", re.I)
API_LABEL = re.compile(r"^\**(\u8bf7\u6c42\u5934|\u8def\u5f84\u53c2\u6570|\u67e5\u8be2\u53c2\u6570|\u8bf7\u6c42\u4f53|\u8bf7\u6c42\u53c2\u6570|\u5165\u53c2|\u54cd\u5e94|\u54cd\u5e94\u53c2\u6570|\u8fd4\u56de\u53c2\u6570|\u54cd\u5e94\u5b57\u6bb5|\u8fd4\u56de\u5b57\u6bb5|\u51fa\u53c2|"
                       r"\u8fd4\u56de\u503c|\u7ed3\u6784)\**\s*(?:`([^`]+)`)?\s*(?:[\uff08(]([^\uff09)]*)[\uff09)])?\s*(?:[\uff1a:\uff0c,\u3002]\s*(.*)|$)")
LABEL_KIND = {"\u8bf7\u6c42\u5934": "header", "\u8def\u5f84\u53c2\u6570": "path", "\u67e5\u8be2\u53c2\u6570": "query", "\u8bf7\u6c42\u4f53": "body", "\u8bf7\u6c42\u53c2\u6570": "params",
              "\u5165\u53c2": "params", "\u7ed3\u6784": "struct"}  # every other label introduces the response
API_IN = ("header", "path", "query")
API_COLUMNS = {"name": ("\u5b57\u6bb5", "\u53c2\u6570", "\u53c2\u6570\u540d", "\u5b57\u6bb5\u540d", "\u5c5e\u6027"), "type": ("\u7c7b\u578b",),
               "required": ("\u5fc5\u586b", "\u662f\u5426\u5fc5\u586b"), "rule": ("\u6821\u9a8c", "\u6821\u9a8c\u89c4\u5219", "\u7ea6\u675f", "\u53d6\u503c"),
               "default": ("\u9ed8\u8ba4\u503c",), "desc": ("\u8bf4\u660e", "\u63cf\u8ff0", "\u542b\u4e49", "\u5907\u6ce8"), "example": ("\u793a\u4f8b", "\u793a\u4f8b\u503c")}
FILE_RESPONSE = re.compile(r"Excel|xlsx|\.xls|\u6587\u4ef6\u6d41|\u4e8c\u8fdb\u5236\u6d41")
ERR_CODES = re.compile(r"\u9519\u8bef\u7801\s*[\uff1a:]?\s*((?:\d{3,6}(?:\s*[\u2013\u2014~\uff5e\-\u81f3\u5230]\s*\d{3,6})?(?:\s*[\u3001,\uff0c/\u548c\u53ca]\s*|\s+)?)+)")
TIME_FMT = re.compile(r"yyyy[-/.]?MM[-/.]?dd(?:[ T]HH:mm(?::ss)?)?")
NUM = r"-?\d+(?:\.\d+)?"
RANGE = re.compile(r"(?<![\d.\-])(" + NUM + r")\s*(?:\u2013|\u2014|~|\uff5e|\u81f3|\u5230|-)\s*(" + NUM + r")(?![\d.\-:])")
YES, NO = ("\u662f", "y", "yes", "true", "\u5fc5\u586b", "\u221a"), ("\u5426", "n", "no", "false", "\u975e\u5fc5\u586b", "", "-", "\u2014")
JAVA = {"String": ("string", None), "CharSequence": ("string", None), "char": ("string", None),
        "Character": ("string", None), "LocalTime": ("string", None), "UUID": ("string", "uuid"),
        "Integer": ("integer", "int32"), "int": ("integer", "int32"), "Short": ("integer", "int32"),
        "short": ("integer", "int32"), "Byte": ("integer", "int32"), "byte": ("integer", "int32"),
        "Long": ("integer", "int64"), "long": ("integer", "int64"), "BigInteger": ("integer", None),
        "BigDecimal": ("number", None), "Number": ("number", None), "Double": ("number", "double"),
        "double": ("number", "double"), "Float": ("number", "float"), "float": ("number", "float"),
        "Boolean": ("boolean", None), "boolean": ("boolean", None), "MultipartFile": ("string", "binary")}
DATETIME = {"LocalDateTime", "Date", "Timestamp", "ZonedDateTime", "OffsetDateTime", "Instant", "DateTime"}
DATE_ONLY = {"LocalDate"}
LISTS = {"List", "ArrayList", "LinkedList", "Set", "HashSet", "LinkedHashSet", "TreeSet", "Collection", "Iterable"}
MAPS, VOID, ANY = {"Map", "HashMap", "LinkedHashMap", "TreeMap"}, {"Void", "void"}, {"Object", "JsonNode", "JSONObject"}


def api_status(text):
    """'\uff08\u4fee\u6539\uff1a\u65b0\u589e\u7528\u5238\u53c2\u6570\uff09' -> 'existing', '\uff08\u65b0\u589e\uff09' -> 'new', None if it does not say. The first of
    \u65b0\u589e/\u4fee\u6539/\u4e0d\u53d8/\u590d\u7528/\u6cbf\u7528 inside parentheses decides."""
    for part in re.findall(r"[\uff08(]([^\uff09)]*)[\uff09)]", text.replace("*", "")):
        m = re.search(r"\u65b0\u589e|\u4fee\u6539|\u4e0d\u53d8|\u590d\u7528|\u6cbf\u7528", part)
        if m:
            return "new" if m.group(0) == "\u65b0\u589e" else "existing"
    return None


def java_type(text):
    """'Result<PageResult<CouponVO>>' -> ('Result', [('PageResult', [('CouponVO', [])])]); None if unreadable."""
    s = re.sub(r"\s+", "", re.split(r"[\uff08(\u4e00-\u9fff]", text.replace("`", ""), maxsplit=1)[0])
    pos = [0]

    def node():
        m = re.compile(r"[A-Za-z_$][\w.$]*").match(s, pos[0])
        if not m:
            raise ValueError(s)
        name, args = m.group(0).split(".")[-1], []
        pos[0] = m.end()
        if s[pos[0]:pos[0] + 1] == "<":
            pos[0] += 1
            args.append(node())
            while s[pos[0]:pos[0] + 1] == ",":
                pos[0] += 1
                args.append(node())
            if s[pos[0]:pos[0] + 1] != ">":
                raise ValueError(s)
            pos[0] += 1
        while s[pos[0]:pos[0] + 2] == "[]":
            pos[0] += 2
            name, args = "List", [(name, args)]
        return name, args

    try:
        n = node()
    except ValueError:
        return None
    return n if pos[0] == len(s) else None


def field_rows(rows):
    """A parameter or field table -> [{name, type, required, rule, default, desc, example}], None if not one."""
    head = [re.sub(r"[*\s]", "", c) for c in rows[0]]
    col = {k: next((i for i, h in enumerate(head) if h in names), None) for k, names in API_COLUMNS.items()}
    if col["name"] is None or col["type"] is None:
        return None
    out = []
    for r in rows[1:]:
        f = {k: (re.sub(r"<br\s*/?>", "\n", r[i]).strip() if i is not None and i < len(r) else "") for k, i in col.items()}
        names = [n for n in re.split(r"\s*[/\u3001,\uff0c]\s*", re.sub(r"[`*]", "", f["name"]).strip()) if n]
        if len(names) > 1 and not all(re.fullmatch(r"[A-Za-z_$][\w$-]*", n) for n in names):
            names = [re.sub(r"[`*\s]", "", f["name"])]  # one name that happens to contain a slash
        out += [dict(f, name=n) for n in names if n]  # 'page/size' is two parameters
    return out


def codes_in(text):
    out = []
    for m in ERR_CODES.finditer(text):
        for a, b in re.findall(r"(\d{3,6})(?:\s*[\u2013\u2014~\uff5e\-\u81f3\u5230]\s*(\d{3,6}))?", m.group(1)):
            a, b = int(a), int(b or a)
            out += list(range(a, b + 1)) if 0 <= b - a <= 50 else [a, b]
    return out


def int_enum(text):
    """'1 \u6ee1\u51cf\u5238\uff0c2 \u6298\u6263\u5238' / '1 \u6216 2' -> [(1, '\u6ee1\u51cf\u5238'), (2, '\u6298\u6263\u5238')]"""
    out = []
    for p in (p.strip() for p in re.split(r"[\uff0c,\u3001;\uff1b/|]|\u6216", text) if p.strip()):
        m = re.fullmatch(r"(-?\d+)(?:\s*[-:\uff1a=.]?\s*([\u4e00-\u9fffA-Za-z][^\uff0c,\u3001;\uff1b/|]*))?", p)
        if not m:
            return None
        out.append((int(m.group(1)), (m.group(2) or "").strip()))
    return out if len(out) >= 2 and len({v for v, _ in out}) == len(out) else None


def str_enum(text):
    """'UNUSED \u672a\u4f7f\u7528 / USED \u5df2\u4f7f\u7528' -> [('UNUSED', '\u672a\u4f7f\u7528'), ('USED', '\u5df2\u4f7f\u7528')]"""
    out = []
    for p in (p.strip() for p in re.split(r"[\uff0c,\u3001;\uff1b/|]", text) if p.strip()):
        m = re.fullmatch(r"`?([A-Z][A-Z0-9_]+)`?(?:\s*[-:\uff1a=]?\s*[\uff08(]?\s*([\u4e00-\u9fffA-Za-z][^\uff09)]*?)\s*[\uff09)]?)?", p)
        if not m:
            return None
        out.append((m.group(1), (m.group(2) or "").strip()))
    return out if len(out) >= 2 and len({v for v, _ in out}) == len(out) else None


def enum_text(desc):
    """The enum part of a \u8bf4\u660e cell: '\u8fd0\u8425\u72b6\u6001\uff1aA \u7532 / B \u4e59\uff1b\u7531\u2026\u8ba1\u7b97' -> 'A \u7532 / B \u4e59'"""
    return re.sub(r"^[^\uff1a:\uff0c,]{1,20}[\uff1a:]\s*", "", re.split(r"[\uff1b;\u3002\n]", desc, maxsplit=1)[0])


def annotation_args(text):
    text = text.strip()
    pairs = re.findall(r"(\w+)\s*=\s*(\"(?:[^\"\\]|\\.)*\"|[^,]+)", text)
    if pairs:
        return {k: v.strip().strip('"') for k, v in pairs}
    return {"value": text.strip('"')} if text else {}


def number(text, kind):
    v = float(text)
    return int(v) if kind == "integer" or v.is_integer() else v


def coerce(text, s):
    """A default or example written in the doc, as the field's JSON type; None if it does not fit."""
    text, kind = text.strip().strip("`'\""), s.get("type")
    try:
        if kind in ("integer", "number"):
            v = number(text, kind)
        elif kind == "boolean":
            v = {"true": True, "\u662f": True, "false": False, "\u5426": False}[text.lower()]
        elif kind == "string" and (re.fullmatch(r"[\w.:\- ]+", text, re.A) or text in s.get("enum", [])):
            v = text
        else:
            return None
    except (ValueError, KeyError):
        return None
    return v if "enum" not in s or v in s["enum"] else None


def describe(f):
    parts, req, rule = [f["desc"]], f["required"].strip().strip("*"), f["rule"].strip()
    if req and req.lower() not in YES + NO:
        parts.append(req)  # a condition, e.g. required only for one coupon type
    if rule not in ("", "-", "\u2014", "/", "\u65e0") and not re.fullmatch(r"\u9ed8\u8ba4(?:\u503c)?(?:\u4e3a)?\s*[\uff1a:]?\s*\S+", rule):
        parts.append("\u6821\u9a8c\uff1a" + rule)
    return "\uff1b".join(p for p in parts if p)


def sample(s, f):
    """An example value that satisfies the schema, so Postman's mock returns something sensible."""
    if s.get("enum"):
        return s["enum"][0]
    if "default" in s:
        return s["default"]
    kind, lo, hi = s.get("type"), s.get("minimum"), s.get("maximum")
    if kind in ("integer", "number"):
        m = re.search(r"(?<![\d.])(" + NUM + r")\s*(?:\u8868\u793a|\u4ee3\u8868)", f["desc"])
        c = number(m.group(1), kind) if m else None
        if c is not None and (lo is None or c >= lo) and (hi is None or c <= hi):
            return c
        step = s.get("multipleOf")
        for c in (100, 10, 1):
            if (lo is None or c >= lo) and (hi is None or c <= hi) and (not step or abs(c / step - round(c / step)) < 1e-9):
                return c
        return lo if lo is not None else hi
    if kind == "boolean":
        return True
    if kind == "string" and not s.get("format") and "pattern" not in s:
        m = re.search(r"\u5982\s*[\u201c\"\u300c]([^\u201d\"\u300d]+)[\u201d\"\u300d]", f["desc"]) or re.search(  # an example the text gives
            r"(?<![\w.\-])([\w.\-]+)\s*(?:\u8868\u793a|\u4ee3\u8868)", f["desc"], re.A)
        text = m.group(1) if m else re.split(r"[\uff0c,\uff1b;\u3002\uff08(\uff1a:\n]", f["desc"])[0].strip() or f["name"]
        return text[:s["maxLength"]] if "maxLength" in s else text
    return None


def time_schema(fmt, date_only):
    if not fmt:
        return {"type": "string", "format": "date" if date_only else "date-time"}
    if date_only:
        fmt = re.split(r"[ T]", fmt)[0]
    rx, ex = "", fmt
    for tok in re.findall(r"yyyy|MM|dd|HH|mm|ss|.", fmt):
        rx += "\\d{%d}" % len(tok) if len(tok) > 1 else "\\." if tok == "." else tok
    for tok, v in (("yyyy", "2026"), ("MM", "12"), ("dd", "10"), ("HH", "09"), ("mm", "30"), ("ss", "00")):
        ex = ex.replace(tok, v)
    return {"type": "string", "pattern": "^" + rx + "$", "example": ex,
            "x-apifox-mock": "@%s('%s')" % ("datetime" if "HH" in fmt else "date", fmt)}


class ApiDesign:
    """Section 2.3 \u63a5\u53e3\u8bbe\u8ba1 of a design doc -> OpenAPI 3.0 for Apifox and Postman. An API starts at a heading
    or paragraph that opens with `METHOD /path`; its parameters and fields are the tables after the lines
    \u8bf7\u6c42\u5934 / \u8def\u5f84\u53c2\u6570 / \u67e5\u8be2\u53c2\u6570 / \u8bf7\u6c42\u53c2\u6570 / \u8bf7\u6c42\u4f53 `T` / \u54cd\u5e94 `T` / \u7ed3\u6784 `T`. APIs marked \u4fee\u6539/\u4e0d\u53d8/\u590d\u7528
    already exist and are not exported. Whatever it cannot read becomes a finding, never a guess."""

    def __init__(self, md, stem):
        bl = blocks(md)
        self.stem, self.issues, self.notes, self.apis, self.labels = stem, [], [], [], []
        self.listed, self.codes, self.generic, self.named, self.fallback = {}, {}, {}, {}, set()
        m = re.match(r"(.+?)-\u8be6\u7ec6\u8bbe\u8ba1", stem)  # the skill names its files <feature>-<detailed design>[-v0.2]
        titles = [b[2].strip() for b in bl if b[0] == "h" and b[1] == 1 and not re.match(r"\u7b2c\S{1,3}\u90e8\u5206", b[2])]
        self.title = titles[0] if titles else (m.group(1) + " \u8be6\u7ec6\u8bbe\u8ba1" if m else stem)
        self.feature = m.group(1) if m else (re.sub(r"\s*\u8be6\u7ec6\u8bbe\u8ba1.*$", "", self.title) or self.title)
        self.version = next((r[1].strip() for b in bl if b[0] == "table" for r in b[1][1:]
                             if len(r) > 1 and r[0].strip("* ") == "\u7248\u672c"), "") or "v1"
        start = next((i for i, b in enumerate(bl) if b[0] == "h" and "\u63a5\u53e3\u8bbe\u8ba1" in b[2]), None)
        self.found = start is not None
        if not self.found:
            return
        end = next((i for i in range(start + 1, len(bl)) if bl[i][0] == "h" and bl[i][1] <= bl[start][1]), len(bl))
        sec = bl[start + 1:end]
        text = "\n".join(x if isinstance(x, str) else " ".join(" ".join(r) for r in x) for b in sec for x in b[1:]
                         if isinstance(x, (str, list)))
        m = TIME_FMT.search(text)
        self.time_fmt = m.group(0) if m else None
        self.parse(sec)
        self.doc = self.build()

    def where(self, api):
        return "%s %s" % (api["method"].upper(), api["path"])

    def issue(self, where, msg):
        x = "%s: %s" % (self.where(where) if isinstance(where, dict) else where, msg)
        if x not in self.issues:
            self.issues.append(x)

    # ---- reading the section

    def new_api(self, name, method, path, status):
        a = {"name": name, "method": method.lower(), "path": path, "status": status, "params": [], "body": None,
             "resp": None, "legacy_resp": None, "codes": [], "notes": [], "loose": []}
        self.apis.append(a)
        return a

    @staticmethod
    def declaration(text):
        """'`GET /a`\uff08\u65b0\u589e\uff09' or '`POST /a` / `GET /b`\uff08\u4fee\u6539\uff09\uff1a\u8bf4\u660e' -> ([(method, path)], status, rest);
        None when the paragraph does not open with APIs."""
        apis, pos = [], 0
        while True:
            m = API_DECL.match(text, pos)
            if not m:
                break
            apis.append((m.group(1), m.group(2)))
            pos = m.end()
            sep = re.compile(r"\s*(?:/|\u3001|\uff0c|,|\u548c|\u53ca)\s*").match(text, pos)
            if not (sep and API_DECL.match(text, sep.end())):
                break
            pos = sep.end()
        m = re.compile(r"\s*([\uff08(][^\uff09)]*[\uff09)])?\s*(?:[\uff1a:]\s*(.*)|$)", re.S).match(text, pos) if apis else None
        return (apis, api_status(m.group(1) or ""), (m.group(2) or "").strip()) if m else None

    def parse(self, sec):
        group, level, depth, pending = [], 0, 0, None
        for k, b in enumerate(sec):
            nxt = sec[k + 1] if k + 1 < len(sec) else ("",)
            if b[0] == "h":
                m = API_HEAD.match(b[2])
                if m:
                    group, level = [self.new_api(m.group(1).strip(" *"), m.group(2), m.group(3),
                                                 api_status(m.group(4)))], b[1]
                elif b[1] <= level:
                    group = []
                depth = b[1]
                continue
            if b[0] == "table":
                rows = b[1]
                if pending:
                    self.labels.append(pending + (rows,))
                    pending = None
                    continue
                head = [re.sub(r"[*\s]", "", c) for c in rows[0]]
                if head[0] == "\u63a5\u53e3":
                    for r in rows[1:]:
                        m = re.search(r"`?(GET|POST|PUT|DELETE|PATCH)\s+(/[^`\s]*)`?", r[0], re.I)
                        if m:
                            self.listed[(m.group(1).lower(), m.group(2))] = dict(zip(head, r))
                elif head[0] == "\u9519\u8bef\u7801":
                    for r in rows[1:]:
                        if re.fullmatch(r"\d{3,6}", r[0].strip()):
                            self.codes[int(r[0])] = r[1].strip() if len(r) > 1 else ""
                elif field_rows(rows) is not None:
                    for a in group:
                        a["loose"].append("a table has no \u8bf7\u6c42\u5934/\u8def\u5f84\u53c2\u6570/\u67e5\u8be2\u53c2\u6570/\u8bf7\u6c42\u4f53/\u54cd\u5e94 line right before it")
                continue
            if b[0] == "p":
                m = API_LABEL.match(b[1])
                if m:
                    label = (m.group(1), m.group(2), m.group(3) or "", ERR_CODES.sub("", m.group(4) or "").strip(),
                             list(group))
                    if nxt[0] == "table":
                        pending = label
                    else:
                        self.labels.append(label + (None,))
                    for a in group:
                        a["codes"] += codes_in(b[1])
                    continue
                d = self.declaration(b[1])
                if d:  # an API written as a paragraph instead of a heading
                    group, level = [self.new_api("", mth, path, d[1]) for mth, path in d[0]], depth
                    if not d[2]:
                        continue
                    text = d[2]
                else:
                    text = b[1]
            elif b[0] == "li":
                text = "  " * b[1] + ("- " if b[2] in "-*+" else b[2] + " ") + b[3]
            elif b[0] == "quote":
                text = "> " + b[1]
            elif b[0] == "code":
                text = "```%s\n%s\n```" % (b[1], b[2])
            else:
                continue
            if re.fullmatch(r"\*\*[^*]+\*\*\s*[\uff1a:]?", text):
                continue  # a bold caption belongs to the table below it
            if not group:
                self.notes.append(text)
                continue
            for a in group:
                a["codes"] += codes_in(text)
                if b[0] in ("p", "li"):
                    for m in re.finditer(r"\u54cd\u5e94\s*(?:`([^`]+)`|([A-Z][a-z]\w*(?:<[^>\uff0c\u3002\uff1b\s]*>+)?))", text):
                        found = (0 if m.group(1) else 1, m.group(1) or m.group(2))  # `Class` beats a bare word
                        if a["legacy_resp"] is None or found[0] < a["legacy_resp"][0]:
                            a["legacy_resp"] = found
                    m = re.search(r"\u8bf7\u6c42\u5934|\u8def\u5f84\u53c2\u6570|\u67e5\u8be2\u53c2\u6570|\u8bf7\u6c42\u53c2\u6570|\u5165\u53c2", text)
                    if m:
                        a["loose"].append("%s are written in a sentence; put them in a table after a line '%s\uff1a'"
                                          % (m.group(0), m.group(0)))
                if ERR_CODES.sub("", text).strip(" \u3002.\uff1b;\uff0c,") or b[0] != "p":
                    a["notes"].append(text)
        for a in self.apis:
            row = self.listed.get((a["method"], a["path"]), {})
            a["existing"] = (a["status"] or self.listed_status(row)) == "existing"
            if not a["name"]:
                a["name"] = re.sub(r"[\uff08(][^\uff09)]*[\uff09)]", "", row.get("\u8bf4\u660e", "")).strip("* ") or self.where(a)
        for label, typ, paren, rest, group, rows in self.labels:
            kind = LABEL_KIND.get(label, "resp")
            if not typ:  # the class may sit in parentheses after the label
                m = re.search(r"[A-Z][A-Za-z0-9_]*(?:<[^>\uff08\uff09()]*>)?", paren)
                typ = m.group(0) if m else None
            where = group[0] if group else ("\u7ed3\u6784 `%s`" % typ if kind == "struct" else "\u63a5\u53e3\u8bbe\u8ba1")
            fields = field_rows(rows) if rows else None
            if rows and fields is None:
                self.issue(where, "the table after '%s' needs the columns \u5b57\u6bb5 (or \u53c2\u6570) and \u7c7b\u578b" % label)
                continue
            if kind == "struct":
                node = java_type(typ or "")
                if node is None or not fields:
                    self.issue(where, "\u7ed3\u6784 needs a class name in backticks and a field table")
                elif node[1]:
                    self.generic[node[0]] = ([a[0] for a in node[1]], fields)
                else:
                    self.define(node[0], fields, where)
                continue
            if not group:
                self.issue(where, "'%s' is not under an API (a heading or a paragraph starting with `METHOD /path`)"
                           % label)
            for a in group:
                k = kind if kind != "params" else ("query" if a["method"] in ("get", "delete") else "body")
                if k in API_IN:
                    if fields is None:
                        a["loose"].append("%s has no table" % label)
                    a["params"] += [(k, f) for f in fields or []]
                else:
                    a[k] = (typ, fields, rest)
        for a in self.apis:
            if a["resp"] is None and a["legacy_resp"]:  # the response class was only named in a sentence
                a["resp"] = (a["legacy_resp"][1], None, "")
            for slot in ("body", "resp"):  # a table after a body/response line describes the innermost class of its type
                if a[slot] and a[slot][0] and a[slot][1] and not a["existing"]:
                    node = java_type(a[slot][0])
                    own = self.own_types(node) if node else []
                    if not own:
                        self.issue(a, "`%s` has no class of its own for the table to describe" % a[slot][0])
                    else:
                        self.define(own[-1], a[slot][1], a)

    @staticmethod
    def listed_status(row):
        change = row.get("\u53d8\u66f4\u7c7b\u578b", "").strip("* ")
        if change:
            return "new" if change == "\u65b0\u589e" else "existing"
        return api_status(" ".join(row.values()))

    def known(self, name):
        return (name in JAVA or name in DATETIME or name in DATE_ONLY or name in LISTS or name in MAPS
                or name in VOID or name in ANY or name in self.generic)

    def own_types(self, node, out=None):
        out = [] if out is None else out
        for a in node[1]:
            self.own_types(a, out)
        if not node[1] and not self.known(node[0]) and not (len(node[0]) == 1 and node[0].isupper()):
            out.append(node[0])
        return out

    def define(self, name, fields, where):
        old = self.named.get(name)
        if old is None:
            self.named[name] = fields
        elif [f["name"] for f in old] != [f["name"] for f in fields]:
            self.issue(where, "%s is described twice with different fields; the first table is used" % name)

    # ---- building OpenAPI

    def resolve(self, node, env, where):
        name, args = node
        if name in env:
            return env[name]
        if name in VOID:
            return None
        if name in ANY:
            return {}
        if name in JAVA:
            kind, fmt = JAVA[name]
            return dict({"type": kind}, **({"format": fmt} if fmt else {}))
        if name in DATETIME or name in DATE_ONLY:
            return time_schema(self.time_fmt, name in DATE_ONLY)
        inner = [self.resolve(a, env, where) for a in args]
        if name in LISTS:
            return {"type": "array", "items": inner[0] if inner and inner[0] is not None else {}}
        if name in MAPS:
            return {"type": "object", "additionalProperties": inner[-1] if inner and inner[-1] is not None else {}}
        if name in self.generic:
            params, fields = self.generic[name]
            return self.object_schema(fields, dict(zip(params, inner)), where)
        if args:  # a wrapper the doc never described: assume the usual shape, and say so
            page = "Page" in name
            if name not in self.fallback:
                self.fallback.add(name)
                self.issue(where, "%s<T> is not described; exported as %s. Add a table '\u7ed3\u6784 `%s<T>`\uff1a' with the "
                                  "real field names" % (name, "total/records" if page else "code/message/data", name))
            item = inner[-1] if inner[-1] is not None else {"type": "object", "nullable": True}
            if page:
                return {"type": "object", "properties": {"total": {"type": "integer", "format": "int64"},
                                                         "records": {"type": "array", "items": item}}}
            return {"type": "object", "properties": {"code": {"type": "integer", "format": "int32"},
                                                     "message": {"type": "string"}, "data": item}}
        if name in self.named:
            return {"$ref": "#/components/schemas/" + name}
        if len(name) == 1 and name.isupper():
            return {}
        self.issue(where, "class %s has no field table: add one after the line that returns it, or as '\u7ed3\u6784 `%s`\uff1a'. "
                          "If the class already exists, copy its fields from the code" % (name, name))
        return {"type": "object"}

    def field_schema(self, f, env, where):
        node = java_type(f["type"])
        where = "%s, %s" % (self.where(where) if isinstance(where, dict) else where, f["name"])
        if node is None:
            self.issue(where, "cannot read the type '%s'" % f["type"])
            s = {"type": "string"}
        elif (not node[1] and node[0] not in env and node[0] not in self.named and not self.known(node[0])
              and (str_enum(f["rule"]) or str_enum(enum_text(f["desc"])))):
            s = {"type": "string"}  # a Java enum, serialized by name
        else:
            s = self.resolve(node, env, where)
            s = {"type": "object", "nullable": True} if s is None else dict(s)
        d = describe(f)
        if "$ref" in s:
            return {"allOf": [s], "description": d} if d else s
        self.cur_where = where.rsplit(", ", 1)[0]
        self.constrain(s, f, node)
        if re.search(r"\u4e3a\u7a7a|\u7a7a\u8868\u793a|\u53ef\u4e3a\u7a7a|\u53ef\u7a7a|\bnull\b", f["desc"], re.I) and "properties" not in s:
            s["nullable"] = True
        if d:
            s["description"] = d
        return s

    def constrain(self, s, f, node):
        """Validation rules written in the doc -> JSON Schema keywords."""
        rule, desc, kind = f["rule"], f["desc"], s.get("type")
        for m in re.finditer(r"@(\w+)\s*(?:\(([^)]*)\))?", rule):
            ann, args = m.group(1), annotation_args(m.group(2) or "")
            v = args.get("value")
            if ann in ("NotBlank", "NotEmpty") and kind == "string":
                s["minLength"] = max(1, s.get("minLength", 0))
            elif ann == "NotEmpty" and kind == "array":
                s["minItems"] = 1
            elif ann in ("Size", "Length"):
                key = ("minItems", "maxItems") if kind == "array" else ("minLength", "maxLength")
                for a, k in (("min", key[0]), ("max", key[1])):
                    if args.get(a) is not None:
                        s[k] = int(float(args[a]))
            elif ann in ("Min", "DecimalMin", "Max", "DecimalMax") and v is not None and kind in ("integer", "number"):
                low = "Min" in ann
                s["minimum" if low else "maximum"] = number(v, kind)
                if args.get("inclusive") == "false":
                    s["exclusiveMinimum" if low else "exclusiveMaximum"] = True
            elif ann in ("Positive", "PositiveOrZero"):
                s["minimum"] = 0
                if ann == "Positive":
                    s["exclusiveMinimum"] = True
            elif ann == "Pattern" and args.get("regexp"):
                s["pattern"] = args["regexp"].replace("\\\\", "\\")
            elif ann == "Email":
                s["format"] = "email"
            elif ann == "Digits" and args.get("fraction") is not None and kind == "number":
                s["multipleOf"] = 10 ** -int(args["fraction"])
        fm = TIME_FMT.search(rule) or TIME_FMT.search(desc)
        if kind == "string" and fm:
            s.pop("format", None)
            s.update(time_schema(fm.group(0), node is not None and node[0] in DATE_ONLY))
        if kind in ("integer", "number", "string") and "pattern" not in s:
            m = RANGE.search(rule)
            if m and kind == "string":
                s.setdefault("minLength", int(float(m.group(1))))
                s.setdefault("maxLength", int(float(m.group(2))))
            elif m:
                s.setdefault("minimum", number(m.group(1), kind))
                s.setdefault("maximum", number(m.group(2), kind))
            for rx, k, strict in ((r"(?:\u2265|>=|\u4e0d\u5c0f\u4e8e)\s*(" + NUM + ")", "minimum", None),
                                  (r"(?:\u2264|<=|\u4e0d\u5927\u4e8e)\s*(" + NUM + ")", "maximum", None),
                                  (r"(?:(?<![<>=])>(?!=)|\uff1e|\u5927\u4e8e)\s*(" + NUM + ")", "minimum", "exclusiveMinimum"),
                                  (r"(?:(?<![<>=])<(?!=)|\uff1c|\u5c0f\u4e8e)\s*(" + NUM + ")", "maximum", "exclusiveMaximum")):
                m = re.search(rx, rule)
                if m and kind != "string" and k not in s:
                    s[k] = number(m.group(1), kind)
                    if strict:
                        s[strict] = True
            m = re.search(r"(\d)\s*\u4f4d\u5c0f\u6570", rule)
            if m and kind == "number":
                s.setdefault("multipleOf", 10 ** -int(m.group(1)))
        if (kind == "string" and "pattern" not in s and not s.get("format") and node is not None
                and node[0] in JAVA and re.search(r"(Time|Date|At)$", f["name"])):
            self.issue(self.cur_where, "%s looks like a time: write its format in \u6821\u9a8c (e.g. `yyyy-MM-dd HH:mm:ss`) "
                                       "or type it LocalDateTime" % f["name"])
        m = re.search(r"\u2208\s*[{\uff5b\[]([^}\uff5d\]]+)[}\uff5d\]]", rule)  # set notation: the element-of sign followed by {03,02}
        if m and kind in ("integer", "string") and "enum" not in s:
            vals = [v.strip().strip("'\"`") for v in re.split(r"[,\uff0c\u3001/|]", m.group(1)) if v.strip()]
            if kind == "integer" and all(re.fullmatch(r"-?\d+", v) for v in vals):
                vals = [int(v) for v in vals]
            if kind == "string" or all(isinstance(v, int) for v in vals):
                s["enum"] = vals
        if kind in ("integer", "string") and "enum" not in s:
            for text in (rule, enum_text(desc)):
                e = (int_enum if kind == "integer" else str_enum)(text) if text else None
                if e:
                    s["enum"] = [v for v, _ in e]
                    if any(label for _, label in e):
                        s["x-apifox-enum"] = [{"value": v, "name": "", "description": label} for v, label in e]
                    break
        m = None if f["default"] else re.search(r"\u9ed8\u8ba4(?:\u503c)?(?:\u4e3a)?\s*[\uff1a:]?\s*([^\s\uff0c,\uff1b;\u3002\u3001\uff08\uff09()]+)", rule + "\uff1b" + desc)
        dv = f["default"] or (m.group(1) if m else "")
        if dv and coerce(dv, s) is not None:
            s["default"] = coerce(dv, s)
        ex = coerce(f["example"], s) if f["example"] else None
        ex = sample(s, f) if ex is None else ex
        if ex is not None and "example" not in s:
            s["example"] = ex

    def object_schema(self, fields, env, where):
        props, req = {}, []
        for f in fields:
            if not re.fullmatch(r"[A-Za-z_$][\w$-]*", f["name"]):
                self.issue(where, "field '%s': describe a nested object with its own '\u7ed3\u6784 `Xxx`\uff1a' table" % f["name"])
                continue
            props[f["name"]] = self.field_schema(f, env, where)
            if f["required"].strip().strip("*").lower() in YES:
                req.append(f["name"])
        return dict({"type": "object", "properties": props}, **({"required": req} if req else {}))

    def payload(self, slot, api):
        typ, fields, _ = slot
        if typ:
            node = java_type(typ)
            if node is None:
                self.issue(api, "cannot read the type `%s`" % typ)
                return {"type": "object"}
            return self.resolve(node, {}, api)
        if fields:
            self.issue(api, "add the class name, e.g. '\u8bf7\u6c42\u4f53 `XxxDTO`\uff1a'")
            return self.object_schema(fields, {}, api)
        self.issue(api, "the \u8bf7\u6c42\u4f53/\u54cd\u5e94 line has neither a class name nor a table")
        return None

    def operation(self, a):
        row = self.listed.get((a["method"], a["path"]), {})
        caller = (row.get("\u8c03\u7528\u65b9") or "").strip("* ")
        params = []
        for where_in, f in a["params"]:
            s = self.field_schema(f, {}, a)
            p = {"name": f["name"], "in": where_in, "schema": s,
                 "required": where_in == "path" or f["required"].strip().strip("*").lower() in YES}
            if s.get("description"):
                p["description"] = s.pop("description")
            params.append(p)
        given = {p["name"] for p in params if p["in"] == "path"}
        for var in re.findall(r"\{(\w+)\}", a["path"]):
            if var not in given:
                self.issue(a, "{%s} has no row in a \u8def\u5f84\u53c2\u6570 table" % var)
                params.append({"name": var, "in": "path", "required": True, "schema": {"type": "string"}})
        for var in given - set(re.findall(r"\{(\w+)\}", a["path"])):
            self.issue(a, "\u8def\u5f84\u53c2\u6570 %s is not in the path" % var)
        desc = (["\u5173\u8054\u9700\u6c42\uff1a" + row["\u5173\u8054\u9700\u6c42"]] if row.get("\u5173\u8054\u9700\u6c42") else []) + a["notes"]
        codes = sorted(set(a["codes"]))
        if codes:
            desc.append("\u9519\u8bef\u7801\uff1a\n\n" + "\n".join(("- %d %s" % (c, self.codes.get(c, ""))).rstrip() for c in codes))
        folder = "/".join(x.replace("\\", "\\\\").replace("/", "\\/") for x in (self.feature, caller) if x)
        op = {"summary": a["name"], "tags": [caller or self.feature], "x-apifox-folder": folder}
        if desc:
            op["description"] = "\n\n".join(desc)
        if params:
            op["parameters"] = params
        if a["body"]:
            s = self.payload(a["body"], a)
            if s is not None:
                own = self.own_types(java_type(a["body"][0]) or ("", [])) if a["body"][0] else []
                fields = a["body"][1] or [f for t in own for f in self.named.get(t, [])]
                upload = any("MultipartFile" in f["type"] for f in fields)
                op["requestBody"] = {"required": True, "content": {
                    "multipart/form-data" if upload else "application/json": {"schema": s}}}
                if a["body"][2]:
                    op["requestBody"]["description"] = a["body"][2]
        resp = {"description": "\u6210\u529f"}
        said = " ".join(a["notes"] + ([a["resp"][2]] if a["resp"] else []))
        if a["resp"] and (a["resp"][0] or a["resp"][1]):
            s = self.payload(a["resp"], a)
            if a["resp"][2]:
                resp["description"] = a["resp"][2]
            if s is not None:
                resp["content"] = {"application/json": {"schema": s}}
        elif FILE_RESPONSE.search(said):  # an export: the response is the file
            resp = {"description": "\u6587\u4ef6\u4e0b\u8f7d", "content": {"application/octet-stream": {
                "schema": {"type": "string", "format": "binary"}}}}
        elif a["resp"] and a["resp"][2]:
            resp["description"] = a["resp"][2]
        else:
            self.issue(a, "no \u54cd\u5e94 line, e.g. '\u54cd\u5e94 `Result<Void>`\u3002'")
        op["responses"] = {"200": resp}
        return op

    def build(self):
        if not self.apis:
            self.issue("\u63a5\u53e3\u8bbe\u8ba1", "no API found: start each API with a heading like "
                                   "'#### \u521b\u5efa\u4f18\u60e0\u5238 `POST /api/v1/coupons`'")
        seen = set()
        for a in self.apis:
            key = (a["method"], a["path"])
            if key in seen:
                self.issue(a, "described twice")
            seen.add(key)
            if self.listed and key not in self.listed:
                self.issue(a, "missing from the \u63a5\u53e3\u6e05\u5355 table")
            if a["existing"]:
                continue
            for x in a["loose"]:
                self.issue(a, x)
            if not a["params"] and not a["body"] and re.search(r"\u540c\u6761\u4ef6|\u540c\u4e0a|\u53c2\u6570\u540c|\u4e0e.{0,15}(\u76f8\u540c|\u4e00\u81f4)",
                                                                    " ".join(a["notes"])):
                self.issue(a, "its parameters are only referred to ('\u540c\u6761\u4ef6'/'\u540c\u4e0a'); repeat them in a table")
        for (m, p), row in self.listed.items():
            if (m, p) not in seen and self.listed_status(row) != "existing":
                self.issue("%s %s" % (m.upper(), p), "listed in \u63a5\u53e3\u6e05\u5355 but not described in \u63a5\u53e3\u8be6\u60c5")
        schemas = {name: self.object_schema(fields, {}, name) for name, fields in list(self.named.items())}
        paths, tags = {}, []
        for a in self.apis:
            if a["existing"]:
                continue
            op = self.operation(a)
            paths.setdefault(a["path"], {})[a["method"]] = op
            tags += [t for t in op["tags"] if t not in tags]
        intro = ["\u7531\u8be6\u7ec6\u8bbe\u8ba1\u300a%s\u300b\u7684\u201c\u63a5\u53e3\u8bbe\u8ba1\u201d\u5bfc\u51fa\u3002\u63a5\u53e3\u7ea6\u5b9a\u4ee5\u8bc4\u5ba1\u786e\u8ba4\u7684 Word \u4e3a\u51c6\uff0c\u6807\u6709\u3010\u5047\u8bbe\u3011\u3010\u5f85\u786e\u8ba4\u3011\u7684\u5185\u5bb9"
                 "\u53ef\u80fd\u968f\u8bc4\u5ba1\u7b54\u590d\u53d8\u5316\u3002" % self.stem] + self.notes
        if self.codes:
            intro.append("\u9519\u8bef\u7801\uff1a\n\n" + "\n".join(("- %d %s" % kv).rstrip() for kv in sorted(self.codes.items())))
        if self.skipped():
            intro.append("\u672a\u5bfc\u51fa\u7684\u5df2\u6709\u63a5\u53e3\uff08\u4fee\u6539\u6216\u4e0d\u53d8\u7684\u63a5\u53e3\uff0c\u8bbe\u8ba1\u91cc\u53ea\u5199\u4e86\u6539\u52a8\u90e8\u5206\uff0c\u5bfc\u5165\u4f1a\u8986\u76d6\u5de5\u5177\u91cc\u5df2\u6709\u7684\u5b8c\u6574\u5b9a\u4e49\uff0c"
                         "\u6539\u52a8\u8bf7\u5728 Apifox \u6216 Postman \u91cc\u624b\u5de5\u8865\u4e0a\uff09\uff1a\n\n" + "\n".join("- " + x for x in self.skipped()))
        doc = {"openapi": "3.0.3", "info": {"title": self.title, "version": self.version, "description": "\n\n".join(intro)},
               "tags": [{"name": t} for t in tags], "paths": paths}
        if schemas:
            doc["components"] = {"schemas": schemas}
        return doc

    def skipped(self):
        """Existing APIs (\u4fee\u6539/\u4e0d\u53d8/\u590d\u7528): described or only listed, they are not exported."""
        out = [self.where(a) for a in self.apis if a["existing"]]
        return out + ["%s %s" % (m.upper(), p) for (m, p), row in self.listed.items()
                      if self.listed_status(row) == "existing" and "%s %s" % (m.upper(), p) not in out]

    def report(self):
        n = sum(len(v) for v in self.doc["paths"].values())
        skipped = self.skipped()
        note = (", %d existing (\u4fee\u6539/\u4e0d\u53d8) not exported: %s" % (len(skipped), ", ".join(skipped))) if skipped else ""
        print("[api] %d to export%s%s" % (n, note, "" if self.issues else " -- ok"))
        for x in self.issues:
            print("  ! api " + x)


def api_export(md, stem, out_dir=None):
    """Check the API design; with out_dir, also write <stem>.openapi.json there. False when an export was
    asked for and nothing could be exported."""
    api = ApiDesign(md, stem)
    if not api.found:
        if out_dir:
            print("[api] no \u63a5\u53e3\u8bbe\u8ba1 section, nothing to export")
        return not out_dir
    api.report()
    if not out_dir:
        return True
    n = sum(len(v) for v in api.doc["paths"].values())
    if not n:
        print("  -> nothing could be exported, so no file was written. Rewrite section 2.3.2 in the table format "
              "(SKILL.md: Exporting the API contract) and export again")
        return False
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, stem + ".openapi.json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(api.doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print("wrote %s  (%d APIs, %d schemas)" % (slash(path), n, len(api.doc.get("components", {}).get("schemas", {}))))
    if api.issues:
        print("  -> the file is incomplete: fix the findings above in section 2.3.2 (SKILL.md: Exporting the API "
              "contract), convert, and export again")
    return True


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
    ap.add_argument("--openapi", action="store_true",
                    help="design docs: also write <name>.openapi.json (OpenAPI 3) from section 2.3 for Apifox or "
                         "Postman; a .docx input is read first")
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
            if args.read or (args.openapi and ext.lower() == ".docx"):
                if ext.lower() != ".docx":
                    print(f"skip {f}: --read takes .docx (.pdf \u2192 read it directly, .doc/.wps \u2192 save as .docx)")
                    failed = True
                    continue
                md_path = None
                if args.read:
                    out_dir = args.out_dir or os.path.join(tempfile.gettempdir(), "md2docx-" + re.sub(r"[^\w.-]", "_", stem))
                    md_path, images = read_docx(f, out_dir)
                    report(md_path, images)
                if args.openapi:
                    if md_path:
                        md = open(md_path, encoding="utf-8").read()
                    else:
                        with tempfile.TemporaryDirectory() as td:
                            md = open(read_docx(f, td)[0], encoding="utf-8").read()
                    if not api_export(md, stem, args.out_dir or os.path.dirname(os.path.abspath(f))):
                        failed = True
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
            design = trace_check(md)
            print(f"wrote {slash(out)}" + (f", diagrams {ok}/{n}" if n else ""))
            if (design or args.openapi) and not api_export(md, stem, out_dir if args.openapi else None):
                failed = True
    except BrokenPipeError:  # output piped into `head`; files are already written
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
