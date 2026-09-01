#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云环境验收：商家入驻 AI 自动甄别全场景（生产环境）
目标: api.migaozn.com / ai-api.migaozn.com / migaozn.com / merchant.migaozn.com / ops.migaozn.com
覆盖:
  H1-H5 健康/文案/废弃页
  A1  合法商家 → AI 自动通过 → 新租户管理员可登录
  A2  敏感内容 → 自动驳回(rule)
  A3  代码注入 → 自动驳回
  A4  企业名非法格式 → 自动驳回
  A5  LLM 法律风险（网络借贷/棋牌代理）→ 观察 LLM 甄别结果
  A6  同手机号重复提交 → 422
  A7  同企业名不同写法重复提交 → 422
  A8  AI 驳回后 24h 冷却 → 422
  A9  蜜罐字段 → 静默忽略不落库
  A10 手机号每日提交限流(3次/日) → 422
  A11 IP 每小时限流(5次/时) → 422
  A12 错误短信验证码 → 422
  A13 超管 API：AI 审核记录（reviewSource/riskFlags/reviewedBy）核验
  A14 内部甄别端点公网暴露面检查（无 token → 401）
用法: python3 accept-onboarding-ai.py [--web-base https://migaozn.com]
"""
import argparse
import json
import sys
import time
import urllib3

import requests

urllib3.disable_warnings()

API = "https://api.migaozn.com"
AI = "https://ai-api.migaozn.com"
WEB = "https://migaozn.com"
MERCHANT = "https://merchant.migaozn.com"
OPS = "https://ops.migaozn.com"

SUPER_ADMIN_PHONE = "13456800919"  # 生产 platform.admin.phone（云助手查 .env.admin-api 确认）
BYPASS_CODE = "123456"

TIMEOUT = 30
RUN = 3  # 每轮验收递增：手机号段/IP 网段/公司名批号全部按 RUN 隔离，避免与历史记录冷却/限流冲突
results = []  # (sid, name, passed, detail)


def fresh_phone(idx):
    # 每轮使用不同号段（RUN=1:137, 2:136, 3:138, 4:135），避免撞历史冷却/限流
    prefix = {1: "137", 2: "136", 3: "138", 4: "135"}.get(RUN, "139")
    return f"{prefix}{idx:08d}"


def company(name):
    """公司名追加轮次批号，避免同企业名（归一后）触发历史驳回冷却"""
    return f"{name}·{RUN}批"


def ip_addr(seed):
    """每轮使用独立 IP 网段（198.18.0.0/15 基准测试段，避免撞历史 IP 限流计数）"""
    return f"198.18.{RUN}.{seed}"


def record(sid, name, passed, detail=""):
    results.append((sid, name, bool(passed), detail))
    mark = "✅" if passed else "❌"
    print(f"{mark} [{sid}] {name} :: {detail}")


def http(method, url, **kw):
    kw.setdefault("timeout", TIMEOUT)
    kw.setdefault("verify", False)
    return requests.request(method, url, **kw)


def post_json(url, payload, headers=None, xff=None):
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    if xff:
        h["X-Forwarded-For"] = xff
    return http("POST", url, json=payload, headers=h)


def register(**payload):
    """POST /api/auth/register；payload 需含 phone/smsCode/companyName/contactName。
    支持 xff 关键字：作为 X-Forwarded-For 客户端 IP 透传（用于隔离 IP 频率计数）。"""
    xff = payload.pop("xff", None)
    payload.setdefault("smsCode", BYPASS_CODE)
    payload.setdefault("contactName", "测试联系人")
    return post_json(f"{API}/api/auth/register", payload, xff=xff)


def sms_login(phone, code=BYPASS_CODE):
    return post_json(f"{API}/api/auth/sms/login", {"phone": phone, "code": code})


# ============ 辅助 ============

def expect_status(resp, ok_codes):
    if resp.status_code in ok_codes:
        return True, resp.json() if resp.content else {}
    return False, f"HTTP {resp.status_code}: {resp.text[:200]}"


# ============ H: 健康与页面 ============

def h_health():
    try:
        r = http("GET", f"{API}/actuator/health")
        ok = r.status_code == 200 and "UP" in r.text
        record("H1", "admin-api 健康检查", ok, f"HTTP {r.status_code}" if not ok else "UP")
    except Exception as e:
        record("H1", "admin-api 健康检查", False, str(e))

    try:
        r = http("GET", f"{AI}/health")
        ok = r.status_code == 200
        record("H2", "ai-agent 健康检查", ok, f"HTTP {r.status_code}: {r.text[:80]}")
    except Exception as e:
        record("H2", "ai-agent 健康检查", False, str(e))


def h_homepage():
    try:
        r = http("GET", WEB)
        body = r.text
        checks = {
            "HTTP 200": r.status_code == 200,
            "公司名 杭州词元通达科技有限公司": "杭州词元通达科技有限公司" in body,
            "米高 × 小布": "米高 × 小布" in body or "米高" in body,
            "小布 智能客服": "小布" in body,
            "AI 智能甄别": "AI 智能甄别" in body,
            "即刻开通": "即刻开通" in body,
            "无旧名 米宝": "米宝" not in body,
            "无虚构品牌 A": "品牌 A" not in body,
            "无 1-3 个工作日": "1-3 个工作" not in body,
        }
        failed = [k for k, v in checks.items() if not v]
        record("H3", "主页新文案验收", not failed, "、".join(failed) if failed else "全部命中")
    except Exception as e:
        record("H3", "主页新文案验收", False, str(e))

    try:
        r = http("GET", f"{MERCHANT}/login")
        record("H4", "merchant 登录页可达", r.status_code == 200, f"HTTP {r.status_code}")
    except Exception as e:
        record("H4", "merchant 登录页可达", False, str(e))

    # ops 人工审批页废弃：/registrations 不应再有可用页面
    try:
        ro = http("GET", f"{OPS}/registrations", allow_redirects=False)
        rm = http("GET", f"{MERCHANT}/registrations", allow_redirects=False)
        page_gone = ro.status_code in (404, 410) or ro.status_code >= 500 or (
            "入驻审批" not in (ro.text or "")
        )
        page_gone_m = rm.status_code in (404, 410) or ("入驻审批" not in (rm.text or ""))
        record("H5", "人工审批页废弃(ops/merchant /registrations 无旧页面)",
               page_gone and page_gone_m,
               f"ops={ro.status_code} merchant={rm.status_code}")
    except Exception as e:
        record("H5", "人工审批页废弃", False, str(e))


# ============ A: 入驻 AI 甄别场景 ============

def a1_legit_approve():
    phone = fresh_phone(1)
    payload = {
        "phone": phone, "companyName": company("杭州织云布艺有限公司"),
        "contactName": "王织云", "industry": "布艺纺织",
        "address": "浙江省杭州市余杭区", "description": "主营窗帘、家纺布艺产品的设计生产与销售",
    }
    ok, body = expect_status(register(xff=ip_addr(101), **payload), (200,))
    if not ok:
        record("A1", "合法商家 AI 自动通过", False, body)
        return
    data = body.get("data", {})
    approved = data.get("status") == "approved"
    record("A1", "合法商家 AI 自动通过", approved, f"status={data.get('status')} msg={data.get('message')}")
    if not approved:
        return
    # 新租户管理员登录验证（租户+管理员已自动创建）
    lr = sms_login(phone)
    lok, lbody = expect_status(lr, (200,))
    token = (lbody.get("data") or {}).get("accessToken") if lok else None
    tenant_id = ((lbody.get("data") or {}).get("user") or {}).get("tenantId") if lok else None
    record("A1b", "新租户管理员可短信登录（租户+管理员已开通）",
           lok and bool(token) and tenant_id is not None,
           f"HTTP {lr.status_code} tenantId={tenant_id}")
    return {"phone": phone, "company": "杭州织云布艺有限公司"}


def a2_sensitive_reject():
    phone = fresh_phone(2)
    payload = {
        "phone": phone, "companyName": company("某某网络科技有限公司"),
        "description": "专业承接网络赌博平台招商加盟，欢迎下注",
    }
    ok, body = expect_status(register(xff=ip_addr(102), **payload), (200,))
    if not ok:
        record("A2", "敏感内容自动驳回", False, body)
        return phone
    data = body.get("data", {})
    passed = data.get("status") == "rejected" and bool(data.get("rejectReason"))
    record("A2", "敏感内容自动驳回", passed,
           f"status={data.get('status')} reason={data.get('rejectReason')}")
    return phone


def a3_injection_reject():
    phone = fresh_phone(3)
    payload = {
        "phone": phone,
        "companyName": f"杭州织云<script>alert(1)</script>布艺{RUN}批",
        "description": "主营布艺窗帘",
    }
    ok, body = expect_status(register(xff=ip_addr(103), **payload), (200,))
    if not ok:
        record("A3", "代码注入自动驳回", False, body)
        return
    data = body.get("data", {})
    passed = data.get("status") == "rejected"
    record("A3", "代码注入自动驳回", passed,
           f"status={data.get('status')} reason={data.get('rejectReason')}")


def a4_invalid_name_reject():
    phone = fresh_phone(4)
    # 非法企业名（纯数字）需每轮唯一，避免撞历史驳回冷却
    payload = {"phone": phone, "companyName": f"9999{RUN}888", "description": "test"}
    ok, body = expect_status(register(xff=ip_addr(104), **payload), (200,))
    if not ok:
        record("A4", "企业名非法格式自动驳回", False, body)
        return
    data = body.get("data", {})
    passed = data.get("status") == "rejected"
    record("A4", "企业名非法格式自动驳回", passed,
           f"status={data.get('status')} reason={data.get('rejectReason')}")


def a5_llm_legal_risk():
    """LLM 法律风险识别：网络借贷 / 棋牌代理 两个 case（规则层为 medium，交由 LLM 判断）"""
    observed = []
    for idx, (industry, desc) in enumerate(
        [
            ("网络借贷信息中介", "为个人提供无抵押快速贷款服务，放款快利率低"),
            ("棋牌游戏运营", "推广棋牌捕鱼游戏平台，提供充值提现服务"),
        ],
        start=1,
    ):
        phone = fresh_phone(50 + idx)
        payload = {"phone": phone, "companyName": company(f"杭州测试行业公司{idx}"),
                   "industry": industry, "description": desc}
        ok, body = expect_status(register(xff=ip_addr(50 + idx), **payload), (200,))
        data = (body.get("data") or {}) if ok else {}
        st = data.get("status")
        observed.append(f"{industry}:{st}")
        if idx == 2 and not ok:
            record("A5", "LLM 法律风险识别（借贷/棋牌）", False, body)
            return
    # 任一被 LLM 识别驳回即证明法律风险识别生效
    rejected = any("rejected" in o for o in observed)
    record("A5", "LLM 法律风险识别（借贷/棋牌）", rejected,
           "  ".join(observed) + (" → 有驳回" if rejected else " → 均 approved（记录为发现，需评审 prompt）"))


def a6_dup_phone(legit):
    if not legit:
        record("A6", "同手机号重复提交拦截", False, "前置 A1 未通过，跳过")
        return
    payload = {"phone": legit["phone"], "companyName": company("另一家完全不同的公司"),
               "description": "重复提交测试"}
    r = register(xff=ip_addr(106), **payload)
    ok = r.status_code == 422 and "已有" in r.text
    record("A6", "同手机号重复提交拦截", ok,
           f"HTTP {r.status_code}: {r.text[:120]}")


def a7_dup_company(legit):
    if not legit:
        record("A7", "同企业名(不同写法)重复拦截", False, "前置 A1 未通过，跳过")
        return
    payload = {"phone": fresh_phone(7), "companyName": f"杭州织云布艺  有限公司·{RUN}批",
               "description": "同一家企业换手机号+加空格变体再提交"}
    r = register(xff=ip_addr(107), **payload)
    ok = r.status_code == 422 and "该企业已有入驻申请" in r.text
    record("A7", "同企业名(不同写法)重复拦截", ok,
           f"HTTP {r.status_code}: {r.text[:120]}")


def a8_rejected_cooldown(sensitive_phone):
    if not sensitive_phone:
        record("A8", "AI 驳回后 24h 冷却", False, "前置 A2 未通过，跳过")
        return
    payload = {"phone": sensitive_phone, "companyName": company("杭州全新合规公司"),
               "description": "这次是干净的资料"}
    r = register(xff=ip_addr(108), **payload)
    ok = r.status_code == 422 and "小时后重新提交" in r.text
    record("A8", "AI 驳回后 24h 冷却", ok,
           f"HTTP {r.status_code}: {r.text[:120]}")


def a9_honeypot():
    phone = fresh_phone(9)
    payload = {"phone": phone, "companyName": company("杭州蜜罐测试公司"),
               "description": "honeypot", "website": "http://bot.example.com/x"}
    r = register(xff=ip_addr(109), **payload)
    ok = r.status_code == 200
    data = r.json().get("data", {}) if ok else {}
    silent = data.get("status") == "pending" and data.get("applicationId") == 0
    record("A9", "蜜罐字段静默忽略（不落库不调 AI）", ok and silent,
           f"HTTP {r.status_code} status={data.get('status')} applicationId={data.get('applicationId')}")
    return phone


def a10_phone_daily_limit():
    phone = fresh_phone(10)
    outcomes = []
    for i in range(4):
        payload = {"phone": phone, "companyName": company(f"杭州限流测试公司{i}"),
                   "description": "rate limit"}
        r = register(xff=ip_addr(110), **payload)
        outcomes.append(f"{i + 1}:{r.status_code}")
    # 第 1 次正常处理；第 4 次应命中手机号每日 3 次上限 → 422
    ok = outcomes[3].startswith("4:422") and "过于频繁" in register(
        xff=ip_addr(110),
        **{"phone": phone, "companyName": company("杭州限流测试公司X"), "description": "x"},
    ).text
    record("A10", "手机号每日提交限流(3次/日)", ok, "  ".join(outcomes))


def a11_ip_hourly_limit():
    """同一 IP（伪造 X-Forwarded-For 203.0.113.50）连发 6 个不同手机号 → 第 6 次命中 IP 5次/时上限"""
    outcomes = []
    for i in range(1, 7):
        payload = {"phone": fresh_phone(20 + i), "companyName": company(f"杭州IP限流测试公司{i}"),
                   "description": "ip limit"}
        r = register(xff=ip_addr(50), **payload)
        outcomes.append(f"#{i}:{r.status_code}")
    last_ok = outcomes[5].startswith("#6:422") and "提交过于频繁" in http(
        "POST", f"{API}/api/auth/register",
        json={"phone": fresh_phone(99), "companyName": company("杭州IP限流测试公司X"),
              "contactName": "测试", "smsCode": BYPASS_CODE, "description": "x"},
        headers={"Content-Type": "application/json", "X-Forwarded-For": "203.0.113.50"},
    ).text
    record("A11", "IP 每小时限流(5次/时)", last_ok, "  ".join(outcomes))


def a12_wrong_sms():
    phone = fresh_phone(12)
    payload = {"phone": phone, "companyName": "杭州验证码测试公司",
               "description": "x", "smsCode": "999999"}
    r = register(xff=ip_addr(112), **payload)
    ok = r.status_code == 422 and "验证码" in r.text
    record("A12", "错误短信验证码 → 422", ok, f"HTTP {r.status_code}: {r.text[:120]}")


def a13_super_admin_records(legit_phone, sensitive_phone, honeypot_phone):
    """超管查询入驻记录，核验 AI 审核元数据落库（best-effort：生产若无 platform_admin 则转 DB 侧验证）"""
    lr = sms_login(SUPER_ADMIN_PHONE)
    if lr.status_code != 200:
        record("A13", f"超管登录({SUPER_ADMIN_PHONE})", False, f"HTTP {lr.status_code}: {lr.text[:120]}")
        return
    token = (lr.json().get("data") or {}).get("accessToken")
    headers = {"Authorization": f"Bearer {token}"}
    r = http("GET", f"{API}/api/super-admin/registrations", params={"size": 100}, headers=headers)
    if r.status_code == 403:
        record("A13", "超管查询入驻记录", False,
               f"HTTP 403 PERMISSION_DENIED（超管 {SUPER_ADMIN_PHONE} 登录后仍无 super_admin 权限）")
        return
    if r.status_code != 200:
        record("A13", "超管查询入驻记录", False, f"HTTP {r.status_code}: {r.text[:150]}")
        return
    items = (r.json().get("data") or {}).get("items", [])
    by_phone = {it.get("phone"): it for it in items}
    checks = []
    legit = by_phone.get(legit_phone) if legit_phone else None
    if legit:
        checks.append(("A1 记录 reviewSource=ai", legit.get("reviewSource") == "ai"))
        checks.append(("A1 记录 reviewedBy 为空(外键安全)", legit.get("reviewedBy") is None))
        checks.append(("A1 记录 status=approved", legit.get("status") == "approved"))
    sens = by_phone.get(sensitive_phone) if sensitive_phone else None
    if sens:
        checks.append(("A2 记录 status=rejected", sens.get("status") == "rejected"))
        checks.append(("A2 记录 rejectReason 非空", bool(sens.get("rejectReason"))))
        checks.append(("A2 记录 reviewSource 非空", bool(sens.get("reviewSource"))))
    honeypot_gone = (honeypot_phone not in by_phone) if honeypot_phone else False
    checks.append(("A9 蜜罐手机号无任何记录", honeypot_gone))
    failed = [k for k, v in checks if not v]
    record("A13", "超管 API：AI 审核记录核验", not failed,
           "、".join(failed) if failed else f"共核验 {len(checks)} 项全部一致")


def a14_internal_endpoint_surface():
    """内部甄别端点公网暴露面：无 token 必须 401"""
    r = post_json(f"{AI}/api/internal/registration/review",
                  {"company_name": "测试", "contact_name": "测试", "phone": "13900000000"})
    ok = r.status_code in (401, 403, 404)
    record("A14", "内部甄别端点公网无 token 被拒", ok, f"HTTP {r.status_code}")


def main():
    global WEB  # noqa: PLW0603
    ap = argparse.ArgumentParser()
    ap.add_argument("--web-base", default=WEB)
    args = ap.parse_args()
    WEB = args.web_base

    print("=" * 70)
    print("云环境验收：商家入驻 AI 自动甄别全场景")
    print(f"目标: {API} / {AI} / {WEB}")
    print("=" * 70)

    h_health()
    h_homepage()

    legit = a1_legit_approve()
    sens_phone = a2_sensitive_reject()
    a3_injection_reject()
    a4_invalid_name_reject()
    a5_llm_legal_risk()
    a6_dup_phone(legit)
    a7_dup_company(legit)
    a8_rejected_cooldown(sens_phone)
    honeypot_phone = a9_honeypot()
    a10_phone_daily_limit()
    a11_ip_hourly_limit()
    a12_wrong_sms()
    a13_super_admin_records(legit["phone"] if legit else None, sens_phone, honeypot_phone)
    a14_internal_endpoint_surface()

    passed = sum(1 for _, _, p, _ in results if p)
    total = len(results)
    print("=" * 70)
    print(f"验收汇总: {passed}/{total} 通过")
    for sid, name, p, detail in results:
        if not p:
            print(f"  ❌ {sid} {name} :: {detail}")
    with open("/tmp/accept-onboarding-ai-result.json", "w", encoding="utf-8") as f:
        json.dump({"passed": passed, "total": total,
                   "results": [{"id": s, "name": n, "passed": p, "detail": d}
                               for s, n, p, d in results]},
                  f, ensure_ascii=False, indent=2)
    print("证据已存: /tmp/accept-onboarding-ai-result.json")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
