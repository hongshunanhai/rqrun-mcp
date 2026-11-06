#!/usr/bin/env python3
"""把 mcp-rqrun 条目追加到 DSH profile 的 cordis.patch.yml。

要点：
  * 原文件末尾**没有换行符**时先补一个，否则新条目会和最后一行粘成无效 YAML
  * 追加前插入空行分隔，保持可读
  * 已存在同 id 条目则不动
  * 写入前做结构校验；环境里若有 PyYAML 则额外做一次真正的解析校验
  * 改动前留 .bak

用法： append_dsh_patch.py <cordis.patch.yml> <python路径> <rq_mcp.py路径>
"""
import os
import shutil
import sys


def build_block(python_path: str, script_path: str) -> str:
    return (
        "- id: mcp-rqrun\n"
        "  name: '@deepseek-ai/dsh-mcp-client'\n"
        "  config:\n"
        "    serverName: rqrun\n"
        "    transport: stdio\n"
        "    command: \"%s\"\n"
        "    args:\n"
        "      - \"%s\"\n"
        "    failOnStartupError: false\n"
        "    toolCallTimeoutMs: 600000\n" % (python_path, script_path)
    )


def validate(text: str) -> None:
    if not text.endswith("\n"):
        raise SystemExit("  ✗ 结果末尾缺少换行，已放弃写入")
    if text.count("- id: mcp-rqrun") != 1:
        raise SystemExit("  ✗ 结果中 mcp-rqrun 条目数量异常，已放弃写入")
    try:                                        # 有 PyYAML 就做一次真解析
        import yaml                             # noqa: F401
    except ImportError:
        return
    try:
        data = yaml.safe_load(text)
    except Exception as e:                      # noqa: BLE001
        raise SystemExit(f"  ✗ 合并后 YAML 无法解析（{e}），已放弃写入")
    if not isinstance(data, list) or not any(
            isinstance(i, dict) and i.get("id") == "mcp-rqrun" for i in data):
        raise SystemExit("  ✗ 合并后 YAML 结构不符合预期，已放弃写入")


def append(path: str, python_path: str, script_path: str) -> str:
    text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if "id: mcp-rqrun" in text:
        return "already"

    block = build_block(python_path, script_path)
    if text.strip():
        if not text.endswith("\n"):
            text += "\n"                        # ← 关键：防止粘行
        text += "\n"                            # 空行分隔
    text += block

    validate(text)

    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    open(path, "w", encoding="utf-8").write(text)
    return "added"


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("用法: append_dsh_patch.py <patch.yml> <python> <script>")
    status = append(sys.argv[1], sys.argv[2], sys.argv[3])
    if status == "already":
        print("  - 已存在 mcp-rqrun，未改动")
    else:
        print(f"  ✓ {sys.argv[1]}（已追加）")
