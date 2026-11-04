#!/usr/bin/env python3
"""Consistency check for a detailed design doc, plus optional design-vs-code progress.

Doc checks (fail the run):
  - every R item has at least one AC and is referenced in the technical part
  - every referenced R/AC/Q/D id is defined (first cell of a table row)
  - no 【假设，见 Q-xx】 left for a Q already marked 已确认
Reports: open / blocking questions, assumption count.

With --scan <scan.json> (from spring-delivery-docs/scripts/scan_spring.py):
  - designed APIs / tables / columns not found in code
  - code endpoints under the designed path prefixes that the design never mentions
  These are progress information and only fail the run with --strict.

Usage:
    python3 design_check.py <design.md> [--scan scan.json] [--strict]
"""
import argparse
import json
import re
import sys

ID_KINDS = ("R", "AC", "Q", "D", "T")
ID_RE = re.compile(r"(?<![\w-])(R|AC|Q|D|T)-(\d{1,3})(?![\w])")
API_RE = re.compile(r"`(GET|POST|PUT|DELETE|PATCH)\s+(/[^`\s]*)`")
TABLE_HEAD_RE = re.compile(r"^#{2,6}\s+`(\w+)`(.*)$")
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def is_sep(line):
    return re.match(r"^\s*\|?\s*:?-{2,}", line) is not None


def norm_path(p):
    p = re.sub(r"\{[^}]*\}", "{}", p.split("?")[0])
    return p.rstrip("/") or "/"


def parse(text):
    lines = text.splitlines()
    split_at = next((i for i, l in enumerate(lines)
                     if l.startswith("#") and "技术设计" in l and not l.startswith("####")), len(lines))
    part1, part2 = "\n".join(lines[:split_at]), "\n".join(lines[split_at:])

    defined = {k: {} for k in ID_KINDS}  # id -> row cells
    in_code = False
    for line in lines:
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line.lstrip().startswith("|") or is_sep(line):
            continue
        c = cells(line)
        m = ID_RE.fullmatch(c[0].replace("*", "")) if c else None
        if m:
            defined[m.group(1)][f"{m.group(1)}-{m.group(2)}"] = c

    refs = {k: set() for k in ID_KINDS}
    for line in lines:
        c = cells(line) if line.lstrip().startswith("|") else None
        body = " | ".join(c[1:]) if c and ID_RE.fullmatch(c[0].replace("*", "")) else line
        for m in ID_RE.finditer(body):
            refs[m.group(1)].add(f"{m.group(1)}-{m.group(2)}")

    tables, cur = {}, None
    for line in part2.splitlines():
        hm = TABLE_HEAD_RE.match(line)
        if hm:
            cur = hm.group(1)
            tables[cur] = {"change": "修改" if "修改" in hm.group(2) else "新增", "columns": []}
            continue
        if line.startswith("#"):
            cur = None
            continue
        if cur and line.lstrip().startswith("|") and not is_sep(line):
            first = cells(line)[0].strip("`* ")
            if IDENT_RE.match(first) and first not in ("字段", "字段名", "列名"):
                tables[cur]["columns"].append(first)

    apis = sorted({(m.group(1), m.group(2)) for m in API_RE.finditer(part2)})
    # an API is a modification of an existing one if any line naming it says 修改
    modified = {a for a in apis for line in part2.splitlines()
                if f"`{a[0]} {a[1]}`" in line and "修改" in line}
    return part1, part2, defined, refs, tables, apis, modified


def sort_ids(ids):
    return sorted(ids, key=lambda x: (x.split("-")[0], int(x.split("-")[1])))


def utf8_output():
    # Claude Code reads piped output as UTF-8; on Chinese Windows Python would emit GBK
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main():
    utf8_output()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("design")
    ap.add_argument("--scan")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    text = open(args.design, encoding="utf-8").read()
    part1, part2, defined, refs, tables, apis, modified = parse(text)
    failed = False

    def fail(msg):
        nonlocal failed
        failed = True
        print(f"  FAIL {msg}")

    print(f"[ids] R={len(defined['R'])} AC={len(defined['AC'])} Q={len(defined['Q'])} "
          f"D={len(defined['D'])} T={len(defined['T'])}")
    if not defined["R"]:
        fail("no requirement items found (rows whose first cell is R-xx)")

    for kind in ("R", "AC", "Q", "D", "T"):
        for i in sort_ids(refs[kind] - set(defined[kind])):
            fail(f"{i} is referenced but never defined")

    ac_cover = set()
    for row in defined["AC"].values():
        ac_cover |= {f"R-{m.group(2)}" for m in ID_RE.finditer(" ".join(row[1:2])) if m.group(1) == "R"}
    tech_refs = {f"R-{m.group(2)}" for m in ID_RE.finditer(part2) if m.group(1) == "R"}
    for r in sort_ids(defined["R"]):
        if r not in ac_cover:
            fail(f"{r} has no acceptance criterion (AC row with {r} in its 2nd column)")
        if r not in tech_refs:
            fail(f"{r} is not referenced anywhere in the technical part")

    open_q, block_q, confirmed = [], [], set()
    for q, row in defined["Q"].items():
        rowtxt = " ".join(row)
        status = row[-1]
        if "已确认" in status or "已取消" in status:
            confirmed.add(q)
            continue
        open_q.append(q)
        if "阻塞" in rowtxt and "非阻塞" not in rowtxt:
            block_q.append(q)
    assumptions = re.findall(r"【假设[^】]*】", text)
    for a in assumptions:
        for m in ID_RE.finditer(a):
            q = f"{m.group(1)}-{m.group(2)}"
            if q in confirmed:
                fail(f"stale assumption for confirmed {q}: {a}")
    print(f"[questions] open {len(open_q)} (blocking {len(block_q)}: {', '.join(sort_ids(block_q)) or '-'}), "
          f"closed {len(confirmed)}")
    print(f"[assumptions] {len(assumptions)} × 【假设】")
    print(f"[design] {len(apis)} APIs, {len(tables)} tables "
          f"({sum(len(t['columns']) for t in tables.values())} columns)")
    if not apis and not tables:
        print("  WARN no `METHOD /path` APIs or #### `table` headings found in the technical part")

    if args.scan:
        scan = json.load(open(args.scan, encoding="utf-8"))
        code_eps = {(e["method"], norm_path(e["path"])) for e in scan["endpoints"]}
        code_any = {p for m, p in code_eps if m == "ANY"}
        code_tables = {}
        for t in scan.get("entity_tables", []):
            code_tables.setdefault(t["table"].lower(), set()).update(c["column"].lower() for c in t["columns"])
        for t in scan.get("ddl_tables", []):
            code_tables.setdefault(t["table"].lower(), set()).update(c["column"].lower() for c in t["columns"])

        gaps = 0
        exists = [a for a in apis if (a[0], norm_path(a[1])) in code_eps or norm_path(a[1]) in code_any]
        new_apis = [a for a in apis if a not in modified]
        done = [a for a in new_apis if a in exists]
        print(f"[progress] new APIs implemented {len(done)}/{len(new_apis)}")
        for a in new_apis:
            if a not in done:
                print(f"  TODO api {a[0]} {a[1]}")
                gaps += 1
        for a in sorted(modified):
            state = "exists, verify the change by reading the code" if a in exists else "MISSING in code"
            print(f"  MODIFY api {a[0]} {a[1]}: {state}")
            if a not in exists:
                gaps += 1
        tdone = 0
        for name, t in tables.items():
            cols = code_tables.get(name.lower())
            if cols is None:
                print(f"  TODO table {name} ({t['change']})")
                gaps += 1
                continue
            miss = [c for c in t["columns"] if c.lower() not in cols]
            if miss:
                print(f"  TODO columns {name}: {', '.join(miss)}")
                gaps += 1
            else:
                tdone += 1
        print(f"[progress] tables complete {tdone}/{len(tables)}")

        prefixes = {"/".join(norm_path(p).split("/")[:4]) for _, p in new_apis}
        designed = {(m, norm_path(p)) for m, p in apis}
        extra = sorted(e for e in code_eps if e not in designed
                       and any(e[1] == px or e[1].startswith(px + "/") for px in prefixes))
        if extra:
            print(f"[scope] {len(extra)} code endpoints under designed prefixes but not in the design:")
            for m, p in extra:
                print(f"  EXTRA {m} {p}")
        if args.strict and (gaps or extra):
            failed = True

    print("FAIL" if failed else "PASS")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
