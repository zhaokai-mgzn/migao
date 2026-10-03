#!/usr/bin/env python3
"""ai-agent e2e 面的**前置就绪探针**（issue #6160）—— 供 ``verify-all.sh`` 的 ``ai-agent-e2e`` 用。

判据本体**不在这里**：每个「需要本机服务 + 凭据」的测试面自己声明

    LIVE_SERVICE_PROBE = {"endpoint": "http://…/api/chat/send", "headers": {…}}   # 必须是**字面量**

判定由 ``backend/ai-agent-service/tests/live_service_readiness.py::not_ready_reason()`` 承担 ——
用例的 skipif 与本探针调**同一个函数** ⇒ 不会漂移。本脚本只做三件事：

  ① **现取**面清单：扫 ai-agent 的 tests 树（尊重该服务 ``pytest.ini`` 的 ``--ignore=``：被 ignore
     的测试面根本不收集），挑出声明了该契约的模块 —— **不钉手抄清单**；
  ② ``ast.literal_eval`` 现取端点 / 凭据（**不执行**模块代码 ⇒ 不需要 venv / httpx），真去探一次；
  ③ 三态出口：``0`` 全部就绪 / ``1`` 有面未就绪（逐面打印一行可行动说明）/ ``2`` **无法判定**
     （面清单为空 / 契约不是可解析的字面量）—— 「判不了」绝不长得像「就绪」。

🔴 本脚本**不跑**用例、也**不看**业务断言：探得通之后用例照常跑、照常判红绿
（真失败仍由 pytest 判 ❌，不许被吞成「未就绪」）。

用法：
    python3 scripts/ai-agent-e2e-readiness.py [--service-dir <ai-agent-service 目录>]
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SERVICE_DIR = ROOT / "backend" / "ai-agent-service"
CONTRACT = "LIVE_SERVICE_PROBE"
READINESS_MODULE = "tests/live_service_readiness.py"


def _load_readiness(service_dir: Path):
    """载入判定模块本体（契约模块 ⇒ 判定单一实现）。"""
    path = service_dir / READINESS_MODULE
    spec = importlib.util.spec_from_file_location("_migao_live_service_readiness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ignored_paths(service_dir: Path) -> list:
    """现取 ``pytest.ini`` 的 ``--ignore=`` 面：被 ignore 的测试面**根本不收集** ⇒ 不该被探。"""
    ini = service_dir / "pytest.ini"
    if not ini.is_file():
        return []
    ignored = []
    for line in ini.read_text(encoding="utf-8").splitlines():
        if not line.startswith("addopts"):
            continue
        for token in line.split():
            if token.startswith("--ignore="):
                ignored.append((service_dir / token.split("=", 1)[1]).resolve())
    return ignored


def _declares_contract(module: ast.Module) -> bool:
    for node in module.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if any(getattr(t, "id", None) == CONTRACT for t in targets):
            return True
    return False


def _extract_contract(source: str):
    """``(endpoint, headers)``；契约缺失 / 不是可解析字面量 ⇒ ``None``（**判不了**，不是就绪）。"""
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(getattr(t, "id", None) == CONTRACT for t in targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            return None
        if not isinstance(value, dict):
            return None
        endpoint, headers = value.get("endpoint"), value.get("headers")
        if not isinstance(endpoint, str) or not isinstance(headers, dict):
            return None
        return endpoint, {str(k): str(v) for k, v in headers.items()}
    return None


def face_modules(service_dir: Path) -> list:
    """现取：pytest 会收集的测试面里，声明了就绪契约的那些。"""
    ignored = _ignored_paths(service_dir)
    faces = []
    for path in sorted((service_dir / "tests").rglob("test_*.py")):
        resolved = path.resolve()
        if any(resolved == ig or ig in resolved.parents for ig in ignored):
            continue
        if _declares_contract(ast.parse(path.read_text(encoding="utf-8"))):
            faces.append(path)
    return faces


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ai-agent e2e 面的前置就绪探针")
    parser.add_argument("--service-dir", default=str(DEFAULT_SERVICE_DIR))
    args = parser.parse_args(argv)
    service_dir = Path(args.service_dir).resolve()

    faces = face_modules(service_dir)
    if not faces:
        print(f"无法判定：{service_dir} 下没有声明 {CONTRACT} 契约的测试面（不是「就绪」）")
        return 2
    try:
        readiness = _load_readiness(service_dir)
    except Exception as exc:  # noqa: BLE001 —— 契约模块自身坏了 ⇒「判不了」，不许当就绪
        print(f"无法判定：{service_dir}/{READINESS_MODULE} 载入失败（{type(exc).__name__}: {exc}）")
        return 2

    unready = []
    for face in faces:
        contract = _extract_contract(face.read_text(encoding="utf-8"))
        if contract is None:
            print(f"无法判定：{os.path.relpath(face, ROOT)} 的 {CONTRACT} 不是可解析的字面量")
            return 2
        reason = readiness.not_ready_reason(*contract)
        if reason:
            unready.append(f"{os.path.relpath(face, ROOT)}：{reason}")
    if unready:
        for line in unready:
            print(line)
        return 1
    print(f"就绪：{len(faces)} 个面（{'、'.join(os.path.relpath(f, ROOT) for f in faces)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
