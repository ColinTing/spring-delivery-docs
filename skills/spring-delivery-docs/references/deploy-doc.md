# 部署运维手册模板

Structure for `03-部署运维手册.md`. Readers are the client's ops staff, who may not know Java. Commands must be copy-pasteable.

````markdown
# {项目名称} 部署运维手册

| 项目 | 内容 |
|---|---|
| 版本 | {version} |
| 产物 | `{artifactId}-{version}.jar` |
| 更新日期 | {date} |

## 1. 系统概述
{一段话：做什么、对外提供什么（端口/上下文路径）、依赖哪些外部系统}

## 2. 环境要求

| 组件 | 版本要求 | 用途 | 依据 |
|---|---|---|---|
| JDK | {java.version / Docker 基础镜像} | 运行环境 | pom.xml |
| MySQL | 【待确认】 | 业务数据 | mysql-connector |
| Redis | 【待确认】 | 缓存/会话 | spring-boot-starter-data-redis |

服务器建议配置：{来自 Dockerfile/启动脚本的 -Xmx 等；没有就写【待确认】}

## 3. 配置说明

### 3.1 配置文件与环境
| 文件 | 环境 | 说明 |
|---|---|---|

激活方式：`--spring.profiles.active=prod`

### 3.2 关键配置项
| 配置项 | 说明 | 示例/默认值 | 是否必须修改 |
|---|---|---|---|
| spring.datasource.password | 数据库密码 | `******` | 是，由运维提供 |

## 4. 部署步骤

### 4.1 初始化数据库
{按顺序列出 SQL 文件；Flyway/Liquibase 则说明启动时自动执行}

### 4.2 构建
```bash
mvn clean package -DskipTests -P{profile}
```

### 4.3 启动
{有 Dockerfile 给 docker 方式；同时给 java -jar 方式。按实际脚本写，参数来自 Dockerfile/脚本}

### 4.4 验证
{健康检查地址：actuator 开启则 `/actuator/health`（注意 context-path）；否则给一个无需登录的接口}

## 5. 运维

- 日志位置：{logging.file / logback 配置}
- 停止/重启：{脚本或命令}
- 备份建议：{数据库、上传文件目录}

## 6. 外部系统对接
{Feign/HTTP 调用的第三方：配置项名、网络连通要求（需开放的出口），不写真实地址密钥}

## 7. 常见问题
{只写由代码/配置可推出的：端口占用、profile 未激活导致连错库、时区（serverTimezone）、文件上传大小限制等}

## 附录：待确认事项
````

Notes:
- Never copy real passwords, keys or production IPs from config. Name the config key and say "由运维提供".
- Distinguish facts from recommendations. Recommendations (e.g. memory size when nothing is configured) are labelled 建议.
