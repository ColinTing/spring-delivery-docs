#!/usr/bin/env python3
"""Scan a Spring Boot project and emit a JSON fact sheet for delivery docs.

Pure stdlib. Parses Java sources with a light structural parser (not a full
compiler), so treat the output as facts plus warnings, never as gospel.

Usage:
    python3 scan_spring.py <project_root> [--out scan.json]
"""
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

SKIP_DIRS = {".git", "target", "build", "node_modules", ".idea", ".gradle", "out", "dist"}

MAPPING_METHODS = {
    "GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT",
    "DeleteMapping": "DELETE", "PatchMapping": "PATCH", "RequestMapping": None,
}
FRAMEWORK_PARAM_TYPES = {
    "HttpServletRequest", "HttpServletResponse", "HttpSession", "Model", "ModelMap",
    "BindingResult", "Principal", "Authentication", "Locale", "ServerWebExchange",
    "Errors", "RedirectAttributes", "WebRequest", "Pageable", "Sort",
}
SIMPLE_TYPES = {
    "String", "Integer", "int", "Long", "long", "Short", "short", "Byte", "byte",
    "Double", "double", "Float", "float", "Boolean", "boolean", "Character", "char",
    "BigDecimal", "BigInteger", "Date", "LocalDate", "LocalDateTime", "LocalTime",
    "Instant", "OffsetDateTime", "ZonedDateTime", "UUID", "Object", "Void", "void",
    "MultipartFile", "Timestamp",
}
CONTAINER_TYPES = {"List", "Set", "Collection", "Map", "Optional", "ResponseEntity",
                   "Mono", "Flux", "Page", "IPage", "Iterable", "ArrayList", "HashMap",
                   "LinkedList", "HashSet", "CompletableFuture", "Callable", "DeferredResult"}
ENTITY_ANNOTATIONS = {"Entity", "Table", "TableName", "Document"}
VALIDATION_ANNOTATIONS = {"NotNull", "NotBlank", "NotEmpty", "Size", "Length", "Min", "Max",
                          "DecimalMin", "DecimalMax", "Pattern", "Email", "Positive",
                          "PositiveOrZero", "Negative", "Past", "Future", "Range", "Digits"}
REQUIRED_ANNOTATIONS = {"NotNull", "NotBlank", "NotEmpty"}


# --------------------------------------------------------------------------- lexing

def mask_source(src):
    """Replace strings, chars, comments with markers so braces inside them are inert."""
    strings, docs, comments = [], [], []
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith('"""', i):  # text block
            j = src.find('"""', i + 3)
            j = n if j < 0 else j + 3
            strings.append(src[i + 3:j - 3])
            out.append(f'"__S{len(strings) - 1}__"')
            i = j
        elif c == '"':
            j = i + 1
            buf = []
            while j < n and src[j] != '"':
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j:j + 2])
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            strings.append("".join(buf))
            out.append(f'"__S{len(strings) - 1}__"')
            i = j + 1
        elif c == "'":
            j = i + 1
            while j < n and src[j] != "'":
                j += 2 if src[j] == "\\" else 1
            out.append("'_'")
            i = j + 1
        elif src.startswith("/**", i) and not src.startswith("/**/", i):
            j = src.find("*/", i + 3)
            j = n if j < 0 else j + 2
            docs.append(clean_javadoc(src[i + 3:j - 2]))
            out.append(f" __D{len(docs) - 1}__ ")
            out.append("\n" * src.count("\n", i, j))
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(" " + "\n" * src.count("\n", i, j))
            i = j
        elif src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            comments.append(src[i + 2:j].strip())
            out.append(f" __C{len(comments) - 1}__ ")
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out), strings, docs, comments


def clean_javadoc(raw):
    lines = []
    for line in raw.splitlines():
        line = re.sub(r"^\s*\*?\s?", "", line).rstrip()
        lines.append(line)
    text = "\n".join(lines).strip()
    tags = {"param": {}, "return": None}
    body = []
    for line in text.splitlines():
        m = re.match(r"@param\s+(\w+)\s*(.*)", line)
        if m:
            tags["param"][m.group(1)] = m.group(2).strip()
            continue
        m = re.match(r"@return\s*(.*)", line)
        if m:
            tags["return"] = m.group(1).strip()
            continue
        if line.startswith("@") or re.match(r"(?i)^(created\s+(by|on|at)|author\b|date\s*[:：]|作者|创建(人|时间|日期))", line):
            continue
        body.append(line)
    desc = re.sub(r"<[^>]+>", "", "\n".join(body)).strip()
    return {"text": desc, "params": tags["param"], "return": tags["return"]}


# --------------------------------------------------------------------------- helpers

def split_top(text, sep=","):
    """Split on sep outside (), {}, <>, []."""
    parts, depth, buf = [], 0, []
    for ch in text:
        if ch in "({<[":
            depth += 1
        elif ch in ")}>]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def match_paren(text, i, open_ch="(", close_ch=")"):
    depth = 0
    for j in range(i, len(text)):
        if text[j] == open_ch:
            depth += 1
        elif text[j] == close_ch:
            depth -= 1
            if depth == 0:
                return j
    return len(text) - 1


def snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class Ctx:
    def __init__(self, strings, docs, comments):
        self.strings, self.docs, self.comments = strings, docs, comments

    def restore(self, s):
        return re.sub(r'"__S(\d+)__"', lambda m: '"' + self.strings[int(m.group(1))] + '"', s)

    def literal_values(self, s):
        return [self.strings[int(x)] for x in re.findall(r'"__S(\d+)__"', s)]


def parse_annotation_args(args, ctx):
    """Return dict name -> raw expression; positional value stored as 'value'."""
    args = args.strip()
    if not args:
        return {}
    parts = split_top(args)
    res = {}
    for p in parts:
        m = re.match(r"^(\w+)\s*=\s*(.*)$", p, re.S)
        if m:
            res[m.group(1)] = m.group(2).strip()
        else:
            res["value"] = p
    return res


def ann_str(ann, *keys, ctx=None):
    """First string literal for any of keys."""
    for k in keys:
        if k in ann["args"]:
            vals = ctx.literal_values(ann["args"][k])
            if vals:
                return vals[0]
    return None


def ann_strs(ann, *keys, ctx=None):
    for k in keys:
        if k in ann["args"]:
            vals = ctx.literal_values(ann["args"][k])
            if vals:
                return vals
    return []


def ann_raw(ann, key):
    return ann["args"].get(key)


def strip_header(head, ctx):
    """Pull markers + annotations off a declaration head.

    Returns (decl_text, annotations, doc, comments_before, comments_first_line).
    """
    first_nl = head.find("\n")
    first_line = head if first_nl < 0 else head[:first_nl]
    first_line_comments = [ctx.comments[int(x)] for x in re.findall(r"__C(\d+)__", first_line)] \
        if not re.sub(r"__C\d+__", "", first_line).strip() else []
    rest = head if not first_line_comments else head[first_nl + 1:] if first_nl >= 0 else ""

    doc = None
    for x in re.findall(r"__D(\d+)__", rest):
        doc = ctx.docs[int(x)]
    comments = [ctx.comments[int(x)] for x in re.findall(r"__C(\d+)__", rest)]
    rest = re.sub(r"__[DC]\d+__", " ", rest)

    anns = []
    out = []
    i = 0
    while i < len(rest):
        if rest[i] == "@" and not rest.startswith("@interface", i):
            m = re.match(r"@([\w.]+)\s*", rest[i:])
            if not m:
                out.append(rest[i])
                i += 1
                continue
            name = m.group(1).split(".")[-1]
            j = i + m.end()
            args = ""
            if j < len(rest) and rest[j] == "(":
                k = match_paren(rest, j)
                args = rest[j + 1:k]
                j = k + 1
            anns.append({"name": name, "args": parse_annotation_args(args, ctx), "raw": args})
            i = j
        elif rest[i] == "(":  # parameter lists keep their own annotations
            k = match_paren(rest, i)
            out.append(rest[i:k + 1])
            i = k + 1
        else:
            out.append(rest[i])
            i += 1
    decl = re.sub(r"\s+", " ", "".join(out)).strip()
    return decl, anns, doc, comments, first_line_comments


def ann_map(anns):
    return {a["name"]: a for a in anns}


def schema_desc(amap, ctx):
    for name, keys in (("Schema", ("description", "title")), ("ApiModelProperty", ("value", "notes")),
                       ("ApiModel", ("description", "value")), ("Parameter", ("description",)),
                       ("ApiParam", ("value",)), ("Comment", ("value",)),
                       ("Tag", ("name", "description")), ("Api", ("tags", "value"))):
        if name in amap:
            v = ann_str(amap[name], *keys, ctx=ctx)
            if v:
                return v
    return None


def type_names(t):
    """All simple type identifiers inside a generic type expression."""
    return [x for x in re.findall(r"[A-Za-z_][\w]*", t or "") if x not in ("extends", "super")]


# --------------------------------------------------------------------------- parser

class JavaFile:
    def __init__(self, path, src):
        self.path = path
        code, strings, docs, comments = mask_source(src)
        self.ctx = Ctx(strings, docs, comments)
        self.code = code
        m = re.search(r"^\s*package\s+([\w.]+)\s*;", code, re.M)
        self.package = m.group(1) if m else ""
        self.classes = []
        self._pos = 0
        self._parse_members(0, None)

    def _match_brace(self, i):
        return match_paren(self.code, i, "{", "}")

    def _parse_members(self, i, owner):
        code = self.code
        n = len(code)
        start = i
        paren = 0
        while i < n:
            c = code[i]
            if c == "(":
                paren += 1
            elif c == ")":
                paren -= 1
            elif paren == 0 and c == ";":
                self._stmt(code[start:i], owner, block=False)
                start = i + 1
            elif paren == 0 and c == "{":
                head = code[start:i]
                bare = re.sub(r"__[DC]\d+__", " ", head)
                bare_noann = re.sub(r"@[\w.]+\s*(\([^()]*(\([^()]*\)[^()]*)*\))?", " ", bare)
                cm = re.search(r"\b(class|interface|enum|record)\s+(\w+)", bare_noann)
                if cm and "=" not in bare_noann.split(cm.group(0))[0] and "new " not in bare_noann:
                    cls = self._new_class(head, owner)
                    i = self._parse_members(i + 1, cls)
                    start = i + 1
                elif "=" in re.sub(r"\([^()]*\)", "", bare_noann) or re.search(r"\bnew\s", bare_noann):
                    i = self._match_brace(i)  # initializer, keep accumulating until ';'
                elif owner is not None and owner["kind"] == "enum" and not owner.get("_consts_done"):
                    # enum constant with body: treat as constants chunk
                    i = self._match_brace(i)
                else:
                    self._stmt(head, owner, block=True)
                    i = self._match_brace(i)
                    start = i + 1
            elif paren == 0 and c == "}":
                tail = code[start:i]
                if owner is not None and owner["kind"] == "enum" and not owner.get("_consts_done"):
                    self._stmt(tail, owner, block=False)
                elif owner is not None:
                    _, _, _, _, flc = strip_header(tail, self.ctx)
                    self._attach_trailing(owner, flc)
                return i
            i += 1
        return i

    def _attach_trailing(self, owner, comments):
        if comments and owner and owner.get("_last_field") is not None:
            f = owner["_last_field"]
            if not f.get("description"):
                f["description"] = " ".join(comments)

    def _new_class(self, head, owner):
        decl, anns, doc, comments, flc = strip_header(head, self.ctx)
        if owner is not None:
            self._attach_trailing(owner, flc)
        m = re.search(r"\b(class|interface|enum|record)\s+(\w+)\s*(<[^{]*?>)?", decl)
        kind, name = m.group(1), m.group(2)
        ext = re.search(r"\bextends\s+([\w.<>, ?]+?)(\s+implements\b|$)", decl)
        impl = re.search(r"\bimplements\s+([\w.<>, ?]+)$", decl)
        amap = ann_map(anns)
        cls = {
            "name": name, "kind": kind, "package": self.package,
            "file": self.path, "annotations": [a["name"] for a in anns], "_anns": amap,
            "doc": doc["text"] if doc else (" ".join(comments) or None),
            "description": schema_desc(amap, self.ctx),
            "extends": ext.group(1).strip() if ext and kind != "interface" else None,
            "interfaces": split_top(impl.group(1)) if impl else
            (split_top(ext.group(1)) if ext and kind == "interface" else []),
            "fields": [], "methods": [], "enum_constants": [], "outer": owner["name"] if owner else None,
            "_last_field": None,
        }
        if kind == "record":
            rm = re.search(r"\brecord\s+\w+\s*(<[^>]*>)?\s*\(", decl)
            if rm:
                k = match_paren(decl, rm.end() - 1)
                for p in split_top(decl[rm.end():k]):
                    f = self._field_from_text(p, [], None, [])
                    if f:
                        cls["fields"].append(f)
        self.classes.append(cls)
        return cls

    def _stmt(self, head, owner, block):
        if owner is None or not head.strip():
            return
        decl, anns, doc, comments, flc = strip_header(head, self.ctx)
        self._attach_trailing(owner, flc)
        if not decl:
            return
        if owner["kind"] == "enum" and not owner.get("_consts_done"):
            owner["_consts_done"] = True
            if "(" not in decl.split(",")[0] or re.match(r"^[A-Z_][A-Z0-9_]*\s*\(", decl):
                for part in split_top(decl):
                    m = re.match(r"^([A-Za-z_]\w*)\s*(\((.*)\))?", part, re.S)
                    if m:
                        args = [self.ctx.restore(a) for a in split_top(m.group(3) or "")]
                        owner["enum_constants"].append({"name": m.group(1), "args": args})
                return
        if decl.startswith(("static", "{")) and decl.strip() == "static":
            return
        top = re.sub(r"<[^<>]*(<[^<>]*>[^<>]*)*>", "", decl)  # drop generics for detection
        if "(" in top and "=" not in top.split("(")[0]:
            self._method(decl, anns, doc, comments, owner)
        else:
            f = self._field_from_text(decl, anns, doc, comments)
            if f:
                owner["fields"].append(f)
                owner["_last_field"] = f

    def _field_from_text(self, decl, anns, doc, comments):
        mods = set()
        d = decl
        if not anns:
            d2, anns, doc2, comments2, _ = strip_header(d, self.ctx)
            d, doc, comments = d2, doc or doc2, comments or comments2
        d = d.split("=")[0].strip()
        while True:
            m = re.match(r"^(public|private|protected|static|final|transient|volatile)\s+", d)
            if not m:
                break
            mods.add(m.group(1))
            d = d[m.end():]
        m = re.match(r"^(.+?)\s+(\w+)\s*(\[\])?$", d.strip())
        if not m or "static" in mods:
            return None
        amap = ann_map(anns)
        ctx = self.ctx
        desc = schema_desc(amap, ctx) or (doc["text"] if doc else None) or (" ".join(comments) or None)
        constraints = []
        for a in anns:
            if a["name"] in VALIDATION_ANNOTATIONS:
                raw = ctx.restore(a["raw"]).strip()
                constraints.append(f"@{a['name']}" + (f"({raw})" if raw else ""))
        required = any(a["name"] in REQUIRED_ANNOTATIONS for a in anns)
        if "Schema" in amap and re.search(r"required\s*=\s*true|requiredMode\s*=\s*\S*REQUIRED", amap["Schema"]["raw"]):
            required = True
        if "ApiModelProperty" in amap and "required" in amap["ApiModelProperty"]["args"] and \
                amap["ApiModelProperty"]["args"]["required"].strip() == "true":
            required = True
        field = {
            "name": m.group(2), "type": m.group(1).strip() + (m.group(3) or ""),
            "description": desc, "required": required, "constraints": constraints,
        }
        if "JsonProperty" in amap:
            jn = ann_str(amap["JsonProperty"], "value", ctx=ctx)
            if jn:
                field["json_name"] = jn
        if "JsonIgnore" in amap:
            field["json_ignored"] = True
        if "JsonFormat" in amap:
            p = ann_str(amap["JsonFormat"], "pattern", ctx=ctx)
            if p:
                field["format"] = p
        ex = None
        if "Schema" in amap:
            ex = ann_str(amap["Schema"], "example", ctx=ctx)
        if "ApiModelProperty" in amap:
            ex = ex or ann_str(amap["ApiModelProperty"], "example", ctx=ctx)
        if ex:
            field["example"] = ex
        # persistence hints
        col = {}
        if "TableId" in amap or "Id" in amap:
            col["primary_key"] = True
            if "TableId" in amap:
                col["column"] = ann_str(amap["TableId"], "value", ctx=ctx)
                t = ann_raw(amap["TableId"], "type")
                if t:
                    col["id_type"] = t.split(".")[-1]
        if "GeneratedValue" in amap:
            col["generated"] = (ann_raw(amap["GeneratedValue"], "strategy") or "AUTO").split(".")[-1]
        if "TableField" in amap:
            tf = amap["TableField"]
            col["column"] = col.get("column") or ann_str(tf, "value", ctx=ctx)
            if (ann_raw(tf, "exist") or "").strip() == "false":
                col["not_a_column"] = True
            fill = ann_raw(tf, "fill")
            if fill:
                col["auto_fill"] = fill.split(".")[-1]
        if "Column" in amap:
            c = amap["Column"]
            col["column"] = ann_str(c, "name", ctx=ctx) or col.get("column")
            for k in ("length", "nullable", "unique", "precision", "scale", "columnDefinition"):
                if k in c["args"]:
                    col[k] = ctx.restore(c["args"][k]).strip('"')
        if "TableLogic" in amap:
            col["logic_delete"] = True
        if "Version" in amap:
            col["optimistic_lock"] = True
        if "Transient" in amap or "transient" in mods:
            col["not_a_column"] = True
        for rel in ("ManyToOne", "OneToMany", "OneToOne", "ManyToMany", "JoinColumn"):
            if rel in amap:
                col.setdefault("relations", []).append(rel)
                if rel == "JoinColumn":
                    col["column"] = ann_str(amap[rel], "name", ctx=ctx) or col.get("column")
        if col:
            field["persistence"] = col
        return field

    def _method(self, decl, anns, doc, comments, owner):
        k = decl.find("(")
        before = decl[:k].strip()
        end = match_paren(decl, k)
        params_txt = decl[k + 1:end]
        before = re.sub(r"^((public|private|protected|static|final|abstract|synchronized|default|native)\s+)+", "", before)
        before = re.sub(r"^<[^>]*>\s*", "", before)  # method type params
        m = re.match(r"^(.*?)\s*\b(\w+)$", before)
        if not m:
            return
        ret, name = m.group(1).strip(), m.group(2)
        params = []
        for p in split_top(params_txt):
            pd, pa, _, _, _ = strip_header(p, self.ctx)
            pd = re.sub(r"^final\s+", "", pd)
            pm = re.match(r"^(.+?)\s+(\w+)$", pd)
            if pm:
                params.append({"type": pm.group(1).strip(), "name": pm.group(2), "_anns": ann_map(pa)})
        owner["methods"].append({
            "name": name, "return_type": ret or None, "params": params, "_anns": ann_map(anns),
            "annotations": [a["name"] for a in anns],
            "doc": doc, "comments": comments,
        })


# --------------------------------------------------------------------------- endpoints

def mapping_info(amap, ctx):
    for ann_name, http in MAPPING_METHODS.items():
        if ann_name in amap:
            a = amap[ann_name]
            paths = ann_strs(a, "value", "path", ctx=ctx) or [""]
            methods = [http] if http else []
            if not http:
                raw = a["args"].get("method", "")
                methods = re.findall(r"(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)", raw) or ["ANY"]
            return methods, paths, a
    return None


def join_path(base, sub):
    p = "/" + "/".join(x.strip("/") for x in (base, sub) if x and x.strip("/"))
    return p if p != "" else "/"


def build_endpoints(classes, ctxs, warnings):
    endpoints = []
    for cls in classes:
        amap = cls["_anns"]
        is_rest = "RestController" in amap
        is_ctrl = "Controller" in amap
        if not (is_rest or is_ctrl):
            continue
        ctx = ctxs[cls["file"]]
        base_paths = [""]
        if "RequestMapping" in amap:
            base_paths = ann_strs(amap["RequestMapping"], "value", "path", ctx=ctx) or [""]
        tag = None
        if "Tag" in amap:
            tag = ann_str(amap["Tag"], "name", ctx=ctx)
        if "Api" in amap:
            tag = tag or (ann_strs(amap["Api"], "tags", "value", ctx=ctx) or [None])[0]
        tag = tag or (cls["doc"].splitlines()[0] if cls["doc"] else None)
        class_body = "ResponseBody" in amap or is_rest
        for m in cls["methods"]:
            mi = mapping_info(m["_anns"], ctx)
            if not mi:
                continue
            http_methods, sub_paths, _ = mi
            ma = m["_anns"]
            summary = None
            detail = None
            if "Operation" in ma:
                summary = ann_str(ma["Operation"], "summary", ctx=ctx)
                detail = ann_str(ma["Operation"], "description", ctx=ctx)
            if "ApiOperation" in ma:
                summary = summary or ann_str(ma["ApiOperation"], "value", ctx=ctx)
                detail = detail or ann_str(ma["ApiOperation"], "notes", ctx=ctx)
            doc = m["doc"] or {"text": "", "params": {}, "return": None}
            if not summary and doc["text"]:
                summary = doc["text"].splitlines()[0].rstrip("。.")
                rest = "\n".join(doc["text"].splitlines()[1:]).strip()
                detail = detail or (rest or None)
            if not summary and m["comments"]:
                summary = " ".join(m["comments"])
            params = []
            for p in m["params"]:
                pa = p["_anns"]
                base_t = re.sub(r"<.*", "", p["type"]).split(".")[-1]
                if base_t in FRAMEWORK_PARAM_TYPES and not pa:
                    continue
                entry = {"name": p["name"], "type": p["type"], "required": True,
                         "description": doc["params"].get(p["name"])}
                for pn, keys in (("Parameter", ("description",)), ("ApiParam", ("value",))):
                    if pn in pa:
                        entry["description"] = ann_str(pa[pn], *keys, ctx=ctx) or entry["description"]
                if "RequestBody" in pa:
                    entry["in"] = "body"
                    entry["required"] = (pa["RequestBody"]["args"].get("required", "true").strip() != "false")
                elif "PathVariable" in pa:
                    entry["in"] = "path"
                    entry["name"] = ann_str(pa["PathVariable"], "value", "name", ctx=ctx) or p["name"]
                    entry["required"] = pa["PathVariable"]["args"].get("required", "true").strip() != "false"
                elif "RequestParam" in pa or "RequestPart" in pa:
                    a = pa.get("RequestParam") or pa.get("RequestPart")
                    entry["in"] = "query" if "RequestParam" in pa else "form"
                    entry["name"] = ann_str(a, "value", "name", ctx=ctx) or p["name"]
                    dv = ann_str(a, "defaultValue", ctx=ctx)
                    req = a["args"].get("required", "true").strip() != "false"
                    if dv is not None:
                        entry["default"] = dv
                        req = False
                    entry["required"] = req
                    if base_t == "MultipartFile":
                        entry["in"] = "form"
                elif "RequestHeader" in pa:
                    entry["in"] = "header"
                    entry["name"] = ann_str(pa["RequestHeader"], "value", "name", ctx=ctx) or p["name"]
                    entry["required"] = pa["RequestHeader"]["args"].get("required", "true").strip() != "false"
                elif "CookieValue" in pa:
                    entry["in"] = "cookie"
                elif base_t in SIMPLE_TYPES:
                    entry["in"] = "form" if base_t == "MultipartFile" else "query"
                    entry["required"] = False
                    entry["note"] = "no annotation: Spring binds it as optional query/form param"
                elif base_t in FRAMEWORK_PARAM_TYPES:
                    continue
                else:
                    entry["in"] = "query-object"
                    entry["required"] = False
                    entry["note"] = "object without @RequestBody: fields bind as query/form params"
                validated = any(x in pa for x in ("Valid", "Validated"))
                if validated:
                    entry["validated"] = True
                params.append(entry)
            ret = m["return_type"]
            for hm in http_methods:
                for bp in base_paths:
                    for sp in sub_paths:
                        ep = {
                            "module": cls.get("module"), "method": hm, "path": join_path(bp, sp),
                            "controller": cls["name"], "handler": m["name"], "file": cls["file"],
                            "tag": tag, "summary": summary, "detail": detail,
                            "params": params, "return_type": ret,
                            "return_doc": doc.get("return"),
                            "deprecated": "Deprecated" in ma,
                            "response_body": class_body or "ResponseBody" in ma,
                        }
                        if not summary:
                            warnings.append(f"no description: {hm} {ep['path']} ({cls['name']}.{m['name']})")
                        endpoints.append(ep)
    endpoints.sort(key=lambda e: (e["module"] or "", e["tag"] or "", e["path"], e["method"]))
    return endpoints


def build_feign(classes, ctxs):
    out = []
    for cls in classes:
        if "FeignClient" not in cls["_anns"]:
            continue
        ctx = ctxs[cls["file"]]
        a = cls["_anns"]["FeignClient"]
        info = {"name": cls["name"], "module": cls.get("module"), "file": cls["file"],
                "service": ann_str(a, "value", "name", ctx=ctx),
                "url": ann_str(a, "url", ctx=ctx),
                "calls": []}
        for m in cls["methods"]:
            mi = mapping_info(m["_anns"], ctx)
            if mi:
                info["calls"].append({"method": mi[0][0], "path": mi[1][0], "handler": m["name"],
                                      "description": (m["doc"] or {}).get("text") or None})
        out.append(info)
    return out


# --------------------------------------------------------------------------- models & tables

def public_class(c):
    return {k: v for k, v in c.items() if not k.startswith("_") and k != "methods"}


def collect_models(endpoints, by_name):
    seen, queue = set(), []
    for ep in endpoints:
        names = type_names(ep["return_type"])
        for p in ep["params"]:
            names += type_names(p["type"])
        queue += names
    while queue:
        n = queue.pop()
        if n in seen or n not in by_name:
            continue
        seen.add(n)
        c = by_name[n]
        if c["extends"]:
            queue += type_names(c["extends"])
        for f in c["fields"]:
            queue += type_names(f["type"])
    return sorted(seen)


def build_tables(classes, ctxs, by_name):
    tables = []
    for cls in classes:
        amap = cls["_anns"]
        if not (set(amap) & ENTITY_ANNOTATIONS):
            continue
        ctx = ctxs[cls["file"]]
        tname = None
        for an, keys in (("TableName", ("value",)), ("Table", ("name", "value")), ("Document", ("collection", "value"))):
            if an in amap:
                tname = ann_str(amap[an], *keys, ctx=ctx) or tname
        auto = tname is None
        tname = tname or snake(cls["name"])
        # walk inheritance for BaseEntity-style parents
        fields, chain, cur = [], [], cls
        while cur is not None:
            chain.append(cur)
            parent = type_names(cur["extends"])[0] if cur["extends"] else None
            cur = by_name.get(parent) if parent and parent not in ("Model",) else None
        for c in chain:  # own fields first, then BaseEntity-style parents
            fields += c["fields"]
        cols = []
        for f in fields:
            p = f.get("persistence", {})
            if p.get("not_a_column"):
                continue
            cols.append({
                "field": f["name"], "column": p.get("column") or snake(f["name"]),
                "java_type": f["type"], "description": f["description"],
                "primary_key": bool(p.get("primary_key")) or (f["name"] == "id" and "TableName" in amap),
                **{k: v for k, v in p.items() if k not in ("column", "primary_key")},
            })
        tables.append({"table": tname, "table_name_inferred": auto, "entity": cls["name"], "module": cls.get("module"),
                       "store": "document (MongoDB/Elasticsearch)" if "Document" in amap else "sql",
                       "file": cls["file"], "description": cls["description"] or cls["doc"],
                       "columns": cols})
    tables.sort(key=lambda t: t["table"])
    return tables


DDL_RE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(?:\w+[`\"]?\.[`\"]?)?(\w+)[`\"]?\s*\(", re.I)


def parse_sql_file(path):
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return []
    text = re.sub(r"--[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out = []
    for m in DDL_RE.finditer(text):
        start = m.end() - 1
        end = match_paren(text, start)
        body = text[start + 1:end]
        tail = text[end + 1: text.find(";", end) if text.find(";", end) > 0 else len(text)]
        tcm = re.search(r"COMMENT\s*=?\s*'((?:[^']|'')*)'", tail, re.I)
        cols, indexes, pk = [], [], []
        for part in split_top(body):
            p = part.strip()
            up = p.upper()
            if up.startswith("PRIMARY KEY"):
                pk = re.findall(r"[`\"]?(\w+)[`\"]?", p[p.find("(") + 1:p.rfind(")")])
            elif re.match(r"(UNIQUE\s+)?(KEY|INDEX)\b|UNIQUE\b|CONSTRAINT\b|FOREIGN\s+KEY|FULLTEXT|SPATIAL", up):
                indexes.append(re.sub(r"\s+", " ", p))
            else:
                cm = re.match(r"[`\"]?(\w+)[`\"]?\s+([\w]+(?:\s*\([^)]*\))?(?:\s+unsigned)?)(.*)$", p, re.I | re.S)
                if not cm:
                    continue
                rest = cm.group(3)
                com = re.search(r"COMMENT\s+'((?:[^']|'')*)'", rest, re.I)
                dv = re.search(r"DEFAULT\s+('(?:[^']|'')*'|\S+)", rest, re.I)
                col = {
                    "column": cm.group(1), "type": re.sub(r"\s+", "", cm.group(2)),
                    "nullable": not re.search(r"NOT\s+NULL", rest, re.I),
                    "default": dv.group(1) if dv else None,
                    "auto_increment": bool(re.search(r"AUTO_INCREMENT|IDENTITY|SERIAL", rest + cm.group(2), re.I)),
                    "comment": com.group(1).replace("''", "'") if com else None,
                }
                if re.search(r"PRIMARY\s+KEY", rest, re.I):
                    pk.append(col["column"])
                cols.append(col)
        for c in cols:
            c["primary_key"] = c["column"] in pk
        out.append({"table": m.group(1), "comment": tcm.group(1) if tcm else None,
                    "columns": cols, "indexes": indexes, "primary_key": pk, "file": path})
    # COMMENT ON (PostgreSQL / Oracle)
    by = {t["table"].lower(): t for t in out}
    for m in re.finditer(r"COMMENT\s+ON\s+COLUMN\s+(?:\w+\.)?(\w+)\.(\w+)\s+IS\s+'((?:[^']|'')*)'", text, re.I):
        t = by.get(m.group(1).lower())
        if t:
            for c in t["columns"]:
                if c["column"].lower() == m.group(2).lower():
                    c["comment"] = c["comment"] or m.group(3)
    for m in re.finditer(r"COMMENT\s+ON\s+TABLE\s+(?:\w+\.)?(\w+)\s+IS\s+'((?:[^']|'')*)'", text, re.I):
        t = by.get(m.group(1).lower())
        if t:
            t["comment"] = t["comment"] or m.group(2)
    return out


# --------------------------------------------------------------------------- build files

def pom_text(el, tag, ns):
    x = el.find(f"m:{tag}", ns) if ns else el.find(tag)
    return x.text.strip() if x is not None and x.text else None


def parse_pom(path):
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as e:
        return {"file": path, "error": str(e)}
    ns = {"m": root.tag[1:root.tag.index("}")]} if root.tag.startswith("{") else {}
    q = (lambda t: f"m:{t}") if ns else (lambda t: t)
    info = {"file": path, "groupId": pom_text(root, "groupId", ns), "artifactId": pom_text(root, "artifactId", ns),
            "version": pom_text(root, "version", ns), "packaging": pom_text(root, "packaging", ns) or "jar",
            "name": pom_text(root, "name", ns), "description": pom_text(root, "description", ns)}
    parent = root.find(q("parent"), ns)
    if parent is not None:
        info["parent"] = f"{pom_text(parent, 'groupId', ns)}:{pom_text(parent, 'artifactId', ns)}:{pom_text(parent, 'version', ns)}"
    props = root.find(q("properties"), ns)
    if props is not None:
        info["properties"] = {re.sub(r"^\{.*\}", "", p.tag): (p.text or "").strip() for p in props}
    mods = root.find(q("modules"), ns)
    if mods is not None:
        info["modules"] = [m.text for m in mods]
    deps = []
    dnode = root.find(q("dependencies"), ns)
    if dnode is not None:
        for d in dnode:
            g, a = pom_text(d, "groupId", ns), pom_text(d, "artifactId", ns)
            if a:
                deps.append(":".join(x for x in (g, a, pom_text(d, "version", ns)) if x)
                            + (f" ({pom_text(d, 'scope', ns)})" if pom_text(d, "scope", ns) else ""))
    info["dependencies"] = deps
    profiles = root.find(q("profiles"), ns)
    if profiles is not None:
        info["maven_profiles"] = [pom_text(p, "id", ns) for p in profiles]
    plugins = root.findall(f".//{q('plugin')}", ns)
    info["plugins"] = [pom_text(p, "artifactId", ns) for p in plugins]
    return info


MIDDLEWARE_HINTS = [
    ("MySQL", r"mysql-connector|mysql:mysql"), ("PostgreSQL", r"postgresql"), ("Oracle", r"ojdbc"),
    ("SQL Server", r"mssql-jdbc"), ("达梦 DM", r"DmJdbcDriver|dm\w*-jdbc"), ("H2", r"com\.h2database"),
    ("Redis", r"redis|redisson|jedis|lettuce"), ("RabbitMQ", r"amqp|rabbit"), ("Kafka", r"kafka"),
    ("RocketMQ", r"rocketmq"), ("Elasticsearch", r"elasticsearch"), ("MongoDB", r"mongodb"),
    ("Nacos", r"nacos"), ("Eureka", r"eureka"), ("Apollo", r"apollo-client"), ("XXL-JOB", r"xxl-job"),
    ("MinIO", r"minio"), ("阿里云 OSS", r"aliyun-sdk-oss"), ("Seata", r"seata"), ("Sentinel", r"sentinel"),
    ("Flyway", r"flyway"), ("Liquibase", r"liquibase"), ("Spring Cloud Gateway", r"spring-cloud-starter-gateway"),
    ("OpenFeign", r"openfeign"), ("Spring Security", r"spring-boot-starter-security"),
    ("Sa-Token", r"sa-token"), ("Actuator", r"actuator"), ("Knife4j/Swagger", r"knife4j|springfox|springdoc"),
    ("MyBatis-Plus", r"mybatis-plus"), ("MyBatis", r"mybatis(?!-plus)"), ("Spring Data JPA", r"data-jpa"),
]


def detect_middleware(blob):
    return [name for name, pat in MIDDLEWARE_HINTS if re.search(pat, blob, re.I)]


# --------------------------------------------------------------------------- main

def module_of(path, root):
    """Nearest ancestor dir with a build file, relative to root ('.' for single-module)."""
    d = os.path.dirname(path)
    while d.startswith(root):
        if any(os.path.exists(os.path.join(d, f)) for f in ("pom.xml", "build.gradle", "build.gradle.kts")):
            return os.path.relpath(d, root)
        if d == root:
            break
        d = os.path.dirname(d)
    return "."


def walk(root):
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")]
        for f in files:
            yield os.path.join(d, f)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root")
    ap.add_argument("--out", help="write JSON here instead of stdout")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    rel = lambda p: os.path.relpath(p, root)

    java, poms, gradles, configs, sqls, mapper_xml, deploy_files = [], [], [], [], [], [], []
    for p in walk(root):
        name = os.path.basename(p)
        rp = rel(p)
        if name.endswith(".java"):
            if "/test/" in "/" + rp.replace(os.sep, "/"):
                continue
            java.append(p)
        elif name == "pom.xml":
            poms.append(p)
        elif name in ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"):
            gradles.append(rp)
        elif re.match(r"(application|bootstrap)([-.][\w-]+)?\.(ya?ml|properties)$", name):
            configs.append(rp)
        elif name.endswith(".sql"):
            sqls.append(p)
        elif name.endswith(".xml") and "mapper" in rp.lower():
            mapper_xml.append(rp)
        elif re.match(r"(Dockerfile.*|docker-compose.*\.ya?ml|.*\.sh|Jenkinsfile|\.gitlab-ci\.yml|.*\.service|"
                      r"nginx.*\.conf|k8s.*\.ya?ml|deployment\.ya?ml)$", name):
            deploy_files.append(rp)

    classes, ctxs, parse_errors = [], {}, []
    for p in sorted(java):
        try:
            src = open(p, encoding="utf-8", errors="replace").read()
            jf = JavaFile(rel(p), src)
        except Exception as e:  # never die on one odd file
            parse_errors.append(f"{rel(p)}: {type(e).__name__}: {e}")
            continue
        ctxs[jf.path] = jf.ctx
        mod = module_of(p, root)
        for c in jf.classes:
            c["module"] = mod
        classes += jf.classes

    by_name = {}
    for c in classes:
        by_name.setdefault(c["name"], c)

    warnings = []
    endpoints = build_endpoints(classes, ctxs, warnings)
    model_names = collect_models(endpoints, by_name)
    models = {n: public_class(by_name[n]) for n in model_names}
    enums = {c["name"]: public_class(c) for c in classes if c["kind"] == "enum"}
    tables = build_tables(classes, ctxs, by_name)
    ddl = []
    for s in sorted(sqls):
        for t in parse_sql_file(s):
            t["file"] = rel(t["file"])
            ddl.append(t)

    pom_infos = [parse_pom(p) for p in sorted(poms)]
    for pi in pom_infos:
        pi["file"] = rel(pi["file"])
    blob = json.dumps(pom_infos) + " ".join(open(os.path.join(root, g), errors="replace").read() for g in gradles)
    has_main = [c["file"] for c in classes if "SpringBootApplication" in c["_anns"]]

    for t in tables:
        if not t["description"]:
            warnings.append(f"no table description: {t['table']} ({t['entity']})")
    entity_tables = {t["table"].lower() for t in tables if t["store"] == "sql"}
    ddl_tables = {t["table"].lower() for t in ddl}
    if ddl:
        for t in sorted(entity_tables - ddl_tables):
            warnings.append(f"entity table not found in any .sql DDL: {t}")
        orphan = sorted(ddl_tables - entity_tables)
        if tables and len(orphan) <= 10:
            warnings += [f"DDL table has no entity class: {t}" for t in orphan]
        elif orphan:
            warnings.append(f"{len(orphan)} DDL tables have no annotated entity class (plain MyBatis/"
                            f"generator models or external tables?), e.g. {', '.join(orphan[:5])}")

    out = {
        "project_root": root,
        "build": {"maven": pom_infos, "gradle_files": gradles,
                  "spring_boot_main": has_main, "middleware_detected": detect_middleware(blob)},
        "config_files": sorted(configs),
        "deploy_files": sorted(deploy_files),
        "sql_files": sorted(rel(s) for s in sqls),
        "mapper_xml": sorted(mapper_xml),
        "endpoints": endpoints,
        "feign_clients": build_feign(classes, ctxs),
        "models": models,
        "enums": enums,
        "entity_tables": tables,
        "ddl_tables": ddl,
        "stats": {"java_files": len(java), "classes": len(classes), "endpoints": len(endpoints),
                  "models": len(models), "entity_tables": len(tables), "ddl_tables": len(ddl)},
        "warnings": warnings,
        "parse_errors": parse_errors,
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        s = out["stats"]
        print(f"wrote {args.out}: {s['endpoints']} endpoints, {s['models']} models, "
              f"{s['entity_tables']} entity tables, {s['ddl_tables']} DDL tables, "
              f"{len(warnings)} warnings, {len(parse_errors)} parse errors")
    else:
        sys.stdout.write(text + "\n")


if __name__ == "__main__":
    main()
