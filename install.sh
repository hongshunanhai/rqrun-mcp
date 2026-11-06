#!/usr/bin/env bash
# RQrun MCP 一键安装器
#   用法:  ./install.sh [--client=all|claude|codex|zcode|workbuddy|dsh] [--no-login] [--help]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_SCRIPT="$REPO_DIR/rq_mcp.py"
VENV="$REPO_DIR/.venv"
CLIENT="all"
DO_LOGIN=1

B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; D=$'\033[2m'; N=$'\033[0m'

for arg in "$@"; do
  case "$arg" in
    --client=*) CLIENT="${arg#*=}" ;;
    --no-login) DO_LOGIN=0 ;;
    -h|--help)
      cat <<EOF
RQrun MCP 安装器

  --client=all|claude|codex|zcode|workbuddy|dsh   只配置指定客户端（默认全部自动检测）
  --no-login                                     跳过登录（稍后可用 login 工具登录）

示例：
  ./install.sh
  ./install.sh --client=claude
  ./install.sh --no-login
EOF
      exit 0 ;;
    *) echo "未知参数: ${arg}（用 --help 查看用法）"; exit 1 ;;
  esac
done

step() { printf "\n${B}%s${N}\n" "$1"; }
ok()   { printf "  ${G}✓${N} %s\n" "$1"; }
warn() { printf "  ${Y}!${N} %s\n" "$1"; }
die()  { printf "  ${R}✗${N} %s\n" "$1"; exit 1; }

printf "${B}"
cat <<'EOF'
  ┌─────────────────────────────────────┐
  │   RQrun MCP · 安装向导              │
  │   把 RQrun 训练数据接给你的 AI      │
  └─────────────────────────────────────┘
EOF
printf "${N}"

# --------------------------------------------------------------------------
step "[1/4] 检查 Python"
PY=""
CAND=()
# 优先 3.11–3.13（3.14 可用但生态较新，遇到编译问题换 3.12）
for n in python3.13 python3.12 python3.11; do
  p="$(command -v "$n" 2>/dev/null || true)"
  [ -n "$p" ] && CAND+=("$p")
done
CAND+=(
  "$HOME"/.pyenv/versions/3.13*/bin/python3
  "$HOME"/.pyenv/versions/3.12*/bin/python3
  "$HOME"/.pyenv/versions/3.11*/bin/python3
  /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12
)
p="$(command -v python3 2>/dev/null || true)" && [ -n "$p" ] && CAND+=("$p")
for c in "${CAND[@]}"; do
  [ -x "$c" ] || continue
  ver="$("$c" -c 'import sys;print(sys.version_info[0]*100+sys.version_info[1])' 2>/dev/null || echo 0)"
  if [ "$ver" -ge 311 ] 2>/dev/null; then PY="$c"; break; fi
done
[ -n "$PY" ] || die "没有找到 Python 3.11+（websockets 17 / pillow 13 需要）。请安装：https://www.python.org/downloads/"
ok "$("$PY" -V 2>&1)  ($PY)"

# --------------------------------------------------------------------------
step "[2/4] 安装依赖到项目内的虚拟环境"
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$REPO_DIR/requirements.txt"
ok "依赖就绪（mcp / websockets / pillow）"
VENV_PY="$VENV/bin/python"

# --------------------------------------------------------------------------
step "[3/4] 登录 RQrun"
if [ "$DO_LOGIN" -eq 0 ]; then
  warn "已跳过（之后可在对话里说「登录 RQrun」）"
elif [ -f "$HOME/.rq-mcp/session.json" ] && "$VENV_PY" "$PY_SCRIPT" status >/dev/null 2>&1; then
  ok "已登录，无需重复"
else
  echo "  ${D}马上会弹出一个浏览器窗口，请在里面正常登录（密码 / 短信 / 微信扫码均可）${N}"
  echo "  ${D}⚠️  不要按 F12 打开开发者工具${N}"
  echo ""
  "$VENV_PY" "$PY_SCRIPT" login || warn "登录未完成，可稍后重跑 ./install.sh"
fi

# --------------------------------------------------------------------------
step "[4/4] 配置 AI 客户端"

want() { [ "$CLIENT" = "all" ] || [ "$CLIENT" = "$1" ]; }

# 用 venv 的 python 做 JSON 合并，避免手写 JSON 出错
merge_json() { # $1=文件 $2=python 表达式（对 cfg 字典操作）
  "$VENV_PY" - "$1" "$2" "$VENV_PY" "$PY_SCRIPT" <<'PYEOF'
import json, os, sys, shutil
path, mode, py, script = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
entry = {"command": py, "args": [script], "env": {}}
os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
cfg = {}
if os.path.exists(path):
    try:
        cfg = json.load(open(path, encoding="utf-8")) or {}
    except Exception:
        print(f"  ! {path} 不是合法 JSON，已跳过（原文件未改动）")
        sys.exit(0)
    shutil.copy2(path, path + ".bak")
if mode == "mcpServers":
    cfg.setdefault("mcpServers", {})["rqrun"] = entry
elif mode == "zcode":
    cfg.setdefault("mcp", {}).setdefault("servers", {})["rqrun"] = entry
json.dump(cfg, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"  ✓ {path}")
PYEOF
}

# 判断某个 JSON 配置里是否**真的存在** MCP 服务（只看文件存在是不够的）
json_has_mcp() { # $1=文件 $2=native|agents
  [ -f "$1" ] || return 1
  "$VENV_PY" - "$1" "$2" <<'PYEOF' >/dev/null 2>&1
import json, sys
path, kind = sys.argv[1], sys.argv[2]
try:
    data = json.load(open(path, encoding="utf-8"))
except Exception:
    sys.exit(1)
if not isinstance(data, dict):
    sys.exit(1)
servers = (data.get("mcp") or {}).get("servers") if kind == "native" else data.get("mcpServers")
sys.exit(0 if isinstance(servers, dict) and servers else 1)
PYEOF
}

# 写入或更新 Codex 的 [mcp_servers.rqrun] 段（TOML 解析 → 合并 → 回验）
write_codex_toml() { # $1=config.toml
  "$VENV_PY" "$REPO_DIR/scripts/merge_codex_toml.py" "$1" "$VENV_PY" "$PY_SCRIPT"
}

# ---- Claude Code ----
if want claude; then
  if command -v claude >/dev/null 2>&1; then
    if claude mcp list 2>/dev/null | grep -q "rqrun"; then
      ok "Claude Code：已配置过 rqrun"
    elif claude mcp add --scope user rqrun -- "$VENV_PY" "$PY_SCRIPT" >/dev/null 2>&1; then
      ok "Claude Code：已写入用户级配置（claude mcp list 可查看）"
    else
      warn "Claude Code：自动添加失败，请手动执行："
      echo "      claude mcp add --scope user rqrun -- \"$VENV_PY\" \"$PY_SCRIPT\""
    fi
  else
    warn "Claude Code：未检测到 claude 命令（未安装或不在 PATH）"
  fi
fi

# ---- Codex CLI ----
if want codex; then
  if command -v codex >/dev/null 2>&1 || [ -d "$HOME/.codex" ]; then
    CO="$HOME/.codex/config.toml"
    mkdir -p "$HOME/.codex"
    write_codex_toml "$CO"
  else
    warn "Codex：未检测到 ~/.codex（未安装 Codex CLI）"
  fi
fi

# ---- ZCode ----
if want zcode; then
  if [ -d "$HOME/.zcode" ] || [ -d "$HOME/.agents" ] || command -v zcode >/dev/null 2>&1; then
    ZC="$HOME/.zcode/cli/config.json"
    AG="$HOME/.agents/mcp.json"
    if json_has_mcp "$ZC" native; then
      merge_json "$ZC" zcode
      ok "ZCode：已合并进原有原生配置 $ZC"
    elif json_has_mcp "$AG" agents; then
      merge_json "$AG" mcpServers
      ok "ZCode：已合并进 ${AG}（沿用原有 .agents 来源，未新建 .zcode）"
    else
      merge_json "$ZC" zcode
      ok "ZCode：已写入 $ZC"
    fi
  else
    warn "ZCode：未检测到 ~/.zcode（未安装 ZCode）"
  fi
fi

# ---- WorkBuddy ----
if want workbuddy; then
  if [ -d "$HOME/.workbuddy" ] || command -v workbuddy >/dev/null 2>&1; then
    merge_json "$HOME/.workbuddy/mcp.json" mcpServers
    ok "WorkBuddy：已写入 ~/.workbuddy/mcp.json"
  else
    warn "WorkBuddy：未检测到 ~/.workbuddy（未安装 WorkBuddy）"
  fi
fi

# ---- DeepSeek Harness ----
if want dsh; then
  DSH_PATCH=""
  AVAILABLE=""
  if [ -d "$HOME/.dsh/profiles" ]; then
    AVAILABLE="$(ls "$HOME/.dsh/profiles" 2>/dev/null | tr '\n' ' ' || true)"
  fi
  if [ -n "${DSH_PROFILE:-}" ]; then
    CAND="$HOME/.dsh/profiles/$DSH_PROFILE/cordis.patch.yml"
    if [ -f "$CAND" ]; then
      DSH_PATCH="$CAND"
    else
      warn "指定的 DSH_PROFILE=$DSH_PROFILE 不存在，已跳过（可用：${AVAILABLE:-无}）"
    fi
  else
    COUNT=0
    ONLY=""
    for p in "$HOME"/.dsh/profiles/*/cordis.patch.yml; do
      [ -f "$p" ] || continue
      COUNT=$((COUNT + 1))
      ONLY="$p"
    done
    if [ "$COUNT" -eq 1 ]; then
      DSH_PATCH="$ONLY"
    elif [ "$COUNT" -gt 1 ]; then
      warn "检测到 $COUNT 个 DSH profile，为避免写错已跳过"
      warn "请指定后重跑：DSH_PROFILE=<名字> ./install.sh --client=dsh"
      warn "可用：${AVAILABLE:-无}"
    fi
  fi
  if [ -n "$DSH_PATCH" ]; then
    "$VENV_PY" "$REPO_DIR/scripts/append_dsh_patch.py" "$DSH_PATCH" "$VENV_PY" "$PY_SCRIPT" \
      && ok "DeepSeek Harness：已处理 ${DSH_PATCH}（重启 DSH 后生效）"
  fi
fi

# --------------------------------------------------------------------------
printf "\n${G}${B}安装完成${N}\n\n"
printf "  启动命令（任何客户端都填这两个）:\n"
printf "    command:  %s\n" "$VENV_PY"
printf "    args:     %s\n" "$PY_SCRIPT"
cat <<'EOF'

  接下来：
    1. 重启你的 AI 客户端
    2. 问它一句：「我今天跑了多少公里」
    3. 如果提示未登录，直接说「登录 RQrun」

  详细说明见 README.md，各客户端单独说明见 docs/
EOF
