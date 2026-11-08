---
name: spring-detailed-design
description: Turn a business requirements document (需求文档 / PRD / 需求说明书 / 需求规格, in Word, PDF, Markdown, or pasted text) into a pre-development detailed design document (详细设计 / 详细设计说明书 / 概要设计 / 技术方案 / 开发设计) delivered as a Word .docx, for a Java Spring project. The document has a business-confirmation part (numbered requirements, rules, flows, acceptance criteria, and a clarification question list for 需求评审 / 需求澄清 / 对齐颗粒度 with the business side) and a technical part (tables, APIs, state machines, task breakdown) that guides coding. Use when the user has a requirement doc and wants a design, wants to review/clarify requirements before coding, asks "这个需求怎么设计", "出个详细设计", "需求评审要准备什么", or brings back a reviewed/commented design .docx or answers to update it. Also use to check implementation progress against an existing design, and to export the designed APIs as an OpenAPI file for Apifox or Postman (导出接口、给前端 Mock、OpenAPI、Swagger).
---

# 需求 → 详细设计（Word）

Most rework in project-based delivery comes from one gap: the business side wrote "支持优惠券", developers built their interpretation, and the mismatch surfaced at 验收. This skill closes that gap *before* coding. Every vague sentence becomes either a concrete rule the business signs off on, or a numbered question with a recommended answer.

The design document serves two readers:

- **Part 1 (业务确认)**: business owners and PMs. Plain language, no class names. They should be able to read it and say "yes, that is what we mean", or point at a numbered item and correct it.
- **Part 2 (技术设计)**: developers. Precise enough to code from without re-reading the requirement doc.

The deliverable is a **Word .docx**, because review meetings run on Word. You draft in Markdown as a working file, and the bundled `md2docx.py` turns it into the .docx. The .docx is the master copy: `md2docx.py --read` turns it back into Markdown losslessly, Mermaid diagrams included (their source is kept in the image alt text). So never hand the user a .md unless they ask for one.

## Core rules

1. **Never invent business rules silently.** A requirement doc always leaves gaps (limits, edge cases, permissions, what happens on failure). For each gap, raise a question `Q-xx` with 2–3 options and a recommended default. Then write the design using that default, marked inline as `【假设，见 Q-xx】`. The doc stays complete enough to estimate and code, and every guess stays visible and reversible.
2. **Technical choices are yours, business choices are theirs.** Index design, idempotency keys and lock strategy are design decisions: make them, and record notable ones as `D-xx` with the reason. Anything that changes what a user sees or what money/data does is a business question: ask it.
3. **Traceability.** Every requirement item `R-xx` must map to design elements and to at least one acceptance criterion `AC-xx`. That mapping is what lets you answer "is this requirement covered?" at review, and "is it done?" during development.
4. **Fit the existing system.** A design that ignores existing conventions creates a second architecture inside the project.

## Environment

- This skill is two files: this SKILL.md and `md2docx.py` next to it. The script needs python-docx (`python -m pip install python-docx`). Diagrams need Node.js and are optional: without it, their source is kept in the document.
- On Windows, `python3` is often missing or opens the Microsoft Store, so use `python` (or `py -3`). Put working files in the system temp dir by absolute path (on Windows, `/tmp` means different places to Git Bash and to native programs).
- **Keep outputs bounded.** On a large project, one huge tool output (a whole directory listing, an unbounded `grep -r`, a full `git log`, a big file read in one go) can exhaust Claude Code's memory and crash the session. Step 3 has the rules.

## Workflow

### 1. Read the inputs

- **Requirement doc**: `.docx` → `python <skill_dir>/md2docx.py --read <requirement.docx>`. It writes Markdown to the system temp dir and prints the path and an outline (headings with line numbers). Read the .md, in parts if it is long. Then view the extracted images: prototypes and flowcharts carry half the requirements. EMF/WMF drawings cannot be viewed, so ask for screenshots if they matter. `.pdf` → Read it directly. `.doc`/`.wps` → ask the user to save it as .docx. Screenshots and pasted text → use them as they are.
- **A design .docx that came back from review**: go to "Updating after review" below.

### 2. Decompose into requirement items

Split the requirement doc into `R-01, R-02, …`. Each item describes one user-observable behavior that can be tested. "优惠券管理" is a module, not an item. "运营可以创建满减券，设置门槛金额和减免金额" is an item. For each item, record its source (section/page of the requirement doc) so the business side can find where it came from.

Items the doc implies but never states (e.g. "the coupon must be returned when an order is cancelled") are still items. Mark their source as `推导` and raise a Q to confirm them.

### 3. Check the existing code

A design that does not match the code gets torn up at the first code review, so confirm, don't assume. Skip this step only for a brand-new project with no code, and say so in 2.1.

Do it **without reading the whole project**. A large repository has tens of thousands of files, and big outputs pulled into the session exhaust Claude Code's memory. Rules:

- Search with `git grep`. It only looks at tracked files (so `target/`, `node_modules` and build output are skipped) and stays fast on large repos. Outside git: `grep -rIl --include=*.java --exclude-dir={target,build,node_modules,.git} …`.
- Every command has a ceiling: ask for file names (`-l`) or counts (`-c`) before lines, and end with `| head -50` or less (PowerShell: `| Select-Object -First 50`).
- Check a file's size (`wc -l`) before reading it. Read big files only around the line numbers `git grep -n` found (Read with offset/limit). Never read generated code, minified files, lock files, logs or SQL data dumps.
- Write findings to `<system temp dir>/spring-detailed-design/{功能名}-代码调研.md` as you go (file path + one-line finding), and work from these notes afterwards instead of re-reading code.

What to find, in this order:

1. **Project shape**, in a few commands:
   ```bash
   git ls-files "*pom.xml" "*build.gradle*" | head -30        # modules
   git ls-files "*Controller.java" | wc -l                      # scale
   git grep -l -E "mybatis-plus|mybatis|spring-boot-starter-data-jpa" -- "*pom.xml" "*.gradle" | head
   ```
2. **Conventions**, reading one file each:
   ```bash
   git grep -l -E "class (Result|R|AjaxResult|CommonResult|ApiResponse)[<{ ]" -- "*.java" | head    # response wrapper
   git grep -l -E "@(Rest)?ControllerAdvice" -- "*.java" | head                                      # errors, error codes
   git grep -l -E "class (Base[A-Za-z]*(Entity|DO|PO|Model)|[A-Za-z]*BaseEntity)[ <{]" -- "*.java" | head
   git grep -n -E "SecurityContextHolder|getLoginUser|UserContext|X-User-Id" -- "*.java" | head -10  # who is the current user
   ```
   From those plus 2–3 entities with their DDL, note: path style, table prefix, primary-key strategy, audit fields, logic delete, enum style, how the current user is identified, and which error-code ranges are taken.
3. **What the feature touches.** For each R item, take its domain terms in Chinese and English (优惠券/coupon, 订单/order, 取消/cancel …) and search code, DDL and mapper XML:
   ```bash
   git grep -l -i -E "coupon|优惠券" -- "*.java" "*.xml" "*.sql" | head -50
   git grep -n -E '@(Get|Post|Put|Delete|Request)Mapping.*order' -- "*.java" | head -40
   git grep -n -i -E "create table[^(]*order" -- "*.sql" | head
   ```
   Then read only what the design depends on: the entity and DDL of every table you will change (real column names and types), the controller method and service of every API you will change, and **one similar existing feature end to end** (controller → service → mapper/XML), so the new code follows its layering and naming.
4. **Does it already exist?** If part of the feature is already there (a coupon table, a half-built module, an unused endpoint), design a modification, not a duplicate, and say so in 1.1 and 2.1. If something the requirement depends on is missing (e.g. no order-cancel flow), raise it as a Q.

Put the evidence in the design. 2.1 lists the conventions followed and the files they came from, and every 修改 table or API matches the code you read. Anything you could not confirm in the code is 【待确认】, never a guess.

### 4. Run the granularity checklist

Walk every R item through the checklist at the end of this file, together with what step 3 found in the code. This is where most of the value is. Each unanswered point that matters becomes a `Q-xx`. Classify each question:

- **阻塞**: development cannot start, or the answer changes table structure or the API contract
- **非阻塞**: the default can be used and changed later cheaply

Keep questions answerable in a meeting: concrete, one decision per question, options listed, recommendation given with a one-line reason. "请明确优惠券规则" is useless. "同一订单能否叠加多张券？A 不可叠加（推荐，规则简单、财务对账清晰） B 不同类型可叠加 C 任意叠加" works.

### 5. Write the draft

Follow the template at the end of this file, in the user's language (default 中文). Write the draft to `<system temp dir>/spring-detailed-design/{功能名}-详细设计.md`. The file name becomes the Word file's name. Points that matter:

- Part 1 contains no code identifiers except where business people already use them (e.g. status names they know).
- Use Mermaid for flows (`flowchart`), state machines (`stateDiagram-v2`) and key interactions (`sequenceDiagram`). Business people do read diagrams.
- **API addresses are written `` `METHOD /path` ``**, and table design headings are `` #### `table_name` 说明（新增|修改） ``.
- **API details are tables, not sentences.** Under each `` #### 名称 `METHOD /path` `` heading, the 请求头, 路径参数 and 查询参数, the request body's fields and the response class's fields each get a table, introduced by a line that names it (see the template). Describe the project's response wrapper and page class once, as `` 结构 `Result<T>`： `` and `` 结构 `PageResult<T>`： `` with the field names used in the code. Write enum values as `1 满减券，2 折扣券` or `UNUSED 未使用 / USED 已使用`, time formats as `yyyy-MM-dd HH:mm:ss`, and error codes as `错误码：3002–3005`. These tables are the API contract that `md2docx.py --openapi` exports for the frontend and testers. A parameter mentioned only in a sentence is lost, and the check flags it.
- Extending an existing table: list only the new or changed columns, and say "修改" in the heading. The same goes for an existing API: list only the new fields, and end its heading with （修改）.
- DDL must be executable for the project's database.
- Task breakdown: each task references its R items. Use relative size (S/M/L) unless the user asks for person-days.

### 6. Convert to Word and check

```bash
python <skill_dir>/md2docx.py <draft.md> --out-dir <target dir> [--template 公司模板.docx]
```

Target dir: where the user asked for it (often the folder holding the requirement doc), else `docs/design/` in the project. Write nothing else into the source tree. Read the output:

- `[check] … -- ok`: traceability holds. Every `!` line is a defect: an R without an AC, an R missing from the technical part, an id used but never defined, or a 【假设】 left for an answered question. Fix the draft and convert again until the line ends with `ok`.
- `[api] … -- ok`: section 2.3 can be exported as an API contract. Every `! api` line names an API and what the export cannot read: parameters written in a sentence, a class with no field table, a path variable with no row, a time field without a format. Fix the draft and convert again. APIs marked （修改） are counted but never exported.
- `python-docx is required`: give the user the install command it printed, and stop there. Do not hand-build a .docx some other way.
- `no Mermaid renderer` / `diagrams 0/N`: the .docx is still produced, with the diagram source kept. Rendering needs Node.js, but no global install: the script falls back to `npx` (installs into the user's npm cache, no admin rights; the first run downloads ~300 MB). To warm it up once: `npx -y @mermaid-js/mermaid-cli@11.4.2 --version` with `PUPPETEER_SKIP_DOWNLOAD=1` set (PowerShell: `$env:PUPPETEER_SKIP_DOWNLOAD = "1"; npx ...`). It uses the installed Chrome/Edge. Never suggest running npm as administrator.
- `cannot write … close it in Word first`: the user has the file open.
- If the user has a company Word template, pass `--template`: its styles, header and footer are kept.

Never send document content to online services: design docs are confidential to the client.

### 7. Hand over

Tell the user:
- the .docx path, and the R/AC/Q counts. List the **blocking questions** first, ready to paste into the meeting invite.
- the assumptions with the biggest impact if wrong.
- that Word asks to update fields when the file opens. Answering yes fills in the table of contents.
- the next step: review Part 1 with the business side, then come back with the answers or their marked-up .docx.
- that once the API-related questions are settled, the APIs can be exported for Apifox or Postman so the frontend and testers can start on mocks (see "Exporting the API contract").

## Updating after review

The user brings answers ("Q-03 选 B，Q-05 上限改成 3 张"), or the .docx with the business side's tracked changes and comments.

1. `python <skill_dir>/md2docx.py --read <latest design .docx>`. Their insertions come back as `[+text+]`, deletions as `[-text-]`, comments as `[批注 作者：内容]`, and diagrams as Mermaid. This Markdown is the new draft.
2. Update each answered Q's status to `已确认` and record the answer and date. Keep the row, because the question history is part of the agreement.
3. Remove the matching `【假设，见 Q-xx】` markers and rewrite the affected rules, tables, APIs and ACs. Search the whole draft for the Q id, since one answer usually touches several sections.
4. Resolve every review mark: apply or reject it, and note the outcome in the Q table or 修订记录. None may remain in the new version.
5. New questions get new ids. Never renumber existing ones.
6. Add a row to 修订记录, bump the version, and save the draft as `{功能名}-详细设计-v0.2.md` so the new .docx does not overwrite the reviewed one. Convert. The check flags assumptions left for answered questions.

## Exporting the API contract (OpenAPI)

When the user wants the APIs in Apifox or Postman, wants mocks for the frontend or testers, or asks for OpenAPI or Swagger, export from the latest design .docx, because review may have changed it:

```bash
python <skill_dir>/md2docx.py --openapi <design.docx> [--out-dir DIR]
```

It writes `<name>.openapi.json` (OpenAPI 3.0) next to the .docx and prints the same `[api]` check as the conversion. If there are `! api` findings, fix the design (as in "Updating after review") and export again. Never edit the JSON by hand: the Word document stays the master, and the JSON is regenerated from it after every review. Then tell the user:

- **Apifox**: 导入数据 → OpenAPI/Swagger, then choose the file. The APIs land in folders `{功能名}/{调用方}`, and the mock data follows the field types, ranges, lengths, enums and time formats, so the frontend can start before the backend exists.
- **Postman**: Import the file. Postman fills request bodies with placeholders such as `<string>` unless "Parameter generation" in the import settings is set to Example.
- **Not exported**: the APIs marked （修改）. The design lists only their new fields, and importing them would overwrite the complete definition already in the tool, so name the fields to add by hand.
- **Still open**: the open questions that affect the APIs (Q ids cited by 【假设】 in 2.3). Until they are answered the contract can change; export and import again after the next review.

The export runs locally. As with the design itself, do not upload it to any online service; importing it into the team's tool is the user's step.

## Checking implementation progress

Read the design (`--read` if you only have the .docx). For each API in the 接口清单 and each table in the 表清单, look it up in the code with the bounded searches from step 3, e.g. `git grep -n -F '"/api/v1/coupons' -- "*.java" | head` and `git grep -n -i "t_coupon" -- "*.java" "*.xml" "*.sql" | head`. Report a table of done / missing / changed, plus endpoints under the same path prefix that the design does not mention. Treat differences as questions to resolve, not automatically as code bugs: sometimes the code is right and the design should be updated.

## Granularity checklist

Walk each R item through the relevant groups. Skip groups that obviously do not apply (a read-only report has no concurrency questions). A point becomes a Q only when the requirement doc does not answer it **and** the answer changes behavior, data, or effort. Do not pad the question list. Ten sharp questions get answered; sixty get ignored.

### 1. 数据与字段
- 每个输入字段：必填？类型/长度/格式？取值范围？默认值？能否修改，谁能改，改了之后历史数据怎么办？
- 金额：单位（元/分）、精度、舍入方式、能否为 0 或负数
- 时间：精确到天还是秒？“截止 3 月 31 日”是含当天 23:59:59 吗？时区？
- 唯一性：名称、编号能否重复？编号规则（前缀、日期、流水号）？
- 枚举：值的完整列表？以后会扩展吗？

### 2. 规则与边界
- 数量上限：每人/每天/每单/总量的上限？超出时提示什么？
- 叠加与互斥：多个规则同时满足时怎么算？优先级？
- 边界值：等于门槛时算不算满足（≥ 还是 >）？
- 计算顺序：先折扣还是先满减？分摊到明细时如何分配，尾差给谁？

### 3. 状态与生命周期
- 对象有哪些状态？每个状态允许哪些操作？
- 状态之间如何流转、由谁触发（用户、管理员、定时任务、外部回调）？
- 能否撤销或回退？过期、作废、删除的区别？删除是物理删除还是逻辑删除，删除后关联数据怎么显示？

### 4. 角色与权限
- 谁能看、谁能操作？按角色还是按数据范围（本人、本部门、本门店）？
- 需要审批吗？几级审批？审批人是谁？驳回之后怎么办？
- 操作是否需要留痕（操作日志：谁、什么时间、改了什么）？

### 5. 异常与失败
- 外部系统（支付、短信、物流）失败、超时：重试？提示用户？人工处理？
- 用户重复提交、并发抢同一资源（库存、名额、券）：结果是什么？
- 中途失败的数据如何回滚或补偿？
- 用户看到的提示文案由谁定？

### 6. 联动与影响
- 这个功能影响哪些已有功能（订单、退款、报表、对账）？
- 已有数据要迁移或初始化吗？上线时老数据怎么处理？
- 退款、取消、售后时这个功能的数据怎么处理（券退还？积分扣回？）

### 7. 查询与展示
- 列表：哪些筛选条件、排序规则、默认排序？分页大小？
- 显示哪些字段？敏感信息要脱敏吗？
- 需要导出吗？什么格式，数据量多大？导出是否受权限控制？

### 8. 通知与触达
- 什么事件需要通知、通知谁、通过什么渠道（站内信、短信、邮件、企业微信）？
- 通知失败要处理吗？用户能退订吗？

### 9. 非功能
- 预期数据量（一年多少条）与并发（峰值 QPS、是否有秒杀或活动）
- 响应时间要求
- 数据保留期限、合规要求（个人信息、财务数据）
- 需要兼容的端（PC、H5、小程序、App）以及版本

### 10. 上线与运营
- 需要后台配置开关吗？能否灰度？
- 需要哪些统计报表来衡量效果？
- 上线时间约束（活动日期）会不会影响范围（先上哪些、后上哪些）？

## Design document template

Keep the id formats exactly, because `md2docx.py` checks them:

- Requirement items `R-01`: the **first cell** of a row in the 需求清单 table
- Acceptance criteria `AC-01`: first cell of a row in the 验收标准 table, with the R id(s) in the second cell
- Questions `Q-01`: first cell of a row in the 待澄清问题 table; status in the last cell (待确认 / 已确认：答复与日期 / 已取消)
- Design decisions `D-01`, tasks `T-01`: first cell of their tables
- The technical part starts with a heading containing 技术设计
- APIs `` `METHOD /path` ``; table design headings `` #### `table_name` 说明（新增|修改） ``
- API details (exported to OpenAPI): heading `` #### 名称 `METHOD /path` ``, with （修改） at the end for a changed existing API. Each table comes right after a line naming it: `请求头：`, `路径参数：`, `查询参数：`, `` 请求体 `Class`： ``, `` 响应 `Result<Class>`： ``. A response without fields of its own is one line, e.g. `` 响应 `Result<Void>`。 ``. Classes shared by several APIs, nested classes and generic wrappers are described once as `` 结构 `Class`： `` or `` 结构 `Result<T>`： ``. Parameter and request tables have the columns 参数/字段 | 类型 | 必填 | 校验 | 说明, response tables 字段 | 类型 | 说明, with Java types in 类型

Everything else is guidance. Drop a subsection that truly does not apply, and write "无" rather than leaving an empty heading where the reader would expect content (e.g. 权限).

````markdown
# {功能名称} 详细设计

| 项目 | 内容 |
|---|---|
| 版本 | v0.1（评审稿） |
| 需求来源 | {需求文档名称、版本、日期} |
| 所属系统 | {项目名，若有扫描结果则写模块} |
| 编写日期 | {YYYY-MM-DD} |
| 状态 | 待评审 / 已确认 / 开发中 |

## 修订记录

| 版本 | 日期 | 说明 |
|---|---|---|
| v0.1 | {date} | 初稿，待需求评审 |

---

# 第一部分 业务确认

> 本部分供业务方确认。请重点查看 **1.5 待澄清问题**，并逐条核对 **1.2 需求清单** 和 **1.4 验收标准** 是否符合预期。

## 1.1 背景与目标
{两三句：为什么做、做完后谁得到什么。来自需求文档，不要发挥}

**范围内**：{列表}
**范围外**：{列表，明确不做什么，避免验收时扩展}

## 1.2 需求清单

| 编号 | 需求描述 | 角色 | 来源 | 优先级 |
|---|---|---|---|---|
| R-01 | 运营可以创建满减券，设置门槛金额和减免金额 | 运营 | 需求文档 2.1 | 必须 |
| R-02 | … | | 推导，见 Q-03 | |

## 1.3 业务规则与流程

### 1.3.1 业务流程
```mermaid
flowchart TD
```

### 1.3.2 业务规则

| 规则 | 内容 | 关联需求 |
|---|---|---|
| 门槛判定 | 订单商品金额 ≥ 门槛金额时可用【假设，见 Q-02】 | R-03 |

### 1.3.3 状态说明
```mermaid
stateDiagram-v2
```

| 状态 | 含义 | 允许的操作 |
|---|---|---|

### 1.3.4 角色与权限

| 角色 | 可执行操作 | 数据范围 |
|---|---|---|

### 1.3.5 页面与字段
{按页面列出：字段、是否必填、校验规则、提示文案。有原型就引用原型页码}

### 1.3.6 异常场景

| 场景 | 系统行为 | 用户看到的提示 |
|---|---|---|

## 1.4 验收标准

| 编号 | 关联需求 | 前置条件 | 操作 | 预期结果 |
|---|---|---|---|---|
| AC-01 | R-01 | 运营已登录 | 创建门槛 100 减 10 的券 | 创建成功，状态为“未开始” |

{每个 R 至少一条；有边界值的规则要有边界用例}

## 1.5 待澄清问题

| 编号 | 问题 | 选项 | 建议 | 影响 | 类型 | 状态 |
|---|---|---|---|---|---|---|
| Q-01 | 同一订单能否使用多张券？ | A 不可叠加<br>B 不同类型可叠加<br>C 任意叠加 | A，规则简单、对账清晰 | R-04，表结构 | 阻塞 | 待确认 |

{类型：阻塞 / 非阻塞。状态：待确认 / 已确认（写明答复与日期）/ 已取消}

---

# 第二部分 技术设计

## 2.1 总体设计
- 涉及模块：{新增/修改的包、类}
- 与现有功能的关系：{哪些现有接口、表、流程被修改}
- 遵循的现有约定：{来自代码调研：Result 包装、路径前缀、主键策略、逻辑删除、审计字段}
- 代码依据：{调研时读过的关键文件，如 `common/Result.java`、`entity/Order.java`、`db/schema.sql`；已有类似功能写明是哪个}

```mermaid
sequenceDiagram
```

## 2.2 数据库设计

### 2.2.1 表清单

| 表名 | 说明 | 变更类型 | 关联需求 |
|---|---|---|---|

### 2.2.2 表结构

#### `t_coupon` 优惠券模板（新增）

| 字段 | 类型 | 允许空 | 默认值 | 说明 |
|---|---|---|---|---|

索引：{名称、字段、原因}

#### `t_order` 订单表（修改）

| 字段 | 类型 | 允许空 | 默认值 | 说明 |
|---|---|---|---|---|
{只列新增或修改的字段}

### 2.2.3 DDL
```sql
```

## 2.3 接口设计

### 2.3.1 接口清单

| 接口 | 说明 | 调用方 | 关联需求 |
|---|---|---|---|
| `POST /api/v1/admin/coupons` | 创建优惠券 | 管理后台 | R-01 |

### 2.3.2 接口详情

{统一返回类和分页类各写一次，字段名以代码为准；再写一句时间字段的格式}

结构 `Result<T>`：

| 字段 | 类型 | 说明 |
|---|---|---|
| code | Integer | 状态码，0 表示成功，其他为错误码 |
| msg | String | 提示信息 |
| data | T | 业务数据 |

结构 `PageResult<T>`：

| 字段 | 类型 | 说明 |
|---|---|---|
| total | Long | 总条数 |
| records | List<T> | 当前页数据 |

#### 创建优惠券 `POST /api/v1/admin/coupons`

请求体 `CouponCreateDTO`：

| 字段 | 类型 | 必填 | 校验 | 说明 |
|---|---|---|---|---|
| name | String | 是 | `@NotBlank @Size(max=30)` | 券名称 |
| type | Integer | 是 | 1 满减券，2 折扣券 | 券类型 |
| reduceAmount | BigDecimal | 满减券必填 | 0.01–9999.99 | 减免金额 |
| startTime | String | 是 | `yyyy-MM-dd HH:mm:ss` | 开始时间 |

响应 `Result<Long>`：data 为券 ID。

错误码：3001

#### 优惠券列表 `GET /api/v1/admin/coupons`

查询参数：

| 参数 | 类型 | 必填 | 校验 | 说明 |
|---|---|---|---|---|
| pageNum | Integer | 否 | 默认 1 | 页码 |
| state | String | 否 | NOT_STARTED 未开始 / ONGOING 进行中 / ENDED 已结束 | 运营状态 |

响应 `Result<PageResult<AdminCouponVO>>`：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | Long | 券 ID |
| maxDiscountAmount | BigDecimal | 最高优惠金额，为空表示不封顶 |
| endTime | LocalDateTime | 有效期结束 |

#### 领取优惠券 `POST /api/v1/coupons/{id}/receive`

请求头：

| 参数 | 类型 | 必填 | 校验 | 说明 |
|---|---|---|---|---|
| X-User-Id | Long | 是 | | 当前用户 ID |

路径参数：

| 参数 | 类型 | 必填 | 校验 | 说明 |
|---|---|---|---|---|
| id | Long | 是 | | 券 ID |

处理逻辑见 2.4.1。

响应 `Result<Long>`：data 为用户券 ID。

错误码：3002–3005

#### 创建订单 `POST /api/v1/orders`（修改）

{格式同上，只列新增或修改的字段}

## 2.4 关键逻辑
{状态机实现、计算公式、并发控制（锁/乐观锁/唯一索引）、幂等、事务边界、定时任务（cron、处理量、失败重试）、与外部系统交互。每段注明关联需求}

## 2.5 设计决策

| 编号 | 决策 | 原因 | 备选方案 |
|---|---|---|---|
| D-01 | 领券用唯一索引 (coupon_id, user_id) 防重复 | 并发下比查询后插入可靠 | 分布式锁 |

## 2.6 非功能设计
{性能、数据量估算、缓存、安全（越权校验）、日志与审计}

## 2.7 开发任务拆分

| 任务 | 内容 | 关联需求 | 规模 | 依赖 |
|---|---|---|---|---|
| T-01 | 建表与实体 | R-01…R-05 | S | Q-01 |

## 2.8 上线与回滚
{DDL 执行顺序、配置项、数据初始化、开关、回滚方案}
````
