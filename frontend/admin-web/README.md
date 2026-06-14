# Admin Web

米高 AI 智能客服 — Next.js 管理后台

## 技术栈

- Next.js 14 (App Router) + TypeScript + Tailwind CSS
- Zustand（状态管理）+ Axios（HTTP 请求）
- 米宝 AI 助手（FloatingAssistant SSE 流式对话）

## 快速开始

```bash
# 1. 安装依赖
npm install

# 2. 启动（端口 3001）
npm run dev

# 3. 访问: http://localhost:3001
```

## 测试

```bash
npx vitest run                                # 全量单测
npx vitest run tests/unit/lib/utils.test.ts   # 指定文件
npx tsc --noEmit                              # 类型检查
```

## 项目结构

```
src/
├── app/(dashboard)/  # 仪表盘页面（订单/商品/客户/知识库等）
├── components/       # 共享组件（ai-assistant/ products/ chat/）
├── lib/              # API 客户端（api.ts）、工具函数
├── store/            # Zustand 状态管理
└── types/            # TypeScript 类型定义
```

## E2E 测试

项目级 E2E 测试位于 `tests/e2e/`，使用 Playwright：

```bash
cd tests && BASE_URL=http://localhost:3001 npx playwright test
```
