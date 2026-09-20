package com.migao.admin.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;

/**
 * 密码编码器（BCrypt）配置 —— 从 {@link com.migao.admin.security.SecurityConfig} **抽出**的独立配置类
 * （issue #4770，P0 线上故障热修）。
 *
 * <h2>为什么要抽出来：它是启动期 Bean 环的**唯一回流边**</h2>
 * <p>本 bean 原先声明在 {@code SecurityConfig} 里。而 #4733（工人登录态）让
 * {@code SecurityConfig} 在**构造期**依赖 {@code WorkerSessionFilter}
 * → {@code WorkerSessionService} → {@code PasswordEncoder} —— 最后这条边又回到
 * {@code SecurityConfig}（{@code @Bean} 方法在配置类上）⇒ 成环：</p>
 * <pre>
 * securityConfig → workerSessionFilter → workerSessionService → securityConfig
 * （Requested bean is currently in creation: Is an unresolvable circular reference?）
 * </pre>
 * <p>⇒ admin-api **每次启动都崩**（{@code APPLICATION FAILED TO START}）⇒ nginx 502。</p>
 *
 * <h2>破环方式是结构性的（不是 {@code @Lazy} 绕过）</h2>
 * <p>把环上唯一的回流边（{@code PasswordEncoder} 这个 @Bean）挪到本类 ⇒ 依赖方向**单向化**：</p>
 * <pre>
 * SecurityConfig → WorkerSessionFilter → WorkerSessionService → PasswordEncoderConfig
 * </pre>
 * <p>语义**零变化**：仍是同一个 bean 名（{@code passwordEncoder}）与同一实现
 * （{@code BCryptPasswordEncoder}），商家账号密码 / 工人 PIN 共用同一份编码器的口径不变。</p>
 *
 * <p>🔴 <b>不要把它挪回 {@code SecurityConfig}</b> —— 环会原样复发。判据 =
 * {@code SecurityConfigTest#contextLoads_workerSessionChainIsReallyWired()}
 * （完整上下文加载 + 「SecurityConfig 不得声明 PasswordEncoder @Bean」的静态断言）。</p>
 */
@Configuration
public class PasswordEncoderConfig {

    /**
     * 配置密码编码器（BCrypt）。
     *
     * @return PasswordEncoder
     */
    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
}
