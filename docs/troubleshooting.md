# 常见问题排查

## 工具列表里没有 rqrun

1. 确认配置里的 `command` 是**绝对路径**，指向 `.venv/bin/python`
2. 手动跑一次，看有没有报错：

```bash
/绝对路径/rqrun-mcp/.venv/bin/python /绝对路径/rqrun-mcp/rq_mcp.py status
```

3. 有输出 `❌ 未登录` 说明服务端本身是好的，只是没登录
4. 改完配置后**重启客户端**（多数客户端只在启动时读配置）

## 提示「尚未登录或登录已过期」

在对话里说「登录 RQrun」（会调用 `login` 工具弹窗），或者：

```bash
./.venv/bin/python rq_mcp.py login
```

## 登录窗口打不开 / 一闪而过

- 确认装了 **Google Chrome**（路径 `/Applications/Google Chrome.app`）
- macOS 首次运行可能提示「无法验证开发者」：右键 → 打开
- 上次的 Chrome 没退干净时会报「调试端口未就绪」，重启电脑或手动关掉对应进程

## 登录窗口里的页面自己刷新 / 变空白

你按了 F12 或打开了开发者工具。RQrun 有反调试脚本会自毁页面。
**重新跑一次 login，别开 DevTools** 即可。

## 手动登录（Windows / Linux / 自动登录失败）

```bash
./.venv/bin/python rq_mcp.py login --manual
```

按提示从浏览器复制 `RQWEBSESSID` 的值粘贴进去。

## 图表里中文变成方块

系统缺少中文字体。目前会按顺序尝试：

```
/System/Library/Fonts/STHeiti Medium.ttc
/System/Library/Fonts/Hiragino Sans GB.ttc
```

Linux 上可以装 `fonts-noto-cjk`；如果仍然不行，删掉 Pillow 用 `pip install --force-reinstall pillow` 重装。

## 安装依赖失败

- 需要 **Python 3.10+**，推荐 3.11–3.13
- 某些系统 3.14 太新，`pillow` 没有预编译包，会尝试本地编译并失败；换 3.12 即可
- 公司网络需要代理时，先 `export https_proxy=...` 再跑 `./install.sh`

## Apple Silicon 与 Intel

同一份代码通用。`install.sh` 会优先挑 3.11–3.13 的 Python 来建虚拟环境。

## 数据看起来不对

- 距离单位是公里、时长是 `时:分:秒`，配速是 `分'秒"`
- 室内跑步机记录**没有 GPS**，爬升和轨迹为空是正常的
- 时序数据默认按 30 秒降采样；要原始精度，`get_activity` 传 `resolution_sec: 1`
