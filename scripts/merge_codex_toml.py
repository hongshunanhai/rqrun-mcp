#!/usr/bin/env python3
"""把 rqrun 的 MCP 配置合并进 Codex 的 config.toml。

设计要点：
  * 先确认原文件是合法 TOML，不是就拒绝改动（避免把用户的配置写坏）
  * 只更新 rqrun 这一段里的 4 个受管字段，**保留**用户自己加的
    enabled / enabled_tools / disabled_tools / env_vars / 注释等
  * 段标题允许带行尾注释，例如 [mcp_servers.rqrun] # existing
  * 写回前再解析一次结果，非法则放弃并报错

用法： merge_codex_toml.py <config.toml> <python路径> <rq_mcp.py路径>
"""
import os
import re
import shutil
import sys
import tomllib

MANAGED = ("command", "args", "startup_timeout_sec", "tool_timeout_sec")
HEADER_RE = re.compile(r"^\s*\[mcp_servers\.rqrun\]\s*(?:#.*)?$")
ANY_HEADER_RE = re.compile(r"^\s*\[")
KEY_RE = re.compile(r"^\s*([A-Za-z0-9_\-]+)\s*=")


def _bounds(lines):
    start = next((i for i, l in enumerate(lines) if HEADER_RE.match(l)), None)
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if ANY_HEADER_RE.match(lines[j]):
            end = j
            break
    return start, end


def _strip_managed(body):
    """去掉受管字段（含跨行数组），其余行原样保留。"""
    out, i = [], 0
    while i < len(body):
        line = body[i]
        m = KEY_RE.match(line)
        if m and m.group(1) in MANAGED:
            depth = line.count("[") + line.count("{") - line.count("]") - line.count("}")
            i += 1
            while depth > 0 and i < len(body):
                depth += (body[i].count("[") + body[i].count("{")
                          - body[i].count("]") - body[i].count("}"))
                i += 1
            continue
        out.append(line)
        i += 1
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def build_body(existing_body, python_path, script_path):
    managed = [
        f'command = "{python_path}"',
        f'args = ["{script_path}"]',
        "startup_timeout_sec = 30.0",
        "tool_timeout_sec = 600.0",
    ]
    kept = _strip_managed(existing_body)
    return managed + ([""] + kept if kept else [])


def merge(path, python_path, script_path):
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if text.strip():
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            raise SystemExit(f"  ✗ {path} 不是合法 TOML（{e}），已跳过，未做任何修改")

    lines = text.splitlines()
    found = _bounds(lines)
    if found is None:
        prefix = lines + ([""] if lines and lines[-1].strip() else [])
        new_lines = prefix + ["[mcp_servers.rqrun]"] + build_body([], python_path, script_path)
        status = "新增"
    else:
        start, end = found
        body = build_body(lines[start + 1:end], python_path, script_path)
        tail = ([""] + lines[end:]) if end < len(lines) else []
        new_lines = lines[:start] + [lines[start]] + body + tail
        status = "更新"

    new_text = "\n".join(new_lines).rstrip("\n") + "\n"
    try:
        tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"  ✗ 合并后 TOML 非法（{e}），已放弃写入")
    if "mcp_servers" not in tomllib.loads(new_text):
        raise SystemExit("  ✗ 合并结果缺少 mcp_servers，已放弃写入")

    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    open(path, "w", encoding="utf-8").write(new_text)
    print(f"  ✓ {path}（{status}）")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("用法: merge_codex_toml.py <config.toml> <python> <script>")
    merge(sys.argv[1], sys.argv[2], sys.argv[3])
