package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.IndustryCodes;
import com.migao.admin.dto.ProductionSeedTemplateInfo;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPriceVersion;
import com.migao.admin.entity.ProductionOptionFactor;
import com.migao.admin.entity.ProductionOptionRouting;
import com.migao.admin.entity.ProductionRouting;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPriceVersionMapper;
import com.migao.admin.mapper.ProductionOptionFactorMapper;
import com.migao.admin.mapper.ProductionOptionRoutingMapper;
import com.migao.admin.mapper.ProductionRoutingMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.io.InputStream;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 行业生产种子模板服务（issue #4361 交付物 2/3；收口 #4316）。
 *
 * <h3>为什么需要它（#4316 的根因）</h3>
 * 生产模块的**全部**种子迁移只种 {@code tenant_id = 1}（V54/V56/V58/V59 全是字面量 1，
 * 四个文件里 {@code FROM tenants} 出现 0 次）⇒ 非 1 号租户工序库/路线库为空，
 * {@code ProcessingOrderService.resolveRoute} 两次都不命中 ⇒ 抛 {@code ERR_ROUTING_NOT_FOUND}（422）
 * ⇒ <b>该租户一张加工单也生成不了</b>。用户裁定（2026-09-19）：
 * <b>模板复制 + 开租自动套用</b>（不是循环播种 —— 循环播种会把 1 号租户被客户改过的工艺
 * 在后续迁移里复刻给新租户；模板复制才能让「客户改过的库」成为新租户的初始值）。
 *
 * <h3>形态照 {@link KnowledgeTemplateService}（既有范式，不另造抽象）</h3>
 * 模板 = 平台预置资产（{@code resources/production-templates/<templateId>/seed.json}，jar 内可读），
 * 一键套用 = 把模板行复制为**当前租户**的行。索引 {@code index.json} 给目录，
 * 按 {@code templateId} 取模板文件。
 *
 * <h3>幂等（本类的核心不变量）</h3>
 * 幂等键 = <b>{@code (tenant_id, name)}</b> / <b>{@code (tenant_id, curtain_type, craft)}</b>
 * —— 对齐 V49 的**部分唯一索引**（{@code uk_production_operations_tenant_name ... WHERE deleted = 0}），
 * <b>不是 id</b>。套用前先查已有键，只插缺的那些 ⇒ 连续套用两次行数不变（第二次全 skipped、零 insert）。
 *
 * <h3>落库 id：**不得沿用模板 id**</h3>
 * 模板里的 {@code op-v54-01} 是**模板内的稳定键**（供文件内交叉引用/守卫逐行比对），
 * 而 {@code production_operations.id} 是**全局主键**（V49）且 1 号租户已占用
 * ⇒ 原样插库会撞主键，<b>第二个租户必崩</b>。故 id 由 {@code IdType.ASSIGN_UUID} 生成
 * （与既有写面 {@code ProductionOperationCommandService.create} 同款）。
 *
 * <h3>「不套用」必须显式</h3>
 * {@code other} 行业 / 模板缺失 ⇒ <b>不落任何行</b>并返回可读 {@code reason}（点名原值）。
 * 静默返回空结果会被读成「套用成功了，只是库是空的」—— 那正是 #4316 的形态。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ProductionSeedTemplateService {

    private static final String TEMPLATES_ROOT = "production-templates";
    private static final String INDEX_FILE = TEMPLATES_ROOT + "/index.json";

    /** 工序 provenance 取值（与 V62 的 CHECK 枚举一致）。 */
    public static final Set<String> OPERATION_SOURCES = Set.of("占位待确认", "推算", "实证");
    /** 路线 provenance 取值（与 V62 的 CHECK 枚举一致）。 */
    public static final Set<String> ROUTING_SOURCES = Set.of("占位待确认", "推算", "实证");

    private final ProductionOperationMapper productionOperationMapper;
    private final ProductionRoutingMapper productionRoutingMapper;
    private final ProductionOptionRoutingMapper productionOptionRoutingMapper;
    private final ProductionOptionFactorMapper productionOptionFactorMapper;
    /** 单价版本账（V55 口径「当前价 = 最新版本行」）——不补 ⇒ 模板套出来的工序在改价/追溯面没有价。 */
    private final ProductionOperationPriceVersionMapper priceVersionMapper;

    private final ObjectMapper objectMapper = new ObjectMapper();

    // ══════════════════════ 目录 ══════════════════════

    /** 平台预置模板目录（{@code GET /api/admin/production/seed-templates}）。 */
    public List<ProductionSeedTemplateInfo> listTemplates() {
        List<ProductionSeedTemplateInfo> result = new ArrayList<>();
        JsonNode index = readJson(INDEX_FILE);
        for (JsonNode t : index.path("templates")) {
            JsonNode seed = loadTemplateFile(t.path("file").asText());
            result.add(ProductionSeedTemplateInfo.builder()
                    .templateId(t.path("templateId").asText())
                    .industry(t.path("industry").asText())
                    .name(t.path("name").asText())
                    .version(t.path("version").asInt(1))
                    .description(t.path("description").asText())
                    .operationCount(seed.path("operations").size())
                    .routingCount(seed.path("routings").size())
                    .optionCount(seed.path("option_routings").size())
                    .build());
        }
        return result;
    }

    // ══════════════════════ 套用 ══════════════════════

    /**
     * 按行业套用模板（开租自动套用的入口）。
     *
     * @param tenantId 目标租户（**显式传入**，不读 {@code TenantContext} —— 开租路径在
     *                 {@code TenantContext.setTenantId} 生效期间调用，但显式参数让「给哪个租户套」
     *                 在调用点可读，也避免上下文错位时静默套到别的租户）
     * @param industry 原始行业文本（可未归一；本方法先归一为受控 code）
     * @return {@code {templateId, applied, reason, created_operations, created_routings,
     *         created_options, skipped}}；{@code applied=false} 时 {@code reason} 必非空
     */
    public Map<String, Object> applyTemplate(Long tenantId, String industry) {
        String code = IndustryCodes.normalize(industry);
        JsonNode template = findTemplateByIndustry(code);
        if (template == null) {
            String reason = "行业「" + (industry == null ? "" : industry) + "」归一为受控 code「" + code
                    + "」，平台没有该行业的预置生产模板 ⇒ 未套用任何工序/路线（不是套用失败，是"
                    + "本来就没有；如需布艺窗帘模板，请把行业改成「布艺」或「窗帘」，或经 "
                    + "POST /api/admin/production/seed-templates/{templateId}/apply 手动补套）";
            log.warn("生产种子模板未套用: tenantId={}, industry={}, code={}, reason={}",
                    tenantId, industry, code, reason);
            return result(templateIdOrNull(code), false, reason, 0, 0, 0, 0);
        }
        return applyTemplateNode(tenantId, template);
    }

    /**
     * 模板 id → 行业 code（**模板目录的 id 不是行业 code** —— 目录名可改而行业 code 是受控词表，
     * 把两者混为一谈会让「加一个模板」变成「改词表」）。未知 ⇒ 404。
     */
    public String industryOfTemplate(String templateId) {
        for (JsonNode t : readJson(INDEX_FILE).path("templates")) {
            if (templateId.equals(t.path("templateId").asText())) {
                return t.path("industry").asText();
            }
        }
        throw BusinessException.notFound("生产种子模板");
    }

    private Map<String, Object> applyTemplateNode(Long tenantId, JsonNode template) {
        String templateId = template.path("templateId").asText();
        List<ProductionOperation> newOperations = planOperations(tenantId, template.path("operations"));
        List<ProductionRouting> newRoutings = planRoutings(tenantId, template.path("routings"));
        List<ProductionOptionRouting> newOptions =
                planOptionRoutings(tenantId, template.path("option_routings"));
        List<ProductionOptionFactor> newFactors =
                planOptionFactors(tenantId, template.path("option_factors"));

        int skipped = (template.path("operations").size() - newOperations.size())
                + (template.path("routings").size() - newRoutings.size())
                + (template.path("option_routings").size() - newOptions.size())
                + (template.path("option_factors").size() - newFactors.size());

        for (ProductionOperation op : newOperations) {
            productionOperationMapper.insert(op);
            // 单价版本账首行（与既有写面同口径）：不补 ⇒ 新工序在「当前价 = 最新版本行」下没有价
            priceVersionMapper.insert(ProductionOperationPriceVersion.builder()
                    .tenantId(tenantId)
                    .operationId(op.getId())
                    .unitPrice(op.getUnitPrice())
                    .createdAt(OffsetDateTime.now())
                    .deleted(0)
                    .build());
        }
        newRoutings.forEach(productionRoutingMapper::insert);
        newOptions.forEach(productionOptionRoutingMapper::insert);
        newFactors.forEach(productionOptionFactorMapper::insert);

        log.info("套用生产种子模板: templateId={}, tenantId={}, operations={}, routings={}, "
                        + "options={}, factors={}, skipped={}",
                templateId, tenantId, newOperations.size(), newRoutings.size(),
                newOptions.size(), newFactors.size(), skipped);

        Map<String, Object> result = result(templateId, true, null,
                newOperations.size(), newRoutings.size(), newOptions.size(), skipped);
        result.put("created_option_factors", newFactors.size());
        return result;
    }

    // ══════════════════════ 计划（只读现状 → 算出该插哪些） ══════════════════════

    /** 幂等键 = {@code (tenant_id, name)}；只返回库里还没有的那些。 */
    private List<ProductionOperation> planOperations(Long tenantId, JsonNode nodes) {
        Set<String> existing = new LinkedHashSet<>();
        List<ProductionOperation> rows = productionOperationMapper.selectList(
                new LambdaQueryWrapper<ProductionOperation>()
                        .eq(ProductionOperation::getTenantId, tenantId)
                        .eq(ProductionOperation::getDeleted, 0));
        if (rows != null) {
            rows.forEach(op -> existing.add(op.getName()));
        }
        List<ProductionOperation> plan = new ArrayList<>();
        for (JsonNode node : nodes) {
            String name = node.path("name").asText();
            if (existing.contains(name)) {
                continue;
            }
            plan.add(ProductionOperation.builder()
                    .tenantId(tenantId)
                    .name(name)
                    .groupName(node.path("group").asText("其他"))
                    .position(node.path("position").isNull() ? null : node.path("position").asText())
                    .unit(node.path("unit").asText("米"))
                    .unitPrice(new BigDecimal(node.path("unit_price").asText("0")))
                    .isMustFinish(node.path("is_must_finish").asBoolean(false))
                    .isStartMarker(node.path("is_start_marker").asBoolean(false))
                    .sortOrder(node.path("sort_order").asInt(0))
                    .status(node.path("status").asText("active"))
                    // provenance（本单的诚实性核心）：逐字取模板标注，**不在套用路径上"顺手修正"**
                    .source(sourceOf(node, OPERATION_SOURCES))
                    .createdAt(OffsetDateTime.now())
                    .updatedAt(OffsetDateTime.now())
                    .deleted(0)
                    .build());
        }
        return plan;
    }

    /** 幂等键 = {@code (tenant_id, curtain_type, craft)}。 */
    private List<ProductionRouting> planRoutings(Long tenantId, JsonNode nodes) {
        Set<String> existing = existingRoutingKeys(tenantId);
        List<ProductionRouting> plan = new ArrayList<>();
        for (JsonNode node : nodes) {
            String curtainType = node.path("curtain_type").asText();
            String craft = node.path("craft").asText();
            if (existing.contains(curtainType + "×" + craft)) {
                continue;
            }
            plan.add(ProductionRouting.builder()
                    .tenantId(tenantId)
                    .curtainType(curtainType)
                    .craft(craft)
                    // 路线按**工序名**引用（JSONB 数组），不需要 id 映射
                    .operations(stringList(node.path("operations")))
                    .status(node.path("status").asText("active"))
                    .source(sourceOf(node, ROUTING_SOURCES))
                    .createdAt(OffsetDateTime.now())
                    .updatedAt(OffsetDateTime.now())
                    .deleted(0)
                    .build());
        }
        return plan;
    }

    /** 库中现有的路线键（{@code 部位×工艺}）——幂等判据的现状侧。 */
    private Set<String> existingRoutingKeys(Long tenantId) {
        Set<String> keys = new LinkedHashSet<>();
        List<ProductionRouting> rows = productionRoutingMapper.selectList(
                new LambdaQueryWrapper<ProductionRouting>()
                        .eq(ProductionRouting::getTenantId, tenantId)
                        .eq(ProductionRouting::getDeleted, 0));
        if (rows != null) {
            rows.forEach(r -> keys.add(r.getCurtainType() + "×" + r.getCraft()));
        }
        return keys;
    }

    /** 幂等键 = {@code (tenant_id, option_name, operation_name)}（V59 部分唯一索引同款）。 */
    private List<ProductionOptionRouting> planOptionRoutings(Long tenantId, JsonNode nodes) {
        Set<String> existing = new LinkedHashSet<>();
        List<ProductionOptionRouting> rows = productionOptionRoutingMapper.selectList(
                new LambdaQueryWrapper<ProductionOptionRouting>()
                        .eq(ProductionOptionRouting::getTenantId, tenantId)
                        .eq(ProductionOptionRouting::getDeleted, 0));
        if (rows != null) {
            rows.forEach(r -> existing.add(r.getOptionName() + "×" + r.getOperationName()));
        }
        List<ProductionOptionRouting> plan = new ArrayList<>();
        for (JsonNode node : nodes) {
            String optionName = node.path("option_name").asText();
            String operationName = node.path("operation_name").asText();
            if (existing.contains(optionName + "×" + operationName)) {
                continue;
            }
            plan.add(ProductionOptionRouting.builder()
                    .tenantId(tenantId)
                    .optionName(optionName)
                    .operationName(operationName)
                    .afterOperation(node.path("after_operation").asText())
                    .sortOrder(node.path("sort_order").asInt(0))
                    .status("active")
                    .createdAt(OffsetDateTime.now())
                    .updatedAt(OffsetDateTime.now())
                    .deleted(0)
                    .build());
        }
        return plan;
    }

    /** 幂等键 = {@code (tenant_id, option_name, operation_name)}（NULL = 平摊档，按选项去重）。 */
    private List<ProductionOptionFactor> planOptionFactors(Long tenantId, JsonNode nodes) {
        Set<String> existing = new LinkedHashSet<>();
        List<ProductionOptionFactor> rows = productionOptionFactorMapper.selectList(
                new LambdaQueryWrapper<ProductionOptionFactor>()
                        .eq(ProductionOptionFactor::getTenantId, tenantId)
                        .eq(ProductionOptionFactor::getDeleted, 0));
        if (rows != null) {
            rows.forEach(f -> existing.add(f.getOptionName() + "×" + f.getOperationName()));
        }
        List<ProductionOptionFactor> plan = new ArrayList<>();
        for (JsonNode node : nodes) {
            String optionName = node.path("option_name").asText();
            String operationName = node.path("operation_name").isNull()
                    ? null : node.path("operation_name").asText();
            if (existing.contains(optionName + "×" + operationName)) {
                continue;
            }
            plan.add(ProductionOptionFactor.builder()
                    .tenantId(tenantId)
                    .optionName(optionName)
                    .operationName(operationName)
                    .factor(new BigDecimal(node.path("factor").asText("1")))
                    .source(node.path("source").asText("推算"))
                    .createdAt(OffsetDateTime.now())
                    .updatedAt(OffsetDateTime.now())
                    .deleted(0)
                    .build());
        }
        return plan;
    }

    // ══════════════════════ 模板读取 ══════════════════════

    /** 按行业 code 找模板（找不到 ⇒ null，由调用方决定「显式跳过」还是「404」）。 */
    private JsonNode findTemplateByIndustry(String industryCode) {
        for (JsonNode t : readJson(INDEX_FILE).path("templates")) {
            if (industryCode.equals(t.path("industry").asText())) {
                return withTemplateId(loadTemplateFile(t.path("file").asText()),
                        t.path("templateId").asText());
            }
        }
        return null;
    }

    /** 按 templateId 找模板（找不到 ⇒ null）。 */
    private JsonNode findTemplate(String templateId) {
        for (JsonNode t : readJson(INDEX_FILE).path("templates")) {
            if (templateId.equals(t.path("templateId").asText())) {
                return withTemplateId(loadTemplateFile(t.path("file").asText()), templateId);
            }
        }
        return null;
    }

    /**
     * 模板正文补 {@code templateId}（正文里也写了一份，索引是权威 —— 两者不一致时以索引为准，
     * 避免「索引改名而正文没改」让 apply 响应报出旧 id）。
     */
    private JsonNode withTemplateId(JsonNode seed, String templateId) {
        if (seed instanceof com.fasterxml.jackson.databind.node.ObjectNode objectNode) {
            objectNode.put("templateId", templateId);
        }
        return seed;
    }

    private JsonNode loadTemplateFile(String file) {
        try {
            return readJson(TEMPLATES_ROOT + "/" + file);
        } catch (RuntimeException e) {
            log.error("读取生产种子模板文件失败: file={}", file, e);
            throw BusinessException.notFound("生产种子模板");
        }
    }

    private JsonNode readJson(String classpath) {
        ClassPathResource resource = new ClassPathResource(classpath);
        try (InputStream in = resource.getInputStream()) {
            return objectMapper.readTree(in);
        } catch (IOException e) {
            throw BusinessException.notFound("生产种子模板目录");
        }
    }

    // ══════════════════════ 工具 ══════════════════════

    /**
     * 取模板行的 provenance 标注；标注缺失或越出枚举 ⇒ **报错**（不静默补默认值）。
     * 「来源未知」不许冒充「占位待确认」—— 那正是本单要治的「库里看不出单价是占位的」。
     */
    private static String sourceOf(JsonNode node, Set<String> allowed) {
        String source = node.path("source").asText("");
        if (!allowed.contains(source)) {
            throw new IllegalStateException("模板 provenance 标注非法: source=" + source
                    + "（允许 " + allowed + "）—— 模板资产损坏，拒绝静默套用");
        }
        return source;
    }

    private static List<String> stringList(JsonNode array) {
        List<String> names = new ArrayList<>();
        array.forEach(node -> names.add(node.asText()));
        return names;
    }

    private static String templateIdOrNull(String industryCode) {
        return IndustryCodes.CURTAIN.equals(industryCode) ? "curtain" : null;
    }

    private static Map<String, Object> result(String templateId, boolean applied, String reason,
                                              int operations, int routings, int options, int skipped) {
        Map<String, Object> result = new java.util.LinkedHashMap<>();
        result.put("templateId", templateId);
        result.put("applied", applied);
        result.put("reason", reason);
        result.put("created_operations", operations);
        result.put("created_routings", routings);
        result.put("created_options", options);
        result.put("skipped", skipped);
        return result;
    }
}
