// GitHub 限流的**判定**只有一份实现：`.github/rate_limit_backoff.py`（issue #7549）。
// 本文件只做 github-script 侧的「循环 + 等待」，判定一律问 Python ⇒ 不存在第二份策略副本。
//
// 为什么需要它：`actions/github-script` 里的 octokit 调用**没有**内置限流退避，
// 而安装令牌打满时 403 与「真没权限」外表一致（实测 PR #8551：`listComments - 403`，
// `x-ratelimit-remaining: '0'`）。两条腿（Danger Scan / QA Growth Gate）都必须走这里。
//
// 🔴 fail-closed：桥本身出错（python3 缺失 / 脚本读不到 / JSON 坏）⇒ **原样抛出原错误**，
// 既不多试一次、也不把错误改写成「限流」—— 判不了就立刻红，绝不吞。
'use strict';

const path = require('path');
const { execFileSync } = require('child_process');

const ROOT = process.env.GITHUB_WORKSPACE || process.cwd();
const CLI = path.join(ROOT, '.github', 'rate_limit_backoff.py');

/** 把一次失败交给唯一的判定点，返回 `{outcome, delay?}`。 */
function classify(status, headers, message, attempt) {
  const args = [CLI, 'classify', '--json', JSON.stringify({
    status: status || 0,
    headers: headers || {},
    message: message || '',
  })];
  if (attempt) args.push('--attempt', String(attempt));
  return JSON.parse(execFileSync('python3', args, { encoding: 'utf8' }));
}

/**
 * 执行 `fn()`，**只对限流**做有界退避。
 * 非限流（含真没权限）⇒ 立刻抛出，一次也不多试（负控：别把真红吞掉）。
 */
async function withRateLimitRetry(label, fn, options) {
  const opts = options || {};
  const attempts = opts.attempts || 3;
  const sleep = opts.sleep || ((ms) => new Promise((r) => setTimeout(r, ms)));

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await fn();
    } catch (e) {
      const headers = (e && e.response && e.response.headers) || {};
      let verdict;
      try {
        verdict = classify(e && e.status, headers, e && e.message, attempt);
      } catch (bridgeError) {
        throw e; // 判定不了 ⇒ 不重试（fail-closed）
      }
      if (verdict.outcome !== 'rate_limited') throw e;
      if (attempt >= attempts) {
        const err = new Error(
          `${label}：限流退避用尽（已尝试 ${attempts} 次）——**未判定**，不是本 PR 的问题；重跑该腿即可。`
          + ` 读数：HTTP ${e && e.status}`
          + ` x-ratelimit-remaining=${headers['x-ratelimit-remaining'] ?? '?'}`
          + ` retry-after=${headers['retry-after'] ?? '?'}`
          + ` ${e && e.message}`,
        );
        err.rateLimited = true;
        throw err;
      }
      await sleep(Math.max(0, Number(verdict.delay || 0)) * 1000);
    }
  }
  throw new Error(`${label}：不可达分支`); // attempts < 1
}

module.exports = { withRateLimitRetry, classify };
