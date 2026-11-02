package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.migao.admin.entity.BriefingAction;
import com.migao.admin.mapper.BriefingActionMapper;
import com.migao.admin.time.BusinessClock;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDate;
import java.util.List;
import java.util.Set;

/**
 * 决策采纳记录（issue #8260）。
 *
 * <p>设计判据见 {@code briefing_actions} 迁移注释与 {@link BriefingAction} 类注释。这里只说明三处刻意取舍：</p>
 *
 * <ol>
 *   <li><b>幂等靠「先查后写」而不是数据库异常重试</b>：{@code UNIQUE} 约束是兜底，
 *       常规路径走 {@code selectOne → insert / updateById}。这样在 PG 事务里不会因为一次
 *       唯一键冲突把整个事务打成 aborted（PG 的 25P02 状态会让后续语句全部失败）。</li>
 *   <li><b>非法动作静默忽略而不是抛错</b>：上报是 fire-and-forget 的内部信号，
 *       它失败不该让用户的点击失败（用户点的是「问黄金策」，不是「记一条日志」）。</li>
 *   <li><b>只记 hash</b>：见 {@link #itemKey(String)}。</li>
 * </ol>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class BriefingActionService {

    /** 看历史 / 看记录的天数硬上限（与 {@code getBriefingHistory} 同口径：一次大数不许把全表读进内存） */
    public static final int MAX_DAYS = 90;

    /**
     * 动作白名单。**目前只有一种**：{@code opened_agent} =「点开问了」。
     *
     * <p>{@code done} / {@code ignored} 不在本单（需要 UI 上的「已处理 / 忽略」按钮，
     * 那是产品决策，见 issue #8260「不在本单」）。白名单之外一律忽略 —— 不猜、不落库。</p>
     */
    public static final Set<String> ACTIONS = Set.of("opened_agent");

    /** 简报 content 里三个数组的名字，不另造一套词汇 */
    public static final Set<String> ITEM_KINDS = Set.of("todo", "risk", "suggestion");

    private final BriefingActionMapper briefingActionMapper;

    private final BusinessClock businessClock = new BusinessClock();

    /**
     * 条目标题 ⇒ 稳定 key（sha256 前 16 位十六进制）。
     *
     * <p>为什么不直接用标题：标题是 LLM 组织的中文短句，进库就等于把简报原文抄了一份
     * （内容冗余 + PII 面扩大）。为什么不直接用下标：简报每次重排都会变，会把「同一条」记成两条。</p>
     */
    public static String itemKey(String title) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest((title == null ? "" : title).getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(16);
            for (int i = 0; i < 8; i++) {
                sb.append(String.format("%02x", hash[i]));
            }
            return sb.toString();
        } catch (NoSuchAlgorithmException e) {
            // SHA-256 是 JDK 强制实现，走不到这里；走到了说明运行环境坏了，宁可炸也不静默降级
            throw new IllegalStateException("SHA-256 不可用", e);
        }
    }

    public boolean isKnownAction(String action) {
        return action != null && ACTIONS.contains(action);
    }

    public boolean isKnownItemKind(String itemKind) {
        return itemKind != null && ITEM_KINDS.contains(itemKind);
    }

    /**
     * 记录一次动作（幂等）。
     *
     * @return true = 落库（新增或更新）；false = 被忽略（非法动作 / 非法条目类型 / 参数缺失）
     */
    public boolean record(Long tenantId, String bizDate, String itemKind, String title,
                          String action, String actorId) {
        if (tenantId == null || !isKnownAction(action) || !isKnownItemKind(itemKind) || bizDate == null) {
            log.debug("briefing action ignored: tenant={} kind={} action={}", tenantId, itemKind, action);
            return false;
        }
        LocalDate date;
        try {
            date = LocalDate.parse(bizDate);
        } catch (RuntimeException e) {
            log.debug("briefing action ignored: 非法日期 {}", bizDate);
            return false;
        }
        String key = itemKey(title);

        BriefingAction existing = briefingActionMapper.selectOne(
                new LambdaQueryWrapper<BriefingAction>()
                        .eq(BriefingAction::getTenantId, tenantId)
                        .eq(BriefingAction::getBizDate, date)
                        .eq(BriefingAction::getItemKind, itemKind)
                        .eq(BriefingAction::getItemKey, key));
        if (existing != null) {
            existing.setAction(action);
            existing.setActorId(actorId);
            briefingActionMapper.updateById(existing);
            return true;
        }
        briefingActionMapper.insert(BriefingAction.builder()
                .tenantId(tenantId)
                .bizDate(date)
                .itemKind(itemKind)
                .itemKey(key)
                .action(action)
                .actorId(actorId)
                .build());
        return true;
    }

    /**
     * 查最近 {@code days} 天的动作记录（倒序）。
     * 查不到 ⇒ **空列表**（不是 null）：调用方据条数自己说「还没有记录」。
     */
    public List<BriefingAction> listRecent(Long tenantId, int days) {
        int bounded = Math.max(1, Math.min(days, MAX_DAYS));
        List<BriefingAction> rows = briefingActionMapper.selectList(
                new LambdaQueryWrapper<BriefingAction>()
                        .eq(BriefingAction::getTenantId, tenantId)
                        .ge(BriefingAction::getBizDate, businessClock.today().minusDays(bounded - 1L))
                        .orderByDesc(BriefingAction::getBizDate)
                        .last("LIMIT " + (bounded * 50L)));
        return rows == null ? List.of() : rows;
    }
}
