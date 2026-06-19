#!/usr/bin/env python3
"""
确定性断言校验工具 v3.3 — verify-agent 的唯一校验层。

verify-agent 将 curl 返回的 JSON 通过管道传入本工具做逐项校验。
输出确定性 JSON，不受 LLM 波动影响。check_assert 说 fail 就是 fail。

用法:
  # 正向断言
  curl -s ... | python3 check_assert.py --rule "data > 0" --rule "items 非空"
  curl -s ... | python3 check_assert.py --rule "每项 status = pending"

  # HTTP 状态码断言（v3.3 新增）
  curl -s ... | python3 check_assert.py --rule "status = 200"
  curl -s ... | python3 check_assert.py --rule "status >= 400"   # 负向测试

  # 响应结构断言（v3.3 新增）
  curl -s ... | python3 check_assert.py --rule "success = true"
  curl -s ... | python3 check_assert.py --rule "error.code = VALIDATION_ERROR"

输出:
  {"all_pass": true/false, "rules": [{"rule":"...","pass":true/false,"detail":"..."}]}
"""

import argparse
import json
import re
import sys


def check_data_op(data: dict, rule: str) -> "tuple[bool, str]":
    """data > N / data >= N / data < N / data <= N / data == N"""
    rule_lower = rule.lower().strip()
    m = re.match(r"data\s*(>=|<=|>|<|==|=)\s*(\d+)", rule_lower)
    if not m:
        return False, f"无法解析: {rule}"
    op, val = m.group(1), int(m.group(2))
    actual = data.get("data")
    if not isinstance(actual, (int, float)):
        return False, f"data 字段不是数值 (实际: {type(actual).__name__})"
    if op in (">",): ok = actual > val
    elif op in (">=",): ok = actual >= val
    elif op in ("<",): ok = actual < val
    elif op in ("<=",): ok = actual <= val
    elif op in ("==", "="): ok = actual == val
    else: ok = False
    return ok, f"data={actual} {op} {val}"


def check_status(data: dict, rule: str) -> "tuple[bool, str]":
    """HTTP 状态码校验: status = 200 / status >= 400 / status != 500"""
    rule_lower = rule.lower().strip()
    m = re.match(r"status\s*(>=|<=|>|<|!=|==|=)\s*(\d+)", rule_lower)
    if not m:
        return False, f"无法解析: {rule}"
    op, expected = m.group(1), int(m.group(2))
    # HTTP 响应可能包含 status 字段（由调用方在 curl 后注入），
    # 也可能在 error.code 或顶层 code 字段
    actual = data.get("status")
    if actual is None:
        actual = data.get("code")
    if actual is None:
        return False, f"响应中无 status/code 字段，无法校验"
    if not isinstance(actual, (int, float)):
        try:
            actual = int(actual)
        except (ValueError, TypeError):
            return False, f"status 字段不是数值 (实际: {type(actual).__name__} = {actual})"
    if op in (">",): ok = actual > expected
    elif op in (">=",): ok = actual >= expected
    elif op in ("<",): ok = actual < expected
    elif op in ("<=",): ok = actual <= expected
    elif op in ("==", "="): ok = actual == expected
    elif op == "!=": ok = actual != expected
    else: ok = False
    return ok, f"status={actual} {op} {expected}"


def check_response_field(data: dict, rule: str) -> "tuple[bool, str]":
    """校验响应顶层字段: success = true / error.code = VALIDATION_ERROR"""
    rule_stripped = rule.strip()
    m = re.match(r"(success|error\.\w+)\s*(>=|<=|>|<|!=|==|=)\s*(.+)", rule_stripped, re.IGNORECASE)
    if not m:
        return False, f"无法解析: {rule}"
    field, op, expected_str = m.group(1), m.group(2), m.group(3).strip()

    # 支持嵌套字段如 error.code
    if "." in field:
        parts = field.split(".")
        val = data
        for p in parts:
            val = val.get(p) if isinstance(val, dict) else None
    else:
        val = data.get(field)

    if val is None:
        return False, f"字段 {field} 不存在或为 null"

    # Boolean handling
    if isinstance(val, bool) or expected_str.lower() in ("true", "false"):
        expected_bool = expected_str.lower() == "true"
        if op in ("==", "="):
            ok = bool(val) == expected_bool
        elif op == "!=":
            ok = bool(val) != expected_bool
        else:
            ok = False
        return ok, f"{field}={val} {op} {expected_str}"

    # String comparison
    sv = str(val)
    ev = expected_str.strip("'\"")
    if op in ("==", "="): ok = sv == ev
    elif op == "!=": ok = sv != ev
    else: ok = False
    return ok, f"{field}={sv} {op} {ev}"


def check_nonempty(data: dict, rule: str) -> "tuple[bool, str]":
    """items 非空 / data 非空"""
    m = re.match(r"(items|data|结果)\s*非空|不为空", rule)
    if not m:
        return False, f"无法解析: {rule}"
    field = m.group(1)
    if field in ("data", "结果"):
        target = data.get("data", data)
    else:
        target = data.get("data", {}).get("items", data.get("items", []))
    if isinstance(target, (list, dict)):
        ok = len(target) > 0
        return ok, f"{field} 非空: 长度={len(target)}"
    return False, f"{field} 不存在或为空"


def check_each(data: dict, rule: str) -> "tuple[bool, str]":
    """每项/每条/每个 field op value"""
    rule_lower = rule.lower().strip()
    m = re.match(
        r"(?:items\s*中\s*)?每(?:条|项|个)\s*(\w+)\s*(>=|<=|!=|>|<|=|==|not\s*in)\s*(.+)",
        rule_lower
    )
    if not m:
        return False, f"无法解析: {rule}"

    field, op, val_str = m.group(1), m.group(2).replace(" ", ""), m.group(3).strip()
    items = data.get("data", {}).get("items", data.get("items", data.get("data", [])))
    if not isinstance(items, list):
        return False, f"items 不是数组 (实际: {type(items).__name__})"
    if len(items) == 0:
        return False, "items 为空"

    if op == "notin":
        vals = [v.strip().strip("'\"") for v in val_str.strip("()").split(",")]
        failures = []
        for idx, item in enumerate(items):
            item_val = str(item.get(field, ""))
            if item_val in vals:
                failures.append(f"[{idx}] {field}={item_val}")
        if failures:
            return False, f"{len(failures)}/{len(items)} 项 {field} 在禁止值中: {failures[:3]}"
        return True, f"全部 {len(items)} 项 {field} NOT IN ({', '.join(vals)})"

    # 数值或字符串比较
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
            sv, ev = str(item_val), str(expected_val)
            if op in ("=", "==") and sv != ev: failures.append(f"[{idx}] {field}={sv}")
            elif op == "!=" and sv == ev: failures.append(f"[{idx}] {field}={sv}")

    if failures:
        return False, f"{len(failures)}/{len(items)} 项不满足 {field} {op} {val_str}: {failures[:3]}"
    return True, f"全部 {len(items)} 项 {field} {op} {val_str}"


def check_one(data: dict, rule: str) -> "tuple[bool, str]":
    """根据规则类型分发"""
    r = rule.strip()
    # 组合规则 AND 分解
    if " AND " in r.upper() or " and " in r:
        sub_results = []
        for sub in re.split(r"\s+AND\s+|\s+and\s+", r, flags=re.IGNORECASE):
            sub = sub.strip()
            if sub:
                sub_results.append(check_one(data, sub))
        all_ok = all(sr[0] for sr in sub_results)
        detail = " AND ".join(sr[1] for sr in sub_results)
        return all_ok, detail

    # 按模式匹配分发
    if re.match(r"^status\s*(>=|<=|>|<|!=|==|=)\s*\d+", r.lower()):
        return check_status(data, r)
    if re.match(r"^(success|error\.\w+)\s*(>=|<=|>|<|!=|==|=)", r, re.IGNORECASE):
        return check_response_field(data, r)
    if re.match(r"^data\s*(>=|<=|>|<|==|=)\s*\d+", r.lower()):
        return check_data_op(data, r)
    if re.search(r"非空|不为空", r):
        return check_nonempty(data, r)
    if re.search(r"每(?:条|项|个)", r):
        return check_each(data, r)

    return False, f"⚠️ 规则无法解析: {r[:80]}"


def main():
    parser = argparse.ArgumentParser(
        description="确定性断言校验 — stdin 接 curl JSON 输出，--rule 定义校验规则"
    )
    parser.add_argument("--rule", action="append", default=[],
                        help="校验规则（可重复）。支持: data>N, items非空, 每项 field=value, 每项 field NOT IN(...)")
    parser.add_argument("--quiet", action="store_true",
                        help="静默模式，输出干净 JSON（不包含空 API 响应时的警告）")
    parser.add_argument("--infile", type=str,
                        help="从文件读 JSON（不通过管道时使用）")
    args = parser.parse_args()

    if not args.rule:
        print(json.dumps({"all_pass": False, "error": "至少需要一条 --rule"}, ensure_ascii=False))
        sys.exit(2)

    # 读取输入
    if args.infile:
        with open(args.infile) as f:
            raw = f.read()
    else:
        raw = sys.stdin.read()

    if not raw.strip():
        print(json.dumps({"all_pass": False, "error": "stdin 为空，curl 可能失败或未返回数据"},
                         ensure_ascii=False))
        sys.exit(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({
            "all_pass": False,
            "error": "stdin 不是有效 JSON（curl 可能返回了非 JSON 响应）"
        }, ensure_ascii=False))
        sys.exit(1)

    # 逐条规则校验
    results = []
    for rule in args.rule:
        passed, detail = check_one(data, rule)
        results.append({
            "rule": rule,
            "pass": passed,
            "detail": detail
        })

    all_pass = all(r["pass"] for r in results)

    output = {
        "all_pass": all_pass,
        "passed": sum(1 for r in results if r["pass"]),
        "failed": sum(1 for r in results if not r["pass"]),
        "total": len(results),
        "rules": results
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
