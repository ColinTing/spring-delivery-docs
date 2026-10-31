# 接口文档模板

Structure for `01-接口文档.md`. Keep the headings, adapt the content. Omit a subsection only when it is truly empty for that endpoint (e.g. no path params), not because the info was hard to find.

````markdown
# {项目名称} 接口文档

| 项目 | 内容 |
|---|---|
| 版本 | {pom version / git tag} |
| 更新日期 | {YYYY-MM-DD} |
| 服务地址 | `http://{host}:{server.port}{context-path}`（host 由部署环境决定） |
| 接口数量 | {N} |

## 1. 通用说明

### 1.1 请求约定
- 数据格式：`application/json; charset=UTF-8`（文件上传为 `multipart/form-data`）
- 认证方式：{从过滤器/拦截器/Security 配置得出，如 请求头 `Authorization: Bearer <token>`；找不到写【待确认】}
- 时间格式：{从 @JsonFormat / jackson 配置得出}

### 1.2 统一响应结构
{来自统一返回类，例如 Result<T>}

| 字段 | 类型 | 说明 |
|---|---|---|
| code | Integer | 状态码，0 表示成功 |
| msg | String | 提示信息 |
| data | T | 业务数据，见各接口 |

### 1.3 错误码
{来自错误码枚举 / 全局异常处理 / 接口 notes 中提到的码；没有集中定义时列出代码里出现的并注明}

| 错误码 | 含义 | 出现场景 |
|---|---|---|

### 1.4 枚举值
{接口中出现的枚举，每个一张表：值 / 含义}

## 2. {模块名，来自 tag}

### 2.1 {接口名称}

| 项目 | 内容 |
|---|---|
| 接口地址 | `{METHOD} {path}` |
| 描述 | {summary；detail 有则补充} |
| 调用方 | 前端 / 第三方 {仅特殊接口写} |

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|---|---|---|---|

**查询参数**

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|

**请求头**（仅接口特有的；通用认证头在 1.1 已说明）

**请求体**（`application/json`）

| 字段 | 类型 | 必填 | 校验规则 | 说明 |
|---|---|---|---|---|
| items | Array<Object> | 是 | 不能为空 | 商品明细 |
| └─ skuId | Long | 是 |  | SKU ID |

**请求示例**

```json
{ }
```

**响应参数**（data 部分，已展开泛型）

| 字段 | 类型 | 说明 |
|---|---|---|

**响应示例**

```json
{ "code": 0, "msg": "success", "data": { } }
```

## 3. 回调与内部接口
{不对前端开放的接口，写明调用方、验签方式【待确认】、幂等要求}

## 4. 外部依赖接口
{来自 feign_clients：服务名、地址配置项（不写真实地址）、调用的路径和用途}

## 附录：待确认事项
{本文件所有【待确认】集中列一遍}
````

Notes:
- `query-object` params (an object without `@RequestBody`): flatten its fields into the 查询参数 table.
- A method mapped to several paths/methods: one section, list all `{METHOD} {path}` combinations in 接口地址.
- Endpoints with no description: derive a neutral name from the handler + path (e.g. "Ping 检测") and add `【待确认：代码中无接口说明】`.
- Order sections by tag, then by path, the same order as the scan.
