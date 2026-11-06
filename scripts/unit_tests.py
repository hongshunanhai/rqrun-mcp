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

    # 路径里带方括号，曾导致字符计数的数组边界判断吞掉后续用户设置
    f4 = d / "c4.toml"
    f4.write_text(
        '[mcp_servers.rqrun] # existing\n'
        'command = "/old/[local/python"\n'
        'args = ["/old/rq_mcp.py"]\n'
        'enabled = false\n'
        'env_vars = { FOO = "bar" }\n',
        encoding="utf-8")
    M.merge(str(f4), "/new/python", "/new/rq_mcp.py")
    d4 = tomllib.loads(f4.read_text(encoding="utf-8"))["mcp_servers"]["rqrun"]
    check("路径含方括号不误吞后续设置", d4.get("enabled") is False, d4)
    check("路径含方括号时 env_vars 保留", d4.get("env_vars") == {"FOO": "bar"}, d4)

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


def test_chart_pagination_boundary():
    """用假 API 验证两个边界：
    1) 目标起始周当天有 100+ 条记录时，不能读完第一页就停
    2) 本月累计来自周期接口，而不是分页读到的部分记录
    """
    print("周跑量分页边界（假 API）")
    from datetime import date, timedelta

    today = date.today()
    curw = today - timedelta(days=today.weekday())
    target_start = curw - timedelta(days=7)      # weeks=2
    calls = {"list": 0, "month": 0}

    def fake_api(action, **kw):
        if action == "User/Record/get_list":
            calls["list"] += 1
            if calls["list"] == 1:               # 整页都是起始周周一
                return {"total": 500, "list": [
                    {"training_at": f"{target_start} 08:00:00",
                     "sport_id": "1", "distance": "1000"} for _ in range(100)]}
            if calls["list"] == 2:               # 第二页才出现更早的记录
                older = target_start - timedelta(days=1)
                return {"total": 500, "list": [
                    {"training_at": f"{older} 08:00:00",
                     "sport_id": "1", "distance": "2000"}]}
            return {"total": 500, "list": []}
        if action == "User/Mydata/record_data_period_total":
            calls["month"] += 1
            return {"total_distance": 17.8}
        raise AssertionError(f"未预期的接口调用: {action}")

    original = R.api
    R.api = fake_api
    try:
        png = R._chart_volume(2)
    finally:
        R.api = original

    check("起始周当天满页时继续翻页", calls["list"] >= 2, f"只调用了 {calls['list']} 次")
    check("本月累计单独查询周期接口", calls["month"] == 1)
    check("图表仍能正常生成", isinstance(png, bytes) and len(png) > 1000)


def test_period_all_branch():
    """生涯分支曾因变量提前引用而崩溃，用假数据把三个别名都覆盖一遍。"""
    print("生涯统计分支")
    payload = {
        "total_distance": 921.2, "total_time": 114.1, "total_count": 142,
        "total_point": 2195.2, "pace": "7'26\"", "avg_hr": 149,
        "last_runlevel": 37.7, "user_rq_level": "中阶级跑者", "join_days": 489,
        "total_marathon_count": 0,
        "period_list": [
            {"period": 2026, "total_distance": 471.3, "pace": "6'58\"",
             "total_point": 1024.6, "last_runlevel": "37.7"},
            {"period": 2025, "total_distance": 449.9, "pace": "7'55\"",
             "total_point": 1170.6, "last_runlevel": "31.8"},
        ],
    }
    original = R.api
    R.api = lambda action, **kw: payload if action == "User/Mydata/record_data_all_total" \
        else (_ for _ in ()).throw(AssertionError(action))
    try:
        for alias in ("all", "alltime", "total"):
            try:
                d = R.t_get_period_stats(alias)
                ok = d["总距离_km"] == 921.2 and len(d["分年"]) == 2
                check(f"period={alias} 正常返回", ok, d.get("分年"))
            except Exception as e:                       # noqa: BLE001
                check(f"period={alias} 正常返回", False, repr(e))
    finally:
        R.api = original


def test_series_seconds():
    print("周期时长求和")
    items = [{"total_time": 2567}, {"total_time": 2084}, {"total_time": 2415}]
    check("按明细秒数求和", R._series_total_seconds(items) == 7066)
    check("空明细返回 0", R._series_total_seconds([]) == 0)
    check("缺字段按 0 处理", R._series_total_seconds([{"total_time": 10}, {}]) == 10)


def test_month_total_fallback():
    print("本月累计回退语义")
    from datetime import date, timedelta

    today = date.today()
    month_start = today.replace(day=1)
    original = R.api

    def failing_api(action, **kw):
        if action == "User/Mydata/record_data_period_total":
            raise R.RQError("模拟接口失败")
        raise AssertionError(action)

    R.api = failing_api
    try:
        # 分页没有覆盖到月初 -> 不能拿部分数据冒充整月
        val, note = R._month_total_km(today, "1", [(today, 5.0)], oldest=today)
        check("未覆盖月初时返回不可用", val is None and note == "暂不可用", (val, note))

        # 恰好停在月初当天：读到了，但不能证明当天已读完 -> 仍不可用
        val_b, note_b = R._month_total_km(today, "1", [(month_start, 5.0)],
                                          oldest=month_start, history_complete=False)
        check("停在月初当天时不兜底", val_b is None and note_b == "暂不可用", (val_b, note_b))

        # 历史已确认读完 -> 可以兜底
        val_c, _ = R._month_total_km(today, "1", [(month_start, 5.0)],
                                     oldest=month_start, history_complete=True)
        check("历史读完时可兜底", val_c == 5.0, val_c)

        # 已覆盖到月初 -> 可以用本地求和兜底
        rows = [(month_start, 6.0), (today, 5.0)]
        val2, note2 = R._month_total_km(today, "1", rows, oldest=month_start - timedelta(days=3))
        check("已覆盖月初时本地兜底求和", val2 == 11.0 and note2 == "", (val2, note2))
    finally:
        R.api = original


def test_incomplete_note():
    print("图表不完整提示")
    from datetime import date
    start = date(2026, 10, 26)
    check("未触顶不提示", R._incomplete_note(False, start, start) == "")
    check("触顶且日期相等要提示", R._incomplete_note(True, start, start) != "")
    check("触顶且更晚要提示", R._incomplete_note(True, date(2026, 11, 2), start) != "")
    check("触顶但已严格更早不提示", R._incomplete_note(True, date(2026, 10, 25), start) == "")
    check("触顶且无数据要提示", R._incomplete_note(True, None, start) != "")


def test_append_dsh_patch():
    print("DSH patch 合并")
    import tempfile
    from pathlib import Path

    sys.path.insert(0, str(ROOT / "scripts"))
    import append_dsh_patch as A
    from ruamel.yaml import YAML

    def load(path):
        return YAML().load(Path(path).read_text(encoding="utf-8"))

    def ids(data):
        return [i.get("id") for i in (data or []) if isinstance(i, dict)]

    d = Path(tempfile.mkdtemp())

    # 1) 合法空列表 []（曾导致"报告成功但没注册"）
    f = d / "empty_list.yml"
    f.write_text("[]\n", encoding="utf-8")
    A.append(str(f), "/py", "/s.py")
    check("空列表 [] 能正确追加", ids(load(f)) == ["mcp-rqrun"], ids(load(f)))

    # 2) 只有注释，且注释里出现同名 id（不能被误判为已安装，注释也不能丢）
    f = d / "comment_only.yml"
    f.write_text("# 说明\n# id: mcp-rqrun\n", encoding="utf-8")
    status = A.append(str(f), "/py", "/s.py")
    text2 = f.read_text(encoding="utf-8")
    check("注释里的同名 id 不算已安装", status == "added" and ids(load(f)) == ["mcp-rqrun"])
    check("纯注释文件的注释被保留", "# 说明" in text2 and "# id: mcp-rqrun" in text2, text2[:40])

    # 2b) 多段注释 + 空行
    f2b = d / "comments_multi.yml"
    f2b.write_text("# 头注释\n\n# 第二段\n", encoding="utf-8")
    A.append(str(f2b), "/py", "/s.py")
    text2b = f2b.read_text(encoding="utf-8")
    check("多段注释都保留",
          "# 头注释" in text2b and "# 第二段" in text2b and ids(load(f2b)) == ["mcp-rqrun"])

    # 3) 追加到已有条目之后，保留原条目与头部注释
    f = d / "with_entries.yml"
    f.write_text("# 头注释\n- id: existing\n  config:\n    provider: deepseek-account\n",
                 encoding="utf-8")
    A.append(str(f), "/py", "/s.py")
    text = f.read_text(encoding="utf-8")
    check("原有条目保留且顺序在前", ids(load(f)) == ["existing", "mcp-rqrun"], ids(load(f)))
    check("头部注释保留", "# 头注释" in text)
    check("没粘行", "-account- id:" not in text)

    # 4) 末尾无换行
    f = d / "no_newline.yml"
    f.write_text("- id: existing\n  config:\n    x: 1", encoding="utf-8")
    A.append(str(f), "/py", "/s.py")
    check("无换行文件也能追加", ids(load(f)) == ["existing", "mcp-rqrun"])

    # 5) 已存在（按解析结果）则不重复写
    before = f.read_text(encoding="utf-8")
    status = A.append(str(f), "/py", "/s.py")
    check("已安装时不重复追加", status == "already" and f.read_text(encoding="utf-8") == before)

    # 6) 顶层不是列表要拒绝
    f = d / "bad.yml"
    f.write_text("key: value\n", encoding="utf-8")
    raised = False
    try:
        A.append(str(f), "/py", "/s.py")
    except SystemExit:
        raised = True
    check("顶层非列表时拒绝", raised and f.read_text(encoding="utf-8") == "key: value\n")


def main():
    test_sport_id()
    test_calendar_days()
    test_weekly_series()
    test_format_helpers()
    test_codex_merge()
    test_chart_pagination_boundary()
    test_month_total_fallback()
    test_period_all_branch()
    test_series_seconds()
    test_incomplete_note()
    test_append_dsh_patch()
    print()
    if FAILS:
        print(f"❌ {len(FAILS)} 项失败: {FAILS}")
        return 1
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
