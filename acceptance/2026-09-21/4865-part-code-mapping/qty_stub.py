#!/usr/bin/env python3
"""算料引擎端点桩（本机替身，**不重写任何算料逻辑**）。

真 ai-agent-service 需要它自己的 DB / Redis / LLM / `SERVICE_TOKEN` 配置，本机没有起它；
本桩只顶替 `POST /api/internal/production/operation-qty` 这一个**上游**端点，做法是
**直接加载本仓的算料真相源** `backend/ai-agent-service/app/production/routing.py` 的
`qty_and_source(operation, calc_info)` —— 与真端点（`app/api/internal.py` 的同名路由）逐字同源，
不是第二份算料逻辑（按文件路径 importlib 加载，避免 `app/__init__.py` 的配置副作用）。

⚠️ 本桩**不校验** `X-Service-Token`（本机一次性实例；真端点校验见 `app/utils/auth.py`）。
"""
import importlib.util
import json
import http.server
import pathlib
import sys

PORT = int(sys.argv[1])
ROOT = pathlib.Path(sys.argv[2]).resolve()

_spec = importlib.util.spec_from_file_location(
    "migao_routing_engine", ROOT / "backend/ai-agent-service/app/production/routing.py")
_routing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_routing)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        print("HEADERS " + repr(dict(self.headers)), flush=True)
        if (self.headers.get("Transfer-Encoding") or "").lower() == "chunked":
            chunks = []
            while True:
                size_line = self.rfile.readline().strip()
                size = int(size_line.split(b";")[0] or b"0", 16)
                if size == 0:
                    self.rfile.readline()
                    break
                chunks.append(self.rfile.read(size))
                self.rfile.readline()
            raw = b"".join(chunks)
        else:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
        print("REQ " + raw.decode("utf-8", "replace")[:2000], flush=True)
        payload = json.loads(raw or b"{}")
        positions = []
        for position in payload.get("positions", []):
            calc_info = position.get("calc_info") or {}
            qty_by_operation, source_by_operation = {}, {}
            for operation in position.get("operations", []):
                qty, source = _routing.qty_and_source(operation, calc_info)
                qty_by_operation[operation] = qty
                source_by_operation[operation] = source
            positions.append({
                "position_name": position.get("position_name"),
                "qty_by_operation": qty_by_operation,
                "qty_source_by_operation": source_by_operation,
            })
        body = json.dumps({"success": True, "data": {"positions": positions}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
