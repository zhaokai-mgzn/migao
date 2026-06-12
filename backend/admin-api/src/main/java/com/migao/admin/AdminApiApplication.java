package com.migao.admin;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * AI 智能客服系统 - 管理后台 API 服务
 * 
 * @author AI Assistant
 * @since 2026-04-12
 */
@SpringBootApplication
@MapperScan("com.migao.admin.mapper")
public class AdminApiApplication {

    public static void main(String[] args) {
        SpringApplication.run(AdminApiApplication.class, args);
    }
}
