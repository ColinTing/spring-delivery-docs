# spring-delivery-docs

> 一句话让 Claude Code 从 Spring Boot 源码生成甲方要的交付文档：接口文档、数据库设计文档、部署运维手册、版本变更说明。

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

```bash
git clone https://github.com/<you>/spring-delivery-docs.git

# 所有项目可用
cp -r spring-delivery-docs/skills/spring-delivery-docs ~/.claude/skills/
# 或只给某个项目
cp -r spring-delivery-docs/skills/spring-delivery-docs <your-project>/.claude/skills/
```

只依赖 Python 3 标准库，不需要装任何包。

## 使用

在 Spring 项目目录里打开 Claude Code，直接说：

- “帮我出一份接口文档给前端”
- “甲方要数据库设计说明”
- “写个部署手册，运维不懂 Java”
- “v1.2.0 到现在改了什么，出个版本说明”
- “交付文档都做一下”（生成全套四份）

需要 Word 版时说“转成 docx”。如果装了 pandoc 会直接转换，并支持套用公司的 Word 模板。

脚本也可以单独用：

```bash
python3 skills/spring-delivery-docs/scripts/scan_spring.py <项目目录> --out scan.json
python3 skills/spring-delivery-docs/scripts/check_docs.py scan.json docs/delivery
```

## 示例

[`examples/demo-shop`](examples/demo-shop) 是一个模拟外包项目，故意混用了 Swagger2、springdoc 和纯 Javadoc，还有 record、泛型包装、逻辑删除、明文密码配置。生成的文档在 [`examples/demo-shop/docs/delivery`](examples/demo-shop/docs/delivery)，可以先看效果。

## 目录结构

```
skills/spring-delivery-docs/
├── SKILL.md                 # 工作流程与写作规则
├── scripts/
│   ├── scan_spring.py       # 源码 → 事实 JSON
│   └── check_docs.py        # 覆盖率 + 密钥泄露校验
└── references/              # 四类文档模板
evals/evals.json             # 测试用例
examples/demo-shop/          # 示例项目及生成结果
```

## Roadmap

- [ ] 输出 OpenAPI 3 JSON，可直接导入 Apifox 或 Postman
- [ ] 识别全局异常处理，自动生成错误码表
- [ ] WebFlux RouterFunction、JAX-RS
- [ ] 国产数据库 DDL 方言（达梦、人大金仓）

欢迎 issue 和 PR，尤其欢迎贴出 scanner 识别错误的代码片段。

## License

MIT
