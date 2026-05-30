#!/usr/bin/env node
/**
 * 构建前环境校验 - 防止生产构建使用开发环境配置
 * 在 package.json 中通过 "prebuild" 钩子自动触发
 */
const fs = require('fs');
const path = require('path');

const RED = '\x1b[31m';
const GREEN = '\x1b[32m';
const RESET = '\x1b[0m';

// 检查 .env.local 是否包含会覆盖生产配置的危险变量
const envLocalPath = path.resolve(__dirname, '../.env.local');
const DANGEROUS_VARS = ['NEXT_PUBLIC_API_BASE_URL', 'NEXT_PUBLIC_AI_API_BASE_URL'];

if (fs.existsSync(envLocalPath)) {
  const content = fs.readFileSync(envLocalPath, 'utf-8');
  const lines = content.split('\n');

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('#') || !trimmed) continue;

    for (const dangerousVar of DANGEROUS_VARS) {
      if (trimmed.startsWith(`${dangerousVar}=`)) {
        const value = trimmed.split('=').slice(1).join('=');
        if (value.includes('localhost') || value.includes('127.0.0.1')) {
          console.error(`${RED}❌ 构建中止：.env.local 中 ${dangerousVar} 指向本地地址${RESET}`);
          console.error(`${RED}   当前值: ${value}${RESET}`);
          console.error(`${RED}   这会导致生产构建使用错误的 API 地址！${RESET}`);
          console.error(`${RED}   请注释掉 .env.local 中的该变量，使用 .env.development 替代${RESET}`);
          process.exit(1);
        }
      }
    }
  }
}

console.log(`${GREEN}✅ 环境校验通过：无危险的本地地址覆盖${RESET}`);
