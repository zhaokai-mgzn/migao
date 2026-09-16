package com.migao.admin.config;

import com.migao.admin.service.DailyBriefingService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * 智能每日经营简报定时调度（issue #3468，设计文档 §2.3/§七）
 *
 * 每分钟扫描一次已开启租户：到生成时刻且当日未生成 → 触发。
 * 关闭租户由 generateDueTenants 内部跳过（熔断，LLM 调用数=0）。
 * 幂等：唯一键 (tenant_id, biz_date) + 生成前查重双保险。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class BriefingScheduler {

    private final DailyBriefingService dailyBriefingService;

    @Scheduled(cron = "0 * * * * *")
    public void generateDueBriefings() {
        try {
            int generated = dailyBriefingService.generateDueTenants();
            if (generated > 0) {
                log.info("定时简报生成完成：本分钟生成 {} 个租户", generated);
            }
        } catch (Exception e) {
            log.error("定时简报生成异常: {}", e.getMessage(), e);
        }
    }
}
