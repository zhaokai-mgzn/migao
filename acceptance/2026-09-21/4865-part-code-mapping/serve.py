#!/usr/bin/env python3
"""本地「nginx 替身」—— 让 #4865 的验收剧本能在**同一个源**上跑完 302 → 落地。

生产上 `/s/<短码>`（admin-api）与 `/w/`（worker-h5 静态件）由同一台 nginx 同源提供，
所以 302 的 `Location` 是**相对路径** `/w/?t=<token>`。本机没有 nginx，用本脚本顶替：

  :8080  /w/**     ⇒ 直接读 `frontend/worker-h5/**`（**逐字节**，含 index.html / src/*.mjs）
        其它路径   ⇒ 反代到 admin-api（:8081），**原样透传状态码与响应头**（302/Location 必须不变）

⚠️ 刻意用 `http.client` 而不是 `urllib`：后者会**自动跟随 302** ⇒ `curl -D -` 就看不到 302 了。
"""
import http.client
import http.server
import pathlib
import sys

PORT = int(sys.argv[1])
BACKEND_PORT = int(sys.argv[2])
STATIC_ROOT = pathlib.Path(sys.argv[3]).resolve()

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 静音：证据由 run.sh 打印
        pass

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PUT(self):
        self._handle()

    def _handle(self):
        path = self.path.split("?")[0]
        if path == "/w" or path.startswith("/w/"):
            self._static(path)
        else:
            self._proxy()

    def _static(self, path):
        relative = path[len("/w/"):] if path.startswith("/w/") else ""
        target = STATIC_ROOT / relative if relative else STATIC_ROOT / "index.html"
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            self._proxy()
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _proxy(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in ("host", "content-length", "connection")}
        conn = http.client.HTTPConnection("127.0.0.1", BACKEND_PORT, timeout=120)
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            response = conn.getresponse()
            data = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() in ("content-length", "transfer-encoding", "connection"):
                    continue
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        finally:
            conn.close()


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
