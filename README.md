# RQrun MCP

[中文](README.md) | [English](README.en.md)

把 **RQrun（rq.run）** 的训练数据接进你的 AI 助手，让它直接回答「我今年跑了多少」「分析一下我昨天那次跑步」「我这周是不是练过量了」。

> 只读。不会修改或删除你的任何记录，**也永远不接触你的账号密码**。

```
你：我今年跑了多少公里
AI：（调用 get_period_stats）2026 年至今 471.3 km，83 次，平均配速 6'58"…
```

---

## 它能做什么

| 你可以这样问 | 它调用的工具 |
|---|---|
| 我今天/昨天跑了多少 | `list_activities` |
| 分析一下我昨天那次跑步，配速稳不稳 | `get_activity` |
| 画一下我这次的分段配速和心率 | `render_chart` |
| 我这个月跑了多少 | `get_period_stats` |
| 我这周是不是练过量了 | `get_training_status` |
| 以我现在的状态，全马能跑多少 | `get_runlevel` |
| 我最近是有氧练太多还是强度不够 | `get_intensity` |
| 我这个月哪几天跑了 | `get_calendar` |
| 我的最大心率、PB、RQ币 | `get_profile` |

图表是服务端直接生成的 PNG，跑友不需要装浏览器自动化之类的东西。

---

## 支持哪些客户端

同一份代码，五个客户端都能接——区别只在「配置文件写在哪」。

| 客户端 | 配置文件 | 说明 |
|---|---|---|
| **Claude Code** | `~/.claude.json`（用户级）或项目内 `.mcp.json` | 也可用 `claude mcp add` |
| **Codex CLI** | `~/.codex/config.toml` → `[mcp_servers.rqrun]` | TOML 格式 |
| **ZCode** | `~/.zcode/cli/config.json`（`mcp.servers`） | 也可用设置面板「导入」 |
| **WorkBuddy** | `~/.workbuddy/mcp.json` | 界面里粘贴 JSON 即可 |
| **DeepSeek Harness** | profile 的 `cordis.patch.yml` | 用 `@deepseek-ai/dsh-mcp-client` |
| 其它（通用） | `~/.agents/mcp.json` | 业界通用约定，ZCode / 部分工具会读 |

每个客户端的图文步骤见 [`docs/`](docs/)。

---

## 快速开始

### 方式一：一键脚本（推荐）

```bash
git clone https://github.com/<你的GitHub用户名>/rqrun-mcp.git
cd rqrun-mcp
./install.sh
```

脚本会自动完成四件事：

```
[1/4] 找 Python（3.11+）
[2/4] 建 .venv 并装依赖（mcp / websockets / pillow，不污染系统）
[3/4] 弹出登录窗口 → 你正常登录一次
[4/4] 自动检测并写入各客户端配置
```

想只配某一个客户端：

```bash
./install.sh --client=claude      # claude / codex / zcode / workbuddy / dsh
```

macOS 用户也可以直接**双击 `install.command`**，效果一样。

### 方式二：手动配置

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python rq_mcp.py login     # 弹窗登录
```

然后把这两行填进你客户端的 MCP 配置（路径换成你的实际路径）：

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

---

## 登录是怎么工作的

第一次运行 `login` 时，会弹出一个**独立的 Chrome 窗口**（不动你平时的浏览器）：

1. 在里面正常登录 RQrun：账号密码 / 短信验证码 / 微信扫码都行
2. 登录成功后窗口自动关闭，凭据保存到 `~/.rq-mcp/session.json`（权限 600）
3. 约 **30 天**有效，过期后在对话里说一句「登录 RQrun」即可

> ⚠️ 不要在登录窗口里按 F12。RQrun 有反调试脚本，开 DevTools 会让页面自毁；登录器已经阻断了这个脚本，正常登录不受影响。

**账号密码全程只输入给 RQrun 自己的登录页**，本工具只保存登录后的会话 Cookie。

---

## 提供的工具（10 个，全部只读）

| 工具 | 作用 |
|---|---|
| `list_activities` | 记录列表，可按日期/运动类型过滤 |
| `get_activity` | 单次训练详情：分段、心率区间，可选逐秒序列 |
| `render_chart` | 生成图表图片：分段配速心率图 / 周跑量柱状图 |
| `get_period_stats` | 年 / 月 / 周 / 自定义 / 生涯汇总 |
| `get_training_status` | 体能·疲劳·状态（≈CTL/ATL/TSB）、恢复时间 |
| `get_runlevel` | 当前跑力、百分位、完赛预测 |
| `get_intensity` | 强度分布（配速口径 + 心率口径）、步频步幅触地 |
| `get_calendar` | 某月每天的训练摘要 |
| `get_profile` | 最大/静息心率、区间、PB、RQ币 |
| `login` | 打开登录窗口 |

明确**没有**封装：发短信验证码、删除记录、改标题、退出登录等一切写操作。

---

## 隐私

**数据的流向要说清楚：**

```
你的机器 ──请求──▶ rq.run（RQrun 官方服务器）
   │
   └──工具返回的训练数据/图表──▶ 你使用的 AI 客户端 ──▶ 模型服务商
```

也就是说：本工具本身不经过任何第三方服务器，但**工具返回的数据会进入你所用 AI 客户端的对话**。如果你用的是云端模型（DeepSeek、Claude、GPT 等），这部分数据会按该服务商的条款被提交处理——这点和你把跑步数据手动贴进对话框没有区别。

**本机保存的东西：**

| 位置 | 内容 | 说明 |
|---|---|---|
| `~/.rq-mcp/session.json` | 会话 Cookie（权限 600） | 删除即退出登录 |
| `~/.rq-mcp/chrome-profile/` | 登录用的独立 Chrome 配置目录 | 含该浏览器的缓存、站点数据，不再需要可整个删除 |

仓库里没有任何用户数据；`.gitignore` 已排除 `.venv/`、`session.json`、`charts/`、本地 bundle。

---

## 常见问题

**Q：提示「登录已过期」**
A：在对话里说「登录 RQrun」，或重跑 `./install.sh`。

**Q：Windows / Linux 能用吗？**
A：可以，但**自动弹窗登录目前只支持 macOS**。其它系统用兜底方式：

```bash
# macOS / Linux
./.venv/bin/python rq_mcp.py login --manual
# Windows（PowerShell）
.venv\Scripts\python.exe rq_mcp.py login --manual
```

注意各平台虚拟环境里的解释器路径不同：

| 平台 | Python 路径 |
|---|---|
| macOS / Linux | `.venv/bin/python` |
| Windows | `.venv\Scripts\python.exe` |

配置 MCP 时 `command` 要填对应平台的路径。Windows 的安装脚本暂未提供，按上表手动配置即可。

**Q：会不会把我的数据传出去？**
A：本工具自身只请求 `rq.run`，没有任何第三方中转。但**工具返回的数据会进入你所用 AI 客户端的对话**——用云端模型时，这部分会按该服务商的条款处理，和你手动把数据贴进对话框一样。本机保存位置见上面的「隐私」一节。

**Q：为什么不用 npx / uvx 分发？**
A：目前是单文件 Python + venv，好处是不依赖 Node 生态、跑友机器上只要有个 Python 就能跑。

更多见 [`docs/troubleshooting.md`](docs/troubleshooting.md)。

---

## 项目结构

```
rqrun-mcp/
├── rq_mcp.py            # 服务端主文件（登录 + 10 个工具 + 画图）
├── install.sh           # 一键安装器（自动配置 5 个客户端）
├── install.command      # macOS 双击版
├── requirements.txt
├── scripts/
│   └── smoke_test.py    # CI 用的协议冒烟测试
├── docs/                # 各客户端接入说明 + 排错
├── examples/            # 可直接复制的配置样例
├── dsh-bundle/          # DeepSeek Harness 的 bundle 形式安装包
└── .github/workflows/   # CI：静态检查 + 冒烟测试 + 安装器测试
```

## 开发

**发布前跑一次自检**（推荐）：

```bash
./scripts/preflight.sh
```

它会依次检查：shell 语法、**是否有未提交的改动**、跟踪文件里有没有 Cookie 或个人绝对路径、单元测试、MCP 握手。任何一项不过都会以非零码退出。

单独跑某一项：

```bash
./.venv/bin/python scripts/unit_tests.py   # 纯逻辑单测（57 项，不联网）
./.venv/bin/python scripts/smoke_test.py   # MCP 协议握手 + 工具清单
bash -n install.sh                         # 安装脚本语法
```

CI 会在 Ubuntu 和 macOS 上各跑一遍：静态检查 → 单元测试 → MCP 握手 → 安装器在干净 HOME 下的写入、幂等与不覆盖性。

---

## 免责声明

本项目为个人开发的第三方工具，与 RQrun 官方无关，通过公开的网页接口读取**你自己账号**的数据。请遵守 RQrun 的服务条款，不要用于批量抓取或商业用途。

## License

MIT
