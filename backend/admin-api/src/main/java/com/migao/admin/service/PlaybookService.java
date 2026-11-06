package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.PageResponse;
import com.migao.admin.entity.Playbook;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.PlaybookMapper;
import com.migao.admin.security.SecurityUser;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 口径卡服务（issue #8175 一期：落卡 → 审核 → 退役）。
 *
 * <p><b>三条硬口径</b>：</p>
 * <ol>
 *   <li><b>落卡只能落成 {@code draft}</b>：写面<b>没有</b>「直接建成 active」的入口 —— 审核这一环
 *       不许被 API 参数绕过（本单的立论就是「必须有人审核」）；</li>
 *   <li><b>迁移是 CAS</b>（见 {@link PlaybookMapper}）：影响行数 0 ⇒ 409 冲突，不静默成功；</li>
 *   <li><b>每次迁移都留审计</b>（谁 / 什么时候 / 从哪个状态到哪个状态）：退役是有后果的动作
 *       （立即从全企业的 prompt 里消失），没有留痕就无法回答「这条口径是谁撤的」。</li>
 * </ol>
 *
 * <p><b>条件不可执行 ⇒ 写面 422</b>（{@link PlaybookConditionValidator}）。这是「自由文本口径不许入库」
 * 的唯一关口；读面另有一次 fail-closed（Python 侧），两层都在，才谈得上判据 2 与判据 6。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PlaybookService {

    public static final String STATE_DRAFT = "draft";
    public static final String STATE_ACTIVE = "active";
    public static final String STATE_RETIRED = "retired";
    public static final List<String> STATES = List.of(STATE_DRAFT, STATE_ACTIVE, STATE_RETIRED);
    public static final List<String> SCOPES = List.of("tenant", "role");

    private static final String RESOURCE_TYPE = "playbook";

    private final PlaybookMapper playbookMapper;
    private final AuditLogService auditLogService;

    /** 审核队列 / 已生效 / 已退役的分页（`state` 缺省 draft）。 */
    public PageResponse<Playbook> page(String state, long page, long size) {
        Long tenantId = requireTenant();
        String effective = StringUtils.hasText(state) ? state : STATE_DRAFT;
        if (!STATES.contains(effective)) {
            throw BusinessException.validationError("未知状态：" + effective + "（合法值：" + STATES + "）");
        }
        LambdaQueryWrapper<Playbook> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Playbook::getTenantId, tenantId)
                .eq(Playbook::getState, effective)
                .orderByDesc(Playbook::getCreatedAt);
        return PageResponse.of(playbookMapper.selectPage(new Page<>(page, size), wrapper));
    }

    /**
     * 落卡：**只落 draft**（审核这一环不可绕过）。
     *
     * @return 新建的 draft 卡
     */
    public Playbook createDraft(Playbook draft) {
        Long tenantId = requireTenant();
        if (draft == null) {
            throw BusinessException.validationError("请求体不能为空");
        }
        if (!StringUtils.hasText(draft.getCorrectText())) {
            throw BusinessException.validationError("口径的正解（correct）不能为空");
        }
        String scope = StringUtils.hasText(draft.getScope()) ? draft.getScope() : "tenant";
        if (!SCOPES.contains(scope)) {
            throw BusinessException.validationError("未知适用范围：" + scope + "（合法值：" + SCOPES + "）");
        }
        if ("role".equals(scope) && !StringUtils.hasText(draft.getScopeRole())) {
            // 不指名岗位的「按岗位生效」= 静默变成「全企业生效」，是最危险的那种降级
            throw BusinessException.validationError("适用范围为岗位（role）时必须指名岗位（scopeRole）");
        }

        List<String> triggerProblems = PlaybookConditionValidator.validateJson(draft.getTriggerJson());
        if (!triggerProblems.isEmpty()) {
            throw BusinessException.validationError("触发条件不可执行：" + String.join("；", triggerProblems));
        }
        if (StringUtils.hasText(draft.getCounterJson())) {
            List<String> counterProblems = PlaybookConditionValidator.validateJson(draft.getCounterJson());
            if (!counterProblems.isEmpty()) {
                // 反例不可判 = 注释。写面就拒，而不是留一张「看起来有反例」的卡
                throw BusinessException.validationError("反例不可执行：" + String.join("；", counterProblems));
            }
        }

        OffsetDateTime now = OffsetDateTime.now();
        Playbook toInsert = Playbook.builder()
                .tenantId(tenantId)
                .scope(scope)
                .scopeRole("role".equals(scope) ? draft.getScopeRole() : null)
                .triggerJson(draft.getTriggerJson())
                .correctText(draft.getCorrectText())
                .counterJson(StringUtils.hasText(draft.getCounterJson()) ? draft.getCounterJson() : null)
                .sourceSessionId(draft.getSourceSessionId())
                .sourceTurn(draft.getSourceTurn())
                .hits(0)
                // 写面**没有**别的状态可写：审核不在这个入口
                .state(STATE_DRAFT)
                .createdAt(now)
                .updatedAt(now)
                .build();
        playbookMapper.insert(toInsert);
        recordAudit("create", toInsert, Map.of("state", STATE_DRAFT, "scope", scope));
        log.info("口径卡落为 draft: id={} tenant={} scope={}", toInsert.getId(), tenantId, scope);
        return toInsert;
    }

    /**
     * 审核通过：{@code draft → active}。
     *
     * <p>同冲突组已有生效卡时**默认拒绝**（不传 supersedes）—— 冲突消解的第一道闸。</p>
     */
    public Playbook activate(String id) {
        return activate(id, null);
    }

    /**
     * 审核通过 + 显式替换（issue #8175 P2 冲突消解，写面 fail-closed）。
     *
     * <p><b>为什么默认拒绝而不是「后审覆盖先审」</b>：同一口径（同 scope + 同触发条件）的两条卡
     * 都被批 active ⇒ prompt 里出现**互相矛盾的两条**，模型只能掷硬币。覆盖则更糟：被覆盖的那条
     * **无痕消失**，没人知道企业口径被谁在什么时候改掉了。</p>
     *
     * <p><b>两条路径</b>：</p>
     * <ol>
     *   <li>不带 {@code supersedes}：同组已有 active ⇒ 409，文案给出「先退役 #xxx」与
     *       「用 supersedes 指定替换」两个可直接照做的出口；</li>
     *   <li>带 {@code supersedes}：同一事务里「先退役旧的 + 再激活新的」；旧的必须真的在
     *       **同一冲突组**（否则那不是替换，是同时留下两条矛盾口径），且 CAS 必须命中。</li>
     * </ol>
     *
     * <p><b>冲突组怎么判</b>：{@code conflict_key} 相等（落库面打的标记）**或** 同 scope + 同
     * 触发条件（JSON 树相等，键顺序无关）。第二个条件是对脏数据的兜底：{@code conflict_key}
     * 可能为 NULL（P1 之前的历史行 / 手工建的卡），只信标记会漏掉真正同组的两条。</p>
     *
     * <p><b>fail-closed</b>：库内触发条件无法解析时视为「可能同组」⇒ 拒绝激活。
     * 宁可让人工先修数据，也不许在「不知道是不是矛盾」的情况下把两条都放进去。</p>
     *
     * @param id         待审核的 draft 卡
     * @param supersedes 要替换掉的同组 active 卡（可选）
     * @throws BusinessException 409 = 不存在 / 跨租户 / 状态已变化 / 同组冲突 / supersedes 不成立
     */
    @Transactional(rollbackFor = Exception.class)
    public Playbook activate(String id, String supersedes) {
        Long tenantId = requireTenant();
        Playbook target = playbookMapper.selectOne(new LambdaQueryWrapper<Playbook>()
                .eq(Playbook::getTenantId, tenantId)
                .eq(Playbook::getId, id));
        if (target == null) {
            throw BusinessException.conflict(
                    "审核失败：口径卡不存在、不属于本租户，或状态已变化",
                    "刷新列表后重试；只有 draft 能审核");
        }
        if (!STATE_DRAFT.equals(target.getState())) {
            throw BusinessException.conflict(
                    "审核失败：只有 draft 能审核（当前状态 " + target.getState() + "）",
                    "只有 draft 能审核、只有 active 能退役；已生效的口径先退役再替换");
        }

        Playbook sibling = findActiveSibling(target, playbookMapper.selectActiveByTenant(tenantId));
        String reviewer = resolveActorId();
        OffsetDateTime now = OffsetDateTime.now();

        if (StringUtils.hasText(supersedes)) {
            if (sibling == null || !sibling.getId().equals(supersedes)) {
                throw BusinessException.conflict(
                        "替换失败：supersedes 指定的口径卡不在本卡的同一冲突组（" + supersedes + "）",
                        "同一冲突组当前生效卡 = " + (sibling == null ? "无" : sibling.getId())
                                + "；不在同一组就不是「替换」，是同时留下两条互相矛盾的口径");
            }
            if (playbookMapper.retireIfActive(supersedes, tenantId, reviewer, now) == 0) {
                throw BusinessException.conflict(
                        "替换失败：旧口径卡状态已变化（不是 active 或不属于本租户）",
                        "刷新列表后重试；替换是同一事务里的「先退役旧的、再激活新的」");
            }
            Playbook retiredOld = playbookMapper.selectOne(new LambdaQueryWrapper<Playbook>()
                    .eq(Playbook::getTenantId, tenantId)
                    .eq(Playbook::getId, supersedes));
            recordAudit("retire", retiredOld != null ? retiredOld
                            : Playbook.builder().id(supersedes).tenantId(tenantId).state(STATE_RETIRED).build(),
                    Map.of("reason", "superseded", "replaced_by", id));
        } else if (sibling != null) {
            throw BusinessException.conflict(
                    "同一口径已有生效卡 " + sibling.getId()
                            + " ⇒ 拒绝激活第二条（否则 prompt 里会出现互相矛盾的两条）",
                    "先退役 " + sibling.getId() + "，或用 supersedes 指定替换："
                            + "POST /api/admin/playbooks/" + id + "/activate?supersedes=" + sibling.getId());
        }

        int affected = playbookMapper.activateIfDraft(id, tenantId, reviewer, now);
        if (affected == 0) {
            throw BusinessException.conflict(
                    "审核失败：口径卡不存在、不属于本租户，或状态已变化",
                    "刷新列表后重试；只有 draft 能审核、只有 active 能退役");
        }
        Playbook current = playbookMapper.selectOne(new LambdaQueryWrapper<Playbook>()
                .eq(Playbook::getTenantId, tenantId)
                .eq(Playbook::getId, id));
        if (current == null) {
            Playbook fallback = Playbook.builder().id(id).tenantId(tenantId).state(STATE_ACTIVE).build();
            recordAudit("activate", fallback, Map.of("affected", 1));
            return fallback;
        }
        recordAudit("activate", current, Map.of("state", current.getState()));
        log.info("口径卡审核通过: id={} tenant={} supersedes={} by={}", id, tenantId, supersedes, reviewer);
        return current;
    }

    /**
     * 同一冲突组的另一条 active（没有 ⇒ null）。
     *
     * <p>先比 {@code conflict_key}（落库面的标记），再比 scope + 触发条件（JSON 树相等）。
     * 前者便宜、后者能盖住「标记缺失 / 过期」的脏数据。</p>
     */
    private Playbook findActiveSibling(Playbook target, List<Playbook> actives) {
        if (actives == null || actives.isEmpty()) {
            return null;
        }
        String conflictKey = target.getConflictKey();
        for (Playbook other : actives) {
            if (other == null || other.getId() == null || other.getId().equals(target.getId())) {
                continue;
            }
            if (StringUtils.hasText(conflictKey)
                    && StringUtils.hasText(other.getConflictKey())
                    && conflictKey.equals(other.getConflictKey())) {
                return other;
            }
            if (!Objects.equals(other.getScope(), target.getScope())
                    || !Objects.equals(other.getScopeRole(), target.getScopeRole())) {
                continue;
            }
            if (sameTrigger(other.getTriggerJson(), target.getTriggerJson())) {
                return other;
            }
        }
        return null;
    }

    /** 触发条件语义相等（JSON 树相等：键顺序 / 空白不影响）。解析不了 ⇒ 视为同组（fail-closed）。 */
    private static boolean sameTrigger(String left, String right) {
        if (!StringUtils.hasText(left) || !StringUtils.hasText(right)) {
            return false;
        }
        try {
            return JSON.readTree(left).equals(JSON.readTree(right));
        } catch (Exception e) {
            log.warn("口径卡触发条件无法解析，按「可能同组」处理（fail-closed）: left={} right={}",
                    left, right, e);
            return true;
        }
    }

    private static final ObjectMapper JSON = new ObjectMapper();

    /**
     * 退役：{@code active → retired}。生效**立即**（读面不缓存，见
     * {@code backend/ai-agent-service/app/playbook/store.py} 的模块 docstring）。
     */
    public Playbook retire(String id) {
        return transition(id, false);
    }

    private Playbook transition(String id, boolean activate) {
        Long tenantId = requireTenant();
        String reviewer = resolveActorId();
        OffsetDateTime now = OffsetDateTime.now();
        int affected = activate
                ? playbookMapper.activateIfDraft(id, tenantId, reviewer, now)
                : playbookMapper.retireIfActive(id, tenantId, reviewer, now);
        if (affected == 0) {
            throw BusinessException.conflict(
                    (activate ? "审核" : "退役") + "失败：口径卡不存在、不属于本租户，或状态已变化",
                    "刷新列表后重试；只有 draft 能审核、只有 active 能退役");
        }
        Playbook current = playbookMapper.selectOne(new LambdaQueryWrapper<Playbook>()
                .eq(Playbook::getTenantId, tenantId)
                .eq(Playbook::getId, id));
        if (current == null) {
            // CAS 成功却读不到：只在「刚被删」这种竞态里出现 ⇒ 审计仍要留，返回值按最小信息构造
            Playbook fallback = Playbook.builder().id(id).tenantId(tenantId).state(
                    activate ? STATE_ACTIVE : STATE_RETIRED).build();
            recordAudit(activate ? "activate" : "retire", fallback, Map.of("affected", 1));
            return fallback;
        }
        recordAudit(activate ? "activate" : "retire", current, Map.of("state", current.getState()));
        log.info("口径卡状态迁移: id={} tenant={} to={} by={}", id, tenantId, current.getState(), reviewer);
        return current;
    }

    private void recordAudit(String action, Playbook playbook, Map<String, Object> details) {
        Long tenantId = requireTenant();
        auditLogService.recordLog(
                tenantId,
                resolveActorId(),
                resolveActorName(),
                action,
                RESOURCE_TYPE,
                null,
                playbook.getId(),
                playbook.getCorrectText(),
                details,
                null,
                null);
    }

    private Long requireTenant() {
        Long tenantId = TenantContext.getTenantId();
        if (tenantId == null) {
            throw BusinessException.tenantInvalid();
        }
        return tenantId;
    }

    /** 「谁干的」= SecurityUser（与 TenantParamAuditService / PieceworkSettlementService 同口径）。 */
    private static String resolveActorId() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof SecurityUser user) {
            return user.getUserId();
        }
        return null;
    }

    private static String resolveActorName() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getPrincipal() instanceof SecurityUser user) {
            return user.getUsername();
        }
        return null;
    }
}
