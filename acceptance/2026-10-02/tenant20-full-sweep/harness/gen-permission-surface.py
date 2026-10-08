#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 生成 out/permission-surface-main.json —— s7 全量 RBAC 矩阵的**端点面输入**。
# 坐标自证（铁律 11）：全部内容从**提交对象** `origin/main`（git show）读取，不读工作树；
# 产物首条 = {"meta": true, "commit": ..., "generated_at": ...}，s7 filter(e.perm) 自然跳过。
# 用法：python3 gen-permission-surface.py [ref]   （默认 origin/main；需 REPO_ROOT 可达）
import json
import re
import subprocess
import sys
import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
# 2026-10-03 固化（验收 §六 #1）：直写 sweep 根 out/（消费侧 s7 同源），消除双目录陷阱。
OUT_DIR = Path(__file__).resolve().parent.parent / "out"
REF = sys.argv[1] if len(sys.argv) > 1 else "origin/main"

MAPPING_RE = re.compile(r'@(Get|Post|Put|Delete|Patch|Request)Mapping(?:\((?:value\s*=\s*)?"([^"]*)"[^)]*\))?')
HTTP_OF = {"Get": "GET", "Post": "POST", "Put": "PUT", "Delete": "DELETE", "Patch": "PATCH", "Request": "REQ"}
PERM_RE = re.compile(r'@RequirePermission\(\s*"([^"]+)"')


def git(*args):
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, check=True).stdout


def main():
    commit = git("rev-parse", REF).strip()
    files = [l for l in git("ls-tree", "-r", "--name-only", REF, "--",
             "backend/admin-api/src/main/java").splitlines() if l.endswith("Controller.java")]
    out = [{"meta": True, "ref": REF, "commit": commit,
            "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}]
    for f in files:
        src = git("show", f"{REF}:{f}")
        base = ""
        base_m = re.search(r'@RequestMapping\("([^"]+)"\)', src)
        if base_m:
            base = base_m.group(1)
        pending = None  # (http, subpath)
        for line in src.splitlines():
            s = line.strip()
            m = MAPPING_RE.search(s)
            # 类级 @RequestMapping 只经上面的 base 提取处理，不得占 pending——否则会吞掉
            # 紧随的方法级 mapping，并把首个 perm 消费成 path=base+base 的垃圾行。
            if m and pending is None and m.group(1) != "Request":
                pending = [HTTP_OF[m.group(1)], m.group(2) or ""]
                continue
            if pending is not None:
                pm = PERM_RE.search(s)
                if pm:
                    sub = pending[1]
                    path = base + sub if sub.startswith("/") else (base + ("/" + sub if sub else ""))
                    out.append({"path": path, "method": pending[0], "perm": pm.group(1), "controller": f.rsplit("/", 1)[-1]})
                    pending = None
                elif s.startswith("public ") or s.startswith("private ") or s.startswith("protected "):
                    pending = None  # 方法签名到顶仍无权限码 ⇒ 无 @RequirePermission 端点，跳过（s7 filter 掉）
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUT_DIR / "permission-surface-main.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    eps = [e for e in out if not e.get("meta")]
    print(f"坐标 {REF}@{commit[:10]} | controller {len(files)} | 端点(带perm) {len(eps)} | 权限码 {len({e['perm'] for e in eps})}")
    print(f"→ {dst}")


if __name__ == "__main__":
    main()
