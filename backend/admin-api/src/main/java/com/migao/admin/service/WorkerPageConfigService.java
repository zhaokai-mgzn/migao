package com.migao.admin.service;

import com.migao.admin.dto.ApiResponse;
import com.migao.admin.entity.WorkerPageConfig;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.WorkerPageConfigMapper;
import com.migao.admin.worker.WorkerPages;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 工人端**页面开关**（租户级，V141，母单 #5161）。读写端点
 * {@code /api/admin/worker-page-config}。
 *
 * <h3>🔴 红线：这不是权限</h3>
 * <p>本服务<b>只</b>回答「工人端页面上看得见什么」，<b>不</b>参与任何授权判定，也<b>不</b>写
 * {@code users.permissions}。工人 session 的 {@code permissions} 恒为 {@code []}，
 * 工人可达面恒为 {@code /api/worker/**}（{@code WorkerSessionService} /
 * {@code SecurityConfig}）—— 页面开关把页面藏起来<b>不等于</b>把接口挡住，
 * 服务端对每个工人都仍然按同一套授权判。</p>
 *
 * <h3>两条口径（与裁高配置同族）</h3>
 * <ol>
 *   <li><b>缺行 = 默认全开</b>（{@code source='default'}）：默认集合只在 {@link WorkerPages}
 *       <b>一处</b>；库里再种一份 = 第二份会漂的默认值。</li>
 *   <li><b>配置来自商家 = 不可信输入</b> ⇒ 未知页面键 / 缺键 / 类型不对一律
 *       {@code 422 + error.details:[{field,message}]} <b>逐条</b>理由，<b>不得静默回退默认值</b>
 *       （静默 = 工人端少了一个页面而无人知道）。</li>
 * </ol>
 *
 * <h3>PUT 是**全量替换**</h3>
 * <p>请求体必须**恰好**是 {@code {pages:[...]}}；缺键 ⇒ 422（不把缺的键悄悄按默认值存）。</p>
 *
 * <h3>变更留痕（§22 P6）</h3>
 * <p>每次写都把 {@code 改前 → 改后} 交给 {@link TenantParamAuditService}；审计写失败
 * <b>不让配置保存失败</b>（口径 B = best-effort，同算料 / 裁高配置）。</p>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class WorkerPageConfigService {

    /** 无活跃行 ⇒ 用的是**默认集合**（读面 {@code source} 取值）。 */
    public static final String SOURCE_DEFAULT = "default";

    /** 本租户有活跃行 ⇒ 用的是商家配置。 */
    public static final String SOURCE_STORED = "stored";

    /** 配置体的合法键（PUT 全量替换 ⇒ 缺键/多键都 422）。 */
    static final Set<String> CONFIG_KEYS = new LinkedHashSet<>(List.of("pages"));

    private final WorkerPageConfigMapper workerPageConfigMapper;
    private final TenantParamAuditService tenantParamAuditService;

    /** 读本租户生效的页面集合（无行 ⇒ 默认全开 + {@code source='default'}）。 */
    public Map<String, Object> get(Long tenantId) {
        requireTenant(tenantId);
        WorkerPageConfig row = workerPageConfigMapper.selectActiveByTenant(tenantId);
        if (row == null) {
            return response(SOURCE_DEFAULT, WorkerPages.defaultPages());
        }
        return response(SOURCE_STORED, row.toPages());
    }

    /**
     * 读本租户生效的**页面键列表**（工人 {@code GET /api/worker/me} 的下发面）。
     *
     * <p>与 {@link #get} 共用同一处读行/默认口径 ⇒ 商家读面与工人读面不可能漂。</p>
     */
    public List<String> pagesFor(Long tenantId) {
        return asList(get(tenantId).get("pages"));
    }

    /**
     * 写本租户页面开关（upsert，**全量替换**）。
     *
     * @throws BusinessException 422 + {@code error.details:[{field,message}]} 逐条理由
     */
    public Map<String, Object> put(Long tenantId, Map<String, Object> body) {
        requireTenant(tenantId);
        List<String> pages = validate(body);
        WorkerPageConfig row = workerPageConfigMapper.selectActiveByTenant(tenantId);
        // 🔴 改前的值必须在覆盖**之前**取到（§22 P6 留痕的「A → B」那一半）。
        //    无行 ⇒ 空映射 ⇒ pages 的改前值为 null（= 本租户当时在用默认全开）。
        Map<String, Object> before = row == null ? Map.of() : row.toConfigMap();
        String operationId = TenantParamAuditService.newOperationId();
        OffsetDateTime now = OffsetDateTime.now();
        if (row == null) {
            row = WorkerPageConfig.builder()
                    .id("wpc-" + tenantId)      // 确定性 id：单行表 + 便于日志/审计定位
                    .tenantId(tenantId)
                    .status("active")
                    .deleted(0)
                    .createdAt(now)
                    .build();
            row.setPages(pages);
            row.setUpdatedAt(now);
            workerPageConfigMapper.insert(row);
            log.info("工人端页面开关新建: tenantId={} pages={} operationId={}", tenantId, pages, operationId);
        } else {
            row.setPages(pages);
            row.setUpdatedAt(now);
            workerPageConfigMapper.updateById(row);
            log.info("工人端页面开关更新: tenantId={} pages={} operationId={}", tenantId, pages, operationId);
        }
        // §22 P6 变更留痕（口径 B = best-effort）：本调用**恒不抛**（失败由审计腿自己大声记日志）。
        tenantParamAuditService.recordChanges(tenantId, TenantParamAuditService.DOMAIN_WORKER_PAGES,
                TenantParamAuditService.OPERATION_PUT, operationId, before, row.toConfigMap());
        return response(SOURCE_STORED, row.toPages());
    }

    /**
     * 校验 + 归一（页面键按 {@link WorkerPages#ALL} 闭词表去重、保持请求顺序），失败 ⇒ 422 带**逐条**理由。
     *
     * <p>规则：配置键必须**恰好**是 {@link #CONFIG_KEYS}（全量替换）· {@code pages} 必须是数组 ·
     * 每项必须是闭词表内的字符串（未知键点名该下标）· 数组内不得重复 ·
     * 允许空数组（= 商家把工人端页面**全关**，那是显式选择，不是配置错误）。</p>
     */
    List<String> validate(Map<String, Object> body) {
        List<ApiResponse.ErrorDetail> details = new ArrayList<>();
        Map<String, Object> in = body == null ? Map.of() : body;

        for (String key : in.keySet()) {
            if (!CONFIG_KEYS.contains(key)) {
                details.add(BusinessException.detail(key,
                        "不是工人端页面配置键（拼错的键会被静默忽略 ⇒ 商家以为改了却没改；合法键：" + CONFIG_KEYS + "）"));
            }
        }
        for (String key : CONFIG_KEYS) {
            if (!in.containsKey(key)) {
                details.add(BusinessException.detail(key,
                        "缺少配置键（PUT 是**全量替换**：缺键会让页面集合静默回到默认全开 ⇒ 显式拒绝，不静默回退）"));
            }
        }

        List<String> pages = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        Object rawPages = in.get("pages");
        if (rawPages != null) {
            if (!(rawPages instanceof List<?> list)) {
                details.add(BusinessException.detail("pages", "必须是数组（如 [\"report\",\"order\"]）"));
            } else {
                int index = 0;
                for (Object raw : list) {
                    String field = "pages[" + index + "]";
                    String page = raw == null ? null : String.valueOf(raw).trim();
                    if (page == null || page.isEmpty()) {
                        details.add(BusinessException.detail(field, "不能为空，合法页面键：" + WorkerPages.ALL));
                    } else if (!WorkerPages.ALL.contains(page)) {
                        details.add(BusinessException.detail(field,
                                "不是工人端页面键：" + page + "（合法页面键：" + WorkerPages.ALL
                                        + "；未知键会被静默忽略 ⇒ 商家以为开了却没开）"));
                    } else if (!seen.add(page)) {
                        details.add(BusinessException.detail(field, "页面键重复：" + page));
                    } else {
                        pages.add(page);
                    }
                    index++;
                }
            }
        }

        if (!details.isEmpty()) {
            throw BusinessException.validationError("工人端页面配置有 " + details.size() + " 处不合法", details,
                    "按逐条理由修正后重试；本接口是**全量替换**，没有部分更新");
        }
        return pages;
    }

    private static Map<String, Object> response(String source, List<String> pages) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("source", source);
        data.put("pages", pages);
        data.put("labels", WorkerPages.labels());
        return data;
    }

    private static List<String> asList(Object raw) {
        if (!(raw instanceof List<?> list)) {
            return List.of();
        }
        List<String> out = new ArrayList<>(list.size());
        for (Object item : list) {
            out.add(String.valueOf(item));
        }
        return out;
    }

    private static void requireTenant(Long tenantId) {
        if (tenantId == null) {
            throw BusinessException.tenantInvalid();
        }
    }
}
