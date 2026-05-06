const http = require('http');
const url = require('url');

const PORT = 3001;

const TARGETS = {
  '/api/': { host: '8.136.139.170', port: 80, stripPrefix: false },
  '/ai/':  { host: '118.178.172.234', port: 80, stripPrefix: true },
};

function getTarget(pathname) {
  for (const prefix in TARGETS) {
    if (pathname.startsWith(prefix)) {
      return { ...TARGETS[prefix], prefix };
    }
  }
  return null;
}

const server = http.createServer((req, res) => {
  const origin = req.headers.origin || 'http://localhost:3002';
  const corsHeaders = {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, PATCH, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-Tenant-Id, Cookie',
    'Access-Control-Allow-Credentials': 'true',
  };

  // Handle OPTIONS preflight
  if (req.method === 'OPTIONS') {
    res.writeHead(204, corsHeaders);
    res.end();
    return;
  }

  const parsed = url.parse(req.url);
  const target = getTarget(parsed.pathname);

  if (!target) {
    res.writeHead(404, { 'Content-Type': 'text/plain', ...corsHeaders });
    res.end('Not Found - no proxy target for this path');
    return;
  }

  // Strip the matched prefix from the path before forwarding (if configured)
  // e.g. /ai/api/chat/send -> /api/chat/send
  const strippedPath = target.stripPrefix
    ? req.url.replace(new RegExp(`^${target.prefix.replace(/\/$/, '')}`), '')
    : req.url;
  // Ensure path starts with /
  const forwardPath = strippedPath.startsWith('/') ? strippedPath : '/' + strippedPath;

  // Build proxy request options
  const options = {
    hostname: target.host,
    port: target.port,
    path: forwardPath,
    method: req.method,
    headers: { ...req.headers },
  };

  // Fix host header to target
  options.headers.host = target.host;
  // Remove origin to avoid target server CORS check
  delete options.headers.origin;
  delete options.headers.referer;

  const proxyReq = http.request(options, (proxyRes) => {
    // Merge CORS headers with upstream response headers
    const responseHeaders = { ...proxyRes.headers, ...corsHeaders };
    res.writeHead(proxyRes.statusCode, responseHeaders);
    proxyRes.pipe(res, { end: true });
  });

  proxyReq.on('error', (err) => {
    console.error(`Proxy error: ${err.message}`);
    res.writeHead(502, { 'Content-Type': 'text/plain', ...corsHeaders });
    res.end(`Proxy Error: ${err.message}`);
  });

  // Pipe request body for POST/PUT/PATCH
  req.pipe(proxyReq, { end: true });
});

server.listen(PORT, () => {
  console.log(`Reverse proxy running on http://localhost:${PORT}`);
  console.log(`  /api/* -> http://8.136.139.170`);
  console.log(`  /ai/*  -> http://118.178.172.234`);
});
