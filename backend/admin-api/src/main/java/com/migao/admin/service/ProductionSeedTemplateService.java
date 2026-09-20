package com.migao.admin.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.IndustryCodes;
import com.migao.admin.dto.ProductionSeedTemplateInfo;
import com.migao.admin.entity.ProductionOperation;
import com.migao.admin.entity.ProductionOperationPriceVersion;
import com.migao.admin.entity.ProductionCraft;
import com.migao.admin.entity.ProductionOperationPosition;
import com.migao.admin.entity.ProductionRouteRule;
import com.migao.admin.entity.ProductionRouteTemplate;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.ProductionCraftMapper;
import com.migao.admin.mapper.ProductionOperationMapper;
import com.migao.admin.mapper.ProductionOperationPositionMapper;
import com.migao.admin.mapper.ProductionOperationPriceVersionMapper;
import com.migao.admin.mapper.ProductionRouteRuleMapper;
import com.migao.admin.mapper.ProductionRouteTemplateMapper;
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
    // ── 新结构（P2b，issue #4459 §1④）：开租必须种「默认路线 + 默认工艺」，否则新租户零默认 ⇒ 建单全 fail-closed ──
    private final ProductionRouteTemplateMapper productionRouteTemplateMapper;
    private final ProductionOperationPositionMapper productionOperationPositionMapper;
    private final ProductionRouteRuleMapper productionRouteRuleMapper;
    private final ProductionCraftMapper productionCraftMapper;
    /** 单价版本账（V55 口径「当前价 = 最新版本行」）——不补 ⇒ 模板套出来的工序在改价/追溯面没有价。 */
    private final ProductionOperationPriceVersionMapper priceVersionMapper;

    /** 规范主线（**10 道** = 9 道 + `打包`，issue #4529；**不含**工艺槽位）；
     * 与 {@code routing.py::ROUTE_MAINLINE_STEPS} 逐字同源。 */
    private static final List<String> ROUTE_MAINLINE_STEPS = List.of(
            "精裁", "三边", "熨烫", "定型", "复烫", "车被", "外帘打卷", "打包", "外帘装袋", "外帘发货");

    /** 默认路线模板名（与 V71/V72 种子逐字一致：同租户活跃路线不得重名 ⇒ 名字必须稳定）。 */
    private static final String ROUTE_TEMPLATE_NAME_DEFAULT = "窗帘工序路线（默认）";

    // ── 第 2 条基础路线：布料（issue #4529，包 F；用户裁定「每个租户默认两条基础工序路线」）──
    /** 第 4 个部位（布料单专用）—— 与 {@code routing.py::FABRIC_POSITION} 逐字同源。 */
    private static final String FABRIC_POSITION = "布料";
    /**
     * 布料主线（2 道）：`裁剪` → `打包` —— **V88（issue #4676）后的终态**。
     *
     * <p>用户裁定逐字：「布料单该用 **裁剪**」（#4673 评论；设计 F5 已把早期「`配料` 是公共工序」
     * 改判掉）。迁移侧由 {@code V88__retire_material_prep_and_fabric_position.sql} 达成；
     * 开租播种**不跑迁移链** ⇒ 必须在本类同步，否则 V88 之后注册的新租户仍会拿到
     * `["配料","打包"]` ⇒ 新单实例里出现 `配料`（**停止条件 S6 红**）。</p>
     *
     * <p>⚠️ 与 {@code routing.py::FABRIC_MAINLINE_STEPS} 的**逐字同源关系已断**（该文件属
     * ai-agent，不在 #4676 的改动面）—— 这是**照实登记的跨单依赖**，不是静默漂移：
     * {@code tests/unit_ci_workflows/test_public_ops_v88_migration.py} 逐条钉住本常量的终态值。</p>
     */
    private static final List<String> FABRIC_MAINLINE_STEPS = List.of("裁剪", "打包");
    /**
     * V88（issue #4676）**退场**的逻辑工序：`配料`（行业里它对应「物料分配」，不在车间三段里）。
     *
     * <p>矩阵常量 {@link #CANONICAL_POSITION_PRICES} **一字不动**（它与
     * {@code routing.py::_POSITION_PRICE_ROWS} 逐行同值、被守卫冻结）⇒ 退场只在播种这一层显式表达。</p>
     */
    private static final Set<String> RETIRED_LOGICAL_NAMES = Set.of("配料");
    /** V88 的**保命格**：`裁剪 × 布料` 必须 `applicable=TRUE`（迁移侧 V88 ④ 的同款终态）。 */
    private static final String FABRIC_KEEP_APPLICABLE_LOGICAL = "裁剪";
    /** 布料路线模板名（与 V79 / schema.sql 种子逐字一致）。 */
    private static final String FABRIC_ROUTE_TEMPLATE_NAME_DEFAULT = "布料工序路线";

    /** 规范工艺词表（默认工艺的候选序；与 V72 迁移的 {@code unnest(ARRAY[...])} 逐字一致）。 */
    private static final List<String> CRAFT_VOCABULARY = List.of("韩褶", "打孔", "四爪钩", "穿杆", "平幔");

    /**
     * 规范工艺变体规则（10 条）：{@code {trigger_value, position|NULL, action, operation, after|NULL}}。
     *
     * <p>与 {@code routing.py::ROUTE_RULES} 的 {@code trigger_kind='craft'} 部分逐条同源
     * （{@code priority} 由播种顺序 10/20/… 生成，与 V71/V72 种子同值）。</p>
     */
    private static final String[][] CRAFT_RULES = {
            {"韩褶", "NULL", "insert", "韩褶", "三边"},
            // 🔴 issue #4937 / O2：规则级 `position` 已退场 ⇒ 开租播种一律 `NULL`
            // （此前这里是 `"布帘"`，与 V71 的字面量同款；存量库由
            //  `V103__clear_route_rule_positions.sql` 清空，新租户不能继续种旧口径）。
            {"韩褶", "NULL", "insert", "上车布", "韩褶"},
            {"打孔", "NULL", "insert", "打孔", "三边"},
            {"四爪钩", "NULL", "insert", "上车布", "三边"},
            {"四爪钩", "NULL", "remove", "定型", "NULL"},
            {"四爪钩", "NULL", "remove", "复烫", "NULL"},
            {"穿杆", "NULL", "remove", "定型", "NULL"},
            {"穿杆", "NULL", "remove", "复烫", "NULL"},
            {"平幔", "NULL", "insert", "帘头制作", "三边"},
            {"平幔", "NULL", "remove", "复烫", "NULL"},
    };

    /**
     * 规范**加工项触发**规则（3 条，issue #4577）：{@code {trigger_value, action, operation, after}}。
     *
     * <p>与 V84 迁移逐条同值（`trigger_kind='processing_item'`，priority 270/280/290；**不**进
     * {@code routing.py::ROUTE_RULES} —— 那张表被守卫钉为「≡ V71 的 26 行字面量种子」）。
     * 触发键 = 订单行 {@code processingInfo.processingItems[].name}，**精确相等**。</p>
     *
     * <p>⚠️ `拼接` / `双眼皮` **刻意不建规则行**（理由登记在 issue #4577：用户裁定「只有选择了
     * 这几个特殊选项才会有拼接工序」—— `拼接`/`双眼皮` 是**特征词**，拼几次由特殊选项
     * `拼1次/拼2次/拼3次` 表达；造行 = 把错误结构化）。</p>
     */
    private static final String[][] PROCESSING_ITEM_RULES = {
            {"花边", "insert", "花边", "三边"},
            {"扣环", "insert", "扣环", "三边"},
            {"接高", "insert", "接高", "精裁"},
    };

    /**
     * 部位价目 + 适用性矩阵（**120 行** = 30 逻辑工序 × 4 部位，issue #4529 起）：
     * {@code {logical_name, position, unit_price|NULL, applicable}}。
     *
     * <p>P1（#4427）冻结的**规范矩阵**的一次快照，与 {@code routing.py::OPERATION_POSITION_PRICES} /
     * V71 的 84 行种子逐行同值（三源收敛由 {@code test_production_catalog_seed.py} 守）。
     * 开租播种需要它：新租户不走迁移链（V72 的按租户回填只覆盖**存量**租户）⇒
     * 没有本表就取不到 `applicable` ⇒ 主线被全部滤掉 ⇒ 实例化零工序。</p>
     */
    private static final String[][] CANONICAL_POSITION_PRICES = {
            {"精裁", "布帘", "0.4", "true"},
            {"精裁", "纱帘", "0.4", "true"},
            {"精裁", "帘头", "0.4", "true"},
            {"裁剪", "布帘", "0.4", "true"},
            {"裁剪", "纱帘", "0.4", "true"},
            {"裁剪", "帘头", "0.4", "true"},
            {"三边", "布帘", "0.4", "true"},
            {"三边", "纱帘", "0.4", "true"},
            {"三边", "帘头", "0.4", "true"},
            {"韩褶", "布帘", "0.4", "true"},
            {"韩褶", "纱帘", "0.4", "true"},
            {"韩褶", "帘头", "0.4", "true"},
            {"上车布", "布帘", "0.5", "true"},
            {"上车布", "纱帘", "0.5", "true"},
            {"上车布", "帘头", null, "false"},
            {"打孔", "布帘", "0.15", "true"},
            {"打孔", "纱帘", "0.15", "true"},
            {"打孔", "帘头", "0.15", "true"},
            {"拼1次", "布帘", "0.8", "true"},
            {"拼1次", "纱帘", null, "false"},
            {"拼1次", "帘头", null, "false"},
            {"拼2次", "布帘", "1.2", "true"},
            {"拼2次", "纱帘", null, "false"},
            {"拼2次", "帘头", null, "false"},
            {"拼3次", "布帘", "1.6", "true"},
            {"拼3次", "纱帘", null, "false"},
            {"拼3次", "帘头", null, "false"},
            {"花边", "布帘", "0.6", "true"},
            {"花边", "纱帘", null, "false"},
            {"花边", "帘头", null, "false"},
            {"铅坠", "布帘", "0.3", "true"},
            {"铅坠", "纱帘", null, "false"},
            {"铅坠", "帘头", null, "false"},
            {"接高", "布帘", "1.0", "true"},
            {"接高", "纱帘", null, "false"},
            {"接高", "帘头", null, "false"},
            {"帘头制作", "布帘", null, "false"},
            {"帘头制作", "纱帘", null, "false"},
            {"帘头制作", "帘头", "2.0", "true"},
            {"熨烫", "布帘", "0.35", "true"},
            {"熨烫", "纱帘", null, "false"},
            {"熨烫", "帘头", null, "false"},
            {"定型", "布帘", "0.4", "true"},
            {"定型", "纱帘", null, "false"},
            {"定型", "帘头", "0.4", "true"},
            {"复烫", "布帘", "0.35", "true"},
            {"复烫", "纱帘", null, "false"},
            {"复烫", "帘头", null, "false"},
            {"车被", "布帘", "0.4", "true"},
            {"车被", "纱帘", null, "false"},
            {"车被", "帘头", null, "false"},
            {"外帘打卷", "布帘", "1.0", "true"},
            {"外帘打卷", "纱帘", "1.0", "true"},
            {"外帘打卷", "帘头", "1.0", "true"},
            {"外帘装袋", "布帘", "1.0", "true"},
            {"外帘装袋", "纱帘", "1.0", "true"},
            {"外帘装袋", "帘头", "1.0", "true"},
            {"质检", "布帘", "1.5", "true"},
            {"质检", "纱帘", "1.5", "true"},
            {"质检", "帘头", "1.5", "true"},
            {"外帘发货", "布帘", "1.0", "true"},
            {"外帘发货", "纱帘", "1.0", "true"},
            {"外帘发货", "帘头", "1.0", "true"},
            {"绑带", "布帘", "0.5", "true"},
            {"绑带", "纱帘", "0.5", "true"},
            {"绑带", "帘头", null, "false"},
            {"抱枕", "布帘", "2.0", "true"},
            {"抱枕", "纱帘", "2.0", "true"},
            {"抱枕", "帘头", "2.0", "true"},
            {"腰靠垫", "布帘", "2.0", "true"},
            {"腰靠垫", "纱帘", "2.0", "true"},
            {"腰靠垫", "帘头", "2.0", "true"},
            {"logo条", "布帘", "0.6", "true"},
            {"logo条", "纱帘", null, "false"},
            {"logo条", "帘头", null, "false"},
            {"立边", "布帘", "0.5", "true"},
            {"立边", "纱帘", null, "false"},
            {"立边", "帘头", null, "false"},
            {"扣环", "布帘", "0.3", "true"},
            {"扣环", "纱帘", null, "false"},
            {"扣环", "帘头", null, "false"},
            {"防翘扣", "布帘", "0.2", "true"},
            {"防翘扣", "纱帘", null, "false"},
            {"防翘扣", "帘头", null, "false"},
            // ── issue #4529（包 F）：第 4 个部位「布料」的 28 行（逐行显式 FALSE）+ 新增两道 ──
            // 84 + 36 = **120 行**。与 V79 / schema.sql / routing.py 逐行同值（三源收敛守卫）。
            // 「适用但未定价」= `applicable=true` 且 `unit_price=null`（`配料`/`打包`，商家自配）。
            {"精裁", "布料", null, "false"},
            {"裁剪", "布料", null, "false"},
            {"三边", "布料", null, "false"},
            {"韩褶", "布料", null, "false"},
            {"上车布", "布料", null, "false"},
            {"打孔", "布料", null, "false"},
            {"拼1次", "布料", null, "false"},
            {"拼2次", "布料", null, "false"},
            {"拼3次", "布料", null, "false"},
            {"花边", "布料", null, "false"},
            {"铅坠", "布料", null, "false"},
            {"接高", "布料", null, "false"},
            {"帘头制作", "布料", null, "false"},
            {"熨烫", "布料", null, "false"},
            {"定型", "布料", null, "false"},
            {"复烫", "布料", null, "false"},
            {"车被", "布料", null, "false"},
            {"外帘打卷", "布料", null, "false"},
            {"外帘装袋", "布料", null, "false"},
            {"质检", "布料", null, "false"},
            {"外帘发货", "布料", null, "false"},
            {"绑带", "布料", null, "false"},
            {"抱枕", "布料", null, "false"},
            {"腰靠垫", "布料", null, "false"},
            {"logo条", "布料", null, "false"},
            {"立边", "布料", null, "false"},
            {"扣环", "布料", null, "false"},
            {"防翘扣", "布料", null, "false"},
            {"配料", "布料", null, "true"},
            {"配料", "布帘", null, "false"},
            {"配料", "纱帘", null, "false"},
            {"配料", "帘头", null, "false"},
            {"打包", "布帘", null, "true"},
            {"打包", "纱帘", null, "true"},
            {"打包", "帘头", null, "true"},
            {"打包", "布料", null, "true"},
    };

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
        // 旧两表**不再读也不再写**（P2b 起它们已退场：活跃行由 V73 软删，规则真值源 = 新结构）。
        // 模板 JSON 的 routings / option_routings / option_factors 仍是**种子数据源**
        // （经逻辑名归一后落进 production_route_templates / production_route_rules）。
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

        // ── 新结构（P2b，issue #4459 §1④）────────────────────────────────────────────
        // 🔴 **P0**：消费路径已切到新结构 ⇒ 新租户**零默认路线**时 `resolveRoute` T3 fail-closed
        // ⇒ 该租户一张加工单也生成不了。故开租播种必须同时种：默认路线模板 + 默认工艺
        // + 部位价目/适用性 + 规则表。
        // 数据源：① 部位价目 = **规范矩阵**（P1 冻结的 84 行，逐条溯源到 routing.py::OPERATION_POSITION_PRICES）；
        //        ② 主线/规则 = 模板 JSON 的 routings / option_routings 经**逻辑名归一**后过滤到本租户工序库。
        // 幂等：一律按业务唯一键先查后插（第二次套用零 insert）。
        List<ProductionOperationPosition> newPositions = planPositions(tenantId);
        List<ProductionRouteTemplate> newTemplates = planRouteTemplates(tenantId, template);
        List<ProductionRouteRule> newRules = planRouteRules(tenantId, template);
        List<ProductionCraft> newCrafts = planCrafts(tenantId, template);

        // `skipped` = 模板里**已存在、本次未插**的种子行数（四个种子组各自计）：
        // 工序 / 路线模板（新结构里 9 条旧路线收敛成 **2** 条模板：窗帘默认 + 布料，issue #4529）
        // / 选项映射 / 系数档。
        int appliedOptionRules = (int) newRules.stream()
                .filter(r -> "option".equals(r.getTriggerKind()) && "insert".equals(r.getAction()))
                .count();
        int appliedFactorRules = (int) newRules.stream()
                .filter(r -> "factor".equals(r.getAction())).count();
        int skipped = (template.path("operations").size() - newOperations.size())
                + (2 - newTemplates.size())
                + (template.path("option_routings").size() - appliedOptionRules)
                + (template.path("option_factors").size() - appliedFactorRules);

        // 旧两表**不再写入**（P2b 起它们已退场：活跃行由 V73 软删，消费真值源 = 新结构）
        newPositions.forEach(productionOperationPositionMapper::insert);
        newTemplates.forEach(productionRouteTemplateMapper::insert);
        newRules.forEach(productionRouteRuleMapper::insert);
        newCrafts.forEach(productionCraftMapper::insert);

        log.info("套用生产种子模板: templateId={}, tenantId={}, operations={}, "
                        + "新-部位价目={}, 新-路线模板={}, 新-规则={}, 新-工艺={}, skipped={}",
                templateId, tenantId, newOperations.size(), newPositions.size(),
                newTemplates.size(), newRules.size(), newCrafts.size(), skipped);

        Map<String, Object> result = result(templateId, true, null,
                newOperations.size(), newTemplates.size(),
                template.path("option_routings").size(), skipped);
        result.put("created_positions", newPositions.size());
        result.put("created_route_rules", newRules.size());
        result.put("created_crafts", newCrafts.size());
        result.put("created_default_route", (int) newTemplates.stream()
                .filter(t -> Boolean.TRUE.equals(t.getIsDefault())).count());
        return result;
    }

    // ══════════════════════ 新结构播种（P2b，issue #4459 §1④） ══════════════════════

    /**
     * 部位价目 + 适用性（规范矩阵，84 行 = 28 逻辑工序 × 3 部位）。
     *
     * <p>与 V71/V72 的种子**同一份规范矩阵**（P1 冻结、逐条溯源到
     * {@code routing.py::OPERATION_POSITION_PRICES}）—— 三源收敛由
     * {@code tests/unit_ci_workflows/test_production_catalog_seed.py} 守。</p>
     *
     * <p>过滤：只种该租户工序库里**归一后存在**的逻辑工序（否则价目行永远取不到变体名，
     * 是「已落库但永不生效」的黑洞 —— 与 V72 的规则过滤同口径）。</p>
     */
    private List<ProductionOperationPosition> planPositions(Long tenantId) {
        Set<String> existing = new LinkedHashSet<>();
        List<ProductionOperationPosition> rows = productionOperationPositionMapper.selectList(
                new LambdaQueryWrapper<ProductionOperationPosition>()
                        .eq(ProductionOperationPosition::getTenantId, tenantId)
                        .eq(ProductionOperationPosition::getDeleted, 0));
        if (rows != null) {
            rows.forEach(r -> existing.add(r.getLogicalName() + "×" + r.getPosition()));
        }
        Set<String> available = logicalNamesOf(tenantId);
        List<ProductionOperationPosition> plan = new ArrayList<>();
        for (String[] row : CANONICAL_POSITION_PRICES) {
            String logical = row[0];
            String position = row[1];
            if (!available.contains(logical) || existing.contains(logical + "×" + position)) {
                continue;
            }
            // ── V88（issue #4676）的两处**显式终态覆盖** ────────────────────────────────────
            // ① 退场工序（`配料`）不再播种。不覆盖的后果：新租户的工序库里留着 `配料`
            //    且矩阵里 `配料 × 布料` 适用 ⇒ 一旦有人把它加回主线，新单实例里就会再出现
            //    `配料`（停止条件 S6）。
            if (RETIRED_LOGICAL_NAMES.contains(logical)) {
                continue;
            }
            // ② **保命格** `裁剪 × 布料` 强制 `applicable=TRUE`。不覆盖的后果：布料主线已改成
            //    `["裁剪","打包"]`，而矩阵里 `裁剪 × 布料` 仍是 `applicable=FALSE`
            //    ⇒ `buildRoute` 静默滤掉 `裁剪` ⇒ **新租户的布料单只剩 `打包` 一道**
            //    （停止条件 S1：布料单实例化工序数 ≠ 2）。
            boolean applicable = Boolean.parseBoolean(row[3])
                    || (FABRIC_KEEP_APPLICABLE_LOGICAL.equals(logical)
                        && FABRIC_POSITION.equals(position));
            plan.add(ProductionOperationPosition.builder()
                    .tenantId(tenantId)
                    .logicalName(logical)
                    .position(position)
                    .unitPrice(row[2] == null ? null : new BigDecimal(row[2]))
                    .applicable(applicable)
                    .status("active")
                    .createdAt(OffsetDateTime.now())
                    .updatedAt(OffsetDateTime.now())
                    .deleted(0)
                    .build());
        }
        return plan;
    }

    /**
     * 基础路线模板（**恰两条**，issue #4529）：`窗帘工序路线（默认）`（{@code is_default=TRUE}）
     * + `布料工序路线`（{@code FALSE}，`positions=["布料"]`）。
     *
     * <p>主线取**规范顺序**（{@code routing.py::ROUTE_MAINLINE_STEPS} /
     * {@code FABRIC_MAINLINE_STEPS}）而不是模板 JSON 里 9 条旧路线的并集 —— 顺序是车间实际走线，
     * 且新模型每个部位只有一条主线。两条主线都过滤到**该租户工序库**（与 V72 的按租户回填同口径：
     * 库里没有的工序不进他的主线，否则实例化 `missing_operations` ⇒ T3 fail-closed 422）。</p>
     *
     * <p>幂等键 = <b>{@code (tenant_id, name)}</b>（逐条判，不是「有任何一条就全跳过」）——
     * 存量租户补布料路线时，已有的窗帘路线不得被重复种。</p>
     */
    private List<ProductionRouteTemplate> planRouteTemplates(Long tenantId, JsonNode template) {
        List<ProductionRouteTemplate> existing = productionRouteTemplateMapper.selectList(
                new LambdaQueryWrapper<ProductionRouteTemplate>()
                        .eq(ProductionRouteTemplate::getTenantId, tenantId)
                        .eq(ProductionRouteTemplate::getDeleted, 0));
        Set<String> existingNames = new LinkedHashSet<>();
        if (existing != null) {
            existing.forEach(row -> existingNames.add(row.getName()));
        }
        Set<String> available = logicalNamesOf(tenantId);
        List<ProductionRouteTemplate> plan = new ArrayList<>();
        // ① 窗帘默认路线（主线 10 道 ∩ 本租户工序库）
        if (!existingNames.contains(ROUTE_TEMPLATE_NAME_DEFAULT)) {
            List<String> mainline = mainlineOf(ROUTE_MAINLINE_STEPS, available);
            plan.add(ProductionRouteTemplate.builder()
                    .tenantId(tenantId)
                    .name(ROUTE_TEMPLATE_NAME_DEFAULT)
                    .isDefault(true)
                    .positions(List.of("布帘", "纱帘", "帘头"))
                    .mainline(mainline.isEmpty() ? ROUTE_MAINLINE_STEPS : mainline)
                    .status("active")
                    .createdAt(OffsetDateTime.now())
                    .updatedAt(OffsetDateTime.now())
                    .deleted(0)
                    .build());
        }
        // ② 布料路线（issue #4529）：每租户**两条**基础路线之一；`is_default=FALSE`
        //    （部分唯一索引 uk_production_route_templates_tenant_default 保证每租户至多一条默认）。
        if (!existingNames.contains(FABRIC_ROUTE_TEMPLATE_NAME_DEFAULT)) {
            List<String> fabricMainline = mainlineOf(FABRIC_MAINLINE_STEPS, available);
            plan.add(ProductionRouteTemplate.builder()
                    .tenantId(tenantId)
                    .name(FABRIC_ROUTE_TEMPLATE_NAME_DEFAULT)
                    .isDefault(false)
                    .positions(List.of(FABRIC_POSITION))
                    .mainline(fabricMainline.isEmpty() ? FABRIC_MAINLINE_STEPS : fabricMainline)
                    .status("active")
                    .createdAt(OffsetDateTime.now())
                    .updatedAt(OffsetDateTime.now())
                    .deleted(0)
                    .build());
        }
        return plan;
    }

    /** 规范主线 ∩ 该租户工序库（**保持规范顺序**）——与 V72/V79 的按租户回填同口径。 */
    private static List<String> mainlineOf(List<String> canonical, Set<String> available) {
        List<String> mainline = new ArrayList<>();
        for (String step : canonical) {
            if (available.contains(step)) {
                mainline.add(step);
            }
        }
        return mainline;
    }

    /**
     * 规则表（工艺变体 + 加工项触发 + 特殊选项 + 计件系数档）。
     *
     * <p>数据源 = 模板 JSON 的 {@code option_routings} / {@code option_factors} + 规范工艺变体规则；
     * **工序名与锚点都归一为逻辑名**（不归一 ⇒ 锚点在逻辑名序列里找不到 ⇒ 条件工序静默追加末尾）。</p>
     */
    private List<ProductionRouteRule> planRouteRules(Long tenantId, JsonNode template) {
        Set<String> existing = new LinkedHashSet<>();
        List<ProductionRouteRule> rows = productionRouteRuleMapper.selectList(
                new LambdaQueryWrapper<ProductionRouteRule>()
                        .eq(ProductionRouteRule::getTenantId, tenantId)
                        .eq(ProductionRouteRule::getDeleted, 0));
        if (rows != null) {
            rows.forEach(r -> existing.add(r.getTriggerKind() + "×" + r.getTriggerValue() + "×"
                    + r.getAction() + "×" + (r.getOperation() == null ? "" : r.getOperation())));
        }
        Set<String> available = logicalNamesOf(tenantId);
        List<ProductionRouteRule> plan = new ArrayList<>();
        int priority = 10;
        // ① 工艺变体（10 条，规范矩阵：与 routing.py::ROUTE_RULES 的 craft 部分逐条同源）
        for (String[] rule : CRAFT_RULES) {
            priority += 10;
            addRule(plan, existing, available, tenantId, "craft", rule[0],
                    "NULL".equals(rule[1]) ? null : rule[1], rule[2], rule[3],
                    "NULL".equals(rule[4]) ? null : rule[4], priority, null);
        }
        // ② 特殊选项条件工序（模板 JSON 逐条搬迁，工序名与锚点归一为逻辑名）
        for (JsonNode node : template.path("option_routings")) {
            priority += 10;
            addRule(plan, existing, available, tenantId, "option", node.path("option_name").asText(),
                    null, "insert", logicalName(node.path("operation_name").asText()),
                    logicalName(node.path("after_operation").asText()), priority, null);
        }
        // ③ 加工项触发（issue #4577：3 条，与 V84 逐条同值）—— 排在选项之后、系数档之前，
        //    与 V84 的 priority 270/280/290（> 选项 260、< 系数 300）**同序**。
        for (String[] rule : PROCESSING_ITEM_RULES) {
            priority += 10;
            addRule(plan, existing, available, tenantId, "processing_item", rule[0],
                    null, rule[1], rule[2], rule[3], priority, null);
        }
        // ④ 计件系数档（模板 JSON 逐条搬迁；operation_name 为空 = 平摊档 ⇒ operation 落 NULL）
        for (JsonNode node : template.path("option_factors")) {
            priority += 10;
            String operationName = node.path("operation_name").isNull()
                    ? null : logicalName(node.path("operation_name").asText());
            addRule(plan, existing, available, tenantId, "option", node.path("option_name").asText(),
                    null, "factor", operationName, null, priority,
                    new BigDecimal(node.path("factor").asText("1")));
        }
        return plan;
    }

    private void addRule(List<ProductionRouteRule> plan, Set<String> existing, Set<String> available,
                         Long tenantId, String kind, String trigger, String position, String action,
                         String operation, String after, int priority, BigDecimal factor) {
        // 该租户工序库里没有这道逻辑工序 ⇒ 不种（否则规则永远插不进来 = 黑洞）
        if (operation != null && !available.contains(operation)) {
            return;
        }
        String key = kind + "×" + trigger + "×" + action + "×" + (operation == null ? "" : operation);
        if (!existing.add(key)) {
            return;
        }
        plan.add(ProductionRouteRule.builder()
                .tenantId(tenantId)
                .triggerKind(kind)
                .triggerValue(trigger)
                .position(position)
                .action(action)
                .operation(operation)
                .afterOperation(after)
                .priority(priority)
                .factor(factor)
                .status("active")
                .createdAt(OffsetDateTime.now())
                .updatedAt(OffsetDateTime.now())
                .deleted(0)
                .build());
    }

    /**
     * 商户级默认工艺（**恰一条** {@code is_default}）。
     *
     * <p>口径与 V72 迁移逐字一致：**优先 {@code 韩褶}**（V54 起的事实默认），否则退到规范工艺词表里
     * 第一个该租户确实有工序的工艺，都没有 ⇒ 落 {@code 韩褶} 作为种子默认
     * （**会落库、可在「工艺配置」改** ⇒ 不是「静默取常量」）。</p>
     */
    private List<ProductionCraft> planCrafts(Long tenantId, JsonNode template) {
        List<ProductionCraft> existing = productionCraftMapper.selectList(
                new LambdaQueryWrapper<ProductionCraft>()
                        .eq(ProductionCraft::getTenantId, tenantId)
                        .eq(ProductionCraft::getDeleted, 0));
        if (existing != null && !existing.isEmpty()) {
            return List.of();
        }
        Set<String> available = logicalNamesOf(tenantId);
        String name = ProcessingOrderService.DEFAULT_CRAFT;
        for (String candidate : CRAFT_VOCABULARY) {
            if (available.contains(candidate)) {
                name = candidate;
                break;
            }
        }
        return List.of(ProductionCraft.builder()
                .tenantId(tenantId)
                .name(name)
                .isDefault(true)
                .status("active")
                .createdAt(OffsetDateTime.now())
                .updatedAt(OffsetDateTime.now())
                .deleted(0)
                .build());
    }

    /** 该租户工序库里的**逻辑工序名**集合（工序库存的是旧名 ⇒ 必须归一）。 */
    private Set<String> logicalNamesOf(Long tenantId) {
        Set<String> names = new LinkedHashSet<>();
        List<ProductionOperation> rows = productionOperationMapper.selectList(
                new LambdaQueryWrapper<ProductionOperation>()
                        .eq(ProductionOperation::getTenantId, tenantId)
                        .eq(ProductionOperation::getDeleted, 0)
                        .eq(ProductionOperation::getStatus, "active"));
        if (rows != null) {
            rows.forEach(op -> names.add(logicalName(op.getName())));
        }
        return names;
    }

    /**
     * 旧工序名 → 逻辑工序名（**复用单一出处**，未登记的名字原样返回）。
     *
     * <p>🔴 issue #4637：本类曾自带一份 35 条的副本表（{@code LOGICAL_NAMES}），与
     * {@link ProductionOperationQueryService} 的那一份并存 —— 两份**逐条同值**，但**改一份不改另一份
     * 不会让任何东西变红**（既有双向比对判据只读运行时归一的行为）⇒ 播种出来的规则/主线锚点名字
     * 会与运行期口径**静默分叉**。现改为直接引用 {@link ProductionOperationQueryService#logicalOperationName}
     * 这个**静态入口**（同一份表；调用方无需注入该服务 ⇒ 播种路径不新增依赖，也没有循环依赖）。</p>
     *
     * <p>同款先例：{@code ProductionService} 的读面派生（#4621）也走这个静态入口，而不是另抄一份表。</p>
     *
     * <p>漂移护栏（两道，都不复制映射表）：① 生产 Java 里不得再出现第二份表 ——
     * {@code tests/unit_ci_workflows/test_logical_name_single_source_guard.py}（含注入自证）；
     * ② 本路径的行为等价（播种规则里的工序名 == 静态入口的输出）——
     * {@code ProductionSeedTemplateServiceTest#seedNormalizationMatchesSingleSource}。</p>
     */
    private static String logicalName(String operationName) {
        return ProductionOperationQueryService.logicalOperationName(operationName);
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
                    // 作用域（issue #4529）：`打包` 是**套级**（`set`）—— 缺该列会让新租户把套级工序
                    // 当部位级 ⇒ 一樘「布+纱」双付（#4408 形态）。模板逐条声明，不硬编码工序名。
                    .scope(node.path("scope").asText("position"))
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
