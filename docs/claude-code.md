# 在 Claude Code 里使用

## 方式 A：命令行（推荐）

```bash
claude mcp add --scope user rqrun -- \
  /绝对路径/rqrun-mcp/.venv/bin/python \
  /绝对路径/rqrun-mcp/rq_mcp.py
```

`--scope user` 表示对所有项目生效。查看是否成功：

```bash
claude mcp list
```

应该能看到 `rqrun`。

## 方式 B：改配置文件

用户级配置文件是 `~/.claude.json`，在里面加：

```json
{
  "mcpServers": {
    "rqrun": {
      "command": "/绝对路径/rqrun-mcp/.venv/bin/python",
      "args": ["/绝对路径/rqrun-mcp/rq_mcp.py"]
    }
  }
}
```

> 改之前先备份：`cp ~/.claude.json ~/.claude.json.bak`

## 方式 C：只给某个项目用

在项目根目录建 `.mcp.json`：

```json
{
  "mcpServers": {
    "rqrun": {
      "command": "/绝对路径/rqrun-mcp/.venv/bin/python",
      "args": ["/绝对路径/rqrun-mcp/rq_mcp.py"]
    }
  }
}
```

这个文件可以提交进 git，团队共享。打开该项目时会提示是否信任这个 MCP 服务器。

## 验证

新开一个 Claude Code 会话，输入：

```
我今年跑了多少公里
```

它会自动调用 `get_period_stats`。工具名会显示为 `mcp__rqrun__get_period_stats`。

## 注意

- `command` **必须是绝对路径**，`~` 不会展开
- 路径含空格时用引号包住
- 修改配置后需要重开会话
