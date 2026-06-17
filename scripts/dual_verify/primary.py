#!/usr/bin/env python3
"""
主验收脚本（#450b / #454）

读 issue 验收契约段 → 跑对应 spec + L2/L3 业务断言
输出：/opt/qa-results/{issue_id}/primary.json

独立证据：跑 Playwright E2E + JUnit + pytest
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", "/opt/youke")).resolve()
QA_RESULT_ROOT = Path(os.getenv("QA_RESULT_ROOT", "/opt/qa-results"))
ISSUE_BODY_CACHE = {}


def load_issue(issue_id: int) -> dict:
    if issue_id in ISSUE_BODY_CACHE:
        return ISSUE_BODY_CACHE[issue_id]
    p = subprocess.Popen(
        ["gh", "issue", "view", str(issue_id), "--json", "title,body,labels,comments"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT)
    )
    out, err = p.communicate()
    if p.returncode != 0:
        raise RuntimeError(f"拉 issue #{issue_id} 失败: {err.decode('utf-8', 'ignore')}")
    data = json.loads(out.decode("utf-8"))
    ISSUE_BODY_CACHE[issue_id] = data
    return data


def extract_specs(issue_body: str):
    """从 issue body 提取 spec 路径"""
    specs = []
    # 匹配 - tests/...  或 - tests/...
    for match in re.finditer(r"^\s*-\s*[`']?(tests/[^\s`']+\.spec\.ts)[`']?", issue_body, re.MULTILINE):
        specs.append(match.group(1).strip())
    # 匹配 pytest markers
    for match in re.finditer(r"^\s*-\s*[`']?(tests/test_[^\s`']+\.py)[`']?", issue_body, re.MULTILINE):
        specs.append(match.group(1).strip())
    # 匹配 Java spec
    for match in re.finditer(r"^\s*-\s*[`']?(src/test/java/[^\s`']+Test\.java)[`']?", issue_body, re.MULTILINE):
        specs.append(match.group(1).strip())
    return list(set(specs))


def is_deployment_issue(issue_body: str) -> bool:
    """检测是否是部署/基础设施类 issue（需云验收，不需本地 spec）

    精确匹配：
    - 标题含 [deploy]/[infra] tag
    - body 含多个部署强信号（SAE+CrashLoop、terraform、迁移文件）
    """
    body_lower = issue_body.lower()
    # 标题 tag 强信号
    if "[deploy]" in body_lower or "[infra]" in body_lower:
        return True
    # 强信号组合（≥2 才算）
    strong_signals = ["sae", "crashloop", "启动崩溃", "terraform", "flyway"]
    hits = sum(1 for kw in strong_signals if kw in body_lower)
    if hits >= 2:
        return True
    # 标题有"部署 / CrashLoop / Flyway"
    title_keywords = ["部署崩溃", "部署失败", "sae crashloop", "flyway"]
    if any(kw in body_lower for kw in title_keywords):
        return True
    return False


def run_e2e_spec(spec_path: str) -> dict:
    """跑 Playwright spec"""
    full = PROJECT_ROOT / spec_path
    if not full.exists():
        return {"spec": spec_path, "status": "skip", "reason": "spec 文件不存在"}
    try:
        p = subprocess.Popen(
            ["npx", "playwright", "test", spec_path, "--reporter=json", "--project=web"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(PROJECT_ROOT / "tests"),
            env={**os.environ, "CI": "true"}
        )
        out, err = p.communicate(timeout=300)
        out_text = out.decode("utf-8", "ignore")
        # 解析 JSON 报告
        try:
            report = json.loads(out_text)
            stats = report.get("stats", {})
            return {
                "spec": spec_path,
                "status": "pass" if p.returncode == 0 else "fail",
                "passed": stats.get("expected", 0),
                "failed": stats.get("unexpected", 0),
                "skipped": stats.get("skipped", 0),
                "duration_ms": stats.get("duration", 0)
            }
        except json.JSONDecodeError:
            return {
                "spec": spec_path,
                "status": "pass" if p.returncode == 0 else "fail",
                "raw_output": out_text[-500:],
                "stderr": err.decode("utf-8", "ignore")[-500:]
            }
    except subprocess.TimeoutExpired:
        p.kill()
        return {"spec": spec_path, "status": "fail", "reason": "timeout 300s"}


def run_python_test(test_path: str) -> dict:
    """跑 pytest"""
    full = PROJECT_ROOT / "backend/ai-agent-service" / test_path
    if not full.exists():
        return {"test": test_path, "status": "skip", "reason": "文件不存在"}
    p = subprocess.Popen(
        [".venv/bin/python", "-m", "pytest", test_path, "-q", "--tb=line"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(PROJECT_ROOT / "backend/ai-agent-service"),
    )
    out, err = p.communicate(timeout=300)
    out_text = out.decode("utf-8", "ignore")
    # 解析 "5 passed" / "2 failed"
    m_pass = re.search(r"(\d+) passed", out_text)
    m_fail = re.search(r"(\d+) failed", out_text)
    return {
        "test": test_path,
        "status": "pass" if p.returncode == 0 else "fail",
        "passed": int(m_pass.group(1)) if m_pass else 0,
        "failed": int(m_fail.group(1)) if m_fail else 0,
        "summary": out_text.split("\n")[-3] if out_text else ""
    }


def run_java_test(test_class: str) -> dict:
    """跑 JUnit test"""
    p = subprocess.Popen(
        ["./mvnw", "test", "-q", f"-Dtest={test_class}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(PROJECT_ROOT / "backend/admin-api"),
    )
    out, err = p.communicate(timeout=600)
    out_text = out.decode("utf-8", "ignore")
    return {
        "test": test_class,
        "status": "pass" if p.returncode == 0 else "fail",
        "output_tail": out_text[-500:]
    }


def classify(spec_path: str) -> str:
    if spec_path.endswith(".spec.ts"):
        return "e2e"
    if spec_path.endswith(".py"):
        return "python"
    if spec_path.endswith("Test.java"):
        return "java"
    return "unknown"


def verify(issue_id: int) -> dict:
    """主验收入口"""
    issue = load_issue(issue_id)
    body = issue.get("body", "")
    title = issue.get("title", "")
    comments = issue.get("comments", [])
    # 部署类 issue 不需本地 spec，等云验收
    if is_deployment_issue(body):
        return {
            "issue_id": issue_id,
            "title": title,
            "verifier": "primary",
            "status": "skip_deployment",
            "reason": "部署/基础设施类 issue — 等云验收（cloud）",
            "specs": [],
            "confidence": 0,
            "hint": "需研发 AI 跑云验收（API + DB + 部署日志）"
        }
    specs = extract_specs(body)
    if not specs:
        return {
            "issue_id": issue_id,
            "title": title,
            "verifier": "primary",
            "status": "skip",
            "reason": "issue body 中未找到 spec 路径（需写 L2/L3 case）",
            "specs": [],
            "confidence": 0,
            "comments_count": len(comments)
        }

    results = []
    for spec in specs:
        kind = classify(spec)
        if kind == "e2e":
            results.append(run_e2e_spec(spec))
        elif kind == "python":
            results.append(run_python_test(spec))
        elif kind == "java":
            results.append(run_java_test(Path(spec).stem))
        else:
            results.append({"spec": spec, "status": "skip", "reason": f"未知类型 {kind}"})

    # 计算通过率
    pass_count = sum(1 for r in results if r.get("status") == "pass")
    fail_count = sum(1 for r in results if r.get("status") == "fail")
    skip_count = sum(1 for r in results if r.get("status") == "skip")
    total = len(results)

    if total == 0:
        confidence = 0
        status = "skip"
    elif fail_count > 0:
        confidence = int(100 * pass_count / total)
        status = "fail"
    else:
        confidence = 100 if skip_count == 0 else int(100 * pass_count / total)
        status = "pass"

    return {
        "issue_id": issue_id,
        "title": title,
        "verifier": "primary",
        "status": status,
        "confidence": confidence,
        "specs_total": total,
        "specs_pass": pass_count,
        "specs_fail": fail_count,
        "specs_skip": skip_count,
        "results": results,
        "timestamp": int(time.time())
    }


def main():
    parser = argparse.ArgumentParser(description="主验收")
    parser.add_argument("issue_id", type=int)
    parser.add_argument("--out", type=str, help="输出 JSON 路径")
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
