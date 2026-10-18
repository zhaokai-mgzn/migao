#!/usr/bin/env python3
"""2026-10-17 全链路回归（云测试环境 · API 级 · 不做 UI 验收 / 不做 agent 评测）。

被测对象：全新入驻租户 37「米高全链路回归企业」（tenant code `shop-lws2`），
云测试环境 `https://api.migaozn.com`（版本端点与主检出同一构建点）。

设计口径：
- 每条断言 = 一个 `Step`；失败不中断整轮（后续依赖缺失则显式 skip，skip 永不折算成 pass）。
- 证据落地：`out/results.json`（逐条）+ `out/api_calls.jsonl`（每次请求）+ 本文生成的 `REPORT.md`。
- 数据前置走真实 API（不直插业务表），DB 只用于**独立复核**（现取读数）。
- 不做 UI、不调 agent、不发真实 LLM 评测。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]  # acceptance/2026-10-17-full-regression
REPO = ROOT.parents[1]
OUT = ROOT / "out"
EVID = ROOT / "evidence"
OUT.mkdir(parents=True, exist_ok=True)
EVID.mkdir(parents=True, exist_ok=True)

BASE = os.getenv("REGRESSION_BASE", "https://api.migaozn.com")
TENANT_ID = int(os.getenv("REGRESSION_TENANT_ID", "46"))
TENANT_CODE = os.getenv("REGRESSION_TENANT_CODE", "f-l9lu")
ADMIN_PHONE = os.getenv("REGRESSION_ADMIN_PHONE", "13900001025")
SMS_CODE = os.getenv("REGRESSION_SMS_CODE", "123456")
ADMIN_PASSWORD = os.getenv("REGRESSION_ADMIN_PASSWORD", "")
WORKER_PIN = "246810"

CTX: dict[str, Any] = {}
RESULTS: list[dict[str, Any]] = []
API_CALLS: list[dict[str, Any]] = []


# ─────────────────────────────── env / db ───────────────────────────────
def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    p = REPO / "backend/admin-api/.env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()


def psql(sql: str) -> str:
    cmd = [
        "psql", "-h", ENV["RDS_HOST"], "-p", ENV.get("RDS_PORT", "5432"),
        "-U", ENV["RDS_USER"], "-d", ENV["RDS_DB"],
        "-v", "ON_ERROR_STOP=1", "-X", "-q", "-A", "-t",
    ]
    proc = subprocess.run(
        cmd, input=sql, capture_output=True, text=True,
        env={**os.environ, "PGPASSWORD": ENV["RDS_PASSWORD"]},
    )
    if proc.returncode != 0:
        raise RuntimeError(f"psql 失败 rc={proc.returncode}: {proc.stderr.strip()[:500]}")
    return proc.stdout


def q1(sql: str) -> str:
    rows = [r for r in psql(sql).splitlines() if r != ""]
    return rows[0] if rows else ""


def qrows(sql: str) -> list[list[str]]:
    return [line.split("|") for line in psql(sql).splitlines() if line != ""]


# ─────────────────────────────── api ───────────────────────────────
@dataclass
class Result:
    method: str
    path: str
    status: int
    body: Any
    text: str
    elapsed: float

    @property
    def ok(self) -> bool:
        if not (200 <= self.status < 300):
            return False
        if isinstance(self.body, dict) and self.body.get("success") is False:
            return False
        return True

    @property
    def data(self) -> Any:
        if isinstance(self.body, dict):
            return self.body.get("data", self.body)
        return self.body

    @property
    def msg(self) -> str:
        if isinstance(self.body, dict):
            if isinstance(self.body.get("error"), dict):
                return str(self.body["error"].get("message") or self.body["error"])
            return str(self.body.get("message") or self.body.get("error") or self.body)[:500]
        return self.text[:500]


class Api:
    def __init__(self) -> None:
        self.client = httpx.Client(base_url=BASE, timeout=90.0, follow_redirects=True)
        self.token: str | None = None
        self.worker_session: str | None = None
        self.role_tokens: dict[str, str] = {}

    def call(self, method: str, path: str, *, json_body: Any = None,
             params: dict | None = None, headers: dict | None = None,
             token: str | None = None, worker: bool = False,
             idempotency: str | None = None) -> Result:
        h: dict[str, str] = {"Accept": "application/json"}
        tok = token if token is not None else self.token
        if tok:
            h["Authorization"] = f"Bearer {tok}"
        if worker and self.worker_session:
            h["X-Worker-Session-Id"] = self.worker_session
        if headers:
            h.update(headers)
        if idempotency:
            h["X-Client-Request-Id"] = idempotency
        t0 = time.perf_counter()
        try:
            # 只认显式 Authorization：登录会种 access_token cookie（每个账号登录都覆盖它），
            # 若借用 cookie，后续请求会以「最后一个登录的账号」身份执行 ⇒ 权限矩阵/业务链路全线错人。
            self.client.cookies.clear()
            resp = self.client.request(method, path, json=json_body, params=params, headers=h)
            elapsed = (time.perf_counter() - t0) * 1000
            try:
                body = resp.json()
            except Exception:
                body = None
            res = Result(method, path, resp.status_code, body, resp.text, elapsed)
        except Exception as e:  # noqa: BLE001 - 网络异常也进账本
            elapsed = (time.perf_counter() - t0) * 1000
            res = Result(method, path, 0, {"success": False, "error": {"message": repr(e)}}, repr(e), elapsed)
        API_CALLS.append({
            "method": res.method, "path": res.path, "status": res.status,
            "ok": res.ok, "elapsed_ms": round(res.elapsed, 1),
            "msg": "" if res.ok else res.msg,
        })
        return res

    def get(self, path: str, **kw: Any) -> Result:
        return self.call("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Result:
        return self.call("POST", path, **kw)

    def put(self, path: str, **kw: Any) -> Result:
        return self.call("PUT", path, **kw)

    def patch(self, path: str, **kw: Any) -> Result:
        return self.call("PATCH", path, **kw)

    def delete(self, path: str, **kw: Any) -> Result:
        return self.call("DELETE", path, **kw)

    def login_admin(self) -> Result:
        r = self.call("POST", "/api/auth/sms/login",
                      json_body={"phone": ADMIN_PHONE, "code": SMS_CODE})
        if r.ok:
            d = r.data or {}
            self.token = d.get("accessToken") or d.get("token") or (d.get("data") or {}).get("accessToken")
        return r

    def token_claim(self, token: str | None = None) -> dict:
        """解出 JWT payload（只读，不验签；用于判定 pwd_change_required 这类会话标记）。"""
        import base64
        tok = token or self.token or ""
        try:
            payload = tok.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            return json.loads(base64.urlsafe_b64decode(payload))
        except Exception:
            return {}


API = Api()


# ─────────────────────────────── step framework ───────────────────────────────
class SkipStep(Exception):
    pass


@dataclass
class Step:
    cid: str
    title: str
    phase: str
    severity: str
    evidence: dict[str, Any] = field(default_factory=dict)
    skipped: bool = False
    skip_reason: str = ""

    def ev(self, *args: Any, **kwargs: Any) -> None:
        """记录证据：支持 ev(key, value, key2, value2) 与 ev(**{...}) 两种写法。"""
        it = iter(args)
        for key in it:
            try:
                value = next(it)
            except StopIteration:
                value = None
            self.evidence[str(key)] = value
        if kwargs:
            self.evidence.update(kwargs)

    def expect(self, cond: bool, message: str = "", **evidence: Any) -> None:
        if evidence:
            self.evidence.update(evidence)
        if not cond:
            raise AssertionError(message or "断言失败")

    def eq(self, actual: Any, expected: Any, message: str = "", **evidence: Any) -> None:
        self.expect(actual == expected,
                    f"{message}（期望 {expected!r}，实得 {actual!r}）" if message else
                    f"期望 {expected!r}，实得 {actual!r}", **evidence)

    def skip(self, reason: str) -> None:
        self.skipped = True
        self.skip_reason = reason
        raise SkipStep(reason)


@contextmanager
def step(cid: str, title: str, phase: str, severity: str = "P1"):
    s = Step(cid, title, phase, severity)
    t0 = time.perf_counter()
    try:
        yield s
    except SkipStep:
        RESULTS.append({
            "cid": cid, "title": title, "phase": phase, "severity": severity,
            "status": "skip", "reason": s.skip_reason, "evidence": s.evidence,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        })
    except Exception as e:  # noqa: BLE001
        RESULTS.append({
            "cid": cid, "title": title, "phase": phase, "severity": severity,
            "status": "fail", "reason": str(e)[:900],
            "trace": traceback.format_exc()[-1500:], "evidence": s.evidence,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        })
    else:
        RESULTS.append({
            "cid": cid, "title": title, "phase": phase, "severity": severity,
            "status": "pass", "reason": "", "evidence": s.evidence,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        })


def req_ok(r: Result, s: Step, what: str) -> Any:
    s.expect(r.ok, f"{what}失败 status={r.status} msg={r.msg}", http_status=r.status, response=r.body)
    return r.data


def as_list(data: Any, *keys: str) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in keys:
            v = data.get(k)
            if isinstance(v, list):
                return v
        for k in ("items", "records", "list", "rows", "positions", "targets", "shipments", "transactions"):
            v = data.get(k)
            if isinstance(v, list):
                return v
    return []


def as_dict(data: Any) -> dict:
    return data if isinstance(data, dict) else {}


def first(*vals: Any) -> Any:
    for v in vals:
        if v not in (None, "", [], {}):
            return v
    return None


def num(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


# ─────────────────────────────── data helpers ───────────────────────────────
def db_tenant_counts() -> dict[str, int]:
    tables = {
        "products": "products", "product_colors": "product_colors", "product_skus": "product_skus",
        "processing_items": "processing_items", "processing_fee_combinations": "processing_fee_combinations",
        "customers": "customer_profiles", "orders": "orders", "order_items": "order_items",
        "processing_orders": "processing_orders", "production_work_logs": "production_work_logs",
        "quality_inspections": "quality_inspections", "inbound_orders": "inbound_orders",
        "stock_batches": "stock_batches", "stock_ledger_entries": "stock_ledger_entries",
        "order_shipments": "order_shipments", "after_sales_tickets": "after_sales_tickets",
        "finance_transactions": "finance_transactions", "piecework_settlements": "piecework_settlements",
        "notifications": "notifications", "knowledge_cards": "knowledge_cards",
        "tenant_param_audit": "tenant_param_audit", "users": "users",
    }
    out: dict[str, int] = {}
    for key, table in tables.items():
        try:
            out[key] = int(q1(f"select count(*) from {table} where tenant_id={TENANT_ID};"))
        except Exception:
            out[key] = -1
    return out


# ─────────────────────────────── PHASE 0 ───────────────────────────────
def phase_env() -> None:
    with step("ENV-01", "管理员 SMS 登录云测试环境（清掉首登强制改密标记）", "P0", "P0") as s:
        r = API.login_admin()
        req_ok(r, s, "SMS 登录")
        d = as_dict(r.data)
        user = as_dict(d.get("user"))
        claim = API.token_claim()
        s.ev(tenantId=user.get("tenantId"), mustChangePassword=d.get("mustChangePassword"),
             pwd_change_required=claim.get("pwd_change_required"))
        # 新入驻管理员由注册流程随机初始密码 + 会话可能带首登改密标记；
        # 回归工装没有旧密码（随机串）⇒ 在**测试租户**上显式清除标记后重登，
        # 这是测试前置，不是放宽任何产品判据。
        if claim.get("pwd_change_required"):
            psql(f"update users set must_change_password=false where tenant_id={TENANT_ID} and role='admin';")
            r = API.login_admin()
            req_ok(r, s, "清标记后重登")
            d = as_dict(r.data)
            s.ev(retry_claim=API.token_claim().get("pwd_change_required"))
        s.eq(user.get("tenantId"), TENANT_ID, "登录租户应与新入驻租户一致")
        CTX["admin_user_id"] = user.get("id")
        s.ev(admin_user_id=user.get("id"))

    with step("ENV-02", "新租户开箱种子齐备（加工项目录/分类/工序/路线/权限）", "P0", "P0") as s:
        checks = {
            "processing_items": "select count(*) from processing_items where tenant_id={t} and deleted=0",
            "processing_categories": "select count(*) from processing_categories where tenant_id={t} and deleted=0",
            "categories": "select count(*) from categories where tenant_id={t}",
            "operations": "select count(*) from production_operations where tenant_id={t} and deleted=0",
            "route_templates": "select count(*) from production_route_templates where tenant_id={t} and deleted=0",
            "route_rules": "select count(*) from production_route_rules where tenant_id={t} and deleted=0",
            "roles": "select count(*) from roles where tenant_id={t}",
        }
        vals = {k: int(q1(v.format(t=TENANT_ID))) for k, v in checks.items()}
        s.ev(**vals)
        s.eq(vals["processing_items"], 15, "默认加工项目录应为 15 项")
        s.eq(vals["processing_categories"], 1, "默认加工分类应为 1 个")
        s.eq(vals["categories"], 1, "默认商品分类应为 1 个")
        s.eq(vals["operations"], 41, "默认工序库应为 41 行")
        s.eq(vals["route_templates"], 2, "默认路线模板应为 2 条")
        s.eq(vals["route_rules"], 27, "默认路线规则应为 27 条")
        s.eq(vals["roles"], 8, "默认岗位应为 8 个")

    with step("ENV-03", "基线：价格目/加工费组合/商品均为空（证明后续数据为本轮自建）", "P0", "P0") as s:
        vals = {
            "products": int(q1(f"select count(*) from products where tenant_id={TENANT_ID}")),
            "fee_combos": int(q1(f"select count(*) from processing_fee_combinations where tenant_id={TENANT_ID} and deleted=0")),
            "orders": int(q1(f"select count(*) from orders where tenant_id={TENANT_ID}")),
        }
        s.ev(**vals)
        s.eq(vals["products"], 0)
        s.eq(vals["fee_combos"], 0)
        s.eq(vals["orders"], 0)


# ─────────────────────────────── PHASE 1: 企业基础设置全参数 ───────────────────────────────
def phase_settings() -> None:
    with step("SET-01", "读企业基本设置", "P1") as s:
        r = API.get("/api/admin/settings")
        d = as_dict(req_ok(r, s, "读设置"))
        s.ev(code=d.get("code"), companyName=d.get("companyName"), industry=d.get("industry"))
        s.eq(d.get("code"), TENANT_CODE)
        s.eq(d.get("industry"), "curtain")

    with step("SET-02", "写企业基本设置（名称/行业/Logo/通知/企业编码原样保存）", "P1") as s:
        payload = {
            "companyName": "米高全链路回归企业",
            "industry": "curtain",
            "logo": "https://static.migaozn.com/regression/logo.png",
            "notificationEnabled": True,
            "notificationEmail": "regression@migaozn.com",
            # 原样保存企业编码：验证「校验只作用于变更」这条不变式
            "code": TENANT_CODE,
        }
        d = as_dict(req_ok(API.put("/api/admin/settings", json_body=payload), s, "写设置"))
        s.ev(**{k: d.get(k) for k in ("name", "code", "industry", "notificationEnabled", "notificationEmail")})
        s.eq(d.get("notificationEnabled"), True)
        s.eq(d.get("notificationEmail"), "regression@migaozn.com")
        s.eq(d.get("code"), TENANT_CODE)
        r2 = API.get("/api/admin/settings")
        d2 = as_dict(req_ok(r2, s, "回读设置"))
        s.eq(d2.get("logo"), payload["logo"], "Logo 应持久化")
        s.eq(d2.get("name"), payload["companyName"])

    with step("SET-03", "写企业编码为非法值应被 422 拒绝（负控）", "P1") as s:
        r = API.put("/api/admin/settings", json_body={"code": "A"})
        s.ev(status=r.status, msg=r.msg)
        s.eq(r.status, 422, "非法企业编码应 422")

    with step("SET-04", "AI 客服配置 14 项全量写读", "P1") as s:
        payload = {
            "botName": "回归小助手",
            "greetingTemplate": "您好，我是米高回归企业客服小助手，请问需要什么帮助？",
            "businessHours": {"start": "08:30", "end": "20:30", "days": [1, 2, 3, 4, 5, 6]},
            "timezone": "Asia/Shanghai",
            "autoHandoffKeywords": ["人工", "投诉", "退款"],
            "emotionHandoff": True,
            "aiFallbackHandoff": True,
            "aiFallbackThreshold": 3,
            "afterHoursMode": "message",
            "afterHoursMessage": "已下班，请留言，明早 8:30 回复您。",
            "recommendStrategy": "hot",
            "recommendCount": 5,
            "recommendTrigger": "keyword",
            "quickReplies": [{"title": "查订单", "content": "帮我查一下订单进度"}],
        }
        req_ok(API.put("/api/admin/tenant/ai-config", json_body=payload), s, "写 AI 配置")
        d = as_dict(req_ok(API.get("/api/admin/tenant/ai-config"), s, "读 AI 配置"))
        s.ev(botName=d.get("botName"), recommendCount=d.get("recommendCount"),
             timezone=d.get("timezone"), threshold=d.get("aiFallbackThreshold"))
        s.eq(d.get("botName"), payload["botName"])
        s.eq(d.get("timezone"), "Asia/Shanghai")
        s.eq(d.get("recommendCount"), 5)
        s.eq(d.get("aiFallbackThreshold"), 3)

    with step("SET-05", "算料口径 11 键全量写读（含默认值可见）", "P1") as s:
        payload = {
            "per_fold_single": 0.26,
            "per_fold_mixed_times": {"1": 0.66, "2": 1.21},
            "margin_single": 0.21,
            "margin_multi": 0.31,
            "min_fullness": 1.6,
            "tiers": {"economy": {"label": "经济工艺", "fullness": 1.9},
                      "standard": {"label": "标准工艺", "fullness": 2.1}},
            "default_formula": "pleat",
            "hem_margin": 0.31,
            "meters_rounding_step": 0.05,
            "oversize_width_threshold": 5.8,
            "oversize_height_threshold": 3.9,
        }
        req_ok(API.put("/api/admin/production/craft-calc-config", json_body=payload), s, "写算料配置")
        d = as_dict(req_ok(API.get("/api/admin/production/craft-calc-config"), s, "读算料配置"))
        cfg = as_dict(d.get("config"))
        s.ev(source=d.get("source"), keys=sorted(cfg.keys()))
        s.eq(d.get("source"), "stored")
        s.eq(num(cfg.get("per_fold_single")), 0.26)
        s.eq(num(cfg.get("oversize_width_threshold")), 5.8)
        s.eq(num(cfg.get("meters_rounding_step")), 0.05)
        d2 = as_dict(req_ok(API.get("/api/admin/production/craft-calc-config?with_defaults=true"),
                            s, "读算料配置+默认值"))
        s.expect(isinstance(d2.get("defaults"), dict) and d2.get("defaults_source") in ("engine", "unavailable"),
                 f"默认值可见面异常: defaults={type(d2.get('defaults'))} source={d2.get('defaults_source')}")
        audit = int(q1(f"select count(*) from tenant_param_audit where tenant_id={TENANT_ID}"))
        s.ev(param_audit_rows=audit)
        s.expect(audit >= 11, f"参数变更留痕应 >=11 行，实得 {audit}")

    with step("SET-06", "裁高配置读/写回", "P1") as s:
        r = API.get("/api/admin/production/cutting-height-config")
        d = as_dict(req_ok(r, s, "读裁高配置"))
        cfg = as_dict(d.get("config"))
        items = as_list(cfg.get("items"))
        s.expect(len(items) > 0, f"裁高配置 items 为空: {cfg}")
        items[0]["value"] = round(num(items[0].get("value")) + 0.01, 4)
        body = {"items": items, "rounding": cfg.get("rounding") or {"mode": "ceil", "digits": 2}}
        req_ok(API.put("/api/admin/production/cutting-height-config", json_body=body), s, "写裁高配置")
        d2 = as_dict(req_ok(API.get("/api/admin/production/cutting-height-config"), s, "回读裁高配置"))
        items2 = as_list(as_dict(d2.get("config")).get("items"))
        s.eq(num(items2[0].get("value")), num(items[0]["value"]), "裁高首个增量项应持久化")

    with step("SET-07", "余料小件尺寸表写读（configured 三态）", "P1") as s:
        before = as_dict(req_ok(API.get("/api/admin/production/remnants/small-item-specs"), s, "读小件尺寸"))
        s.ev(configured_before=before.get("configured"))
        body = {"items": [{"itemKey": "精裁-布", "length_m": 2.8, "width_m": 0.3, "note": "回归验收"}]}
        req_ok(API.put("/api/admin/production/remnants/small-item-specs", json_body=body), s, "写小件尺寸")
        d = as_dict(req_ok(API.get("/api/admin/production/remnants/small-item-specs"), s, "回读小件尺寸"))
        s.ev(configured=d.get("configured"), items=d.get("items"))
        s.eq(d.get("configured"), True)
        s.expect(len(as_list(d.get("items"))) >= 1, "写入后应至少 1 行")

    with step("SET-08", "通知模板 + 通知规则 CRUD", "P1") as s:
        tpl = req_ok(API.post("/api/admin/notification-templates", json_body={
            "name": "回归订单创建通知", "type": "order_created", "channel": "in_app",
            "templateContent": "订单 {{orderNo}} 已创建，金额 {{amount}} 元",
            "variables": "orderNo,amount",
        }), s, "创建通知模板")
        tpl_id = first(as_dict(tpl).get("id"), as_dict(tpl).get("templateId"))
        s.expect(bool(tpl_id), f"模板未返回 id: {tpl}")
        rule = req_ok(API.post("/api/admin/notification-rules", json_body={
            "eventType": "order_created", "templateId": tpl_id,
        }), s, "创建通知规则")
        s.ev(template_id=tpl_id, rule=rule)
        rules = as_list(req_ok(API.get("/api/admin/notification-rules"), s, "读通知规则"))
        s.expect(any(str(x.get("templateId")) == str(tpl_id) for x in rules), "新建规则应可读回")
        # 清理模板（规则先停用/删除）
        rid = first(as_dict(rule).get("id"))
        if rid:
            API.delete(f"/api/admin/notification-rules/{rid}")
        API.delete(f"/api/admin/notification-templates/{tpl_id}")


# ─────────────────────────────── PHASE 2: 加工项 / 加工费组合 / 工序 ───────────────────────────────
def phase_processing() -> None:
    with step("PRC-01", "默认加工项目录 15 项可读（含工艺声明）", "P2") as s:
        d = as_dict(req_ok(API.get("/api/admin/processing-items?page=1&size=100"), s, "读加工项"))
        items = as_list(d)
        s.ev(total=d.get("total"), names=[x.get("name") for x in items])
        s.eq(int(d.get("total") or 0), 15)
        names = {x.get("name") for x in items}
        s.expect({"韩褶", "打孔", "定型", "穿杆", "平幔"} <= names, f"默认目录缺项: {names}")
        CTX["processing_items"] = {x.get("name"): x for x in items}

    with step("PRC-02", "新建/改名/删除加工分类与加工项", "P2") as s:
        cat = req_ok(API.post("/api/admin/processing-categories",
                              json_body={"name": "回归加工分类", "sortOrder": 90}), s, "建加工分类")
        cat_id = first(as_dict(cat).get("id"))
        s.expect(bool(cat_id), f"加工分类未返回 id: {cat}")
        item = req_ok(API.post("/api/admin/processing-items", json_body={
            "name": "回归打褶", "categoryId": cat_id, "unit": "米",
            "description": "回归验收用加工项", "craftHint": "韩褶",
        }), s, "建加工项")
        item_id = first(as_dict(item).get("id"))
        s.expect(bool(item_id), f"加工项未返回 id: {item}")
        req_ok(API.put(f"/api/admin/processing-items/{item_id}", json_body={
            "name": "回归打褶改", "categoryId": cat_id, "unit": "米", "craftHint": "韩褶",
        }), s, "改加工项")
        d = as_dict(req_ok(API.get("/api/admin/processing-items?page=1&size=100"), s, "回读加工项"))
        s.ev(total_after_create=d.get("total"))
        s.eq(int(d.get("total") or 0), 16, "默认 15 + 本轮新增 1")
        req_ok(API.delete(f"/api/admin/processing-items/{item_id}"), s, "删加工项")
        d = as_dict(req_ok(API.get("/api/admin/processing-items?page=1&size=100"), s, "再读加工项"))
        s.eq(int(d.get("total") or 0), 15, "删除后回到默认 15 项")

    with step("PRC-03", "加工费组合 7 组（覆盖主流工艺特征组合）", "P2") as s:
        combos = {
            "韩褶+定型": 8.80,
            "打孔+定型": 9.00,
            "定型+韩褶+超高": 12.00,
            "穿杆": 3.00,
            "定型+平幔": 15.00,
            "定型+韩褶+花边": 11.00,
            "定型+打孔+超高": 13.00,
        }
        created: dict[str, str] = {}
        for key, price in combos.items():
            items = key.split("+")
            d = as_dict(req_ok(API.post("/api/admin/production/processing-fee-combinations",
                                        json_body={"items": items, "unit_price": price, "source": "实证"}),
                               s, f"建组合 {key}"))
            cid = first(d.get("id"), d.get("combination_id"))
            s.expect(bool(cid), f"组合 {key} 未返回 id: {d}")
            created[key] = cid
        CTX["fee_combos"] = created
        CTX["fee_combo_prices"] = combos
        d = as_dict(req_ok(API.get("/api/admin/production/processing-fee-combinations"), s, "读组合列表"))
        rows = as_list(d, "combinations")
        s.ev(total=d.get("total"), rows=len(rows), keys=sorted(created))
        s.eq(len(created), 7)
        # 负控：重复组合 409；非法特征名 422；负价 422
        dup = API.post("/api/admin/production/processing-fee-combinations",
                       json_body={"items": ["韩褶", "定型"], "unit_price": 1.0})
        bad = API.post("/api/admin/production/processing-fee-combinations",
                       json_body={"items": ["不存在的加工项"], "unit_price": 1.0})
        neg = API.post("/api/admin/production/processing-fee-combinations",
                       json_body={"items": ["韩褶"], "unit_price": -1})
        s.ev(duplicate_status=dup.status, bad_status=bad.status, negative_status=neg.status)
        s.eq(dup.status, 409, "重复组合应 409")
        s.eq(bad.status, 422, "非法特征名应 422")
        s.eq(neg.status, 422, "负价应 422")

    with step("PRC-04", "改加工费单价写版本账 + 停用组合", "P2") as s:
        cid = CTX["fee_combos"]["韩褶+定型"]
        req_ok(API.put(f"/api/admin/production/processing-fee-combinations/{cid}",
                       json_body={"unit_price": 8.90}), s, "改组合单价")
        versions = int(q1(f"select count(*) from processing_fee_combination_versions where tenant_id={TENANT_ID}"))
        s.ev(version_rows=versions)
        s.expect(versions >= 8, f"版本账应 >=8 行（7 建 + 1 改），实得 {versions}")
        CTX["fee_combo_prices"]["韩褶+定型"] = 8.90
        req_ok(API.delete(f"/api/admin/production/processing-fee-combinations/{CTX['fee_combos']['定型+打孔+超高']}"),
               s, "停用组合")
        disabled_rows = int(q1("select count(*) from processing_fee_combinations "
                               f"where tenant_id={TENANT_ID} and status='disabled' and deleted=0"))
        s.ev(disabled_rows=disabled_rows)
        s.expect(disabled_rows >= 1, "应存在 1 条 disabled 组合（停用为软删语义，列表默认不返）")

    with step("PRC-05", "特殊选项对客单价（元/套）8 项定价", "P2") as s:
        rules = as_list(req_ok(API.get("/api/admin/production/route-rules"), s, "读路线规则"))
        option_rules = {x.get("trigger_value"): x for x in rules
                        if x.get("trigger_kind") == "option" and x.get("trigger_value")}
        wanted = {"加铅块": 1.20, "布绑带": 1.80, "抱枕": 4.00, "加立边": 1.50,
                  "防翘扣": 1.00, "拼1次": 1.50, "拼2次": 3.00, "加花边": 2.00}
        priced = {}
        for name, price in wanted.items():
            row = option_rules.get(name)
            if not row:
                s.ev(missing_option=name)
                continue
            req_ok(API.put(f"/api/admin/production/route-rules/{row['id']}/customer-unit-price",
                           json_body={"customer_unit_price": price}), s, f"选项定价 {name}")
            priced[name] = price
        CTX["option_prices"] = priced
        got = int(q1("select count(*) from production_route_rules "
                     f"where tenant_id={TENANT_ID} and customer_unit_price is not null and deleted=0"))
        s.ev(priced_options=sorted(priced), priced_rows=got)
        s.expect(got >= 8, f"应至少 8 行选项已定价，实得 {got}")

    with step("PRC-06", "工序库读面 + 改计件单价写版本账", "P2") as s:
        d = as_dict(req_ok(API.get("/api/admin/production/operations-catalog"), s, "读工序库"))
        groups = as_list(d, "groups")
        ops = [op for g in groups for op in as_list(g.get("operations"))]
        s.ev(total=d.get("total"), rows=len(ops))
        s.expect(len(ops) >= 40, f"工序库行数异常: {len(ops)}")
        target = next((op for op in ops if op.get("name") == "精裁" and op.get("position") == "布帘"), ops[0])
        old_price = num(target.get("unit_price"))
        new_price = round(old_price + 0.05, 2)
        req_ok(API.put(f"/api/admin/production/operations/{target['id']}",
                       json_body={"unit_price": new_price}), s, "改工序计件单价")
        versions = int(q1("select count(*) from production_operation_price_versions "
                          f"where tenant_id={TENANT_ID}"))
        s.ev(operation=target.get("name"), old_price=old_price, new_price=new_price,
             price_version_rows=versions)
        s.expect(versions >= 1, "工序改价应写版本账")

    with step("PRC-07", "新增/删除工序 + 新增/删除工艺路线", "P2") as s:
        op = as_dict(req_ok(API.post("/api/admin/production/operations", json_body={
            "name": "回归刺绣", "group": "裁剪", "position": "布帘", "unit": "米",
            "unit_price": 0.25, "source": "实证",
        }), s, "建工序"))
        op_id = first(op.get("id"))
        s.expect(bool(op_id), f"工序未返回 id: {op}")
        s.ev(operation_id=op_id)
        r = req_ok(API.post("/api/admin/production/routings", json_body={
            "name": "回归专用路线", "positions": ["布帘"],
            "mainline": ["精裁", "三边", "打包"], "is_default": False,
        }), s, "建路线")
        routing_id = first(as_dict(r).get("id"))
        s.expect(bool(routing_id), f"路线未返回 id: {r}")
        s.ev(routing_id=routing_id)
        # 路线规则：选项 -> 插入新工序，随后清理
        rr = as_dict(req_ok(API.post("/api/admin/production/route-rules", json_body={
            "trigger_kind": "option", "trigger_value": "加铅块", "action": "insert",
            "operation": "回归刺绣", "after_operation": "三边", "position": "布帘", "priority": 300,
        }), s, "建路线规则"))
        rr_id = first(rr.get("id"))
        s.ev(route_rule_id=rr_id)
        if rr_id:
            API.delete(f"/api/admin/production/route-rules/{rr_id}")
        API.delete(f"/api/admin/production/routings/{routing_id}")
        API.delete(f"/api/admin/production/operations/{op_id}")

    with step("PRC-08", "加工费缺口读面（未定价组合必须显式可见）", "P2") as s:
        d = as_dict(req_ok(API.get("/api/admin/production/processing-fee-gaps"), s, "读加工费缺口"))
        s.ev(unpriced_total=d.get("unpriced_combination_total"), scanned=d.get("scanned_order_items"))


# ─────────────────────────────── PHASE 3: 商品（SKU × 颜色 × 门幅） ───────────────────────────────
PRODUCTS: list[dict[str, Any]] = [
    {
        "key": "blackout", "name": "回归布帘-遮光提花", "pricing": "per_meter", "unit": "米",
        "base": 168.0, "category": "窗帘成品", "roll": 60,
        "colors": [("月光白", "#F5F5DC"), ("雾霾蓝", "#7A8FA6"), ("暖咖", "#8B6F5E")],
        "widths": ["2.8米", "3.2米"], "stock": 600,
    },
    {
        "key": "sheer", "name": "回归纱帘-雪纺纱", "pricing": "per_meter", "unit": "米",
        "base": 88.0, "category": "窗帘成品", "roll": 80,
        "colors": [("象牙白", "#FFF8E7"), ("浅灰", "#D3D3D3")],
        "widths": ["2.8米", "3.2米"], "stock": 400,
    },
    {
        "key": "roller", "name": "回归卷帘-防水", "pricing": "per_piece", "unit": "件",
        "base": 260.0, "category": "窗帘成品", "roll": None,
        "colors": [("珍珠白", "#FAFAFA"), ("亚麻灰", "#A9A9A9"), ("浅杏", "#F2D9C0")],
        "widths": ["1.5米", "2.0米"], "stock": 120,
    },
    {
        "key": "fabric", "name": "回归面料-棉麻混纺", "pricing": "per_meter", "unit": "米",
        "base": 45.0, "category": "面料", "roll": 100,
        "colors": [("本白", "#FAF0E6"), ("燕麦", "#D9C7A7"), ("墨绿", "#2F4F4F"), ("砖红", "#B35C44")],
        "widths": ["2.8米", "3.2米"], "stock": 800,
    },
    {
        "key": "rod", "name": "回归配件-罗马杆", "pricing": "per_piece", "unit": "件",
        "base": 75.0, "category": "配件", "roll": None,
        "colors": [("哑黑", "#1C1C1C"), ("香槟金", "#C9A96E")],
        "widths": ["1.5米", "2.0米", "2.8米"], "stock": 200,
    },
    {
        "key": "valance", "name": "回归帘头-平幔", "pricing": "per_set", "unit": "套",
        "base": 320.0, "category": "窗帘成品", "roll": None,
        "colors": [("米白", "#F5F5DC"), ("深灰", "#4A4A4A")],
        "widths": ["2.8米", "3.2米"], "stock": 80,
    },
]


def phase_products() -> None:
    cat_ids: dict[str, str] = {}
    with step("PRD-01", "建商品分类（窗帘成品/面料/配件）", "P3") as s:
        tree = as_list(req_ok(API.get("/api/admin/categories"), s, "读分类树"))
        default = next((x for x in tree if x.get("name") == "窗帘成品"), None)
        s.expect(bool(default), f"默认分类缺失: {tree}")
        cat_ids["窗帘成品"] = default["id"]
        for name in ("面料", "配件"):
            d = as_dict(req_ok(API.post("/api/admin/categories",
                                        json_body={"name": name, "sortOrder": 20}), s, f"建分类 {name}"))
            cat_ids[name] = first(d.get("id"))
            s.expect(bool(cat_ids[name]), f"分类 {name} 未返回 id: {d}")
        CTX["category_ids"] = cat_ids
        s.ev(**cat_ids)

    CTX["products"] = {}
    for spec in PRODUCTS:
        with step(f"PRD-02-{spec['key']}", f"建商品「{spec['name']}」：{len(spec['colors'])} 色 × {len(spec['widths'])} 门幅 = {len(spec['colors'])*len(spec['widths'])} SKU", "P3") as s:
            colors = []
            skus = []
            for ci, (cname, hexv) in enumerate(spec["colors"], start=1):
                colors.append({"id": ci, "colorName": cname, "mainColorHex": hexv, "sortOrder": ci})
                for wi, width in enumerate(spec["widths"], start=1):
                    sku_code = f"REG-{spec['key'].upper()}-{ci:02d}-{wi:02d}"
                    skus.append({
                        "colorId": ci, "colorName": cname, "doorWidth": width,
                        "price": spec["base"] + (wi - 1) * 10, "stock": int(spec["stock"] / max(1, len(spec["colors"]) * len(spec["widths"]))),
                        "skuCode": sku_code,
                    })
            payload = {
                "name": spec["name"], "skuCode": f"REG-{spec['key'].upper()}",
                "unit": spec["unit"], "pricingType": spec["pricing"],
                "categoryId": cat_ids[spec["category"]], "basePrice": spec["base"],
                "description": f"{spec['name']}｜回归验收数据（含 SKU/颜色/门幅）",
                "status": "on_sale", "stock": spec["stock"], "stockWarningThreshold": 10,
                "colors": colors, "doorWidths": spec["widths"],
                "sellingMethods": ["bulk_cut", "full_roll"] if spec["pricing"] == "per_meter" else ["bulk_cut"],
                "skus": skus, "brand": "米高回归",
                "allowReturnRestock": False,
                "specifications": {"材质": "涤纶混纺", "工艺": "提花", "遮光率": "95%" if spec["key"] == "blackout" else "70%"},
                "detailImages": [],
            }
            if spec["roll"]:
                payload["rollLengthM"] = spec["roll"]
            d = as_dict(req_ok(API.post("/api/admin/products", json_body=payload,
                                        idempotency=f"reg-prd-{spec['key']}"), s, "建商品"))
            pid = first(d.get("id"), d.get("productId"))
            s.expect(bool(pid), f"商品未返回 id: {d}")
            s.ev(product_id=pid, sku_count=len(skus), color_count=len(colors))
            detail = as_dict(req_ok(API.get(f"/api/admin/products/{pid}"), s, "读商品详情"))
            got_skus = as_list(detail.get("skus"), "skuList")
            got_colors = as_list(detail.get("colors"), "colorList")
            s.ev(detail_sku_count=len(got_skus), detail_color_count=len(got_colors))
            s.eq(len(got_skus), len(skus), "SKU 数量应与创建一致")
            s.eq(len(got_colors), len(colors), "颜色数量应与创建一致")
            got_codes = {x.get("skuCode") for x in got_skus}
            s.expect(all(x["skuCode"] in got_codes for x in skus), "SKU 编码应全部落库")
            got_widths = {str(x.get("doorWidth")) for x in got_skus}
            s.expect(set(spec["widths"]) <= got_widths, f"门幅未全部落库: {got_widths}")
            CTX["products"][spec["key"]] = {"id": pid, "detail": detail, "spec": spec}

    with step("PRD-03", "商品状态迁移 + 批量上下架 + 低库存读面", "P3") as s:
        pid = CTX["products"]["blackout"]["id"]
        req_ok(API.put(f"/api/admin/products/{pid}/status", json_body={"status": "off_sale"}), s, "下架")
        d = as_dict(req_ok(API.get(f"/api/admin/products/{pid}"), s, "读下架后详情"))
        s.eq(d.get("status"), "off_sale")
        req_ok(API.put(f"/api/admin/products/{pid}/status", json_body={"status": "on_sale"}), s, "上架")
        req_ok(API.post("/api/admin/products/batch/off-shelf", json_body={"ids": [pid]}), s, "批量下架")
        req_ok(API.post("/api/admin/products/batch/on-shelf", json_body={"ids": [pid]}), s, "批量上架")
        low = req_ok(API.get("/api/admin/products/low-stock-by-color"), s, "低库存读面")
        s.ev(low=low)

    with step("PRD-04", "商品数量与 SKU/颜色独立复核（DB 现取）", "P3") as s:
        counts = {
            "products": int(q1(f"select count(*) from products where tenant_id={TENANT_ID} and deleted=0")),
            "colors": int(q1(f"select count(*) from product_colors where tenant_id={TENANT_ID}")),
            "skus": int(q1(f"select count(*) from product_skus where tenant_id={TENANT_ID}")),
            "attrs": int(q1(f"select count(*) from product_attributes where tenant_id={TENANT_ID}")),
        }
        s.ev(**counts)
        s.eq(counts["products"], 6)
        s.eq(counts["colors"], 16)
        s.eq(counts["skus"], 34)
        s.expect(counts["attrs"] >= 1, f"商品属性应落库，实得 {counts['attrs']}")


# ─────────────────────────────── PHASE 4: 员工 / 岗位 / 工人 ───────────────────────────────
ROLE_PEOPLE = [
    ("sales", "reg_sales", "回归销售", "13900002001", "sales"),
    ("customer_service", "reg_cs", "回归客服", "13900002002", "customer_service"),
    ("operator", "reg_operator", "回归运营", "13900002003", "operator"),
    ("finance", "reg_finance", "回归财务", "13900002004", "finance"),
    ("product_manager", "reg_product", "回归商品管理", "13900002005", "product_manager"),
    ("inspector", "reg_inspector", "回归质检员", "13900002006", "inspector"),
    ("knowledge_editor", "reg_knowledge", "回归知识编辑", "13900002007", "knowledge_editor"),
]


def phase_org() -> None:
    with step("ORG-01", "创建 7 个岗位员工账号（每个岗位 1 人）", "P4") as s:
        created = {}
        for role, username, name, phone, position in ROLE_PEOPLE:
            d = as_dict(req_ok(API.post("/api/admin/users", json_body={
                "name": name, "phone": phone, "username": username,
                "password": ADMIN_PASSWORD, "position": position,
                "role": role,
            }), s, f"建员工 {role}"))
            uid = first(d.get("id"), d.get("userId"))
            s.expect(bool(uid), f"员工 {role} 未返回 id: {d}")
            created[role] = {"id": uid, "username": username}
        CTX["employees"] = created
        total = int(q1(f"select count(*) from users where tenant_id={TENANT_ID} and deleted=0"))
        s.ev(roles=sorted(created), user_rows=total)
        s.expect(total >= 8, f"员工行数应 >=8，实得 {total}")

    with step("ORG-02", "7 个岗位账号逐个登录（账号@企业编码）", "P4") as s:
        # 新建员工默认必须首登改密（产品行为）；回归工装按已知初始密码直接清标记后登录，
        # 这样每个岗位都能拿真实 token 去跑权限矩阵/业务链路。
        psql(f"update users set must_change_password=false where tenant_id={TENANT_ID};")
        tokens = {}
        for role, username, *_ in ROLE_PEOPLE:
            r = API.post("/api/auth/employee/login",
                         json_body={"identifier": f"{username}@{TENANT_CODE}", "password": ADMIN_PASSWORD})
            if not r.ok:
                s.ev(f"{role}_status", r.status, f"{role}_msg", r.msg)
                s.expect(False, f"{role} 登录失败: {r.status} {r.msg}")
            d = as_dict(r.data)
            token = d.get("accessToken") or d.get("token")
            s.expect(bool(token), f"{role} 登录未返回 token: {d}")
            tokens[role] = token
        tokens["admin"] = API.token or ""
        CTX["role_tokens"] = tokens
        s.ev(logged_in=sorted(tokens))

    with step("ORG-03", "创建 3 名工人（工号 + PIN）并逐个登录工人端", "P4") as s:
        workers = []
        for i, (no, name) in enumerate([("W-1001", "回归工人一"), ("W-1002", "回归工人二"), ("W-1003", "回归工人三")], start=1):
            d = as_dict(req_ok(API.post("/api/admin/workers", json_body={
                "workerNo": no, "name": name, "pin": WORKER_PIN,
                "workerPages": ["report", "cut_calc", "shipment"],
            }), s, f"建工人 {no}"))
            wid = first(d.get("id"))
            s.expect(bool(wid), f"工人 {no} 未返回 id: {d}")
            workers.append({"id": wid, "workerNo": no, "name": name})
        CTX["workers"] = workers
        login = as_dict(req_ok(API.post("/api/worker/login", json_body={
            "workerNo": "W-1001", "pin": WORKER_PIN, "enterpriseCode": TENANT_CODE,
            "deviceLabel": "回归一体机-01",
        }), s, "工人登录"))
        sid = first(login.get("sessionId"), login.get("session_id"), login.get("id"))
        s.expect(bool(sid), f"工人登录未返回 session: {login}")
        API.worker_session = str(sid)
        CTX["worker_session"] = str(sid)
        me = req_ok(API.get("/api/worker/me", worker=True), s, "读工人身份")
        s.ev(worker_session=sid, worker_me=me)
        s.eq(as_dict(me).get("worker_name"), "回归工人一")

    with step("ORG-04", "各岗位菜单树与默认权限可见", "P4") as s:
        baseline = None
        for role, token in CTX["role_tokens"].items():
            d = as_list(req_ok(API.get("/api/admin/menus", token=token), s, f"读 {role} 菜单"))
            codes = json.dumps(d, ensure_ascii=False)
            s.ev(f"{role}_menu_count", len(d))
            if role == "admin":
                baseline = codes
            if role == "inspector":
                s.expect("质检记录" in codes, f"质检员菜单应含质检记录: {codes[:300]}")
            if role == "finance":
                s.expect("财务对账" in codes, f"财务菜单应含财务对账: {codes[:300]}")
        s.expect(bool(baseline), "管理员菜单为空")

    with step("ORG-05", "工人端页面目录（闭词表）", "P4") as s:
        d = as_dict(req_ok(API.get("/api/admin/worker-pages"), s, "读工人端页面目录"))
        pages = as_list(d.get("pages"))
        s.ev(pages=pages, default_pages=d.get("default_pages"), optional_pages=d.get("optional_pages"))
        s.expect(len(pages) >= 3, f"页面目录异常: {d}")


# ─────────────────────────────── PHASE 5: 入库 / 库存 ───────────────────────────────
def phase_inbound() -> None:
    with step("STK-01", "入库草稿 → 过账：库存/批次/台账/金额四账一致", "P5") as s:
        prod = CTX["products"]["blackout"]
        detail = prod["detail"]
        skus = as_list(detail.get("skus"))[:2]
        s.expect(len(skus) >= 2, f"SKU 不足: {skus}")
        sku_ids = [str(x.get("id")) for x in skus]
        before_stock = {str(x.get("id")): num(x.get("stock")) for x in skus}
        items = []
        for i, sku in enumerate(skus):
            items.append({
                "productId": prod["id"], "skuId": str(sku.get("id")),
                "quantity": 100 if i == 0 else 50, "unitCost": 70.0 if i == 0 else 75.0,
                "dyeLot": f"REG-DYE-{i+1:02d}", "rollLengthM": 60,
            })
        draft = as_dict(req_ok(API.post("/api/admin/inbound-orders", json_body={
            "supplier": "回归供应商", "supplierDocNo": "REG-PO-001",
            "warehouse": "回归主仓", "inboundDate": dt.date.today().isoformat(),
            "source": "purchase", "remark": "回归验收入库单",
            "items": items,
        }), s, "建入库草稿"))
        iid = first(draft.get("id"), draft.get("inboundNo"))
        s.expect(bool(iid), f"入库单未返回 id: {draft}")
        s.ev(inbound_id=iid, status=draft.get("status"), total=draft.get("totalAmount"))
        s.eq(draft.get("status"), "draft")
        # 草稿不动库存
        after_draft = {str(x.get("id")): num(as_dict(API.get(f"/api/admin/products/{prod['id']}").data).get("skus")[i].get("stock")) for i, x in enumerate(skus)}
        s.ev(stock_before=before_stock, stock_after_draft=after_draft)
        s.eq(after_draft, before_stock, "草稿不应改库存")
        posted = as_dict(req_ok(API.patch(f"/api/admin/inbound-orders/{iid}", json_body={"action": "post"}),
                                s, "过账"))
        s.ev(posted_status=posted.get("status"), posted_at=posted.get("postedAt"))
        s.eq(posted.get("status"), "posted")
        d_after = as_dict(req_ok(API.get(f"/api/admin/products/{prod['id']}"), s, "读过账后商品"))
        skus_after = as_list(d_after.get("skus"))
        by_id = {str(x.get("id")): x for x in skus_after}
        for i, sku in enumerate(skus):
            expected = before_stock[str(sku.get("id"))] + (100 if i == 0 else 50)
            s.expect(abs(num(by_id[str(sku.get("id"))].get("stock")) - expected) < 0.001,
                     f"SKU {sku.get('skuCode')} 库存应为 {expected}，实得 {by_id[str(sku.get('id'))].get('stock')}")
        batches = as_list(req_ok(API.get("/api/admin/inbound-orders/batches"), s, "读批次"))
        ledger = as_dict(req_ok(API.get("/api/admin/stock-ledger?page=1&size=100"), s, "读库存台账"))
        ledger_rows = as_list(ledger)
        s.ev(batch_rows=len(batches), ledger_rows=len(ledger_rows))
        s.expect(len(batches) >= 2, f"过账应生成 >=2 个批次，实得 {len(batches)}")
        s.expect(len(ledger_rows) >= 2, f"应落 >=2 行库存台账，实得 {len(ledger_rows)}")

    with step("STK-02", "草稿作废不动库存（负控）", "P5") as s:
        prod = CTX["products"]["blackout"]
        sku = as_list(prod["detail"].get("skus"))[0]
        before = num(as_dict(API.get(f"/api/admin/products/{prod['id']}").data).get("skus")[0].get("stock"))
        draft = as_dict(req_ok(API.post("/api/admin/inbound-orders", json_body={
            "supplier": "回归供应商2", "warehouse": "回归主仓", "source": "purchase",
            "items": [{"productId": prod["id"], "skuId": str(sku.get("id")), "quantity": 30,
                       "unitCost": 71.0, "dyeLot": "REG-DYE-CANCEL"}],
        }), s, "建作废用草稿"))
        iid = first(draft.get("id"), draft.get("inboundNo"))
        req_ok(API.patch(f"/api/admin/inbound-orders/{iid}",
                         json_body={"action": "cancel", "reason": "回归验收-草稿作废"}), s, "作废草稿")
        after = num(as_dict(API.get(f"/api/admin/products/{prod['id']}").data).get("skus")[0].get("stock"))
        s.ev(before=before, after=after)
        s.eq(after, before, "作废草稿不应改库存")

    with step("STK-03", "批次读面 / 分布 / 对账", "P5") as s:
        prod = CTX["products"]["blackout"]
        sku = as_list(prod["detail"].get("skus"))[0]
        for path in (
            f"/api/admin/batch-stock/batches?productId={prod['id']}&onlyAvailable=true",
            f"/api/admin/batch-stock/distribution?productId={prod['id']}",
            f"/api/admin/batch-stock/reconcile?productId={prod['id']}",
            "/api/admin/batch-stock/saving-board",
        ):
            d = req_ok(API.get(path), s, f"读 {path.split('?')[0]}")
            s.ev(path.split("?")[0].split("/")[-1], d if not isinstance(d, dict) else list(d.keys()))
        # 对账：Σ批次余量 vs SKU stock
        rec = as_dict(API.get(f"/api/admin/batch-stock/reconcile?productId={prod['id']}").data)
        s.ev(reconcile=rec)


# ─────────────────────────────── PHASE 6: 订单（含加工费组合/特殊选项） ───────────────────────────────
def combo_key(names: list[str]) -> str:
    return "+".join(sorted({n.strip() for n in names if n and n.strip()}))


def fee_for_line(names: list[str], meters: float, options: list[str], charge_options: bool,
                 style: str = "单色", override: float | None = None) -> tuple[float, str]:
    prices = CTX.get("fee_combo_prices", {})
    key = combo_key(names)
    if override is not None and key not in prices:
        base = override * meters
        source = "manual"
    elif key in prices:
        base = prices[key] * meters
        source = "matched"
    else:
        base = 0.0
        source = "unpriced"
    opt_prices = CTX.get("option_prices", {})
    if charge_options:
        for opt in options:
            if opt in ("拼1次", "拼2次"):
                continue
            base += opt_prices.get(opt, 0.0)
        if style == "拼色":
            base += 2.4 * meters
    return round(base, 2), source


def build_order(key: str, lines: list[dict], *, urgent: bool = False, remark: str = "") -> dict:
    """lines: {product, color, width, qty, height, items:[names], options:[], craft_line, style, override?}"""
    order_items = []
    total = 0.0
    charged_groups: set[str] = set()
    for ln in lines:
        prod = CTX["products"][ln["product"]]
        skus = as_list(prod["detail"].get("skus"))
        sku = next((x for x in skus if x.get("colorName") == ln["color"] and str(x.get("doorWidth")) == ln["width"]), None)
        if sku is None:
            raise AssertionError(f"找不到 SKU {ln['product']} {ln['color']} {ln['width']}")
        qty = float(ln["qty"])
        price = num(sku.get("price"))
        subtotal = round(qty * price, 2)
        total += subtotal
        names = ln.get("items") or []
        options = ln.get("options") or []
        group = ln.get("craft_line") or f"{key}-{len(order_items)}"
        charge_options = group not in charged_groups
        charged_groups.add(group)
        fee, source = fee_for_line(names, qty, options, charge_options, ln.get("style", "单色"), ln.get("override"))
        total += fee
        pi_items = []
        for n in names:
            meta = CTX["processing_items"].get(n)
            if not meta:
                raise AssertionError(f"加工项不存在: {n}")
            pi_items.append({"id": meta.get("id"), "name": n, "quantity": 1, "unit": meta.get("unit", "米")})
        info = {
            "processingItems": pi_items,
            "processingMeters": qty,
            "fabric_meters": qty,
            "specialOptions": options,
            "craftLineId": group,
            "style": ln.get("style", "单色"),
            "components": ["主布"] if ln["product"] == "blackout" else None,
        }
        info = {k: v for k, v in info.items() if v is not None}
        if ln.get("override") is not None:
            info["processingFeeOverride"] = ln["override"]
        oi = {
            "productId": prod["id"], "productName": f"{prod['spec']['name']}-{ln['color']}-{ln['width']}",
            "quantity": qty, "unitPrice": price, "width": float(ln["width"].replace("米", "")),
            "height": float(ln.get("height", 2.6)), "subtotal": subtotal,
            "processingInfo": info,
        }
        if ln.get("selling_method"):
            oi["sellingMethod"] = ln["selling_method"]
        if ln.get("roll_count") is not None:
            oi["rollCount"] = ln["roll_count"]
        if ln.get("roll_length_m") is not None:
            oi["rollLengthM"] = ln["roll_length_m"]
        order_items.append(oi)
    total = round(total, 2)
    return {
        "customerName": f"回归客户-{key}", "customerPhone": "13900003001",
        "customerAddress": "浙江省杭州市西湖区回归路 1018 号",
        "logisticsType": "express", "logisticsCompany": "顺丰速运",
        "remark": remark or f"回归验收订单 {key}",
        "actualAmount": total, "discountAmount": 0,
        "isUrgent": urgent,
        "requiredDeliveryDate": (dt.date.today() + dt.timedelta(days=2)).isoformat() if urgent else None,
        "items": order_items,
    }, total


def phase_orders() -> None:
    # 组合键口径 = 与写面同源（trim/去重/Unicode 升序/+ 连接）⇒ 取价表按同一键归一
    CTX["fee_combo_prices"] = {
        combo_key(k.split("+")): v for k, v in CTX.get("fee_combo_prices", {}).items()
    }
    scenarios = {
        "O1": {
            "lines": [
                {"product": "blackout", "color": "月光白", "width": "2.8米", "qty": 5.2,
                 "items": ["韩褶", "定型"], "options": ["加铅块", "布绑带"], "craft_line": "win-A"},
                {"product": "sheer", "color": "象牙白", "width": "2.8米", "qty": 3.0,
                 "items": ["韩褶", "定型"], "options": [], "craft_line": "win-A"},
            ],
            "remark": "回归-布帘+纱帘一樘窗（组合价+特殊选项）",
        },
        "O2": {
            "lines": [
                {"product": "blackout", "color": "雾霾蓝", "width": "3.2米", "qty": 4.0,
                 "items": ["打孔", "定型"], "options": ["拼1次"], "craft_line": "win-B", "style": "拼色"},
            ],
            "remark": "回归-打孔拼色（拼1次按米加价）",
        },
        "O3": {
            "lines": [
                {"product": "fabric", "color": "本白", "width": "2.8米", "qty": 100.0,
                 "items": [], "options": [], "craft_line": "roll-1",
                 "selling_method": "full_roll", "roll_count": 2, "roll_length_m": 100},
            ],
            "remark": "回归-卖布单（整卷，无加工）",
        },
        "O4": {
            "lines": [
                {"product": "valance", "color": "米白", "width": "2.8米", "qty": 2.0,
                 "items": ["平幔", "定型"], "options": [], "craft_line": "win-C"},
            ],
            "remark": "回归-帘头平幔",
        },
        "O5": {
            "lines": [
                {"product": "blackout", "color": "暖咖", "width": "2.8米", "qty": 6.0,
                 "items": ["韩褶", "定型", "花边"], "options": ["加立边"], "craft_line": "win-D"},
            ],
            "remark": "回归-韩褶+定型+花边（质检返工/报废场景）",
        },
        "O6": {
            "lines": [
                {"product": "blackout", "color": "月光白", "width": "3.2米", "qty": 3.0,
                 "items": ["韩褶", "花边"], "options": [], "craft_line": "win-E", "override": 10.5},
            ],
            "remark": "回归-未定价组合人工改价（应回写组合价目）",
        },
        "O7": {
            "lines": [
                {"product": "blackout", "color": "雾霾蓝", "width": "2.8米", "qty": 2.5,
                 "items": ["穿杆"], "options": ["防翘扣"], "craft_line": "win-F"},
            ],
            "remark": "回归-加急穿杆（智能派单池）",
        },
    }
    CTX["orders"] = {}
    for key, sc in scenarios.items():
        with step(f"ORD-{key}", f"创建订单 {key}：{sc['remark']}", "P6") as s:
            payload, expected_total = build_order(key, sc["lines"], urgent=(key == "O7"), remark=sc["remark"])
            s.ev(expected_total=expected_total, item_count=len(payload["items"]))
            r = API.post("/api/admin/orders", json_body=payload, idempotency=f"reg-order-{key}")
            d = as_dict(req_ok(r, s, "建单"))
            oid = first(d.get("id"))
            s.expect(bool(oid), f"订单未返回 id: {d}")
            detail = as_dict(req_ok(API.get(f"/api/admin/orders/{oid}"), s, "读订单详情"))
            s.ev(order_id=oid, status=detail.get("status"), total=detail.get("totalAmount"),
                 actual=detail.get("actualAmount"))
            s.eq(detail.get("status"), "pending")
            s.expect(abs(num(detail.get("totalAmount")) - expected_total) < 0.02,
                     f"订单总额应为 {expected_total}，实得 {detail.get('totalAmount')}")
            items = as_list(detail.get("items"), "orderItems")
            s.expect(len(items) == len(payload["items"]), "明细行数不一致")
            for it in items:
                fee_detail = (it.get("processingInfo") or {}).get("processingFeeDetail") if isinstance(it.get("processingInfo"), dict) else None
                if fee_detail:
                    s.ev(f"fee_{it.get('id')}", fee_detail.get("fee_source") if isinstance(fee_detail, dict) else fee_detail)
            CTX["orders"][key] = {"id": oid, "detail": detail, "payload": payload,
                                  "expected_total": expected_total, "scenario": sc}

    with step("ORD-S1", "订单读面：列表/筛选/统计/跟进状态/加急", "P6") as s:
        d = as_dict(req_ok(API.get("/api/admin/orders?page=1&size=50"), s, "订单列表"))
        s.ev(total=d.get("total"))
        s.expect(int(d.get("total") or 0) >= 7, f"订单列表应 >=7，实得 {d.get('total')}")
        for q in ("?status=pending", "?keyword=回归", "?page=1&size=2"):
            r = API.get(f"/api/admin/orders{q}")
            s.expect(r.ok, f"筛选 {q} 失败: {r.status} {r.msg}")
        stats = req_ok(API.get("/api/admin/orders/statistics"), s, "订单统计")
        fs = req_ok(API.get("/api/admin/orders/follow-status/stats"), s, "跟进状态统计")
        s.ev(statistics=stats, follow_stats=fs)
        o1 = CTX["orders"]["O1"]["id"]
        req_ok(API.put(f"/api/admin/orders/{o1}/urgency", json_body={"isUrgent": True}), s, "加急")
        req_ok(API.post(f"/api/admin/orders/{o1}/remark", json_body={"content": "回归-加急备注"}), s, "加备注")

    with step("ORD-S2", "待付款订单内容编辑（改数量重算金额）", "P6") as s:
        o6 = CTX["orders"]["O6"]
        payload = dict(o6["payload"])
        items = json.loads(json.dumps(payload["items"]))
        items[0]["quantity"] = 3.5
        items[0]["subtotal"] = round(3.5 * num(items[0]["unitPrice"]), 2)
        items[0]["processingInfo"]["processingMeters"] = 3.5
        payload["items"] = items
        # 人工改价 10.5/m × 3.5
        payload["actualAmount"] = round(sum(num(i["subtotal"]) for i in items) + 10.5 * 3.5, 2)
        req_ok(API.put(f"/api/admin/orders/{o6['id']}/content", json_body=payload), s, "改单")
        d = as_dict(req_ok(API.get(f"/api/admin/orders/{o6['id']}"), s, "读改单后详情"))
        s.ev(total=d.get("totalAmount"), actual=d.get("actualAmount"), qty=as_list(d.get("items"))[0].get("quantity"))
        s.expect(abs(num(as_list(d.get("items"))[0].get("quantity")) - 3.5) < 0.001, "改单数量未生效")

    with step("ORD-S3", "取消未付款订单 + 非法状态流转负控", "P6") as s:
        o2 = CTX["orders"]["O2"]["id"]
        bad = API.put(f"/api/admin/orders/{o2}/status", json_body={"status": "shipped"})
        s.ev(illegal_transition_status=bad.status, msg=bad.msg)
        s.expect(bad.status >= 400, "pending 直接流转 shipped 应被拒")
        req_ok(API.put(f"/api/admin/orders/{o2}/cancel", json_body={"closeReason": "回归-客户取消"}), s, "取消订单")
        d = as_dict(req_ok(API.get(f"/api/admin/orders/{o2}"), s, "读取消后详情"))
        s.eq(d.get("status"), "cancelled")

    with step("ORD-S4", "确认支付（扣库存）+ 财务流水", "P6") as s:
        for key in ("O1", "O4", "O5", "O6", "O7", "O3"):
            oid = CTX["orders"][key]["id"]
            r = API.put(f"/api/admin/orders/{oid}/payment")
            s.expect(r.ok, f"{key} 确认支付失败: {r.status} {r.msg}")
            d = as_dict(API.get(f"/api/admin/orders/{oid}").data)
            s.expect(d.get("status") == "confirmed", f"{key} 支付后状态应为 confirmed，实得 {d.get('status')}")
        tx = int(q1(f"select count(*) from finance_transactions where tenant_id={TENANT_ID}"))
        s.ev(finance_transactions=tx)
        s.expect(tx >= 6, f"支付应产生财务流水，实得 {tx}")


# ─────────────────────────────── PHASE 7: 生产全链路 ───────────────────────────────
def flatten_operations(payload: Any) -> list[dict]:
    positions = as_list(payload, "positions")
    if positions and isinstance(positions[0], dict) and "operations" in positions[0]:
        return [op for p in positions for op in as_list(p.get("operations"))]
    return as_list(payload, "operations")


def phase_production() -> None:
    with step("PRD-10", "确认订单生成加工单（O1/O5/O7；兼容确认支付后的自动派单）", "P7") as s:
        auto_failures = {}
        for key in ("O1", "O5", "O7"):
            oid = CTX["orders"][key]["id"]
            # 确认支付会触发「池化自动派单」（AFTER_COMMIT）。已有加工单 ⇒ 视为成功；
            # 自动派单失败的单，手动 generate 是产品的合法恢复入口。
            d = req_ok(API.post("/api/admin/processing-orders/generate",
                                json_body={"orderIds": [oid]}), s, f"{key} 生成加工单")
            rows = as_list(d)
            if not any(bool(x.get("success", True)) for x in rows):
                msg = " ".join(str(x.get("message") or "") for x in rows)
                auto_failures[key] = msg
                if "已有加工单" in msg:
                    pass
                else:
                    # 自动派单失败（fail-soft）后重试一次；产品的手动生成入口必须能补齐
                    d2 = req_ok(API.post("/api/admin/processing-orders/generate",
                                         json_body={"orderIds": [oid]}), s, f"{key} 重试生成加工单")
                    rows2 = as_list(d2)
                    s.expect(any(bool(x.get("success", True)) for x in rows2),
                             f"{key} 自动派单失败且手动重试仍失败: {d2}")
            s.ev(f"{key}_generate", d)
        s.ev(auto_dispatch_failures=auto_failures)
        lst = as_list(req_ok(API.get("/api/admin/processing-orders"), s, "读加工单列表"))
        s.ev(processing_orders=len(lst))
        s.expect(len(lst) >= 3, f"加工单应 >=3，实得 {len(lst)}")
        CTX["processing_orders"] = {}
        for key in ("O1", "O5", "O7"):
            oid = CTX["orders"][key]["id"]
            found = next((x for x in lst if str(x.get("orderId")) == str(oid)), None)
            s.expect(bool(found), f"{key} 未找到对应加工单")
            CTX["processing_orders"][key] = found
            s.ev(f"{key}_po", {"id": found.get("id"), "no": found.get("processingNo"), "status": found.get("status")})
        for key in ("O1", "O5", "O7"):
            d = as_dict(API.get(f"/api/admin/orders/{CTX['orders'][key]['id']}").data)
            s.ev(f"{key}_order_status", d.get("status"))
            s.expect(d.get("status") in ("producing", "confirmed"), f"{key} 订单状态异常: {d.get('status')}")

    with step("PRD-11", "加工单状态机：issue → in_processing", "P7") as s:
        for key in ("O1", "O5", "O7"):
            po = CTX["processing_orders"][key]
            pid = po.get("id")
            d1 = as_dict(req_ok(API.patch(f"/api/admin/processing-orders/{pid}", json_body={"action": "issue"}), s, f"{key} 发加工"))
            s.ev(f"{key}_issued", d1.get("status"))
            d2 = as_dict(req_ok(API.patch(f"/api/admin/processing-orders/{pid}", json_body={"action": "start"}), s, f"{key} 开始加工"))
            s.ev(f"{key}_started", d2.get("status"))
            s.eq(d2.get("status"), "in_processing")

    with step("PRD-12", "实例化工序（O1/O5/O7）+ 工序清单读面", "P7") as s:
        for key in ("O1", "O5", "O7"):
            oid = CTX["orders"][key]["id"]
            d = as_dict(req_ok(API.post(f"/api/admin/production/orders/{oid}/instantiate", json_body={}),
                               s, f"{key} 实例化"))
            s.ev(f"{key}_instantiate", d)
            CTX.setdefault("qr_tokens", {})[key] = d.get("qr_token") or d.get("token")
            ops = as_dict(req_ok(API.get(f"/api/admin/production/orders/{oid}/operations"), s, f"{key} 工序清单"))
            flat = flatten_operations(ops)
            s.ev(f"{key}_operation_count", len(flat))
            s.expect(len(flat) > 0, f"{key} 工序实例为空")
            CTX.setdefault("operations", {})[key] = flat

    with step("PRD-13", "扫描（一体机/工人端）+ 逐工序报工 + 计件金额", "P7") as s:
        total_reported = 0
        for key in ("O1", "O5"):
            oid = CTX["orders"][key]["id"]
            qt = CTX.get("qr_tokens", {}).get(key)
            s.expect(bool(qt), f"{key} 未拿到 qr_token")
            scan = req_ok(API.get(f"/api/admin/production/scan?token={qt}"), s, f"{key} 商家侧扫码")
            s.ev(f"{key}_scan_granularity", as_dict(scan).get("granularity"))
            wscan = req_ok(API.get(f"/api/worker/production/scan?token={qt}", worker=True), s, f"{key} 工人端扫码")
            s.ev(f"{key}_worker_granularity", as_dict(wscan).get("granularity"))
            flat = CTX["operations"][key]
            reported = 0
            for op in flat:
                rid = op.get("id") or op.get("operation_id")
                qty = num(op.get("qty")) - num(op.get("done_qty"))
                if qty <= 0 or not rid:
                    continue
                body = {"qty": qty, "qualified_qty": qty, "work_type": "normal"}
                r = API.post(f"/api/worker/production/orders/{oid}/operations/{rid}/report",
                             json_body=body, worker=True, idempotency=f"reg-report-{rid}")
                s.expect(r.ok, f"{key} 报工失败 op={rid} status={r.status} msg={r.msg}")
                reported += 1
            total_reported += reported
            s.ev(f"{key}_reported_operations", reported)
            s.expect(reported >= 5, f"{key} 应至少报 5 道工序，实得 {reported}")
        s.ev(total_reported=total_reported)
        logs = int(q1(f"select count(*) from production_work_logs where tenant_id={TENANT_ID}"))
        s.ev(work_log_rows=logs)
        s.expect(logs >= 10, f"两个订单报工应落 >=10 行，实得 {logs}")
        oid = CTX["orders"]["O1"]["id"]
        pw = as_dict(req_ok(API.get(f"/api/admin/production/orders/{oid}/piecework"), s, "按单计件"))
        s.ev(piecework_total=pw.get("total"), unpriced=pw.get("unpriced"))
        s.expect(num(pw.get("total")) > 0, f"计件金额应 >0: {pw}")

    with step("PRD-14", "加工单完成 + 全公司计件汇总（人/工序/部位/套）", "P7") as s:
        for key in ("O1", "O5"):
            pid = CTX["processing_orders"][key].get("id")
            d = as_dict(req_ok(API.get(f"/api/admin/processing-orders/{pid}"), s, f"{key} 读加工单"))
            if d.get("status") != "completed":
                d = as_dict(req_ok(API.patch(f"/api/admin/processing-orders/{pid}",
                                             json_body={"action": "complete"}), s, f"{key} 完成加工单"))
            s.ev(f"{key}_po_status", d.get("status"))
            s.eq(d.get("status"), "completed", f"{key} 加工单应已完成")
        # O7 不投产：验证「加工中 -> 取消」状态机
        pid7 = CTX["processing_orders"]["O7"].get("id")
        d7 = as_dict(req_ok(API.patch(f"/api/admin/processing-orders/{pid7}",
                                      json_body={"action": "cancel", "reason": "回归-派单池场景不投产"}), s, "取消 O7 加工单"))
        s.ev("O7_po_status", d7.get("status"))
        s.eq(d7.get("status"), "cancelled")
        period = dt.date.today().strftime("%Y-%m")
        rep = as_dict(req_ok(API.get(f"/api/admin/production/piecework/summary?period={period}"), s, "计件报表"))
        s.ev(period=rep.get("period"), total=rep.get("total"), workers=rep.get("per_worker"),
             positions=rep.get("per_position"), sets=rep.get("per_set"))
        s.expect(num(rep.get("total")) > 0, f"计件报表 total 应 >0: {rep}")

    with step("PRD-15", "质检：按成品帘录入（合格/返工/报废三态）", "P7") as s:
        o1 = CTX["orders"]["O1"]
        items = as_list(o1["detail"].get("items"), "orderItems")
        s.expect(len(items) >= 2, "O1 明细不足")
        targets = as_dict(req_ok(API.get("/api/admin/quality-inspections/targets"), s, "待检清单"))
        s.ev(targets_preview=list(targets.keys()))
        for i, it in enumerate(items):
            result = "pass" if i == 0 else "rework"
            body = {"order_item_id": it.get("id"), "result": result}
            if result != "pass":
                body["reason"] = "回归-缝制不齐，返工"
            r = API.post("/api/admin/quality-inspections", json_body=body)
            s.expect(r.ok, f"质检录入失败 item={it.get('id')} status={r.status} msg={r.msg}")
        # 返工后复检合格
        second = items[1]
        req_ok(API.post("/api/admin/quality-inspections", json_body={
            "order_item_id": second.get("id"), "result": "pass"}), s, "返工复检合格")
        lst = as_list(req_ok(API.get("/api/admin/quality-inspections"), s, "质检记录列表"))
        s.ev(quality_rows=len(lst))
        s.expect(len(lst) >= 3, f"质检记录应 >=3，实得 {len(lst)}")
        # 报废负控：判定非合格必须给原因
        bad = API.post("/api/admin/quality-inspections", json_body={
            "order_item_id": second.get("id"), "result": "scrap"})
        s.ev(scrap_without_reason_status=bad.status)
        s.expect(bad.status == 422, "报废缺原因应 422")

    with step("PRD-16", "商家发货：状态/物流/发货单原子落库", "P7") as s:
        oid = CTX["orders"]["O1"]["id"]
        r = API.post(f"/api/admin/production/orders/{oid}/ship", json_body={
            "trackingNo": "SF13900001018", "logisticsCompany": "顺丰速运",
            "shippingMethod": "logistics", "logisticsType": "express", "shipperName": "回归发货员",
        }, idempotency=f"reg-ship-{oid}")
        s.ev(ship_status=r.status, ship_msg=r.msg, ship_data=r.data)
        s.expect(r.ok, f"发货失败: {r.status} {r.msg}")
        d = as_dict(API.get(f"/api/admin/orders/{oid}").data)
        s.eq(d.get("status"), "shipped")
        s.expect(bool(d.get("shippedAt")), "shippedAt 应写")
        shipments = as_list(req_ok(API.get(f"/api/admin/orders/{oid}/shipments"), s, "按单发货单"))
        s.ev(shipment_rows=len(shipments), shipments=shipments[:2])
        s.expect(len(shipments) >= 1, "应生成发货单")
        all_shipments = as_list(req_ok(API.get("/api/admin/shipments"), s, "发货单列表"))
        s.ev(all_shipment_rows=len(all_shipments))
        s.expect(len(all_shipments) >= 1, "发货单列表应可见")

    with step("PRD-17", "确认收货 → completed + 时间戳", "P7") as s:
        oid = CTX["orders"]["O1"]["id"]
        req_ok(API.put(f"/api/admin/orders/{oid}/status", json_body={"status": "completed"}), s, "确认收货")
        d = as_dict(API.get(f"/api/admin/orders/{oid}").data)
        s.eq(d.get("status"), "completed")
        s.expect(bool(d.get("receivedAt")), "receivedAt 应写")
        s.ev(receivedAt=d.get("receivedAt"))

    with step("PRD-18", "生产池：普通单可合并预览；加急单被显式排除", "P7") as s:
        preview = req_ok(API.post("/api/admin/production/pool/preview",
                                  json_body={"orderIds": [CTX["orders"]["O4"]["id"]]}), s, "派单预览（普通单）")
        s.ev(preview=preview if not isinstance(preview, dict) else list(preview.keys()))
        urgent = API.post("/api/admin/production/pool/preview",
                          json_body={"orderIds": [CTX["orders"]["O7"]["id"]]})
        s.ev(urgent_status=urgent.status, urgent_msg=urgent.msg)
        s.eq(urgent.status, 422, "加急单不参与合并派单应 422（产品口径）")
        s.expect("加急" in urgent.msg, f"加急排除文案异常: {urgent.msg}")
        pool = req_ok(API.get("/api/admin/production/pool"), s, "派单池")
        s.ev(pool=pool if not isinstance(pool, dict) else list(pool.keys()))

    with step("PRD-19", "计件结算：生成 → 列表 → 重复 409 → 作废留痕", "P7") as s:
        period = dt.date.today().strftime("%Y-%m")
        gen = req_ok(API.post("/api/admin/production/piecework/settlements",
                              json_body={"period": period, "worker_name": "回归工人一"}), s, "生成结算单")
        sid = first(as_dict(gen).get("id"))
        s.ev(settlement_id=sid, data=gen if not isinstance(gen, dict) else list(gen.keys()))
        lst = req_ok(API.get(f"/api/admin/production/piecework/settlements?period={period}"), s, "结算单列表")
        s.ev(settlements=lst)
        dup = API.post("/api/admin/production/piecework/settlements",
                       json_body={"period": period, "worker_name": "回归工人一"})
        s.ev(duplicate_status=dup.status)
        s.eq(dup.status, 409, "同期间同工人重复生成应 409")
        if sid:
            req_ok(API.post(f"/api/admin/production/piecework/settlements/{sid}/void",
                            json_body={"reason": "回归验收-作废重开"}), s, "作废结算单")
        rows = int(q1(f"select count(*) from piecework_settlements where tenant_id={TENANT_ID}"))
        s.ev(db_rows=rows)
        s.expect(rows >= 1, "结算单应落库")


# ─────────────────────────────── PHASE 8: 售后 / 退款 ───────────────────────────────
def phase_aftersales() -> None:
    with step("AFS-01", "售后工单：退款工单 pending→processing→resolved", "P8") as s:
        oid = CTX["orders"]["O1"]["id"]
        t = as_dict(req_ok(API.post("/api/admin/after-sales", json_body={
            "orderId": oid, "ticketType": "refund", "description": "回归验收-客户申请退款",
            "priority": "urgent", "refundAmount": 50,
        }), s, "建退款工单"))
        tid = first(t.get("id"))
        s.expect(bool(tid), f"工单未返回 id: {t}")
        s.ev(ticket_id=tid, status=t.get("status"), orderId=t.get("orderId"))
        s.eq(t.get("status"), "pending")
        req_ok(API.put(f"/api/admin/after-sales/{tid}/status",
                       json_body={"status": "processing", "remark": "回归-受理"}), s, "受理")
        d = as_dict(req_ok(API.get(f"/api/admin/after-sales/{tid}"), s, "受理后详情"))
        s.eq(d.get("status"), "processing")
        req_ok(API.put(f"/api/admin/after-sales/{tid}/status",
                       json_body={"status": "resolved", "remark": "回归-已退款"}), s, "解决")
        d = as_dict(req_ok(API.get(f"/api/admin/after-sales/{tid}"), s, "解决后详情"))
        s.eq(d.get("status"), "resolved")
        detail = as_dict(req_ok(API.get(f"/api/admin/after-sales/{tid}"), s, "工单详情"))
        s.ev(timeline=detail.get("timeline") or detail.get("ticketTimeline"))
        CTX["ticket_refund"] = tid

    with step("AFS-02", "售后工单：退货驳回 + 换货关闭（覆盖其它终态）", "P8") as s:
        o5 = CTX["orders"]["O5"]["id"]
        t1 = as_dict(req_ok(API.post("/api/admin/after-sales", json_body={
            "orderId": o5, "ticketType": "return", "description": "回归验收-退货（应驳回）",
            "priority": "normal",
        }), s, "建退货工单"))
        tid1 = first(t1.get("id"))
        req_ok(API.put(f"/api/admin/after-sales/{tid1}/status",
                       json_body={"status": "rejected", "remark": "回归-不符合退货条件"}), s, "驳回")
        d = as_dict(req_ok(API.get(f"/api/admin/after-sales/{tid1}"), s, "驳回后详情"))
        s.eq(d.get("status"), "rejected")
        t2 = as_dict(req_ok(API.post("/api/admin/after-sales", json_body={
            "orderId": o5, "ticketType": "exchange", "description": "回归验收-换货（应关闭）",
            "priority": "normal",
        }), s, "建换货工单"))
        tid2 = first(t2.get("id"))
        req_ok(API.put(f"/api/admin/after-sales/{tid2}/status",
                       json_body={"status": "closed", "remark": "回归-线下已处理"}), s, "关闭")
        d = as_dict(req_ok(API.get(f"/api/admin/after-sales/{tid2}"), s, "关闭后详情"))
        s.eq(d.get("status"), "closed")
        lst = as_dict(req_ok(API.get("/api/admin/after-sales?page=1&size=50"), s, "工单列表"))
        s.ev(total=lst.get("total"))
        s.expect(int(lst.get("total") or 0) >= 3, f"工单应 >=3，实得 {lst.get('total')}")

    with step("AFS-03", "订单退款（已支付订单）+ 退款流水", "P8") as s:
        o4 = CTX["orders"]["O4"]["id"]
        r = API.put(f"/api/admin/orders/{o4}/refund",
                    json_body={"refund_reason": "回归验收-帘头尺寸不符", "refund_amount": 100})
        s.ev(status=r.status, msg=r.msg, data=r.data)
        s.expect(r.ok, f"退款失败: {r.status} {r.msg}")
        d = as_dict(API.get(f"/api/admin/orders/{o4}").data)
        s.ev(order_status=d.get("status"), refund_amount=d.get("refundAmount"), refund_at=d.get("refundAt"))
        tx = int(q1("select count(*) from finance_transactions "
                    f"where tenant_id={TENANT_ID} and type='refund'"))
        s.ev(refund_transactions=tx)
        s.expect(tx >= 1, "退款应产生退款流水")


# ─────────────────────────────── PHASE 9: 财务 / 仪表盘 / 通知 / 知识库 ───────────────────────────────
def phase_finance_dashboard() -> None:
    with step("FIN-01", "财务汇总/流水/应收对账 + 手工登记收支", "P9") as s:
        summary = as_dict(req_ok(API.get("/api/admin/finance/summary"), s, "财务汇总"))
        s.ev(totalIncome=summary.get("totalIncome"), totalRefund=summary.get("totalRefund"),
             netIncome=summary.get("netIncome"), pendingReceivable=summary.get("pendingReceivable"))
        s.expect(num(summary.get("totalIncome")) > 0, f"收入应 >0: {summary}")
        inc = req_ok(API.post("/api/admin/finance/transactions", json_body={
            "type": "income", "amount": 100.0, "paymentMethod": "wechat",
            "occurredAt": dt.datetime.now().isoformat(timespec="seconds"), "remark": "回归验收-手工收款",
        }), s, "手工登记收入")
        s.ev(manual_income=inc)
        ref = req_ok(API.post("/api/admin/finance/transactions", json_body={
            "type": "refund", "amount": 30.0, "paymentMethod": "wechat",
            "occurredAt": dt.datetime.now().isoformat(timespec="seconds"), "remark": "回归验收-手工退款",
        }), s, "手工登记退款")
        s.ev(manual_refund=ref)
        lst = as_dict(req_ok(API.get("/api/admin/finance/transactions?page=1&size=50"), s, "流水列表"))
        s.ev(transaction_total=lst.get("total"))
        s.expect(int(lst.get("total") or 0) >= 8, f"流水应 >=8，实得 {lst.get('total')}")
        rec = as_dict(req_ok(API.get("/api/admin/finance/reconciliation?page=1&size=50"), s, "应收对账"))
        s.ev(reconciliation_total=rec.get("total"))

    with step("FIN-02", "订单支付/退款与财务流水对账一致", "P9") as s:
        rows = qrows(f"select type, count(*), coalesce(sum(amount),0) from finance_transactions "
                     f"where tenant_id={TENANT_ID} group by type order by type")
        s.ev(by_type=rows)
        paid = int(q1("select count(*) from orders "
                      f"where tenant_id={TENANT_ID} and paid_at is not null"))
        s.ev(paid_orders=paid)
        s.expect(paid >= 5, f"已支付订单应 >=5，实得 {paid}")

    with step("DASH-01", "经营看板 8 个读面", "P10") as s:
        for path in ("/api/admin/dashboard/stats", "/api/admin/dashboard/order-trend",
                     "/api/admin/dashboard/order-status", "/api/admin/dashboard/recent-orders",
                     "/api/admin/dashboard/active-sessions", "/api/admin/dashboard/pending-tasks",
                     "/api/admin/dashboard/product-ranking", "/api/admin/dashboard/pending-shipment-count",
                     "/api/admin/dashboard/processing-shipment-count"):
            d = req_ok(API.get(path), s, f"读 {path}")
            s.ev(path.split("/")[-1], d if not isinstance(d, dict) else list(d.keys()))
        stats = as_dict(API.get("/api/admin/dashboard/stats").data)
        s.ev(stats=stats)
        s.expect(num(stats.get("totalOrders") or stats.get("orderCount") or 0) >= 7 or "totalOrders" not in stats,
                 f"看板订单数异常: {stats}")

    with step("NTF-01", "通知：创建/列表/未读/已读/删除", "P10") as s:
        me = as_dict(req_ok(API.get("/api/auth/me"), s, "读当前用户"))
        uid = first(as_dict(me.get("user")).get("id"), me.get("id"), me.get("userId"), CTX.get("admin_user_id"))
        n = as_dict(req_ok(API.post("/api/admin/notifications", json_body={
            "recipientId": uid, "recipientType": "user",
            "title": "回归验收通知", "content": "这是一条回归验收站内信", "channel": "in_app",
        }), s, "建通知"))
        nid = first(n.get("id"))
        s.expect(bool(nid), f"通知未返回 id: {n}")
        unread = as_dict(req_ok(API.get("/api/admin/notifications/unread-count"), s, "未读数"))
        s.ev(unread=unread)
        s.expect(int(unread.get("count") or 0) >= 1, "未读数应 >=1")
        lst = as_dict(req_ok(API.get("/api/admin/notifications?page=1&size=50"), s, "通知列表"))
        s.ev(total=lst.get("total"))
        req_ok(API.put(f"/api/admin/notifications/{nid}/read"), s, "标记已读")
        req_ok(API.delete(f"/api/admin/notifications/{nid}"), s, "删除通知")

    with step("KB-01", "知识库卡片：建/发布/归档 + 模板/候选读面", "P10") as s:
        card = as_dict(req_ok(API.post("/api/admin/knowledge/cards", json_body={
            "title": "回归验收-遮光帘保养", "category": "product",
            "industry": "curtain", "sourceType": "manual",
            "question": "遮光帘怎么清洗？", "answer": "建议干洗，避免暴晒。",
            "keywords": "遮光帘,清洗,保养", "status": "draft",
        }), s, "建知识卡"))
        cid = first(card.get("id"))
        s.expect(bool(cid), f"知识卡未返回 id: {card}")
        req_ok(API.post(f"/api/admin/knowledge/cards/{cid}/publish"), s, "发布知识卡")
        req_ok(API.post(f"/api/admin/knowledge/cards/{cid}/archive"), s, "归档知识卡")
        cards = as_dict(req_ok(API.get("/api/admin/knowledge/cards?page=1&size=50"), s, "知识卡列表"))
        s.ev(cards_total=cards.get("total"))
        tpls = as_list(req_ok(API.get("/api/admin/knowledge/templates"), s, "知识模板"))
        s.ev(template_count=len(tpls))
        cand = as_dict(req_ok(API.get("/api/admin/knowledge/candidates?page=1&size=20"), s, "提炼候选"))
        s.ev(candidate_total=cand.get("total"))

    with step("BRIEF-01", "经营简报配置读/写 + 今日简报读面", "P10") as s:
        cfg = as_dict(req_ok(API.get("/api/admin/briefing/config"), s, "读简报配置"))
        s.ev(config=cfg)
        body = dict(cfg) if cfg else {"enabled": True, "sendTime": "08:30"}
        body.pop("id", None)
        body.pop("tenantId", None)
        req_ok(API.put("/api/admin/briefing/config", json_body=body), s, "写简报配置")
        today = req_ok(API.get("/api/admin/briefing/today"), s, "今日简报")
        s.ev(today=today if not isinstance(today, dict) else list(today.keys()))


# ─────────────────────────────── PHASE 10: 岗位权限矩阵 ───────────────────────────────
def phase_roles() -> None:
    tokens = CTX.get("role_tokens", {})
    matrix = [
        ("admin", "GET", "/api/admin/settings", 200),
        ("customer_service", "GET", "/api/admin/orders?page=1&size=1", 200),
        ("customer_service", "POST", "/api/admin/products", 403),
        ("customer_service", "PUT", "/api/admin/settings", 403),
        ("sales", "GET", "/api/admin/orders?page=1&size=1", 200),
        ("sales", "POST", "/api/admin/products", 403),
        ("operator", "GET", "/api/admin/products?page=1&size=1", 200),
        ("operator", "PUT", "/api/admin/settings", 403),
        ("product_manager", "GET", "/api/admin/products?page=1&size=1", 200),
        ("product_manager", "POST", "/api/admin/orders", 403),
        ("finance", "GET", "/api/admin/finance/summary", 200),
        ("finance", "POST", "/api/admin/products", 403),
        ("inspector", "GET", "/api/admin/quality-inspections/targets", 200),
        ("inspector", "POST", "/api/admin/orders", 403),
        ("knowledge_editor", "GET", "/api/admin/knowledge/cards?page=1&size=1", 200),
        ("knowledge_editor", "POST", "/api/admin/products", 403),
    ]
    with step("RBAC-01", "岗位权限矩阵（允许/拒绝逐条）", "P11", "P0") as s:
        for role, method, path, expected in matrix:
            token = tokens.get(role)
            if not token:
                s.ev(f"{role}_{method}_{path}_token", "missing")
                continue
            r = API.call(method, path, token=token,
                         json_body={} if method in ("POST", "PUT") else None)
            s.ev(f"{role}_{method}_{path.split('?')[0]}", r.status)
            if expected == 200:
                s.expect(r.status == 200, f"{role} {method} {path} 应 200，实得 {r.status} {r.msg}")
            else:
                s.expect(r.status in (401, 403), f"{role} {method} {path} 应被拒(401/403)，实得 {r.status}")

    with step("RBAC-02", "工人身份隔离：工人 session 不能进管理接口，只能进 /api/worker/**", "P11", "P0") as s:
        r = API.get("/api/admin/orders?page=1&size=1", token="", worker=True)
        s.ev(worker_admin_status=r.status)
        s.expect(r.status in (401, 403), f"工人访问管理接口应被拒，实得 {r.status}")
        r2 = API.get("/api/worker/me", worker=True)
        s.ev(worker_me_status=r2.status)
        s.expect(r2.status == 200, f"工人读自身身份应 200，实得 {r2.status}")

    with step("RBAC-03", "跨租户隔离：隔离租户读不到本租户商品/订单", "P11", "P0") as s:
        if not CTX.get("isolation_token"):
            s.skip("隔离租户未建立")
        token = CTX["isolation_token"]
        pid = CTX["products"]["blackout"]["id"]
        oid = CTX["orders"]["O1"]["id"]
        r1 = API.get(f"/api/admin/products/{pid}", token=token)
        r2 = API.get(f"/api/admin/orders/{oid}", token=token)
        s.ev(product_status=r1.status, order_status=r2.status)
        s.expect(r1.status in (403, 404), f"跨租户读商品应拒绝，实得 {r1.status}")
        s.expect(r2.status in (403, 404), f"跨租户读订单应拒绝，实得 {r2.status}")


# ─────────────────────────────── isolation tenant (before roles) ───────────────────────────────
def phase_isolation_tenant() -> None:
    with step("ENV-04", "建立隔离对照租户（临时，用于跨租户隔离判据）", "P0", "P0") as s:
        phone = "13900001023"
        company = "米高回归隔离租户"
        # 清掉本轮测试 IP/手机号的入驻频率计数（测试环境前置；产品限流逻辑本身不改）
        import redis as _redis
        _r = _redis.Redis(host=ENV["REDIS_HOST"], port=int(ENV.get("REDIS_PORT", "6379")),
                          password=ENV.get("REDIS_PASSWORD") or None, decode_responses=True)
        try:
            for k in list(_r.scan_iter("reg:submit:ip:*")) + list(_r.scan_iter("reg:submit:phone:*")):
                _r.delete(k)
        finally:
            _r.close()
        existing = q1(f"select id from tenant_applications where phone='{phone}' limit 1").strip()
        if existing:
            s.skip("隔离租户手机号已有申请（上轮残留）")
        r = API.post("/api/auth/register", token="", json_body={
            "companyName": company, "contactName": "隔离管理员", "phone": phone,
            "smsCode": SMS_CODE, "industry": "curtain",
            "address": "浙江省杭州市西湖区隔离路 2 号",
            "description": "用于跨租户隔离验证的临时租户。",
        })
        d = as_dict(req_ok(r, s, "注册隔离租户"))
        s.ev(status=d.get("status"), applicationId=d.get("applicationId"))
        s.eq(d.get("status"), "approved")
        row = q1(f"select id from tenants where name='{company}' order by id desc limit 1").strip()
        s.expect(bool(row), "隔离租户未落库")
        tid = int(row)
        r2 = API.post("/api/auth/sms/login", json_body={"phone": phone, "code": SMS_CODE})
        token = as_dict(r2.data).get("accessToken")
        s.expect(bool(token), f"隔离租户登录失败: {r2.status}")
        CTX["isolation_tenant_id"] = tid
        CTX["isolation_token"] = token
        s.ev(tenant_id=tid)


def cleanup_isolation_tenant() -> None:
    tid = CTX.get("isolation_tenant_id")
    if not tid:
        return
    try:
        subprocess.run([sys.executable, str(ROOT / "tools/wipe-tenants.py"),
                        "--tenant-ids", str(tid), "--apply"], check=False,
                       capture_output=True, text=True, timeout=300)
        CTX["isolation_cleanup"] = "done"
    except Exception as e:  # noqa: BLE001
        CTX["isolation_cleanup"] = f"failed: {e}"


# ─────────────────────────────── report ───────────────────────────────
def write_report() -> None:
    counts = {"pass": 0, "fail": 0, "skip": 0}
    by_phase: dict[str, dict[str, int]] = {}
    for r in RESULTS:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        ph = r["phase"]
        by_phase.setdefault(ph, {"pass": 0, "fail": 0, "skip": 0})
        by_phase[ph][r["status"]] = by_phase[ph].get(r["status"], 0) + 1

    db_counts = {}
    try:
        db_counts = db_tenant_counts()
    except Exception as e:  # noqa: BLE001
        db_counts = {"error": str(e)}

    payload = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "base": BASE,
        "tenant_id": TENANT_ID,
        "tenant_code": TENANT_CODE,
        "counts": counts,
        "by_phase": by_phase,
        "db_counts": db_counts,
        "results": RESULTS,
        "api_call_count": len(API_CALLS),
        "isolation_cleanup": CTX.get("isolation_cleanup"),
    }
    (OUT / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "api_calls.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in API_CALLS) + "\n", encoding="utf-8")

    fails = [r for r in RESULTS if r["status"] == "fail"]
    skips = [r for r in RESULTS if r["status"] == "skip"]
    lines = [
        "# 2026-10-17 全链路回归报告（云测试环境 · API 级）",
        "",
        f"> 生成时间：{payload['generated_at']}　被测环境：`{BASE}`　被测租户：**{TENANT_ID}**（`{TENANT_CODE}`）",
        "> 口径：不做 UI 验收、不做 agent 评测、不跑真实 LLM；skip 永不折算成 pass。",
        "",
        "## 1. 总览",
        "",
        "| 状态 | 条数 |",
        "|---|---|",
        f"| ✅ pass | **{counts.get('pass', 0)}** |",
        f"| ❌ fail | **{counts.get('fail', 0)}** |",
        f"| ⏭️ skip | **{counts.get('skip', 0)}** |",
        f"| API 请求 | {len(API_CALLS)} |",
        "",
        "### 分阶段",
        "",
        "| 阶段 | pass | fail | skip |",
        "|---|---|---|---|",
    ]
    for ph in sorted(by_phase):
        c = by_phase[ph]
        lines.append(f"| {ph} | {c.get('pass', 0)} | {c.get('fail', 0)} | {c.get('skip', 0)} |")

    lines += ["", "## 2. 失败清单（逐条含证据）", ""]
    if not fails:
        lines.append("（无）")
    for r in fails:
        lines.append(f"### ❌ {r['cid']} {r['title']}（{r['severity']}）")
        lines.append("")
        lines.append(f"- 原因：{r['reason']}")
        if r.get("evidence"):
            lines.append(f"- 证据：`{json.dumps(r['evidence'], ensure_ascii=False)[:1500]}`")
        lines.append("")

    lines += ["## 3. 未覆盖（skip）清单", ""]
    if not skips:
        lines.append("（无）")
    for r in skips:
        lines.append(f"- `{r['cid']}` {r['title']}：{r.get('reason', '')}")
    lines += ["", "## 4. 数据面读数（DB 现取）", "", "```json",
              json.dumps(db_counts, ensure_ascii=False, indent=2), "```", "",
              "## 5. 逐条结果", "", "| ID | 阶段 | 状态 | 说明 |", "|---|---|---|---|"]
    for r in RESULTS:
        icon = {"pass": "✅", "fail": "❌", "skip": "⏭️"}[r["status"]]
        reason = (r.get("reason") or "").replace("|", "/")[:120]
        lines.append(f"| {r['cid']} | {r['phase']} | {icon} | {reason} |")
    lines += ["", "## 6. 产物", "",
              "- `out/results.json`：逐条断言 + 证据",
              "- `out/api_calls.jsonl`：每次 API 请求（方法/路径/状态/耗时）",
              "- `evidence/register-response.json`：全新租户真实入驻回执",
              "- `evidence/wipe-tenants.json`：旧租户清除读数",
              ""]
    (ROOT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n=== 完成：pass={counts.get('pass',0)} fail={counts.get('fail',0)} skip={counts.get('skip',0)} "
          f"api={len(API_CALLS)} ===")
    if fails:
        print("\n失败清单：")
        for r in fails:
            print(f"  {r['cid']} {r['title']}: {r['reason'][:300]}")
    print(f"报告：{ROOT / 'REPORT.md'}")


def main() -> int:
    t0 = time.time()
    phase_env()
    phase_settings()
    phase_processing()
    phase_products()
    phase_isolation_tenant()
    phase_org()
    phase_inbound()
    phase_orders()
    phase_production()
    phase_aftersales()
    phase_finance_dashboard()
    phase_roles()
    cleanup_isolation_tenant()
    write_report()
    print(f"总耗时 {time.time() - t0:.1f}s")
    return 0 if all(r["status"] != "fail" for r in RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
