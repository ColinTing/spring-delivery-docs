---
name: spring-detailed-design
description: Turn a business requirements document (需求文档 / PRD / 需求说明书 / 需求规格, in Word, PDF, Markdown, or pasted text) into a pre-development detailed design document (详细设计 / 详细设计说明书 / 概要设计 / 技术方案 / 开发设计) for a Java Spring project. The output has a business-confirmation part (numbered requirements, rules, flows, acceptance criteria, and a clarification question list for 需求评审 / 需求澄清 / 对齐颗粒度 with the business side) and a technical part (tables, APIs, state machines, task breakdown) that guides coding. Use when the user has a requirement doc and wants a design, wants to review/clarify requirements before coding, asks "这个需求怎么设计", "出个详细设计", "需求评审要准备什么", or wants to update a design after the business answered questions. Also use to check implementation progress against an existing design.
---

# 需求 → 详细设计

Most rework in project-based delivery comes from one gap: the business side wrote "支持优惠券", developers built their interpretation, and the mismatch surfaced at 验收. This skill closes that gap *before* coding. Every vague sentence becomes either a concrete rule the business signs off on, or a numbered question with a recommended answer.

The design document serves two readers:

- **Part 1 (业务确认)**: business owners and PMs. Plain language, no class names. They should be able to read it and say "yes, that is what we mean", or point at a numbered item and correct it.
- **Part 2 (技术设计)**: developers. Precise enough to code from without re-reading the requirement doc.

## Core rules

1. **Never invent business rules silently.** A requirement doc always leaves gaps (limits, edge cases, permissions, what happens on failure). For each gap, raise a question `Q-xx` with 2–3 options and a recommended default. Then write the design using that default, marked inline as `【假设，见 Q-xx】`. The doc stays complete enough to estimate and code, and every guess stays visible and reversible.
2. **Technical choices are yours, business choices are theirs.** Index design, idempotency keys and lock strategy are design decisions: make them, and record notable ones as `D-xx` with the reason. Anything that changes what a user sees or what money/data does is a business question: ask it.
3. **Traceability.** Every requirement item `R-xx` must map to design elements and to at least one acceptance criterion `AC-xx`. That mapping is what lets you answer "is this requirement covered?" at review, and "is it done?" during development.
4. **Fit the existing system.** A design that ignores existing conventions creates a second architecture inside the project.

## Workflow

**Running the scripts**: they are Python 3. On Windows, `python3` is often missing or opens the Microsoft Store, so use `python` (or `py -3`) there.

### 1. Read the inputs

- **Requirement doc**: `.docx` → `pandoc -t gfm input.docx -o /tmp/req.md` (add `--extract-media=/tmp/req-media` and look at the images; prototypes and flowcharts carry half the requirements). `.pdf` → read it directly. For images and screenshots of prototypes, read the image. If `pandoc` is not on PATH but `pypandoc_binary` is installed (the usual setup on Windows), use its bundled binary: `"$(python -c 'import pypandoc; print(pypandoc.get_pandoc_path())')" -t gfm input.docx -o /tmp/req.md`. If neither exists, ask the user to install it (`python -m pip install pypandoc_binary`) or to save the document as PDF.
- **Prior design versions or meeting notes**, if the user has them. If this is an update after a review meeting, go to "Updating after review" below.
- **Existing code** (if run inside a Spring project): scan it with the sibling skill's scanner if available:
  ```bash
  python3 <skills_dir>/spring-delivery-docs/scripts/scan_spring.py <project_root> --out /tmp/spring-scan.json
  ```
  From the scan, learn the conventions you must follow: response wrapper (`Result<T>`), path style (`/api/v1/...`), table prefix, primary key strategy, BaseEntity audit fields, logic delete, existing enums, and which existing tables/APIs the new feature touches. If the scanner is not installed, read a couple of existing controllers, entities and the SQL directly.

### 2. Decompose into requirement items

Split the requirement doc into `R-01, R-02, …`. Each item describes one user-observable behavior that can be tested. "优惠券管理" is a module, not an item. "运营可以创建满减券，设置门槛金额和减免金额" is an item. For each item, record its source (section/page of the requirement doc) so the business side can find where it came from.

Items the doc implies but never states (e.g. "the coupon must be returned when an order is cancelled") are still items. Mark their source as `推导` and raise a Q to confirm them.

### 3. Run the granularity checklist

Read `references/granularity-checklist.md` and walk every R item through it. This is where most of the value is. Each unanswered checklist point that matters becomes a `Q-xx`. Classify each question:

- **阻塞**: development cannot start, or the answer changes table structure or the API contract
- **非阻塞**: the default can be used and changed later cheaply

Keep questions answerable in a meeting: concrete, one decision per question, options listed, recommendation given with a one-line reason. "请明确优惠券规则" is useless. "同一订单能否叠加多张券？A 不可叠加（推荐，规则简单、财务对账清晰） B 不同类型可叠加 C 任意叠加" works.

### 4. Write the design document

Follow `references/design-doc-template.md`. Default output: `docs/design/{功能名}-详细设计.md` in the project, in the user's language (default 中文). Points that matter:

- Part 1 contains no code identifiers except where business people already use them (e.g. status names they know).
- Use Mermaid for flows (`flowchart`), state machines (`stateDiagram-v2`) and key interactions (`sequenceDiagram`). Business people do read diagrams.
- **API addresses are written `` `METHOD /path` ``**, and table design headings are `` #### `table_name` 说明 ``. The checker and the delivery-doc skill both rely on this form.
- Extending an existing table: list only the new or changed columns, and say "修改" in the heading.
- DDL in the doc must be executable for the project's database (check the driver in the scan).
- Task breakdown: each task references its R items. Use relative size (S/M/L) unless the user asks for person-days.

### 5. Check

```bash
python3 <skill_dir>/scripts/design_check.py docs/design/xxx-详细设计.md
```

It fails if any R item lacks an acceptance criterion or is not referenced in the technical part, or if a referenced Q/R/AC/D id is never defined. It also reports open and blocking question counts. Fix and rerun until PASS.

### 6. Hand over

Tell the user:
- R/AC/Q counts. List the **blocking questions** first, ready to paste into the meeting invite.
- The assumptions with the biggest impact if wrong.
- Suggested next step: review Part 1 with the business side, then come back with the answers.

### 7. Word 版

Review meetings run on Word documents, so **produce a .docx by default** after the check passes. Use the converter from the sibling skill:

```bash
python3 <skills_dir>/spring-delivery-docs/scripts/md2docx.py docs/design/xxx-详细设计.md [--template 公司模板.docx]
```

It renders the Mermaid flow/state/sequence diagrams to images, formats tables (borders, repeating header row, `<br>` option lists as real line breaks), and highlights 【假设】 in orange and 【待确认】 in red, so the business side sees at a glance what still needs their decision. Handle its messages as described in spring-delivery-docs step 7: install hints for missing pandoc/python-docx, and diagrams kept as source when no Mermaid renderer exists.

The Markdown is the master copy. If the business side sends back an edited or commented .docx, read it (`pandoc -t gfm their.docx`, or open the file for comments), fold the changes into the Markdown as review answers (see below), and regenerate the .docx. Never edit the .docx directly.

## Updating after review

When the user brings answers ("Q-03 选 B，Q-05 上限改成 3 张"):

1. Update each answered Q's status to `已确认` and record the answer and date. Keep the row, because the question history is part of the agreement.
2. Remove the matching `【假设，见 Q-xx】` markers and rewrite the affected rules, tables, APIs and ACs. Search the whole doc for the Q id, since one answer usually touches several sections.
3. New questions raised in the meeting get new ids. Never renumber existing ones.
4. Add a row to 修订记录 and bump the version.
5. Rerun the checker, then regenerate the .docx. Name it with the version (e.g. `优惠券-详细设计-v0.2.docx`, using `--out-dir` or by renaming) so the copy sent after the meeting is distinguishable from the one reviewed.

## Checking implementation progress

During or after development, compare the design with the code:

```bash
python3 <skills_dir>/spring-delivery-docs/scripts/scan_spring.py <project_root> --out /tmp/spring-scan.json
python3 <skill_dir>/scripts/design_check.py docs/design/xxx-详细设计.md --scan /tmp/spring-scan.json
```

It lists designed APIs, tables and columns that are not in the code yet, plus code endpoints under the same path prefixes that the design does not mention (scope creep, or the design needs an update). Report this as a progress table, and treat differences as questions to resolve, not automatically as code bugs: sometimes the code is right and the design should be updated.
