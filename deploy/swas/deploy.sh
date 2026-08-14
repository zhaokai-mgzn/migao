#!/bin/bash
# migao 部署脚本: 在 SWAS 上从源码构建并重启 3 个应用 (CI 通过云助手触发)
set -e
cd /opt/migao-deploy

echo "== 1. 获取最新源码 (codeload) =="
curl -fsSL -o src.tar.gz https://codeload.github.com/zhaokai-mgzn/migao/tar.gz/refs/heads/main
rm -rf src && mkdir -p src && tar xzf src.tar.gz -C src --strip-components=1

echo "== 2. 应用 RESP2 补丁 (Tair 公网代理不支持 RESP3) =="
D=src/backend/admin-api/src/main/java/com/migao/admin/config
if [ ! -f "$D/RedisProtocolConfig.java" ]; then
  cat > "$D/RedisProtocolConfig.java" <<'JAVA'
package com.migao.admin.config;

import io.lettuce.core.ClientOptions;
import io.lettuce.core.protocol.ProtocolVersion;
import org.springframework.boot.autoconfigure.data.redis.LettuceClientConfigurationBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Force Lettuce to RESP2. Alibaba Cloud Tair's public-network proxy does not
 * accept the RESP3 HELLO handshake before AUTH; RESP2 sends plain AUTH first.
 */
@Configuration
public class RedisProtocolConfig {

    @Bean
    public LettuceClientConfigurationBuilderCustomizer lettuceClientConfigurationCustomizer() {
        return builder -> builder.clientOptions(
            ClientOptions.builder().protocolVersion(ProtocolVersion.RESP2).build());
    }
}
JAVA
  echo "RESP2 补丁已应用"
else
  echo "RESP2 补丁已存在"
fi

echo "== 3. 构建并启动 =="
docker compose up -d --build 2>&1 | tail -15

echo "== 4. 健康检查 =="
for spec in "8080 admin-api /actuator/health" "8000 ai-agent /health" "3001 admin-web /"; do
  set -- $spec
  PORT=$1; NAME=$2; PATHV=$3
  for i in 1 2 3 4 5 6 7 8 9 10; do
    CODE=$(curl -s -o /tmp/hc_$NAME.txt -w "%{http_code}" -m 10 "http://127.0.0.1:$PORT$PATHV" || echo 000)
    if [ "$CODE" = "200" ] || [ "$CODE" = "301" ] || [ "$CODE" = "302" ]; then echo "  $NAME OK ($CODE)"; break; fi
    echo "  $NAME -> $CODE (retry $i)"
    sleep 10
  done
done
echo "== deploy.sh 完成 =="
