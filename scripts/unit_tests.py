#!/usr/bin/env python3
"""纯逻辑单元测试（不联网、不依赖登录态）。

覆盖几个曾经出过问题的地方：
  * 运动类型解析（数字 sport_id 被误当成跑步）
  * 月历按周探测是否真的覆盖整月（月末漏天）
  * 周跑量是否包含休息周（周均失真）

用法:  ./.venv/bin/python scripts/unit_tests.py
"""
import datetime as dt
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import rq_mcp as R  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


def test_sport_id():
    print("运动类型解析")
    check("名称 run -> 1", R._sport_id("run") == "1")
    check("名称 ride -> 3", R._sport_id("ride") == "3")
    check("大写 RUN -> 1", R._sport_id("RUN") == "1")
    check("数字 3 -> 3", R._sport_id("3") == "3")
    check("数字 99 -> 99", R._sport_id("99") == "99")
    check("空值走默认", R._sport_id(None, "1") == "1")
    check("空串走默认", R._sport_id("", "2") == "2")
    raised = False
    try:
        R._sport_id("rowing")
    except R.RQError:
        raised = True
    check("非法值报错而不是回落跑步", raised)


def test_calendar_days():
    print("月历按周探测")
    cases = [
        (dt.date(2026, 11, 1), dt.date(2026, 11, 30)),
        (dt.date(2026, 2, 1), dt.date(2026, 2, 28)),
        (dt.date(2027, 1, 1), dt.date(2027, 1, 31)),
        (dt.date(2026, 6, 1), dt.date(2026, 6, 30)),
    ]
    for first, last in cases:
        probes = R._calendar_probe_dates(first, last)
        covered = set()
        for p in probes:
            for i in range(7):
                covered.add(p + dt.timedelta(days=i))
        missing = [d for d in (first + dt.timedelta(days=i)
                               for i in range((last - first).days + 1))
                   if d not in covered]
        check(f"{first:%Y-%m} 全月被覆盖（{len(probes)} 次探测）", not missing,
              f"漏掉: {missing[:3]}")
        check(f"{first:%Y-%m} 探测点都是周一", all(p.weekday() == 0 for p in probes))


def test_weekly_series():
    print("周跑量聚合")
    today = dt.date(2026, 11, 5)          # 周四
    rows = [(dt.date(2026, 11, 3), 10.0)]
    series = R._weekly_series(rows, 2, today=today)
    check("返回 2 个自然周", len(series) == 2)
    check("上周（休息周）为 0", series[0]["km"] == 0, series[0])
    check("本周为 10", series[1]["km"] == 10, series[1])
    check("本周被标记", series[1]["current"] is True and series[0]["current"] is False)
    avg = sum(w["km"] for w in series) / len(series)
    check("周均含休息周 = 5", avg == 5.0, avg)

    rows2 = [(dt.date(2026, 10, 20), 8.0), (dt.date(2026, 11, 3), 6.0)]
    s2 = R._weekly_series(rows2, 3, today=today)
    check("跨周不合并", [w["km"] for w in s2] == [8.0, 0.0, 6.0], [w["km"] for w in s2])
    check("周起始都是周一", all(w["start"].weekday() == 0 for w in s2))
    check("周按时间升序", s2[0]["start"] < s2[-1]["start"])


def test_format_helpers():
    print("格式化与单位换算")
    check("配速 9.2132 km/h -> 6'31\"", R._pace_txt(3600 / 9.2132) == "6'31\"")
    check("km(5333.4) = 5.33", R.km(5333.4) == 5.33)
    check("hms(2084) = 34:44", R.hms(2084) == "34:44")
    check("hms(3661) 带小时", R.hms(3661) == "1:01:01")
    check("速度过小返回 None", R.pace_str(0) is None)


def test_codex_merge():
    print("Codex TOML 合并")
    import tempfile
    import tomllib
    from pathlib import Path

    sys.path.insert(0, str(ROOT / "scripts"))
    import merge_codex_toml as M

    d = Path(tempfile.mkdtemp())
    f = d / "config.toml"
    f.write_text(
        '[model]\nname = "gpt-5"\n\n'
        '[mcp_servers.rqrun] # existing\n'
        'command = "/old/python"\n'
        'args = [\n  "/old/rq_mcp.py",\n]\n'
        'enabled = false\n'
        'enabled_tools = ["a"]\n\n'
        '[mcp_servers.other]\ncommand = "x"\n',
        encoding="utf-8")

    M.merge(str(f), "/new/python", "/new/rq_mcp.py")
    text = f.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    rq = data["mcp_servers"]["rqrun"]

    check("路径已更新", rq["command"] == "/new/python")
    check("超时更新为 600", rq["tool_timeout_sec"] == 600.0)
    check("跨行 args 被整体替换", rq["args"] == ["/new/rq_mcp.py"])
    check("保留 enabled=false", rq.get("enabled") is False)
    check("保留 enabled_tools", rq.get("enabled_tools") == ["a"])
    check("带行尾注释的表头不重复", text.count("[mcp_servers.rqrun]") == 1)
    check("其它 MCP 段保留", data["mcp_servers"]["other"]["command"] == "x")
    check("其它顶层段保留", data["model"]["name"] == "gpt-5")

    f2 = d / "c2.toml"
    f2.write_text("[a]\nx = 1\n", encoding="utf-8")
    M.merge(str(f2), "/py", "/s.py")
    data2 = tomllib.loads(f2.read_text(encoding="utf-8"))
    check("没有该段时新增", "rqrun" in data2["mcp_servers"] and data2["a"]["x"] == 1)

    f3 = d / "c3.toml"
    f3.write_text("this is not toml\n", encoding="utf-8")
    raised = False
    try:
        M.merge(str(f3), "/py", "/s.py")
    except SystemExit:
        raised = True
    check("非法 TOML 拒绝修改且原样保留", raised and f3.read_text(encoding="utf-8") == "this is not toml\n")


def main():
    test_sport_id()
    test_calendar_days()
    test_weekly_series()
    test_format_helpers()
    test_codex_merge()
    print()
    if FAILS:
        print(f"❌ {len(FAILS)} 项失败: {FAILS}")
        return 1
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
