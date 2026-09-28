# admin-web Dockerfile
# Next.js 16 App Router 生产部署（运行时 node:20-alpine ⇒ @types/node 同步锁在 ^20）
FROM node:20-alpine

WORKDIR /app

# 统一时区 UTC+8（业务时间均为北京时间；alpine 需 tzdata 才能解析 Asia/Shanghai）
RUN apk add --no-cache tzdata && \
    cp /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone
ENV TZ=Asia/Shanghai

# 安装依赖
COPY package*.json ./
RUN npm ci

# 复制源码
COPY . .

# 构建时环境变量（NEXT_PUBLIC_* 在构建时 baked into JS）
ARG NEXT_PUBLIC_API_BASE_URL=https://api.migaozn.com
ARG NEXT_PUBLIC_AI_API_BASE_URL=https://ai-api.migaozn.com
ARG NEXT_PUBLIC_COOKIE_DOMAIN=.migaozn.com
# B 端 h5 手机端入口（issue #5668）：二维码的**唯一**地址来源（前端不硬编码域名）。
# 缺省即线上落位；置空 = 页面显示「移动端地址未配置」且不画码（不是画一个空码）。
ARG NEXT_PUBLIC_BMINI_H5_URL=https://app.migaozn.com/b/

ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_AI_API_BASE_URL=${NEXT_PUBLIC_AI_API_BASE_URL}
ENV NEXT_PUBLIC_COOKIE_DOMAIN=${NEXT_PUBLIC_COOKIE_DOMAIN}
ENV NEXT_PUBLIC_BMINI_H5_URL=${NEXT_PUBLIC_BMINI_H5_URL}
ENV NODE_ENV=production

# 构建（不再需要 output:export）
RUN npm run build


EXPOSE 3001

CMD ["npx", "next", "start", "-p", "3001"]
