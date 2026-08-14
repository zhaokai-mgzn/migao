package com.migao.admin.config;

import io.lettuce.core.ClientOptions;
import io.lettuce.core.protocol.ProtocolVersion;
import org.springframework.boot.autoconfigure.data.redis.LettuceClientConfigurationBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Force Lettuce to RESP2.
 *
 * <p>Alibaba Cloud Tair's public-network proxy does not accept the RESP3 HELLO
 * handshake before AUTH; RESP2 sends plain AUTH first and works through the
 * public endpoint. The VPC (private) endpoint accepts both, so this is only
 * load-bearing once the app is reached over a public Tair connection.</p>
 */
@Configuration
public class RedisProtocolConfig {

    @Bean
    public LettuceClientConfigurationBuilderCustomizer lettuceClientConfigurationCustomizer() {
        return builder -> builder.clientOptions(
            ClientOptions.builder().protocolVersion(ProtocolVersion.RESP2).build());
    }
}
