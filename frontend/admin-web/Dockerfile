# admin-web Dockerfile
# Next.js 14 App Router 生产部署
FROM node:20-alpine

WORKDIR /app

# 安装依赖
COPY package*.json ./
RUN npm ci

# 复制源码
COPY . .

# 构建时环境变量（NEXT_PUBLIC_* 在构建时 baked into JS）
ARG NEXT_PUBLIC_API_BASE_URL=https://api.migaozn.com
ARG NEXT_PUBLIC_AI_API_BASE_URL=https://ai-api.migaozn.com
ARG NEXT_PUBLIC_COOKIE_DOMAIN=.migaozn.com

ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_AI_API_BASE_URL=${NEXT_PUBLIC_AI_API_BASE_URL}
ENV NEXT_PUBLIC_COOKIE_DOMAIN=${NEXT_PUBLIC_COOKIE_DOMAIN}
ENV NODE_ENV=production

# 构建（不再需要 output:export）
RUN npm run build

EXPOSE 3001

CMD ["npm", "start"]
