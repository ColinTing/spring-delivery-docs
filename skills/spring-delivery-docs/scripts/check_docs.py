#!/usr/bin/env python3
"""Quality gate for generated delivery docs.

Checks, against the scan JSON from scan_spring.py:
  1. every endpoint appears as "METHOD /path" in the API doc (the file whose
     name contains 接口 or api; all files if there is none)
  2. every table (entity or DDL) appears in the docs
  3. no secret value or IP address from application*/bootstrap* config leaks
     into the docs
  4. counts the 【待确认】 placeholders (incl. 【待确认：...】) per file

Usage:
    python3 check_docs.py <scan.json> <docs_dir>
Exit code 1 if coverage is incomplete or a secret leaked.
"""
import json
import os
import re
import sys

SECRET_KEY = re.compile(r"(password|passwd|pwd|secret|token|api[-_]?key|access[-_]?key|private[-_]?key|"
                        r"v3[-_]?key|credential|\bak\b|\bsk\b)", re.I)
PLACEHOLDER = "【待确认"
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
HARMLESS_IPS = {"127.0.0.1", "0.0.0.0", "255.255.255.255"}


def config_secrets(root, files):
    found = []
    for rel in files:
        try:
            lines = open(os.path.join(root, rel), encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue
        for line in lines:
            m = re.match(r"^\s*([\w.\-\[\]]+)\s*[:=]\s*(.+?)\s*$", line)
            if not m or line.lstrip().startswith("#"):
                continue
            key, val = m.group(1), m.group(2).split(" #")[0].strip().strip("'\"")
            leaf = key.split(".")[-1]
            if SECRET_KEY.search(leaf) and len(val) >= 4 and not val.startswith("${") and val not in ("true", "false"):
                found.append((rel, key, val))
            for ip in IPV4.findall(val):
                if ip not in HARMLESS_IPS:
                    found.append((rel, key + " (IP)", ip))
    return found


def utf8_output():
    # Claude Code reads piped output as UTF-8; on Chinese Windows Python would emit GBK
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main():
    utf8_output()
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    scan = json.load(open(sys.argv[1], encoding="utf-8"))
    docs_dir = sys.argv[2]
    texts = {}
    for d, _, files in os.walk(docs_dir):
        for f in files:
            if f.endswith((".md", ".markdown", ".txt", ".html")):
                p = os.path.join(d, f)
                texts[p] = open(p, encoding="utf-8", errors="replace").read()
    if not texts:
        sys.exit(f"no markdown files under {docs_dir}")
    blob = "\n".join(texts.values())

    failed = False
    api_texts = [t for p, t in texts.items() if re.search(r"接口|api", os.path.basename(p), re.I)]
    api_blob = "\n".join(api_texts) if api_texts else blob

    def documented(e):
        if e["method"] == "ANY":
            return re.search(re.escape(e["path"]) + r"(?![\w/{])", api_blob) is not None
        return re.search(re.escape(f"{e['method']} {e['path']}") + r"(?![\w/{])", api_blob) is not None

    missing = sorted({f"{e['method']} {e['path']}" for e in scan["endpoints"] if not documented(e)})
    print(f"[endpoints] {len(scan['endpoints']) - len(missing)}/{len(scan['endpoints'])} documented")
    for m in missing:
        print(f"  MISSING {m}")
        failed = True

    tables = {t["table"] for t in scan["entity_tables"]} | {t["table"] for t in scan["ddl_tables"]}
    tmissing = sorted(t for t in tables if not re.search(r"\b" + re.escape(t) + r"\b", blob, re.I))
    print(f"[tables] {len(tables) - len(tmissing)}/{len(tables)} documented")
    for t in tmissing:
        print(f"  MISSING {t}")
        failed = True

    leaks = []
    for rel, key, val in config_secrets(scan["project_root"], scan["config_files"]):
        for p, t in texts.items():
            if val in t:
                leaks.append(f"{os.path.relpath(p, docs_dir)} contains value of {key} from {rel}")
    print(f"[secrets] {'LEAKED' if leaks else 'ok'}")
    for l in leaks:
        print(f"  LEAK {l}")
        failed = True

    for p, t in sorted(texts.items()):
        n = t.count(PLACEHOLDER)
        if n:
            print(f"[todo] {os.path.relpath(p, docs_dir)}: {n} × 【待确认】")
    print("FAIL" if failed else "PASS")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
