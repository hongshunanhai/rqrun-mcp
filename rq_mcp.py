#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RQrun MCP Server —— 让 AI 直接读取你的 RQrun 训练数据。

用法:
    python3 rq_mcp.py login      # 弹出浏览器窗口，登录一次（30 天免登）
    python3 rq_mcp.py status     # 查看登录状态 / 账号概览
    python3 rq_mcp.py logout     # 退出并清除本地凭据
    python3 rq_mcp.py call <tool> [--args '{"k":"v"}']
    python3 rq_mcp.py            # 以 MCP stdio server 模式运行（默认）

设计要点:
  * 全站只有一个网关 /dc/api?_=模块/控制器/动作，认证仅靠 Cookie RQWEBSESSID
  * 该 Cookie 非 HttpOnly，因此登录窗口里可直接用 document.cookie 读取
  * 站点有 disable-devtool.js 反调试，登录时通过 CDP 阻断该脚本，且全程不开 DevTools
  * 只封装只读接口；发短信验证码、删除记录等写操作一律不暴露
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = "https://rq.run"
API = BASE + "/dc/api"
HOME = Path(os.environ.get("RQ_MCP_HOME", Path.home() / ".rq-mcp"))
SESSION = HOME / "session.json"
PROFILE = HOME / "chrome-profile"
CHROME_MAC = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

SPORT = {"1": "跑步", "2": "游泳", "3": "骑行", "5": "力量", "9": "徒步", "99": "其它"}
SPORT_ID = {"run": "1", "swim": "2", "ride": "3", "strength": "5", "hike": "9"}


# --------------------------------------------------------------------------
# 异常
# --------------------------------------------------------------------------
class AuthRequired(RuntimeError):
    def __init__(self, msg="尚未登录或登录已过期"):
        super().__init__(f"{msg}。请在终端运行:  python3 rq_mcp.py login")


class RQError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# 凭据
# --------------------------------------------------------------------------
def load_cookie() -> str | None:
    try:
        d = json.loads(SESSION.read_text())
        ck = d.get("cookie") or ""
        return ck if "RQWEBSESSID=" in ck else None
    except Exception:
        return None


def save_cookie(cookie: str) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    exp = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    SESSION.write_text(json.dumps({
        "cookie": cookie,
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "approx_expires": exp,
    }, ensure_ascii=False, indent=1))
    os.chmod(SESSION, 0o600)


def clear_cookie() -> None:
    for p in (SESSION,):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


# --------------------------------------------------------------------------
# HTTP 客户端
# --------------------------------------------------------------------------
def api(action: str, **params):
    """调用 RQrun 网关。action 形如 'User/Record/get_list'。"""
    ck = load_cookie()
    if not ck:
        raise AuthRequired()
    q = {"_": action}
    for k, v in params.items():
        if v is None or v == "":
            continue
        q[k] = v
    url = API + "?" + urllib.parse.urlencode(q, doseq=True)
    req = urllib.request.Request(url, headers={
        "Cookie": ck, "User-Agent": UA,
        "X-Requested-With": "XMLHttpRequest", "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.URLError as e:
        raise RQError(f"网络请求失败: {e}") from e
    st = body.get("status")
    if st in (401, 403):
        raise AuthRequired("登录已过期")
    if st != 0:
        raise RQError(body.get("error") or f"接口返回 status={st}")
    return body.get("data")


def api_html(path: str) -> str:
    """抓取服务端渲染的页面（RQ币余额等只在 HTML 里）。"""
    ck = load_cookie()
    if not ck:
        raise AuthRequired()
    req = urllib.request.Request(BASE + path, headers={"Cookie": ck, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    if "login.html" in r.geturl() or "登录/注册" in html[:4000]:
        raise AuthRequired("登录已过期")
    return html


# --------------------------------------------------------------------------
# 数据整形
# --------------------------------------------------------------------------
def pace_str(speed_kmh) -> str | None:
    """km/h -> 分'秒\"（配速）。实测 RQrun 的 speed 字段单位是 km/h。"""
    try:
        s = float(speed_kmh)
    except (TypeError, ValueError):
        return None
    if s <= 0.3:
        return None
    sec = int(round(3600 / s))
    return f"{sec // 60}'{sec % 60:02d}\""


def hms(seconds) -> str | None:
    try:
        t = int(float(seconds))
    except (TypeError, ValueError):
        return None
    h, m, s = t // 3600, t % 3600 // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def km(meters) -> float | None:
    try:
        return round(float(meters) / 1000, 2)
    except (TypeError, ValueError):
        return None


def num(v, nd=1):
    try:
        f = float(v)
        return int(f) if f == int(f) else round(f, nd)
    except (TypeError, ValueError):
        return None



def _sport_id(sport, default: str = "1") -> str:
    """把 run/swim/ride/hike、或数字 sport_id 统一成接口需要的字符串。

    非法值直接报错，避免"查骑行却返回跑步"这类静默错误。
    """
    if sport is None or str(sport).strip() == "":
        return default
    s = str(sport).strip().lower()
    if s in SPORT_ID:
        return SPORT_ID[s]
    if s.isdigit() and s in SPORT:
        return s
    raise RQError(f"未知运动类型: {sport}（可用 run/swim/ride/hike 或 sport_id 1/2/3/9/99）")


def compact(obj):
    """去掉 None 字段，压缩体积。"""
    if isinstance(obj, dict):
        return {k: compact(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [compact(v) for v in obj]
    return obj


def downsample(points: list, step: int) -> list:
    if step <= 1 or len(points) <= 2:
        return points
    out = points[::step]
    if points[-1] not in out:
        out.append(points[-1])
    return out


# --------------------------------------------------------------------------
# 登录：拉起 Chrome + CDP
# --------------------------------------------------------------------------
def _chrome_path() -> str:
    if sys.platform != "darwin":
        raise RQError("当前只支持 macOS。Windows 版登录将在后续提供。")
    if not os.path.exists(CHROME_MAC):
        raise RQError("未找到 Google Chrome，请先安装: https://www.google.com/chrome/")
    return CHROME_MAC


def _read_devtools_port(profile: Path, timeout=25.0) -> tuple[int, str]:
    f = profile / "DevToolsActivePort"
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            lines = f.read_text().splitlines()
            if len(lines) >= 2:
                return int(lines[0]), lines[1].strip()
        except Exception:
            pass
        time.sleep(0.2)
    raise RQError("Chrome 调试端口未就绪（可能已有同名用户目录的 Chrome 在运行）")


class CDP:
    """极简 CDP 客户端：只用 websockets 同步客户端，够登录场景使用。"""

    def __init__(self, ws_url: str):
        from websockets.sync.client import connect
        self.ws = connect(ws_url, max_size=64 * 1024 * 1024, open_timeout=20)
        self._id = 0
        self.session_id = None
        self._target_id = None

    def send(self, method: str, params: dict | None = None, sid: str | None = None):
        self._id += 1
        mid = self._id
        msg = {"id": mid, "method": method, "params": params or {}}
        if sid or self.session_id:
            msg["sessionId"] = sid or self.session_id
        self.ws.send(json.dumps(msg))
        while True:
            raw = self.ws.recv(timeout=25)
            data = json.loads(raw)
            if data.get("id") == mid:
                if "error" in data:
                    raise RQError(f"CDP {method} 失败: {data['error']}")
                return data.get("result", {})

    def attach_first_page(self):
        targets = self.send("Target.getTargets")["targetInfos"]
        pages = [t for t in targets if t["type"] == "page"]
        if not pages:
            self._target_id = self.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        else:
            self._target_id = pages[0]["targetId"]
        self.session_id = self.send("Target.attachToTarget",
                                    {"targetId": self._target_id, "flatten": True})["sessionId"]
        return self.session_id

    def eval(self, expr: str):
        r = self.send("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True, "awaitPromise": True})
        return r.get("result", {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def _cookie_valid(cookie: str) -> bool:
    req = urllib.request.Request(
        API + "?_=" + urllib.parse.quote("User/Analytics/is_opened"),
        headers={"Cookie": cookie, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode()).get("status") == 0
    except Exception:
        return False


def do_login_manual() -> int:
    """非 macOS 或自动登录失败时的兜底：手动粘贴 Cookie。"""
    print("请按下面步骤取一次 Cookie：")
    print("  1. 用浏览器登录 https://rq.run")
    print("  2. 登录完成后打开开发者工具 → Application(应用) → Cookies → https://rq.run")
    print("     （页面可能因反调试自动刷新，不影响已写入的 Cookie）")
    print("  3. 找到 RQWEBSESSID，复制它的值")
    print("")
    try:
        val = input("粘贴 RQWEBSESSID（直接回车取消）: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return 1
    if not val:
        print("已取消")
        return 1
    if val.lower().startswith("rqwebsessid="):
        val = val.split("=", 1)[1]
    val = val.strip().strip('"').strip("'")
    ck = f"RQWEBSESSID={val}"
    if _cookie_valid(ck):
        save_cookie(ck)
        print("✅ 登录成功，凭据已保存（约 30 天有效）")
        return 0
    print("❌ 这个 Cookie 校验没通过，可能复制不完整或已过期")
    return 2


def do_login(timeout_sec: int = 300) -> int:
    """拉起独立 Chrome 窗口，等用户登录完成后自动保存 Cookie。"""
    chrome = _chrome_path()
    HOME.mkdir(parents=True, exist_ok=True)
    PROFILE.mkdir(parents=True, exist_ok=True)

    # 已有有效会话则直接返回
    old = load_cookie()
    if old and _cookie_valid(old):
        print(f"✅ 已登录（本地凭据有效，约可用至 {json.loads(SESSION.read_text()).get('approx_expires')}）")
        print("   如需切换账号: python3 rq_mcp.py logout 后再 login")
        return 0

    try:
        (PROFILE / "DevToolsActivePort").unlink()
    except FileNotFoundError:
        pass

    args = [
        chrome,
        f"--user-data-dir={PROFILE}",
        "--remote-debugging-port=0",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--disable-features=Translate,MediaRouter",
        "--window-size=1020,780",
        "about:blank",
    ]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cdp = None
    try:
        port, path = _read_devtools_port(PROFILE)
        cdp = CDP(f"ws://127.0.0.1:{port}{path}")
        cdp.attach_first_page()

        # 关键：先阻断反调试脚本，再打开登录页
        cdp.send("Network.enable")
        cdp.send("Network.setBlockedURLs", {"urls": ["*disable-devtool*"]})
        cdp.send("Page.enable")
        cdp.send("Page.navigate", {"url": f"{BASE}/home/login/login"})

        print("🌐 已打开登录窗口，请在窗口里完成登录（账号密码 / 短信 / 微信扫码均可）")
        print("   登录成功后窗口会自动关闭，无需手动操作…")

        t0 = time.time()
        last = ""
        while time.time() - t0 < timeout_sec:
            if proc.poll() is not None:
                raise RQError("登录窗口被关闭了，请重新运行 login")
            try:
                raw = cdp.eval("document.cookie") or ""
            except Exception:
                raw = ""
            m = re.search(r"(?:^|;\s*)RQWEBSESSID=([^;]+)", raw)
            if m:
                cookie = f"RQWEBSESSID={m.group(1)}"
                if _cookie_valid(cookie):
                    save_cookie(cookie)
                    print("✅ 登录成功，凭据已保存（仅存本机，权限 600，约 30 天有效）")
                    return 0
                last = "已获取 Cookie 但校验未通过，继续等待…"
            time.sleep(0.5)
        raise RQError(f"等待登录超时（{timeout_sec} 秒）" + (f"：{last}" if last else ""))
    finally:
        if cdp:
            cdp.close()
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


# ==========================================================================
# 工具实现（只读）
# ==========================================================================
def _today() -> str:
    return date.today().isoformat()


def _range1(days: int) -> str:
    end = date.today()
    start = end - timedelta(days=days)
    return f"{start.isoformat()} ~ {end.isoformat()}"


def _calendar_probe_dates(first: date, last: date) -> list:
    """calendar_summary 一次只返回"包含指定日期的那一周"。

    从 first 所在周的周一开始，每 7 天探测一次，保证覆盖 last 所在周的整段。
    （此前从 first 本身开始累加，跨月时会漏掉月末那几天。）
    """
    cur = first - timedelta(days=first.weekday())
    out = []
    while cur <= last:
        out.append(cur)
        cur += timedelta(days=7)
    return out


def _weekly_series(rows, weeks: int, today: date | None = None) -> list:
    """把 [(date, km)] 聚合成最近 weeks 个自然周，**包含休息周**。

    返回按时间正序的列表，current 标记本周（可能是部分周）。
    """
    if int(weeks) < 1:
        raise RQError("weeks 必须 >= 1")
    weeks = int(weeks)
    today = today or date.today()
    curw = today - timedelta(days=today.weekday())
    keys = [curw - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    buckets: dict = {}
    for d, km in rows:
        buckets.setdefault(d - timedelta(days=d.weekday()), []).append(km)
    return [{
        "start": k,
        "km": round(sum(buckets.get(k, [])), 1),
        "n": len(buckets.get(k, [])),
        "current": k == curw,
    } for k in keys]


def t_get_profile() -> dict:
    hr = api("Api/Profile/get_user_hr_data", **{"data[sport_id]": 1})
    try:
        pb = api("Api/User/get_pb_contrast", sport_id=1)
    except RQError:
        pb = []
    coin = None
    try:
        html = api_html("/user/setting/account")
        m = re.search(r"RQ币余额</td>\s*<td>\s*(\d+)", html)
        coin = int(m.group(1)) if m else None
    except Exception:
        pass
    pbs = [{"项目": p.get("text"), "最新": p.get("new_grade"), "时间": p.get("new_at")}
           for p in (pb or []) if p.get("new_grade")]
    return compact({
        "最大心率": hr.get("run_max_hr"),
        "静息心率": hr.get("run_rest_hr"),
        "心率区间上限": {
            "1区下限": hr.get("e_min_hr"), "2区下限": hr.get("m_min_hr"),
            "3区下限": hr.get("t_min_hr"), "4区下限": hr.get("a_min_hr"),
            "5区下限": hr.get("i_min_hr"),
        },
        "RQ币余额": coin,
        "最好成绩": pbs,
    })


def t_list_activities(start_date: str | None = None, end_date: str | None = None,
                      sport: str | None = None, limit: int = 10) -> dict:
    sid = _sport_id(sport, default="") or None
    rows, page, fetched = [], 1, 0
    truncated = False
    MAX_PAGES = 200          # 100 条/页 => 最多回看 2 万条
    while len(rows) < limit:
        if page > MAX_PAGES:
            truncated = True
            break
        d = api("User/Record/get_list", page=page, limit=100, period_type="all")
        lst = d.get("list") or []
        if not lst:
            history_complete = True
            break
        fetched += len(lst)
        stop = False
        for r in lst:
            day = (r.get("training_at") or "")[:10]
            if end_date and day > end_date:
                continue
            if start_date and day < start_date:
                stop = True
                continue
            if sid and str(r.get("sport_id")) != sid:
                continue
            rows.append({
                "id": r.get("id"),
                "日期": day,
                "标题": r.get("title") or r.get("name"),
                "运动": SPORT.get(str(r.get("sport_id")), r.get("sport_id")),
                "距离_km": km(r.get("distance")),
                "时长": hms(r.get("total_time")),
                "配速": pace_str(r.get("avg_speed")),
                "平均心率": num(r.get("avg_hr"), 0),
                "负荷": num(r.get("total_point"), 1),
                "跑力": num(r.get("runlevel"), 1),
                "步频": num(r.get("avg_cadence"), 0),
            })
            if len(rows) >= limit:
                break
        total = d.get("total")
        if stop or (isinstance(total, int) and fetched >= total):
            break
        page += 1
    out = {"数量": len(rows), "记录": rows}
    if truncated:
        out["不完整"] = True
        out["提示"] = "日期超出单次可回看的历史深度，结果可能不完整"
    return compact(out)


def t_get_activity(activity_id: str, include_streams: bool = False,
                   resolution_sec: int = 30) -> dict:
    d = api("User/Record/get_record_info", record_id=activity_id,
            coordinate_id=3, student_user_id=0, group_id=0)
    sm, mo = d.get("summary") or {}, d.get("motion") or {}
    out = {
        "id": sm.get("id"),
        "标题": sm.get("name"),
        "日期": (sm.get("training_at") or "")[:10],
        "运动": SPORT.get(str(sm.get("sport_id")), sm.get("sport_id")),
        "距离_km": km(mo.get("distance")),
        "时长": hms(sm.get("total_time")),
        "平均配速": pace_str(mo.get("avg_speed")),
        "最快配速": pace_str(mo.get("max_speed")),
        "平均心率": num(mo.get("avg_hr"), 0),
        "最大心率": num(mo.get("max_hr"), 0),
        "步频": num(mo.get("avg_cadence"), 0),
        "步幅_米": num(mo.get("avg_step_length"), 2),
        "功率": num(mo.get("avg_power"), 0),
        "爬升_米": num(mo.get("total_ascent"), 0),
        "卡路里": num(mo.get("calorie"), 0),
        "训练负荷": num(mo.get("total_point"), 1),
        "跑力": num(mo.get("runlevel"), 1),
        "跑力变化": num(mo.get("runlevel_diff"), 1),
        "有GPS轨迹": (d.get("map") or {}).get("start_position_lat") not in (None, 360),
    }
    laps = []
    for i, lp in enumerate(d.get("lap") or [], 1):
        laps.append({
            "第": i, "距离_km": km(lp.get("total_distance")),
            "用时": hms(lp.get("total_timer_time")), "配速": pace_str(lp.get("avg_speed")),
            "心率": num(lp.get("avg_hr"), 0), "最大心率": num(lp.get("max_hr"), 0),
            "步频": num(lp.get("avg_cadence"), 0), "功率": num(lp.get("avg_power"), 0),
            "触地_ms": num(lp.get("avg_stance_time"), 0),
        })
    zones = []
    for z in d.get("hr_zone") or []:
        sec = num(z.get("value"), 0) or 0
        zones.append({"区": z.get("label"), "区间": z.get("hr_zone_content"),
                      "秒": sec, "时长": hms(sec)})
    if zones and sm.get("total_time"):
        tot = float(sm["total_time"]) or 1
        for z in zones:
            z["占比"] = f"{round(z['秒'] / tot * 100)}%"
    out["分段"] = laps
    out["心率区间"] = zones
    if include_streams:
        pts = downsample(d.get("trkpt") or [], max(1, int(resolution_sec)))
        def last(k):
            return [p.get(k) for p in pts]
        out["逐秒数据"] = {
            "采样间隔_秒": resolution_sec,
            "说明": "t=相对秒; pace=该点配速; hr=心率; cadence=步频; dist_km=累计公里",
            "t": [p.get("sec") for p in pts],
            "pace": [pace_str(p.get("speed")) for p in pts],
            "hr": last("heart_rate"),
            "cadence": last("cadence"),
            "power": last("power"),
            "dist_km": [km(p.get("distance")) for p in pts],
        }
    return compact(out)


def _series_total_seconds(items) -> float:
    """周期明细里逐条的 total_time 是秒，求和比接口顶层的小时字段精确。"""
    return sum(float(i.get("total_time") or 0) for i in (items or []))


def t_get_period_stats(period: str = "month", date_str: str | None = None,
                       sport: str | None = "run") -> dict:
    period = (period or "month").lower()
    sid = _sport_id(sport, "1")
    if period in ("all", "alltime", "total"):
        d = api("User/Mydata/record_data_all_total", student_user_id=0, group_id=0)
        return compact({
            "范围": "生涯",
            "总距离_km": num(d.get("total_distance"), 1),
            "总时长_小时": num(d.get("total_time"), 1),
            "总次数": d.get("total_count"),
            "总负荷": num(d.get("total_point"), 1),
            "平均配速": d.get("pace"),
            "平均心率": num(d.get("avg_hr"), 0),
            "当前跑力": num(d.get("last_runlevel"), 1),
            "跑者等级": d.get("user_rq_level"),
            "加入天数": d.get("join_days"),
            "全马次数": d.get("total_marathon_count"),
            "分年": [{"年": p.get("period"), "距离_km": p.get("total_distance"),
                      "配速": p.get("pace"), "负荷": num(p.get("total_point"), 1),
                      "跑力": p.get("last_runlevel")}
                     for p in (d.get("period_list") or [])],
        })
    today = date.today()
    ttype = {"year": 1, "month": 2, "week": 3, "custom": 4}.get(period, 2)
    if period == "year":
        ds = date_str or str(today.year)
    elif period == "week":
        ds = date_str or today.isoformat()
    elif period == "custom":
        if not date_str:
            raise RQError("custom 周期需要 date_str，格式 '2026-01-01 ~ 2026-11-04'")
        ds = date_str
    else:
        ds = date_str or today.strftime("%Y-%m")
    d = api("User/Mydata/record_data_period_total", date=ds, ttype=ttype,
            sport_id=sid, ver=1, student_user_id=0, group_id=0)
    # 注意：明细里 total_distance 已是 km，total_time 是秒（与顶层 km/小时 不同）
    items = d.get("period_list") or []
    exact_secs = _series_total_seconds(items)

    series = [{"期": p.get("day_str") or p.get("period"),
               "距离_km": num(p.get("total_distance"), 2),
               "时长": hms(p.get("total_time")),
               "负荷": num(p.get("total_point"), 1),
               "次数": p.get("count")}
              for p in items]
    series = [s for s in series if (s.get("距离_km") or 0) > 0][-30:]
    return compact({
        "范围": d.get("time_section") or ds,
        "起止": f"{d.get('start_date')} ~ {d.get('end_date')}",
        "距离_km": num(d.get("total_distance"), 1),
        "时长": hms(exact_secs) if exact_secs else hms((float(d.get("total_time") or 0)) * 3600),
        "次数": d.get("total_count"),
        "负荷": num(d.get("total_point"), 1),
        "平均配速": d.get("pace"),
        "平均心率": num(d.get("avg_hr"), 0),
        "平均步频": num(d.get("avg_cadence"), 0),
        "爬升_米": num(d.get("total_elev_gain"), 0),
        "当前跑力": num(d.get("last_runlevel"), 1),
        "明细": series,
        "最好成绩": [{"项目": b.get("best_name"), "成绩": b.get("best_time"),
                      "日期": b.get("best_day")}
                     for b in (d.get("best_record") or []) if b.get("best_time") not in (None, "-")],
    })


def t_get_training_status(days: int = 30) -> dict:
    r1 = _range1(days)
    trend = api("User/Analytics/module_training_trend", student_user_id=0,
                group_id=0, range1=r1) or []
    cond = api("User/Analytics/module_condition",
               date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               student_user_id=0, group_id=0)
    series = [{"日期": t.get("date"),
               "体能": num(t.get("fitness"), 2),
               "疲劳": num(t.get("fatigue"), 2),
               "状态": num(t.get("condition"), 2),
               "负荷": num(t.get("point"), 1)}
              for t in trend]
    return compact({
        "今日": {
            "体能": num(cond.get("fitness"), 2),
            "疲劳": num(cond.get("fatigue"), 2),
            "状态": num(cond.get("condition"), 2),
            "评估": cond.get("condition_title"),
            "说明": cond.get("condition_description"),
        },
        "本周": {"负荷": num(cond.get("week_total_point"), 1),
                 "距离_km": km(cond.get("week_total_distance"))},
        "恢复时间": {
            "完全休息_小时": round((cond.get("recovery_time_full") or 0) / 3600, 1),
            "减量50%_小时": round((cond.get("recovery_time_50") or 0) / 3600, 1),
            "减量20%_小时": round((cond.get("recovery_time_80") or 0) / 3600, 1),
        },
        "逐日": series,
        "说明": "体能≈CTL 疲劳≈ATL 状态=体能−疲劳(≈TSB)；状态为负说明疲劳累积",
    })


def t_get_runlevel() -> dict:
    cur = api("User/Analytics/module_current_runlevel", student_user_id=0, group_id=0)
    pred = api("User/Analytics/module_prediction", student_user_id=0, group_id=0)
    try:
        trend = api("User/Analytics/module_runlevel_trend", student_user_id=0,
                    group_id=0, range1=_range1(90)) or {}
    except RQError:
        trend = {}
    rl = trend.get("rlArr") or []
    pts = [{"日期": datetime.fromtimestamp(int(p["ts"])).strftime("%m-%d"),
            "跑力": num(p.get("crl"), 1)} for p in reversed(rl) if p.get("crl")]
    return compact({
        "当前跑力": num(cur.get("runlevel"), 1),
        "超越跑者": cur.get("overtake_rate"),
        "排名": f"{cur.get('rownum')} / {cur.get('self_user_count')}",
        "分组": cur.get("title"),
        "等级": cur.get("level"),
        "完赛预测": [{"项目": i.get("name"), "成绩": i.get("score"), "配速": i.get("pace")}
                     for i in (pred.get("items") or [])],
        "近90天跑力": pts[-40:],
    })


def t_get_intensity(days: int = 30) -> dict:
    r1 = _range1(days)
    secs = api("User/Analytics/module_intensity_secs", student_user_id=0, group_id=0, range1=r1)
    point = api("User/Analytics/module_intensity_point", student_user_id=0, group_id=0, range1=r1)
    out = {
        "区间": r1,
        "按时间": [{"区": i.get("name"), "配速口径": i.get("pace_time"),
                    "心率口径": i.get("hr_time")} for i in (secs.get("items") or [])],
        "按负荷": [{"区": i.get("name"), "负荷": num(i.get("point"), 1),
                    "占比": f"{num(i.get('point_ratio'), 0)}%"}
                   for i in (point.get("items") or [])],
    }
    for key, label in (("cadence", "步频"), ("step_length", "步幅_米"), ("gc_time", "触地_ms")):
        try:
            r = api("User/Analytics/module_skill", student_user_id=0, group_id=0,
                    sport_id=1, skill_type=key, range1=r1)
            out.setdefault("技术", {})[label] = [
                {"区": i.get("zone"), "值": num(i.get("value"), 2)} for i in (r.get("items") or [])]
        except RQError:
            pass
    return compact(out)


def t_get_calendar(month: str | None = None) -> dict:
    """按月返回每天的训练摘要。

    注意：calendar_summary 一次只返回「包含指定日期的那一周」7 天（type 不控制跨度），
    所以这里按周循环、拼出整月。
    """
    import calendar as _cal
    ym = month or date.today().strftime("%Y-%m")
    y, m = int(ym[:4]), int(ym[5:7])
    first = date(y, m, 1)
    last = date(y, m, _cal.monthrange(y, m)[1])
    days: dict[str, dict] = {}
    for probe in _calendar_probe_dates(first, last):
        d = api("User/Calendar/calendar_summary", type=1, date=probe.isoformat(),
                sport_id=0, student_user_id=0, group_id=0)
        for row in d.get("day_list") or []:
            for day in row.values():
                ds = day.get("date")
                if ds and first.isoformat() <= ds <= last.isoformat():
                    days[ds] = day
    out_days = []
    for ds in sorted(days):
        day = days[ds]
        if not day.get("record_count"):
            continue
        out_days.append({
            "日期": ds,
            "距离_km": km(day.get("distance")),
            "时长": hms(day.get("total_time")),
            "负荷": num(day.get("total_point"), 1),
            "记录": [{"id": r.get("id"), "标题": r.get("title"),
                      "距离_km": km(r.get("distance")),
                      "配速": pace_str(r.get("avg_speed")),
                      "负荷": num(r.get("total_point"), 1)}
                     for r in (day.get("records") or [])],
        })
    return compact({
        "月份": ym,
        "训练天数": len(out_days),
        "距离_km": num(sum((d.get("distance") or 0) for d in days.values()) / 1000, 1),
        "负荷": num(sum((d.get("total_point") or 0) for d in days.values()), 1),
        "每天": out_days,
    })

# ==========================================================================
# 图表渲染（Pillow，无浏览器依赖，可直接作为图片返回给 agent）
# ==========================================================================
BG = (255, 255, 255)
INK = (29, 29, 31)
MUTED = (110, 110, 115)
FAINT = (174, 174, 178)
GREEN = (35, 172, 56)
GREEN_DK = (15, 110, 34)
GREEN_LT = (99, 206, 114)
ORANGE = (245, 135, 31)
GRAYLN = (154, 154, 162)
CARD = (247, 248, 249)
HAIR = (239, 239, 242)

_FONTS: dict = {}


# 跨平台中文字体候选（按优先级）：macOS → Linux → Windows
_FONT_BOLD_PATHS = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]
_FONT_REG_PATHS = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
]
_RESOLVED_FONT: dict = {}


def _find_font(bold: bool):
    cache_key = bool(bold)
    if cache_key in _RESOLVED_FONT:
        return _RESOLVED_FONT[cache_key]
    import os as _os
    for path in (_FONT_BOLD_PATHS if bold else _FONT_REG_PATHS):
        if _os.path.exists(path):
            _RESOLVED_FONT[cache_key] = path
            return path
    _RESOLVED_FONT[cache_key] = None
    return None


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    key = (size, bold)
    if key in _FONTS:
        return _FONTS[key]
    path = _find_font(bold)
    f = None
    if path:
        try:
            f = ImageFont.truetype(path, size)
        except Exception:
            f = None
    if f is None:
        try:
            f = ImageFont.load_default(size=size)
        except TypeError:
            f = ImageFont.load_default()
    _FONTS[key] = f
    return f


def _dashed(d, p1, p2, fill, width=3, dash=12, gap=9):
    import math
    x1, y1 = p1
    x2, y2 = p2
    total = math.hypot(x2 - x1, y2 - y1)
    if total == 0:
        return
    ux, uy = (x2 - x1) / total, (y2 - y1) / total
    pos = 0.0
    while pos < total:
        end = min(pos + dash, total)
        d.line([(x1 + ux * pos, y1 + uy * pos), (x1 + ux * end, y1 + uy * end)],
               fill=fill, width=width)
        pos = end + gap


def _pace_txt(sec: float) -> str:
    s = int(round(sec))
    return f"{s // 60}'{s % 60:02d}\""


def _hm(sec: float) -> str:
    s = int(round(sec))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _stat_cards(d, x0, x1, y, items, h=126):
    n = len(items)
    gap = 22
    w = (x1 - x0 - gap * (n - 1)) / n
    for i, (k, v, sub, color) in enumerate(items):
        cx0 = x0 + i * (w + gap)
        cx1 = cx0 + w
        d.rounded_rectangle([cx0, y, cx1, y + h], radius=18, fill=CARD)
        d.text((cx0 + 26, y + 26), k, font=_font(23), fill=MUTED, anchor="la")
        d.text((cx0 + 26, y + 62), v, font=_font(38, True), fill=color or INK, anchor="la")
        if sub:
            vw = d.textlength(v, font=_font(38, True))
            d.text((cx0 + 32 + vw, y + 74), sub, font=_font(21), fill=MUTED, anchor="la")


def _chart_activity(activity_id: str) -> bytes:
    from PIL import Image, ImageDraw
    import io

    d0 = api("User/Record/get_record_info", record_id=activity_id,
             coordinate_id=3, student_user_id=0, group_id=0)
    sm, mo = d0.get("summary") or {}, d0.get("motion") or {}
    laps = []
    for lp in d0.get("lap") or []:
        dist = float(lp.get("total_distance") or 0)
        t = float(lp.get("total_timer_time") or 0)
        if dist < 200:
            continue
        laps.append({"km": len(laps) + 1, "pace": t / (dist / 1000.0),
                     "hr": float(lp.get("avg_hr") or 0),
                     "cad": float(lp.get("avg_cadence") or 0)})
    if not laps:
        raise RQError("这条记录没有可用分段数据")

    W, H = 2000, 1220
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    title = sm.get("name") or "训练"
    day = (sm.get("training_at") or "")[:10]
    dist_km = float(mo.get("distance") or 0) / 1000
    avg_speed = float(mo.get("avg_speed") or 0) or 1
    d.text((96, 74), f"{day}  {title}", font=_font(46, True), fill=INK, anchor="la")
    d.text((96, 138),
           f"{dist_km:.2f} km · {_hm(sm.get('total_time') or 0)} · 平均配速 {_pace_txt(3600/avg_speed)}"
           f" · 平均心率 {int(float(mo.get('avg_hr') or 0))} · 步频 {int(float(mo.get('avg_cadence') or 0))}",
           font=_font(25), fill=MUTED, anchor="la")
    d.text((96, 208), "每公里配速与心率", font=_font(30, True), fill=INK, anchor="la")

    X0, X1 = 236, 1904
    TOP, BASE = 296, 790
    PH = BASE - TOP
    mx_p = max(l["pace"] for l in laps)
    mn_p = min(l["pace"] for l in laps)
    pLo, pHi = mx_p + 45, mn_p - 25          # 慢 -> 快

    # 左侧配速刻度
    for i in range(5):
        y = BASE - PH * i / 4
        pace_at = pLo - (i / 4) * (pLo - pHi)
        d.line([(X0, y), (X1, y)], fill=HAIR, width=2)
        d.text((X0 - 24, y), _pace_txt(pace_at), font=_font(22), fill=FAINT, anchor="rm")

    n = len(laps)
    slot = (X1 - X0) / n
    bw = min(88, slot * 0.52)
    for i, l in enumerate(laps):
        cx = X0 + slot * i + slot / 2
        h = PH * (pLo - l["pace"]) / (pLo - pHi)
        y = BASE - h
        fast = l["pace"] <= mn_p + 0.5
        d.rounded_rectangle([cx - bw / 2, y, cx + bw / 2, BASE], radius=14,
                            fill=GREEN_DK if fast else GREEN)
        d.text((cx, y - 18), _pace_txt(l["pace"]), font=_font(27, True), fill=INK, anchor="ms")
        d.text((cx, BASE + 30), f"{l['km']} km", font=_font(23), fill=MUTED, anchor="ma")

    # 心率曲线
    hpts = []
    for i, l in enumerate(laps):
        cx = X0 + slot * i + slot / 2
        y = BASE - PH * (l["hr"] - 105) / 82
        hpts.append((cx, max(TOP - 10, min(BASE, y)), l["hr"]))
    d.line([(x, y) for x, y, _ in hpts], fill=ORANGE, width=5, joint="curve")
    for cx, y, hr in hpts:
        d.ellipse([cx - 8, y - 8, cx + 8, y + 8], fill=BG, outline=ORANGE, width=4)
    # 右侧心率刻度
    for hr_t in (110, 130, 150, 170):
        y = BASE - PH * (hr_t - 105) / 82
        if TOP - 30 <= y <= BASE + 6:
            d.text((X1 + 20, y), str(hr_t), font=_font(21), fill=ORANGE, anchor="lm")

    # 步频虚线
    cpts = []
    for i, l in enumerate(laps):
        cx = X0 + slot * i + slot / 2
        y = BASE - PH * (l["cad"] - 150) / 64
        cpts.append((cx, max(TOP - 10, min(BASE, y))))
    for a, b in zip(cpts, cpts[1:]):
        _dashed(d, a, b, GRAYLN, width=3)
    for cx, y in cpts:
        d.ellipse([cx - 5, y - 5, cx + 5, y + 5], fill=GRAYLN)

    # 图例
    lx = 96
    for color, label in ((GREEN, "配速（柱）"), (ORANGE, "心率 bpm"), (GRAYLN, "步频 spm")):
        d.rounded_rectangle([lx, 856, lx + 26, 864], radius=4, fill=color)
        d.text((lx + 36, 860), label, font=_font(22), fill=MUTED, anchor="lm")
        lx += 36 + d.textlength(label, font=_font(22)) + 40

    # 心率区间条
    total_sec = float(sm.get("total_time") or 0) or 1
    zones = [(z.get("label"), float(z.get("value") or 0)) for z in (d0.get("hr_zone") or [])]
    fill_a = total_sec - sum(v for _, v in zones)
    segs = ([("恢复/热身", fill_a, (202, 202, 207))] if fill_a > 1 else []) + [
        (lab, v, GREEN if i == 0 else GREEN_LT) for i, (lab, v) in enumerate(zones) if v > 0]
    ty = 952
    d.text((96, ty - 46), "心率区间分布", font=_font(26, True), fill=INK, anchor="la")
    bx = 96
    for lab, v, color in segs:
        w = (X1 - 96) * v / total_sec
        d.rounded_rectangle([bx, ty, bx + max(3, w), ty + 44], radius=9, fill=color)
        if w > 170:
            d.text((bx + 18, ty + 22), f"{lab} {round(v / total_sec * 100)}%",
                   font=_font(21), fill=INK if color == (202, 202, 207) else (255, 255, 255),
                   anchor="lm")
        bx += w

    rl = mo.get("runlevel")
    _stat_cards(d, 96, X1, 1044, [
        ("训练负荷", f"{float(mo.get('total_point') or 0):.1f}", "", INK),
        ("即时跑力", f"{float(rl):.1f}" if rl else "—", "", INK),
        ("平均步频", f"{int(float(mo.get('avg_cadence') or 0))}", "spm", INK),
        ("平均心率", f"{int(float(mo.get('avg_hr') or 0))}", "bpm", INK),
    ])

    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _month_total_km(today, sid, rows, oldest, history_complete=False):
    """本月累计。

    正常走周期接口；接口失败时**只有确认分页已覆盖到月初**才用本地求和，
    否则返回 (None, 说明)，避免把部分数据当成整月展示。
    """
    month_start = today.replace(day=1)
    try:
        st = api("User/Mydata/record_data_period_total", date=today.strftime("%Y-%m"),
                 ttype=2, sport_id=sid, ver=1, student_user_id=0, group_id=0)
        return float(st.get("total_distance") or 0), ""
    except RQError:
        # 只有"确认月初当天的记录也全读完了"才能本地求和：
        #   history_complete    -> 历史已读完，天然覆盖整月
        #   oldest < month_start -> 严格更早，说明月初当天已翻页翻完
        if history_complete or (oldest is not None and oldest < month_start):
            return sum(km for d, km in rows if d >= month_start), ""
        return None, "暂不可用"


def _chart_volume(weeks: int = 10, sport: str = "run") -> bytes:
    from PIL import Image, ImageDraw
    import io

    sid = _sport_id(sport, "1")
    weeks = int(weeks)
    if weeks < 1:
        raise RQError("weeks 必须 >= 1")
    weeks = min(weeks, 52)

    today = date.today()
    curw = today - timedelta(days=today.weekday())
    target_start = curw - timedelta(weeks=weeks - 1)

    rows, page, oldest, hit_cap, history_complete = [], 1, None, False, False
    MAX_PAGES = 200                      # 100 条/页 => 最多回看 2 万条
    while True:
        if page > MAX_PAGES:
            hit_cap = True
            break
        d = api("User/Record/get_list", page=page, limit=100, period_type="all")
        lst = d.get("list") or []
        if not lst:
            break
        for r in lst:
            day = date.fromisoformat((r.get("training_at") or "")[:10])
            if oldest is None or day < oldest:
                oldest = day
            if str(r.get("sport_id")) != sid:
                continue
            rows.append((day, float(r.get("distance") or 0) / 1000))
        if len(lst) < 100:
            history_complete = True
            break                        # 历史读完了
        if oldest and oldest < target_start:
            break                        # 严格更早，目标日当天的记录才不会被截断
        page += 1
    if not rows:
        raise RQError("没有可用的训练记录")

    # 只有"被页数上限截断"才算数据不完整；读完了历史则前面的周是真的没跑
    note = ""
    if hit_cap and (oldest is None or oldest > target_start):
        note = f"※ 仅回溯到 {oldest}，更早的周未计入"

    series = _weekly_series(rows, weeks, today=today)
    bars = [{"label": f"{w['start'].month}/{w['start'].day}",
             "km": w["km"], "n": w["n"], "cur": w["current"]} for w in series]

    # 本月累计单独走周期接口；失败时不会拿部分数据冒充整月
    month_km, month_note = _month_total_km(today, sid, rows, oldest, history_complete)

    W, H = 2000, 1180
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.text((96, 76), f"{date.today().month} 月跑量", font=_font(48, True), fill=INK, anchor="la")
    d.text((96, 144), f"近 {len(bars)} 周 · 单位 km · 每周一起算", font=_font(25), fill=MUTED, anchor="la")

    X0, X1 = 190, 1904
    BASE, TOP = 860, 300
    PH = BASE - TOP
    mx = max(b["km"] for b in bars) or 1
    for i in range(5):
        y = BASE - PH * i / 4
        d.line([(X0, y), (X1, y)], fill=HAIR, width=2)
        d.text((X0 - 22, y), f"{mx*i/4:.0f}", font=_font(22), fill=FAINT, anchor="rm")

    n = len(bars)
    slot = (X1 - X0) / n
    bw = min(96, slot * 0.52)
    for i, b in enumerate(bars):
        cx = X0 + slot * i + slot / 2
        h = max(6, PH * b["km"] / mx)
        y = BASE - h
        d.rounded_rectangle([cx - bw / 2, y, cx + bw / 2, BASE], radius=14,
                            fill=GREEN_DK if b["cur"] else GREEN)
        d.text((cx, y - 18), f"{b['km']:g}", font=_font(26, True), fill=INK, anchor="ms")
        d.text((cx, BASE + 34), b["label"], font=_font(23, True) if b["cur"] else _font(23),
               fill=INK if b["cur"] else MUTED, anchor="ma")
        d.text((cx, BASE + 66), "本周" if b["cur"] else f"{b['n']}次",
               font=_font(21), fill=GREEN if b["cur"] else FAINT, anchor="ma")

    if note:
        d.text((96, 946), note, font=_font(22), fill=(196, 96, 32), anchor="la")

    total_km = sum(b["km"] for b in bars)
    avg = total_km / max(1, len(bars))
    _stat_cards(d, 96, X1, 1000, [
        ("近 %d 周总量" % len(bars), f"{total_km:.0f}", "km", INK),
        ("周均", f"{avg:.1f}", "km", INK),
        ("本月累计", f"{month_km:.1f}" if month_km is not None else "—",
         "km" if month_km is not None else month_note,
         GREEN if month_km is not None else MUTED),
        ("完成周数", f"{sum(1 for b in bars if b['km'] > 0)}", f"/ {len(bars)}", INK),
    ])

    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ==========================================================================
# MCP Server
# ==========================================================================
def _out(obj) -> str:
    return json.dumps(compact(obj), ensure_ascii=False, separators=(",", ":"))


def _guard(fn):
    """把内部异常翻译成对 agent 有意义的错误信息。"""
    import functools
    from mcp.server.mcpserver.tools.base import ToolError

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except AuthRequired as e:
            raise ToolError(str(e)) from e
        except RQError as e:
            raise ToolError(f"RQrun 接口错误：{e}") from e
    return wrapper


def build_server():
    from mcp.server.mcpserver import MCPServer

    mcp = MCPServer(
        "rqrun",
        version="0.1.0",
        instructions=(
            "RQrun（rq.run）训练数据分析。先用 list_activities 找记录 id，"
            "再用 get_activity 取单次详情；长期趋势用 get_training_status / get_runlevel / get_intensity。"
            "数据单位已统一为 公里/秒/配速字符串。"
        ),
    )

    @mcp.tool(description="账号概览：最大/静息心率、心率区间阈值、各项最好成绩、RQ币余额。")
    @_guard
    def get_profile() -> str:
        return _out(t_get_profile())

    @mcp.tool(description=(
        "训练记录列表（按时间倒序）。可按起止日期与运动类型过滤，"
        "返回每次的距离/时长/配速/心率/负荷/跑力。用于先定位到具体某次训练。"))
    @_guard
    def list_activities(start_date: str | None = None, end_date: str | None = None,
                        sport: str | None = None, limit: int = 10) -> str:
        return _out(t_list_activities(start_date, end_date, sport, limit))

    @mcp.tool(description=(
        "单次训练的完整数据：总览、每公里分段、心率区间分布；"
        "include_streams=true 时附带按秒降采样后的配速/心率/步频序列（默认 30 秒一个点）。"))
    @_guard
    def get_activity(activity_id: str, include_streams: bool = False,
                     resolution_sec: int = 30) -> str:
        return _out(t_get_activity(activity_id, include_streams, resolution_sec))

    @mcp.tool(description=(
        "周期汇总统计。period 取 year/month/week/custom/all；"
        "sport 取 run/swim/ride/hike 或其 sport_id。返回总量、均配速、均心率、分期明细与期间最好成绩。"))
    @_guard
    def get_period_stats(period: str = "month", date_str: str | None = None,
                         sport: str | None = "run") -> str:
        return _out(t_get_period_stats(period, date_str, sport))

    @mcp.tool(description=(
        "训练状态：今日体能/疲劳/状态（≈CTL/ATL/TSB）、恢复所需时间、近 N 天逐日曲线。"
        "判断是否过度训练、是否需要减量时优先用它。"))
    @_guard
    def get_training_status(days: int = 30) -> str:
        return _out(t_get_training_status(days))

    @mcp.tool(description="当前跑力、超越百分比与年龄组排名、各距离完赛成绩预测、近 90 天跑力走势。")
    @_guard
    def get_runlevel() -> str:
        return _out(t_get_runlevel())

    @mcp.tool(description=(
        "强度分布：各强度区的时间（配速口径与心率口径两套）与训练负荷占比，"
        "以及分强度区的步频/步幅/触地时间等技术指标。"))
    @_guard
    def get_intensity(days: int = 30) -> str:
        return _out(t_get_intensity(days))

    @mcp.tool(description="日历视图：指定月份（YYYY-MM）有记录的日期与当天训练摘要。")
    @_guard
    def get_calendar(month: str | None = None) -> str:
        return _out(t_get_calendar(month))

    @mcp.tool(name="login", description=(
        "打开 RQrun 登录窗口。用户说「登录 RQrun」，或任何工具返回未登录时调用。"
        "会弹出一个独立的浏览器窗口，用户在窗口里正常登录（密码/短信/微信扫码均可），"
        "登录成功后自动保存凭据，约 30 天免登。"))
    @_guard
    def login() -> str:
        import contextlib
        ck = load_cookie()
        if ck and _cookie_valid(ck):
            exp = ""
            try:
                exp = json.loads(SESSION.read_text()).get("approx_expires") or ""
            except Exception:
                pass
            return json.dumps({"ok": True, "already": True,
                               "message": f"已是登录状态，无需重新登录（约可用至 {exp}）"},
                              ensure_ascii=False)
        # 关键：MCP 的 stdio 用 stdout 传协议，do_login 的提示必须改走 stderr
        with contextlib.redirect_stdout(sys.stderr):
            rc = do_login()
        return json.dumps(
            {"ok": rc == 0, "already": False,
             "message": "登录成功，凭据已保存（约 30 天有效）" if rc == 0 else "登录未完成，请重试"},
            ensure_ascii=False)

    @mcp.tool(name="render_chart", description=(
        "把训练数据画成图，直接以图片返回（不需要任何外部工具）。"
        "kind='activity' 画单次训练的每公里配速、心率、步频曲线（需 activity_id）；"
        "kind='volume' 画近 N 周跑量柱状图（weeks 默认 10）。"))
    @_guard
    def render_chart(kind: str = "activity", activity_id: str | None = None, weeks: int = 10):
        from mcp.server.mcpserver import Image as MCPImage
        k = (kind or "activity").strip().lower()
        if k.startswith("vol") or k in ("weeks", "跑量"):
            png = _chart_volume(int(weeks))
        else:
            if not activity_id:
                from mcp.server.mcpserver.tools.base import ToolError
                raise ToolError("kind='activity' 需要 activity_id，请先用 list_activities 查到记录 id")
            png = _chart_activity(str(activity_id))
        return MCPImage(data=png, format="png")

    return mcp


# ==========================================================================
# CLI
# ==========================================================================
def cmd_status() -> int:
    ck = load_cookie()
    if not ck:
        print("❌ 未登录。运行:  python3 rq_mcp.py login")
        return 1
    ok = _cookie_valid(ck)
    meta = {}
    try:
        meta = json.loads(SESSION.read_text())
    except Exception:
        pass
    print(("✅ 登录有效" if ok else "⚠️  凭据存在但已失效"))
    print(f"   保存于: {meta.get('saved_at')}   预计到期: {meta.get('approx_expires')}")
    print(f"   凭据文件: {SESSION} (权限 {oct(SESSION.stat().st_mode)[-3:]})")
    if ok:
        try:
            d = t_get_profile()
            print(f"   最大心率 {d.get('最大心率')} / 静息 {d.get('静息心率')} / RQ币 {d.get('RQ币余额')}")
        except Exception as e:
            print(f"   (概览获取失败: {e})")
    return 0 if ok else 2


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        build_server().run()
        return 0

    cmd = argv[0]
    try:
        if cmd == "login":
            if "--manual" in argv:
                return do_login_manual()
            return do_login()
        if cmd == "logout":
            clear_cookie()
            shutil.rmtree(PROFILE, ignore_errors=True)
            print("✅ 已清除本地凭据与登录配置")
            return 0
        if cmd == "status":
            return cmd_status()
        if cmd == "call":
            if len(argv) < 2:
                print("用法: python3 rq_mcp.py call <tool> [--args '{...}']")
                return 1
            tool = argv[1]
            args = {}
            if "--args" in argv:
                args = json.loads(argv[argv.index("--args") + 1])
            fn = {
                "get_profile": t_get_profile,
                "list_activities": t_list_activities,
                "get_activity": t_get_activity,
                "get_period_stats": t_get_period_stats,
                "get_training_status": t_get_training_status,
                "get_runlevel": t_get_runlevel,
                "get_intensity": t_get_intensity,
                "get_calendar": t_get_calendar,
            }.get(tool)
            if not fn:
                print(f"未知工具: {tool}")
                return 1
            print(json.dumps(compact(fn(**args)), ensure_ascii=False, indent=1))
            return 0
        if cmd in ("serve", "mcp"):
            build_server().run()
            return 0
        print(__doc__)
        return 1
    except AuthRequired as e:
        print(f"❌ {e}")
        return 2
    except RQError as e:
        print(f"❌ {e}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
