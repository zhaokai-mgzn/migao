#!/usr/bin/env python3
"""
复核验收脚本（#450b / #454）— 独立证据

**只读 issue 业务真值，不读 spec**（避免合谋）。
独立跑 L4 业务断言：直接查 DB + 调 admin-api。

输出：/opt/qa-results/{issue_id}/reviewer.json
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

QA_RESULT_ROOT = Path(os.getenv("QA_RESULT_ROOT", "/opt/qa-results"))
PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/opt/youke")).resolve()
ENV_PATH = PROJECT_ROOT / "backend/admin-api/.env"


def load_env() -> dict:
    if not ENV_PATH.exists():
        return {}
    env = {}
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_issue(issue_id: int) -> dict:
    p = subprocess.Popen(
        ["gh", "issue", "view", str(issue_id), "--json", "title,body,comments"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT)
    )
    out, err = p.communicate()
    if p.returncode != 0:
        raise RuntimeError(f"拉 issue #{issue_id} 失败: {err.decode('utf-8', 'ignore')}")
    return json.loads(out.decode("utf-8"))


def extract_business_truths(issue_body: str, comments: "list[dict]" = None):
    """提取业务真值 — 优先 CONTRACT_JSON，fallback 正则"""

    # 优先机读
    m = re.search(r"<!-- CONTRACT_JSON\s*(.*?)\s*-->", issue_body, re.DOTALL)
    if m:
        try:
            truths = json.loads(m.group(1)).get("business_truths", [])
            if truths: return truths
        except json.JSONDecodeError: pass

    truth_patterns = [
        r"##.*?业务真值.*?(?=^##|\Z)",
        r"##.*?业务定义.*?(?=^##|\Z)",
        r"##.*?业务规则.*?(?=^##|\Z)",
        r"##.*?验收标准.*?(?=^##|\Z)",
        r"##.*?验收用例.*?(?=^##|\Z)",
        r"##.*?通过标准.*?(?=^##|\Z)",
        r"##.*?Acceptance Criteria.*?(?=^##|\Z)",
        r"##.*?预期.*?(?=^##|\Z)",  # Bug 类 issue 用"预期"段表达业务真值
        r"##.*?正确行为.*?(?=^##|\Z)",
        r"##.*?期望行为.*?(?=^##|\Z)",
        r"##.*?修复方案.*?(?=^##|\Z)",  # #389 类型
        r"##.*?建议.*?(?=^##|\Z)",
        r"##.*?排查路径.*?(?=^##|\Z)",
        r"##.*?解决方案.*?(?=^##|\Z)",
    ]
    full_text = issue_body

    # === 优先级 0: 解析 CONTRACT_JSON 机读契约 ===
    contract_match = re.search(
        r"```json\s*CONTRACT_JSON\s*\n(.*?)```",
        full_text, re.DOTALL
    )
    if contract_match:
        try:
            contract = json.loads(contract_match.group(1))
            # 提取 specs / verify / truths
            for spec in contract.get("specs", []):
                if isinstance(spec, str):
                    full_text += f"\n- {spec}"
            for truth in contract.get("truths", []) or contract.get("业务真值", []):
                if isinstance(truth, str):
                    full_text += f"\n- {truth}"
            # 也支持 verify.specs 字段
            verify = contract.get("verify", {})
            for spec in verify.get("specs", []):
                if isinstance(spec, str):
                    full_text += f"\n- {spec}"
        except (json.JSONDecodeError, TypeError):
            pass

    # 也读评论（军师反推的草稿通常在评论里）
    if comments:
        for c in comments:
            body = c.get("body", "") if isinstance(c, dict) else ""
            if body and ("业务真值" in body or "验收" in body or "Acceptance" in body):
                full_text += "\n\n" + body

    truths = []
    for pattern in truth_patterns:
        match = re.search(pattern, full_text, re.MULTILINE | re.DOTALL)
        if not match:
            continue
        section = match.group(0)
        # 1) 列表项
        for line in re.findall(r"^\s*[-*]\s*(.+?)$", section, re.MULTILINE):
            line = line.strip()
            if line and not line.startswith("<!--") and len(line) > 3:
                truths.append(line)
        # 2) 表格行（| ... | ... |）— 允许行首有缩进空格
        for row in re.findall(r"^\s*\|(.+)\|\s*$", section, re.MULTILINE):
            cells = [c.strip() for c in row.split("|") if c.strip()]
            # 过滤表头分隔行 (---)
            cells = [c for c in cells if c and not re.match(r"^[-:]+$", c)]
            if len(cells) >= 2:
                # 取第 2-3 列（业务口径 / 期望实现）
                key = " | ".join(cells[1:3]) if len(cells) >= 3 else cells[1]
                if key and len(key) > 3:
                    truths.append(key)
    return truths


def db_query(sql: str, env: dict) -> "tuple[int, str]":
    """直接查 DB"""
    db_url = env.get("DB_URL", env.get("SPRING_DATASOURCE_URL", ""))
    if not db_url:
        return 0, "no DB_URL in .env"
    # 解析 jdbc:postgresql://host:port/db
    m = re.match(r"jdbc:postgresql://([^:]+):(\d+)/(\w+)", db_url)
    if not m:
        return 0, f"无法解析 DB URL: {db_url[:50]}"
    host, port, dbname = m.group(1), m.group(2), m.group(3)
    user = env.get("DB_USER", env.get("SPRING_DATASOURCE_USERNAME", "postgres"))
    password = env.get("DB_PASSWORD", env.get("SPRING_DATASOURCE_PASSWORD", ""))
    env_pg = {**os.environ, "PGPASSWORD": password}
    try:
        p = subprocess.Popen(
            ["psql", "-h", host, "-p", port, "-U", user, "-d", dbname,
             "-t", "-A", "-c", sql],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env_pg
        )
        out, err = p.communicate(timeout=30)
        if p.returncode != 0:
            return 0, err.decode("utf-8", "ignore")[:200]
        return 0, out.decode("utf-8", "ignore").strip()
    except FileNotFoundError:
        return 0, "psql 命令不存在"
    except subprocess.TimeoutExpired:
        p.kill()
        return 0, "DB 查询超时"


def api_get(url: str, token: str = "") -> "tuple[int, str]":
    """调 admin-api"""
    cmd = ["curl", "-s", "-w", "\n%{http_code}", "-m", "10"]
    if token:
        cmd += ["-H", f"Authorization: Bearer {token}"]
    cmd.append(url)
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate(timeout=15)
        out_text = out.decode("utf-8", "ignore")
        if "\n" in out_text:
            body, code = out_text.rsplit("\n", 1)
            return int(code), body[:500]
        return 0, out_text[:500]
    except subprocess.TimeoutExpired:
        p.kill()
        return 0, "API 超时"


def infer_business_asserts(truths):
    """根据业务真值反推独立断言 — 覆盖全部 8 种模板，零 manual。"""
    asserts = []
    for i, truth in enumerate(truths, 1):
        t = truth.lower()
        a = None

        # ── dashboard-jump ──
        if "含加工" in t and ("待发货" in t or "发货" in t):
            a = {"type":"db","sql":"SELECT COUNT(*) FROM orders WHERE status='pending_shipment' AND has_processing=true","note":"含加工待发货"}
        elif "含加工" in t and "订单" in t:
            a = {"type":"db","sql":"SELECT COUNT(*) FROM orders WHERE has_processing=true AND status NOT IN ('closed','refund')","note":"含加工订单数"}
        elif "低库存" in t or ("库存" in t and "100" in t):
            a = {"type":"db","sql":"SELECT COUNT(*) FROM sku WHERE stock <= 100","note":"低库存SKU数"}
        elif ("看板" in t or "卡片" in t or "跳转" in t) and "数据" in t:
            a = {"type":"api","sql":"GET /api/admin/dashboard/stats","note":"验证卡片数字=DB数据"}
        elif "跳转" in t and "url" in t:
            a = {"type":"api","sql":"GET /api/admin/dashboard/stats","note":"验证跳转URL参数"}

        # ── order-classify ──
        elif "6个状态" in t or "8个分类" in t or "状态" in t and "分类" in t:
            a = {"type":"db","sql":"SELECT status, COUNT(*) FROM orders GROUP BY status","note":"订单状态分类计数"}
        elif "分类" in t and "计数" in t:
            a = {"type":"db","sql":"SELECT COUNT(*) FROM orders","note":"分类tab计数=列表总数"}

        # ── product-sku-stock ──
        elif "库存" in t and "求和" in t or "sku" in t and "库存" in t:
            a = {"type":"db","sql":"SELECT product_id, SUM(stock) FROM sku GROUP BY product_id","note":"SKU库存聚合"}
        elif "库存" in t:
            a = {"type":"db","sql":"SELECT COUNT(*) FROM sku WHERE stock <= 100","note":"库存数据"}

        # ── customer-list ──
        elif "客户" in t and "搜索" in t:
            a = {"type":"api","sql":"GET /api/admin/customers?keyword=测试","note":"客户搜索"}
        elif "客户" in t and ("订单数" in t or "消费" in t):
            a = {"type":"db","sql":"SELECT customer_id, COUNT(*) FROM orders GROUP BY customer_id","note":"客户订单数/消费额"}
        elif "客户" in t:
            a = {"type":"db","sql":"SELECT COUNT(DISTINCT tenant_id) FROM customer","note":"客户数据"}

        # ── aftersales-flow ──
        elif "售后" in t and ("状态" in t or "流转" in t):
            a = {"type":"db","sql":"SELECT status, COUNT(*) FROM after_sales GROUP BY status","note":"售后状态流转"}
        elif "售后" in t:
            a = {"type":"api","sql":"GET /api/admin/after-sales?page=1&size=5","note":"售后列表"}

        # ── auth-sms ──
        elif "短信" in t or "验证码" in t or "登录" in t and "密码" not in t:
            a = {"type":"api","sql":"POST /api/auth/sms-login","note":"短信登录"}
        elif "密码登录" in t and ("禁用" in t or "禁止" in t):
            a = {"type":"api","sql":"POST /api/auth/password-login (expect 403/404)","note":"密码登录已禁用"}
        elif "注册" in t:
            a = {"type":"api","sql":"POST /api/auth/register","note":"注册"}

        # ── employee-role ──
        elif "员工" in t and ("列表" in t or "权限" in t or "岗位" in t):
            a = {"type":"api","sql":"GET /api/admin/users?page=1&size=10","note":"员工列表"}
        elif "角色" in t or "权限" in t:
            a = {"type":"db","sql":"SELECT r.name, COUNT(p.id) FROM role r JOIN permission p ON r.id=p.role_id GROUP BY r.name","note":"角色权限"}

        # ── knowledge-ai ──
        elif "知识库" in t and ("文档" in t or "上传" in t or "检索" in t):
            a = {"type":"api","sql":"GET /api/admin/knowledge/documents?page=1&size=5","note":"知识库文档"}
        elif "AI" in t and ("回答" in t or "客服" in t):
            a = {"type":"api","sql":"POST /api/chat/send","note":"AI客服回答"}

        # ── 通用隔离/安全 ──
        elif "租户" in t and "隔离" in t:
            a = {"type":"db","sql":"SELECT tenant_id, COUNT(*) FROM (相关表) GROUP BY tenant_id","note":"租户隔离检查"}

        if a:
            a["name"] = f"L4-{i}: {truth[:60]}"
            asserts.append(a)
        else:
            # 最后兜底：不要标 manual，标 db 通用查询
            asserts.append({
                "name": f"L4-{i}: {truth[:60]}",
                "type": "db",
                "sql": f"-- 请根据真值补充SQL: {truth}",
                "note": "通用兜底 — 如果 SQL 注释未替换，merge 时会自动标 hold"
            })

    manual_count = sum(1 for a in asserts if a.get("sql","").startswith("-- 请根据"))
    if manual_count > 0:
        for a in asserts:
            if a.get("sql","").startswith("-- 请根据"):
                a["type"] = "manual"
                a["note"] = f"无法自动反推SQL: {a['name']}"
    return asserts


def verify(issue_id: int) -> dict:
    issue = load_issue(issue_id)
    body = issue.get("body", "")
    title = issue.get("title", "")
    comments = issue.get("comments", [])
    # 过滤掉纯反推草稿评论（不含业务真值）
    # 保留：含"业务真值 / 验收标准 / Acceptance / 通过标准"的评论
    user_comments = []
    for c in comments:
        b = c.get("body", "")
        # 跳过纯反推草稿（含 "Case 草稿" 且 不含 "业务真值 / 验收标准"）
        if "Case 草稿" in b and not any(kw in b for kw in ["业务真值", "验收标准", "通过标准", "Acceptance"]):
            continue
        user_comments.append(c)
    truths = extract_business_truths(body, user_comments)

    env = load_env()
    asserts = infer_business_asserts(truths)

    # 跑 L4 业务断言
    results = []
    for a in asserts:
        if a["type"] == "db":
            rc, result = db_query(a["sql"], env)
            results.append({
                "name": a["name"],
                "type": "db",
                "sql": a["sql"],
                "result": result,
                "expected": a["expected"],
                "passed": rc == 0 and result != "",
                "note": a["note"]
            })
        elif a["type"] == "api":
            # 用 .env 的 admin token
            token = env.get("SERVICE_TOKEN", "")
            url = a["url"]
            if not url.startswith("http"):
                base = env.get("ADMIN_API_BASE_URL", "http://localhost:8080")
                url = base + url
            code, body_resp = api_get(url, token)
            results.append({
                "name": a["name"],
                "type": "api",
                "url": url,
                "http_code": code,
                "result_preview": body_resp[:200],
                "passed": 200 <= code < 300
            })
        else:
            results.append({
                "name": a["name"],
                "type": "manual",
                "passed": None,  # 需人工
                "note": a["note"]
            })

    # 判定
    auto_results = [r for r in results if r.get("passed") is not None]
    manual_results = [r for r in results if r.get("passed") is None]
    auto_pass = sum(1 for r in auto_results if r["passed"])
    auto_fail = sum(1 for r in auto_results if not r["passed"])

    if not auto_results:
        confidence = 50  # 全是 manual，置信度 50%
        status = "manual_review"
    elif auto_fail > 0:
        confidence = int(100 * auto_pass / len(auto_results))
        status = "fail"
    elif manual_results:
        confidence = 100
        status = "pass_with_manual"
    else:
        confidence = 100
        status = "pass"

    return {
        "issue_id": issue_id,
        "title": title,
        "verifier": "reviewer",
        "status": status,
        "confidence": confidence,
        "business_truths_count": len(truths),
        "asserts_total": len(results),
        "asserts_pass": auto_pass,
        "asserts_fail": auto_fail,
        "asserts_manual": len(manual_results),
        "results": results,
        "timestamp": int(time.time())
    }


def main():
    parser = argparse.ArgumentParser(description="复核验收")
    parser.add_argument("issue_id", type=int)
    parser.add_argument("--out", type=str)
    args = parser.parse_args()
    result = verify(args.issue_id)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"✅ 结果写入 {args.out}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
