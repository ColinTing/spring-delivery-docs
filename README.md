# spring-delivery-docs

> 给外包和项目制 Java 团队的 Claude Code 技能包，覆盖从需求评审到验收交付的文档工作。

| Skill | 阶段 | 输入 → 输出 |
|---|---|---|
| [`spring-detailed-design`](#spring-detailed-design需求--详细设计) | 开发前 | 需求文档 → 详细设计 Word（业务确认 + 技术设计），以及评审用的待澄清问题清单 |
| [`spring-delivery-docs`](#spring-delivery-docs代码--交付文档) | 验收时 | 源码 → 接口文档、数据库设计文档、部署运维手册、版本变更说明 |

两个 skill 相互独立，可以只装其中一个。Word 转换脚本 `md2docx.py` 在两个 skill 里各有一份相同的副本，只依赖 python-docx。

## spring-detailed-design：需求 → 详细设计

返工最多的地方在于：需求文档写“支持优惠券”，开发按自己的理解做，验收时才发现对不上。这个 skill 把这类偏差提前到写代码之前解决：

```
你：这是运营给的优惠券需求文档，出个详细设计，周三要和他们评审
Claude：拆出 11 条需求、19 条验收标准；有 12 个问题需要运营确认，
        其中 6 个阻塞开发（适用范围、有效期形式、能否叠加……），
        每个问题都附了选项和建议。设计中按建议方案写，并标注了【假设】。
```

- **业务确认部分**：业务方能看懂，没有类名。包括需求清单 R-xx、业务规则、流程图和状态图、验收标准 AC-xx、待澄清问题 Q-xx。评审会上逐条过，业务方签字确认。
- **技术设计部分**：可以直接照着写代码。包括表结构和 DDL、接口清单与详情、并发与幂等方案、设计决策 D-xx、任务拆分 T-xx。
- **颗粒度清单**：用一份 10 类检查清单（字段、边界、状态、权限、异常、联动……）逐条过需求，找出需求文档里没写清楚的地方。
- **遵循现有代码约定**：先读项目里有代表性的代码，沿用现有的统一返回类、路径风格、表前缀、主键策略和审计字段。
- **直接交付 Word**：只输出 `.docx`。Claude 写的 Markdown 只是临时草稿。Word 文件本身就是母版：`md2docx.py --read` 能把它无损还原成 Markdown，流程图也能还原，因为图的源码存在图片的替代文字里。
- **评审后更新**：把业务方改过、批注过的 Word 直接给它，修订显示为 `[+新增+]` / `[-删除-]`，批注显示为 `[批注 作者：内容]`。或者直接告诉它“Q-03 选 B”。它会更新所有受影响的章节，保留问题记录和修订历史，另存为新版本号。
- **自动检查**：转 Word 时会检查每条需求是否都有验收标准、是否出现在技术设计里、编号是否都有定义、已确认的问题是否还残留【假设】。

只需要两个文件：`SKILL.md` 和 `md2docx.py`，方便复制到不能访问 GitHub 的电脑上。

示例：[`优惠券需求说明书`](examples/demo-shop/docs/requirements) → [`优惠券-详细设计.docx`](examples/demo-shop/docs/design/优惠券-详细设计.docx)

## spring-delivery-docs：代码 → 交付文档

外包和项目制 Java 团队每次验收前，都要花几天手写文档，写完就和代码对不上。这个 skill 让文档直接从代码里长出来：

```
你：下周要验收了，甲方要交付文档，帮我把这个项目的文档都整出来
Claude：扫描到 13 个接口、3 张表……已生成 docs/delivery/ 下 4 份文档，
        校验通过；有 11 处【待确认】需要开发/运维补充，清单如下……
```

## 和“让 AI 直接写文档”有什么不同

| 痛点 | 做法 |
|---|---|
| AI 编造字段和错误码 | 先用脚本从源码提取事实（`scan_spring.py`），文档只写代码里有的；不知道的写 `【待确认】`，不猜 |
| 漏接口 | `check_docs.py` 逐个核对接口和表，漏一个就 FAIL |
| 把生产密码写进文档 | 校验脚本读取配置里的密码、密钥和 IP，文档里出现就 FAIL |
| 泛型、嵌套对象看不懂 | `Result<PageResult<UserVO>>` 自动展开成前端能看懂的字段表 |
| 实体和建表 SQL 对不上 | 交叉比对实体类与 DDL，不一致的地方写进文档的“一致性检查” |

## 支持范围

- Spring MVC / Spring Boot 2.x、3.x，Maven 多模块
- 接口说明来源：Swagger2 `@Api`/`@ApiOperation`、springdoc `@Tag`/`@Operation`、Javadoc、行注释
- 持久层：MyBatis-Plus（`@TableName`/`@TableField`/`@TableLogic`）、JPA、MyBatis XML、`.sql` 中的 DDL（MySQL 的 `COMMENT`，PostgreSQL/Oracle 的 `COMMENT ON`）
- 校验注解：`@NotNull` `@Size` `@Pattern` 等会转成“长度 4–32”这样的中文规则
- Java record、内部类、枚举（自动生成状态码表）、`@FeignClient` 外部依赖

在真实项目上的实测结果：

| 项目 | Java 文件 | 识别接口 | 与 grep 计数比对 | DDL 表 | 解析错误 | 耗时 |
|---|---|---|---|---|---|---|
| [macrozheng/mall](https://github.com/macrozheng/mall) | 519 | 246 | 246 / 246 | 76 | 0 | 1.7s |
| [RuoYi-Vue](https://github.com/yangzongzhuan/RuoYi-Vue) | 266 | 148 | 146 个方法，多路径展开后 148 | 31 | 0 | 0.6s |

## 安装

### macOS / Linux

```bash
git clone https://github.com/ColinTing/spring-delivery-docs.git

# 装到用户目录，所有项目可用。两个都装：
mkdir -p ~/.claude/skills && cp -r spring-delivery-docs/skills/* ~/.claude/skills/
# 只装详细设计：cp -r spring-delivery-docs/skills/spring-detailed-design ~/.claude/skills/
# 只给某个项目装：把目标目录换成 <your-project>/.claude/skills/

# Word 转换只依赖 python-docx
python3 -m pip install python-docx
npm i -g @mermaid-js/mermaid-cli    # 可选：流程图、状态图渲染成图片（没有权限就跳过，脚本会自动用 npx）
```

### Windows（PowerShell）

不需要 winget，也不需要管理员权限。

电脑能访问 GitHub 的话：

```powershell
cd D:\IdeaProjects
git clone https://github.com/ColinTing/spring-delivery-docs.git
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
# 只装详细设计：
Copy-Item -Recurse -Force D:\IdeaProjects\spring-delivery-docs\skills\spring-detailed-design "$env:USERPROFILE\.claude\skills\"
# 或者两个都装：
# Copy-Item -Recurse -Force D:\IdeaProjects\spring-delivery-docs\skills\* "$env:USERPROFILE\.claude\skills\"
```

不能访问 GitHub 的话，只需要手工复制两个文件：在 `%USERPROFILE%\.claude\skills\` 下新建 `spring-detailed-design` 文件夹，把 [`SKILL.md`](skills/spring-detailed-design/SKILL.md) 和 [`md2docx.py`](skills/spring-detailed-design/md2docx.py) 的内容粘贴进同名文件，保存为 UTF-8 编码。

然后安装依赖：

```powershell
# Word 转换只依赖 python-docx
python -m pip install --user python-docx

# 可选：流程图渲染成图片（需要 Node.js）。不用全局安装，预热一次 npx 缓存即可，不需要管理员权限；
# 约下载 300 MB，不下载 Chrome，脚本会自动使用本机的 Edge 或 Chrome。看到输出 11.4.2 就是成功了
$env:PUPPETEER_SKIP_DOWNLOAD = "1"; npx -y @mermaid-js/mermaid-cli@11.4.2 --version
```

- 没有 `python` 命令时换成 `py`；两个都没有就先装 [Python 3](https://www.python.org/downloads/)，安装时勾选 “Add python.exe to PATH”
- pip 下载慢可以加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`；npm 下载慢可以先执行 `npm config set registry https://registry.npmmirror.com`（只改当前用户的配置，不需要管理员权限）
- 更新：`git -C D:\IdeaProjects\spring-delivery-docs pull`，然后重新执行上面的 `Copy-Item` 那一行
- 路径以克隆到 `D:\IdeaProjects` 为例，放在别处的话替换成实际路径

## 使用

在 Spring 项目目录里打开 Claude Code，直接说：

- “帮我出一份接口文档给前端”
- “甲方要数据库设计说明”
- “写个部署手册，运维不懂 Java”
- “v1.2.0 到现在改了什么，出个版本说明”
- “交付文档都做一下”（生成全套四份）
- “需求文档是 C:\Users\me\Downloads\迭代9\需求说明书.docx，出个详细设计，放到同一个目录”（写上文件路径；docx、pdf、md 都可以；不指定位置时默认写到项目的 `docs/design/`）
- “评审结果：Q-01 选 A，Q-03 选 B”（更新设计）
- “对照详细设计看看开发进度”

详细设计只交付 Word。交付文档默认同时输出 Markdown 和 Word 两份。Word 版包括：

- 流程图、状态图、时序图渲染成图片
- 表格加边框，表头加底色并跨页重复，列宽按内容自动分配
- 宋体正文、黑体标题，A4 纸，自动生成目录，页脚显示“第 X 页 / 共 Y 页”
- 【待确认】标红、【假设】标橙，评审时一眼能看到还要业务方拍板的地方
- 说“用这个模板 公司模板.docx”，就会套用公司的 Word 样式

脚本也可以单独用：

```bash
M=skills/spring-detailed-design/md2docx.py        # 与 spring-delivery-docs/scripts/md2docx.py 完全相同
python3 $M 详细设计.md --template 公司模板.docx     # Markdown → Word；设计文档会顺带做需求追溯检查
python3 $M --read 评审回来的.docx                  # Word → Markdown，含修订、批注和流程图源码，打印大纲
python3 skills/spring-delivery-docs/scripts/scan_spring.py <项目目录>           # 扫描代码，打印摘要和 JSON 路径
python3 skills/spring-delivery-docs/scripts/check_docs.py <JSON 路径> docs/delivery  # 交付文档覆盖率 + 泄密检查
```

## 示例

[`examples/demo-shop`](examples/demo-shop) 是一个模拟外包项目，故意混用了 Swagger2、springdoc 和纯 Javadoc，还有 record、泛型包装、逻辑删除、明文密码配置。生成的文档在 [`examples/demo-shop/docs/delivery`](examples/demo-shop/docs/delivery)，可以先看效果。

## 目录结构

```
skills/spring-delivery-docs/
├── SKILL.md                 # 工作流程与写作规则
├── scripts/
│   ├── scan_spring.py       # 源码 → 事实 JSON
│   ├── check_docs.py        # 覆盖率 + 密钥泄露校验
│   └── md2docx.py           # Markdown ⇄ Word（源文件）
└── references/              # 四类文档模板
skills/spring-detailed-design/
├── SKILL.md                 # 工作流程 + 颗粒度清单 + 文档模板
└── md2docx.py               # 副本，由 tools/sync_shared.py 同步
tools/sync_shared.py         # 同步 md2docx.py 的副本
evals/evals.json             # 测试用例
examples/demo-shop/          # 示例项目及生成结果
```

## 开发说明

每个 skill 目录都要能单独安装，所以 `md2docx.py` 在两个 skill 里各有一份真实的文件，没有用软链接，因为 Windows 默认检出时软链接会变成普通文本文件。修改时只改 `skills/spring-delivery-docs/scripts/md2docx.py`，然后运行：

```bash
python tools/sync_shared.py          # 更新副本
python tools/sync_shared.py --check  # 只检查；两份不一致时返回非零，CI 里也会跑
```

## Roadmap

- [ ] 输出 OpenAPI 3 JSON，可直接导入 Apifox 或 Postman
- [ ] 识别全局异常处理，自动生成错误码表
- [ ] WebFlux RouterFunction、JAX-RS
- [ ] 国产数据库 DDL 方言（达梦、人大金仓）

欢迎 issue 和 PR，尤其欢迎贴出 scanner 识别错误的代码片段。

## License

MIT
