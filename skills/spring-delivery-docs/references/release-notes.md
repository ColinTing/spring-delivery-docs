# 版本变更说明模板

Structure for `04-版本变更说明.md`.

## Determining the range

1. If the user names versions/tags/dates, use them.
2. Otherwise: `git tag --sort=-creatordate | head` → from the latest tag to `HEAD`. If no tags exist, ask for the range or use the last 30 days and say so.

```bash
git log <from>..<to> --no-merges --pretty=format:'%h|%ad|%an|%s' --date=short
git diff --stat <from>..<to>
git diff <from>..<to> -- '*Controller.java' '*.sql' 'src/main/resources/application*'
```

Commit messages are often useless ("fix", "update", "提交"). Read the diff for those. The doc describes what changed for the client, not what the developer typed.

To find API changes, run `scan_spring.py` on both versions (`git worktree add /tmp/old <from>`) and diff the endpoint lists. This catches added/removed/changed endpoints that commit messages never mention. Remove the worktree afterwards.

````markdown
# {项目名称} 版本变更说明 {to 版本}

| 项目 | 内容 |
|---|---|
| 版本范围 | {from} → {to} |
| 发布日期 | {date} |

## 1. 新增功能
- {面向客户的描述}（{commit 短 hash}）

## 2. 问题修复
-

## 3. 接口变更
| 类型 | 接口 | 说明 | 是否兼容 |
|---|---|---|---|
| 新增 | `GET /api/...` | | 兼容 |
| 修改 | | 新增必填参数 xxx | **不兼容** |

## 4. 数据库变更
{新增/修改的 SQL，给出需要执行的脚本路径和执行顺序}

## 5. 配置变更
{新增/修改的配置项，部署前需要做什么}

## 6. 升级步骤
1. 备份数据库
2. 执行 {sql}
3. 更新配置 {keys}
4. 替换 jar 并重启
5. 验证

## 7. 已知问题
````

Group by meaning, not by commit. Drop pure-internal noise (formatting, refactors without behavior change) unless asked, and mention in one line that they exist.
