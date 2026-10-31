---
name: spring-delivery-docs
description: Generate project delivery documents (交付文档) for a Java Spring / Spring Boot codebase — 接口文档 (API reference), 数据库设计文档 (DB design), 部署运维手册 (deployment & ops manual), and 版本变更说明 (release notes) — written from the actual source code, SQL and config, not from memory. Use whenever the user is in a Spring/Spring Boot project and asks for 交付文档, 接口文档, API 文档, 数据库设计说明, 数据字典, 表结构文档, 部署文档, 部署手册, 上线说明, 运维手册, 版本说明, 变更说明, release notes, handover/delivery docs, or wants to "补文档" for a client/甲方/验收 — even if they don't say "skill" or name every document. Also use for refreshing existing delivery docs after code changes.
---

# Spring 交付文档生成

Outsourced and project-based Java teams lose whole days before every 验收 hand-writing docs that drift from the code. This skill turns the code into the docs: a script extracts facts, you write documents from those facts, and a second script checks nothing was skipped or leaked.

The core rule: **every statement in a delivery doc must trace to code, SQL, config, or git history.** A client will hold the team to these docs. When a fact isn't in the source, write `【待确认】` plus a short note on what is unknown, never a plausible guess. A visible gap gets fixed; a confident fabrication becomes a dispute.

## Workflow

### 1. Scope

Work out which documents are wanted. If the user just says "交付文档" or "把文档都做了", produce the standard set:

| 文件 | 内容 | Template |
|---|---|---|
| `01-接口文档.md` | Every HTTP endpoint | `references/api-doc.md` |
| `02-数据库设计文档.md` | Tables, columns, indexes, ER | `references/db-doc.md` |
| `03-部署运维手册.md` | Environment, config, build, start, troubleshooting | `references/deploy-doc.md` |
| `04-版本变更说明.md` | Changes between two versions | `references/release-notes.md` |

Only read the templates for the docs you are actually writing. Default output dir is `docs/delivery/` in the project root unless the user names another. Write in the user's language (default 中文).

If the project has existing delivery docs, read them first. Keep the client-facing structure and wording conventions they already accepted, and update the facts.

### 2. Scan

```bash
python3 <skill_dir>/scripts/scan_spring.py <project_root> --out /tmp/spring-scan.json
```

It is stdlib-only Python 3 and handles multi-module Maven, MyBatis/MyBatis-Plus/JPA, Swagger2, springdoc and plain Javadoc. Output keys:

- `endpoints`: module (Maven/Gradle module dir), method, full path (class + method mapping, every combination), tag, summary/detail (from `@Operation`/`@ApiOperation`/Javadoc), params with `in` = path/query/body/header/form/query-object, required, default, return type
- `models`: request/response classes reachable from endpoints, with field descriptions, validation constraints, examples, and nested/generic types
- `enums`: constants with their constructor args (usually code + label, ideal for 状态码 tables)
- `entity_tables`: entity → table/column mapping, PK, logic-delete, auto-fill, optimistic lock
- `ddl_tables`: parsed `CREATE TABLE` from `.sql` files, with real column types, NOT NULL, defaults, COMMENT, indexes
- `feign_clients`: outbound calls to other services, for the third-party dependency section
- `build`, `config_files`, `deploy_files`, `sql_files`, `mapper_xml`
- `warnings`: endpoints without descriptions, entity/DDL mismatches, etc.

Read `stats` and `warnings` first. The scanner is a structural parser, not javac. If something looks wrong (zero endpoints in an obviously web project, missing fields), open the source files and trust them over the JSON. If the project uses something the scanner does not see, such as WebFlux router functions, `@Path` JAX-RS, or controllers generated at build time, read those sources directly and say so in the doc's 说明 section.

### 3. Gather what the scan doesn't cover

- **Config**: read every file in `config_files`. You need ports, context-path, profiles, datasource and middleware hosts, custom business keys.
- **Global response and error codes**: look for `@RestControllerAdvice`/`@ControllerAdvice`, error-code enums, the `Result`/`R`/`ApiResponse` wrapper, and auth filters/interceptors (which headers carry the token). These turn a list of endpoints into a usable API doc.
- **Deployment**: read `deploy_files` (Dockerfile, compose, scripts, CI) and the `pom.xml`/Gradle build plugins and profiles.
- **Release notes**: use `git log`/`git tag`. See the template.

### 4. Write

Follow the template for each doc. Points that matter in practice:

- **Write every endpoint address as `` `METHOD /path` ``** (e.g. `` `GET /api/v1/users/{id}` ``), one per combination. The verifier matches that exact form, and readers search for it.
- **Multi-module projects** (several `module` values with endpoints): each deployable module is usually a separate service with its own address. Give each module its own top-level chapter, or its own API doc file (`01-接口文档-mall-admin.md`) when there are more than ~80 endpoints. Never merge modules, because the same path can exist in two of them.
- **Large projects**: write the API doc one module or tag at a time, appending to the file, rather than composing hundreds of endpoints in one pass.
- **Request/response tables come from `models`, expanded recursively.** Show nested objects with a `└─` prefix or `parent.child` naming. Substitute generics: `Result<PageResult<UserVO>>` means show Result's fields with `data` expanded to PageResult, and `records` expanded to UserVO. The client reads the wire format, not the Java type.
- **Use the JSON name** (`json_name` from `@JsonProperty`), omit `json_ignored` fields from responses, and show `format` (e.g. date pattern).
- **Constraints → plain language**: `@Size(min = 4, max = 32)` → "长度 4–32"; `@Pattern` → give the regex and its message.
- **Examples are synthesized from types and must look it.** Use `example` values when present, otherwise realistic but obviously sample values. Never paste real data from configs or SQL inserts.
- **Enums**: when a field's type is an enum, or a description says "状态 1 启用 0 禁用", list the values. Enum constants come from `enums`.
- **DB doc**: prefer `ddl_tables` (the real types and comments) and fall back to `entity_tables`. Mark the source in the 说明. Note mismatches from `warnings` because they are real bugs the client might hit. Draw ER relationships only from FK constraints, JPA relations, or `xxx_id` columns that clearly match a table, and label inferred ones as 推断.
- **Secrets never go in docs.** Passwords, keys, tokens, AK/SK, and real production IPs/hosts: write `******` or `<由运维提供>`, and describe *where* the value is configured instead. Delivery docs get forwarded widely.
- **Deprecated endpoints** stay in the doc, marked `【已废弃】`, because clients may still call them.
- **Not exposed to the frontend** (callbacks, internal endpoints): document them in their own section with the caller named.

### 5. Verify

```bash
python3 <skill_dir>/scripts/check_docs.py /tmp/spring-scan.json <docs_dir>
```

It fails if any endpoint path or table is missing from the docs, or if any secret value from the config files appears in them. Fix and rerun until it prints PASS. It also counts `【待确认】` per file.

### 6. Hand over

Tell the user, briefly:
- which files were written, with endpoint and table counts
- the `【待确认】` items grouped by who can answer (dev, ops, product)
- code problems you noticed along the way, such as entity/DDL drift, endpoints missing descriptions, or unvalidated request bodies. These are worth fixing before 验收.

### 7. Word 版

Clients and reviewers work in Word, so **produce .docx by default** once the check passes. Skip it only if the user says Markdown is enough. Markdown stays the source: edits and the check script work on it, and the .docx is regenerated from it.

```bash
python3 <skill_dir>/scripts/md2docx.py <docs_dir>            # every .md in the dir → .docx next to it
python3 <skill_dir>/scripts/md2docx.py <docs_dir> --template 公司模板.docx   # company styles
```

It renders Mermaid diagrams to images, adds table borders and shaded, repeating header rows, keeps `<br>` line breaks, applies Chinese fonts, A4 page size, a table of contents and page numbers, and highlights 【待确认】 (red) and 【假设】 (orange). Read its output:

- `pandoc is required` / `python-docx is required`: give the user the install command it printed, and stop there. Do not hand-build a .docx some other way.
- `diagrams 0/N` or `no Mermaid renderer`: the docx is still produced with the diagram source kept. Tell the user `npm i -g @mermaid-js/mermaid-cli` fixes it. The first run may also fetch it via npx, which downloads a headless Chrome.
- If the user has a company Word template, ask for it and pass `--template`. Tables and page numbers are still applied on top.

Tell the user that Word asks to update fields when the file opens. That fills in the table of contents. Answer yes.

Never send document content to online diagram services. Design and delivery docs are confidential to the client.
