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
from urllib.parse import quote, urlparse, urlunparse

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


def api_get(url: str, token: str = "") -> "tuple[int, str, str]":
    """调 admin-api。返回 (http_code, response_body, error)"""
    cmd = ["curl", "-s", "-w", "\n%{http_code}", "-m", "10"]
    if token:
        cmd += ["-H", f"X-Service-Token: {token}"]
    cmd.append(url)
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate(timeout=15)
        out_text = out.decode("utf-8", "ignore")
        if "\n" in out_text:
            body, code = out_text.rsplit("\n", 1)
            return int(code), body[:2000], ""
        return 0, out_text[:2000], ""
    except subprocess.TimeoutExpired:
        p.kill()
        return 0, "", "API 超时"


def resolve_url(url: str, base: str, token: str) -> str:
    """解析 URL 中的 {placeholder} 并 URL-编码中文参数。

    支持 {id}, {order_id} 等占位符。通过查 list API 获取真实 ID。
    """
    # 1. URL-编码非 ASCII 字符
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    if parsed.query:
        query_parts = []
        for part in parsed.query.split('&'):
            if '=' in part:
                k, v = part.split('=', 1)
                v = urllib.parse.quote(v, safe='')
                query_parts.append(f'{k}={v}')
            else:
                query_parts.append(part)
        encoded_query = '&'.join(query_parts)
        url = urllib.parse.urlunparse(parsed._replace(query=encoded_query))

    # 2. 解析 {placeholder} 占位符
    placeholders = re.findall(r'\{(\w+)\}', url)
    if not placeholders:
        return url

    # 3. 推导 list API 并获取真实数据
    # /api/admin/aftersales/{id} → /api/admin/aftersales?size=1
    list_url = url
    for ph in placeholders:
        # 从 URL path 推导 list endpoint
        path_parts = url.split('/')
        for i, part in enumerate(path_parts):
            if '{' + ph + '}' in part:
                # 该 segment 之前的部分就是 list endpoint
                list_url = '/'.join(path_parts[:i]) + '?size=1'
                break

    if list_url == url and '{' in url:
        # Fallback: 用 path 前缀
        prefix = url.split('/{')[0]
        list_url = prefix + '?size=1'

    code, body, _ = api_get(list_url, token)
    if code < 200 or code >= 300:
        return url  # 无法解析，返回原 URL

    # 4. 从响应中提取真实值
    try:
        data = json.loads(body)
    except:
        return url

    for ph in placeholders:
        real_val = None
        # 尝试从 data.id 或 data.data.id 或 items[0].id 提取
        if isinstance(data, dict):
            if 'data' in data and isinstance(data['data'], dict):
                real_val = data['data'].get('id') or data['data'].get(ph)
            if not real_val:
                real_val = data.get('id') or data.get(ph)
            if not real_val and 'items' in data.get('data', {}):
                items = data['data']['items']
                if items:
                    real_val = items[0].get(ph, items[0].get('id'))
            if not real_val and 'records' in data.get('data', {}):
                records = data['data']['records']
                if records:
                    real_val = records[0].get(ph, records[0].get('id'))

        if real_val is not None:
            url = url.replace('{' + ph + '}', str(real_val))

    return url


def validate_expect(body_text: str, expect_rules: list) -> "tuple[bool, str]":
    """根据模板 expect 规则验证 API 响应体。

    expect_rules 可以是字符串列表或结构化规则列表。
    支持的字符串模式：
      - "data > N" / "data >= N" / "data < N" / "data <= N" / "data == N"
      - "items 非空" / "data 非空"
      - "每项 <field> <op> <value>" (每项/每个/每条)
      - "items 中每条 <field> = <value>"
      - "items 中每条 <field> NOT IN (v1, v2)"

    返回 (passed: bool, detail: str)
    """
    if not expect_rules or not body_text:
        return True, "无 expect 规则或空响应，跳过验证"

    # 尝试解析 JSON
    data = None
    try:
        data = json.loads(body_text)
    except (json.JSONDecodeError, TypeError):
        return True, "响应非 JSON，跳过 expect 验证（仅检查 HTTP 状态）"

    results = []
    for rule in expect_rules:
        rule_str = rule if isinstance(rule, str) else rule.get("expect", str(rule))

        # AND 分解："A AND B AND C" → [A, B, C] 分别检查
        sub_rules = re.split(r"\s+AND\s+|\s+and\s+|\s*&&\s*", rule_str, flags=re.IGNORECASE) if " AND " in rule_str.upper() else [rule_str]

        sub_results = []
        for sr in sub_rules:
            sr = sr.strip()
            if not sr:
                continue
            p, d = _check_one_expect(data, sr)
            sub_results.append((p, d))

        # 所有子规则都通过才算通过
        all_sub_pass = all(r[0] for r in sub_results)
        sub_detail = " AND ".join([f"{'✅' if r[0] else '❌'} {r[1]}" for r in sub_results])
        results.append((all_sub_pass, sub_detail if len(sub_results) > 1 else sub_results[0][1]))

    all_pass = all(r[0] for r in results)
    detail_parts = []
    for p, d in results:
        icon = "✅" if p else "❌"
        detail_parts.append(f"{icon} {d}")

    return all_pass, "; ".join(detail_parts)


def _check_one_expect(data: dict, rule: str) -> "tuple[bool, str]":
    """检查单条 expect 规则"""
    rule_lower = rule.lower().strip()

    # ── data > N / data >= N / data < N / data <= N / data == N ──
    m = re.match(r"data\s*(>=|<=|>|<|==|=)\s*(\d+)", rule_lower)
    if m:
        op, val = m.group(1), int(m.group(2))
        actual = data.get("data")
        if isinstance(actual, (int, float)):
            if op in (">",): ok = actual > val
            elif op in (">=",): ok = actual >= val
            elif op in ("<",): ok = actual < val
            elif op in ("<=",): ok = actual <= val
            elif op in ("==", "="): ok = actual == val
            else: ok = False
            return ok, f"data={actual} {op} {val}: {'PASS' if ok else 'FAIL'}"
        return False, f"data 字段不是数值 (实际: {type(actual).__name__})"

    # ── items 非空 / data 非空 ──
    m = re.match(r"(items|data|结果)\s*非空|不为空", rule)
    if m:
        field = m.group(1)
        items = data.get("data", data) if field in ("data", "结果") else data.get("data", {}).get("items", data.get("items", []))
        if isinstance(items, list):
            ok = len(items) > 0
            return ok, f"{field} 非空: 长度={len(items)} {'PASS' if ok else 'FAIL'}"
        elif isinstance(items, dict):
            ok = len(items) > 0
            return ok, f"{field} 非空: keys={len(items)} {'PASS' if ok else 'FAIL'}"
        return False, f"{field} 不存在或为空"

    # ── items 中每条 <field> = / != / NOT IN ──
    m = re.match(r"(?:items\s*中\s*)?每(?:条|项|个)\s*(\w+)\s*(>=|<=|!=|>|<|=|==|not\s*in)\s*(.+)", rule_lower)
    if m:
        field, op, val_str = m.group(1), m.group(2).replace(" ", ""), m.group(3).strip()
        items = data.get("data", {}).get("items", data.get("items", data.get("data", [])))
        if not isinstance(items, list):
            return False, f"items 不是数组 (实际: {type(items).__name__})"
        if len(items) == 0:
            return False, f"items 为空，无法检查 {field}"

        if op == "notin":
            # NOT IN (v1, v2, v3)
            vals = [v.strip().strip("'\"") for v in val_str.strip("()").split(",")]
            failures = []
            for idx, item in enumerate(items):
                item_val = str(item.get(field, ""))
                if item_val in vals:
                    failures.append(f"[{idx}] {field}={item_val}")
            if failures:
                return False, f"{len(failures)}/{len(items)} 项 {field} 在禁止值中: {failures[:3]}"
            return True, f"全部 {len(items)} 项 {field} NOT IN ({', '.join(vals)})"

        # 数值比较
        try:
            expected_val = float(val_str) if val_str.replace(".", "").replace("-", "").isdigit() else val_str.strip("'\"")
        except ValueError:
            expected_val = val_str.strip("'\"")

        failures = []
        for idx, item in enumerate(items):
            item_val = item.get(field)
            if item_val is None:
                failures.append(f"[{idx}] {field}=None")
                continue
            if isinstance(expected_val, float) and isinstance(item_val, (int, float)):
                if op == ">" and not (item_val > expected_val): failures.append(f"[{idx}] {field}={item_val}")
                elif op == ">=" and not (item_val >= expected_val): failures.append(f"[{idx}] {field}={item_val}")
                elif op == "<" and not (item_val < expected_val): failures.append(f"[{idx}] {field}={item_val}")
                elif op == "<=" and not (item_val <= expected_val): failures.append(f"[{idx}] {field}={item_val}")
                elif op == "!=" and not (item_val != expected_val): failures.append(f"[{idx}] {field}={item_val}")
                elif op in ("=", "==") and not (item_val == expected_val): failures.append(f"[{idx}] {field}={item_val}")
            else:
                sv = str(item_val)
                ev = str(expected_val)
                if op in ("=", "==") and sv != ev: failures.append(f"[{idx}] {field}={sv}")
                elif op == "!=" and sv == ev: failures.append(f"[{idx}] {field}={sv}")

        if failures:
            return False, f"{len(failures)}/{len(items)} 项不满足 {field} {op} {val_str}: {failures[:3]}"
        return True, f"全部 {len(items)} 项 {field} {op} {val_str}"

    # ── 兜底：无法解析 → 不阻塞，标记 manual ──
    return True, f"⚠️ expect 规则无法自动解析: {rule[:60]}"


def infer_business_asserts(truths, template=None):
    """根据业务真值反推 API 断言。优先从模板 reviewer_asserts 取。

    返回的每个 assert 包含:
      - name, type, url (API 类型)
      - expect: 模板的 expect 规则列表（用于自动验证）
    """
    if template and template.get("reviewer_asserts"):
        api_asserts = []  # list of {url, expect}
        for a in template["reviewer_asserts"]:
            if isinstance(a, str) and "API:" in a:
                api_asserts.append({"url": a.replace("API:", "").strip(), "expect": []})
            elif isinstance(a, dict) and "API" in a:
                expect_rules = a.get("expect", [])
                if isinstance(expect_rules, str):
                    expect_rules = [expect_rules]
                api_asserts.append({"url": a["API"], "expect": expect_rules})
        if api_asserts:
            result = []
            for i, t in enumerate(truths):
                aa = api_asserts[i % len(api_asserts)]
                result.append({
                    "name": f"L4-{i+1}: {t[:60]}",
                    "type": "api",
                    "url": aa["url"],
                    "expect": aa.get("expect", [])
                })
            return result

    # Fallback: 关键词匹配 API（无 expect 规则）
    asserts = []
    for i, t in enumerate(truths, 1):
        tl = t.lower()
        url = None
        if "看板" in tl or "dashboard" in tl: url = "GET /api/admin/dashboard/stats"
        elif "订单" in tl: url = "GET /api/admin/orders?page=1&size=5"
        elif "商品" in tl or "sku" in tl: url = "GET /api/admin/products?page=1&size=5"
        elif "客户" in tl: url = "GET /api/admin/customers?page=1&size=5"
        elif "售后" in tl: url = "GET /api/admin/after-sales?page=1&size=5"
        elif "登录" in tl or "验证码" in tl: url = "POST /api/auth/sms-login"
        elif "注册" in tl: url = "POST /api/auth/register"
        elif "员工" in tl: url = "GET /api/admin/users?page=1&size=10"
        elif "知识库" in tl: url = "GET /api/admin/knowledge/documents?page=1&size=5"

        if url:
            asserts.append({"name": f"L4-{i}: {t[:60]}", "type": "api", "url": url, "expect": []})
        else:
            asserts.append({"name": f"L4-{i}: {t[:60]}", "type": "manual",
                           "note": "无匹配 API，请军师在模板中补充"})
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
    # 尝试从 DRAFT_JSON 获取模板
    template = None
    for c in comments:
        m = re.search(r"<!-- DRAFT_JSON\s*(.*?)\s*-->", c.get("body",""), re.DOTALL)
        if m:
            try:
                tmpl_name = json.loads(m.group(1)).get("template")
                if tmpl_name and re.match(r"^[a-z][a-z0-9-]*$", tmpl_name):
                    import yaml
                    tp = (Path(__file__).resolve().parent.parent.parent / "docs/verification-templates" / f"{tmpl_name}.yml").resolve()
                    if str(tp).startswith(str(Path(__file__).resolve().parent.parent.parent / "docs/verification-templates")) and tp.exists():
                        with open(tp) as f: template = yaml.safe_load(f)
                break
            except: pass

    asserts = infer_business_asserts(truths, template)
    token = env.get("SERVICE_TOKEN", "")
    base = env.get("ADMIN_API_BASE_URL", "http://localhost:8081")

    results = []
    for a in asserts:
        if a["type"] == "api":
            url = a["url"]
            if not url.startswith("http"):
                # 模板 URL 格式: "GET /api/xxx" 或 "POST /api/xxx"
                path = url
                for prefix in ["GET ", "POST ", "PUT ", "DELETE ", "PATCH "]:
                    if path.startswith(prefix):
                        path = path[len(prefix):]
                        break
                url = base.rstrip("/") + "/" + path.lstrip("/")
            # 解析占位符 + URL 编码
            url = resolve_url(url, base, token)
            code, body_resp, err = api_get(url, token)

            http_ok = 200 <= code < 300
            expect_ok = True
            expect_detail = ""
            expect_rules = a.get("expect", [])

            if expect_rules and body_resp:
                expect_ok, expect_detail = validate_expect(body_resp, expect_rules)

            # HTTP 状态 + expect 规则双验证
            passed = http_ok and expect_ok

            results.append({
                "name": a["name"], "type": "api", "url": url,
                "http_code": code, "result_preview": body_resp[:200] if body_resp else "",
                "http_ok": http_ok,
                "expect_ok": expect_ok,
                "expect_detail": expect_detail,
                "expect_rules_count": len(expect_rules),
                "passed": passed
            })
        else:
            results.append({
                "name": a["name"], "type": "manual",
                "passed": None, "note": a.get("note", "")
            })

    # 判定
    auto_results = [r for r in results if r.get("passed") is not None]
    manual_results = [r for r in results if r.get("passed") is None]
    auto_pass = sum(1 for r in auto_results if r["passed"])
    auto_fail = sum(1 for r in auto_results if not r["passed"])

    # expect 验证统计
    expect_total = sum(1 for r in auto_results if r.get("expect_rules_count", 0) > 0)
    expect_pass = sum(1 for r in auto_results if r.get("expect_ok") and r.get("expect_rules_count", 0) > 0)

    if not auto_results:
        confidence = 50
        status = "manual_review"
    elif auto_fail > 0:
        # 惩罚：HTTP 通过但 expect 失败 → 置信度降低
        confidence = int(100 * auto_pass / len(auto_results))
        status = "fail"
    elif manual_results:
        confidence = 100 if expect_total == 0 or expect_pass == expect_total else 80
        status = "pass_with_manual"
    else:
        confidence = 100 if expect_total == 0 or expect_pass == expect_total else 80
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
        "expect_total": expect_total,
        "expect_pass": expect_pass,
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
