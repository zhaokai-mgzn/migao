package com.migao.admin.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.CustomerImportAnalysis;
import com.migao.admin.dto.CustomerImportField;
import com.migao.admin.dto.CustomerImportKey;
import com.migao.admin.dto.CustomerImportReport;
import com.migao.admin.dto.MappingSuggestion;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CustomerProfileMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.multipart.MultipartFile;

import java.text.Normalizer;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;

/**
 * 客户主数据迁移服务（issue #8295）。
 *
 * <p><b>流程</b>：任意表头 Excel → 表头别名 + AI 映射建议 → 人工确认 mapping →
 * 试运行（只读）→ 正式导入（逐行 create/update/skip，externalId 幂等）。</p>
 *
 * <p><b>关键口径</b>：</p>
 * <ul>
 *   <li>主数据逐行部分成功；单行失败不影响其它行，重跑同一份文件按 externalId 收敛；</li>
 *   <li>{@code externalId}（旧系统客户ID）是幂等键，缺它整行报错——没有键就无法保证重跑不重复；</li>
 *   <li>手机号撞**另一个** externalId 的行报错，不静默合并；</li>
 *   <li>试运行绝不写库；正式导入只写客户档案，不碰订单/库存/资金；</li>
 *   <li>日志只记计数，不记客户姓名/手机号/地址。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class CustomerImportService {

    private static final int CHUNK_SIZE = 500;
    private static final Set<String> VIP_LEVELS = Set.of("normal", "vip1", "vip2", "vip3");
    private static final String SOURCE_CHANNEL_MIGRATION = "migration";

    private final CustomerImportParser parser;
    private final CustomerImportAiClient aiClient;
    private final CustomerProfileMapper customerProfileMapper;
    private final CustomerService customerService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    // ==================== 1. 分析（不写库） ====================

    public CustomerImportAnalysis analyze(MultipartFile file) {
        ParsedCustomerSheet sheet = parser.parse(file);
        List<MappingSuggestion> deterministic = deterministicMappings(sheet.headers());
        CustomerImportAiClient.Result ai = aiClient.suggest(
                sheet.headers(), CustomerImportParser.samples(sheet.rows()), CustomerImportFields.ALL);
        List<MappingSuggestion> merged = mergeSuggestions(deterministic, ai, sheet.headers());
        boolean degraded = ai == null || ai.degraded();
        String message = ai == null
                ? "AI 服务暂时不可用，已按表头规则给出建议；请手工确认列映射"
                : ai.message();
        log.info("[customer-import] analyze: tenant={}, headers={}, rows={}, mappings={}, aiDegraded={}",
                TenantContext.getTenantId(), sheet.headers().size(), sheet.totalRows(), merged.size(), degraded);
        return CustomerImportAnalysis.builder()
                .headers(sheet.headers())
                .samples(CustomerImportParser.samples(sheet.rows()))
                .totalRows(sheet.totalRows())
                .fields(CustomerImportFields.ALL)
                .suggestions(merged)
                .aiDegraded(degraded)
                .aiMessage(message == null ? "" : message)
                .build();
    }

    /**
     * 确定性表头别名匹配（不依赖 AI）。AI 不可用/返回垃圾时仍能给出一版建议。
     * 同一 source 只映射一次、同一 target 只映射一次；精确匹配优先于包含匹配。
     */
    private List<MappingSuggestion> deterministicMappings(List<String> headers) {
        Map<String, MappingSuggestion> byTarget = new LinkedHashMap<>();
        Set<Integer> usedSources = new HashSet<>();
        List<String> normalizedHeaders = headers.stream().map(CustomerImportService::normalize).toList();

        // 第一遍：只认**精确表头**。必须先于包含匹配跑，否则 displayName 的泛别名「客户」
        // 会抢走「客户等级 / 客户电话 / 客户备注」这类更具体的列；而更具体字段的精确别名
        // 才是更强证据。同一字段有多个精确候选时取最长别名（更具体）。
        for (CustomerImportField field : CustomerImportFields.ALL) {
            int bestSource = -1;
            int bestAliasLength = -1;
            String bestAlias = null;
            for (int i = 0; i < normalizedHeaders.size(); i++) {
                if (usedSources.contains(i)) {
                    continue;
                }
                String header = normalizedHeaders.get(i);
                if (header.isEmpty()) {
                    continue;
                }
                for (String alias : field.aliases()) {
                    String normalizedAlias = normalize(alias);
                    if (normalizedAlias.isEmpty() || !header.equals(normalizedAlias)) {
                        continue;
                    }
                    if (normalizedAlias.length() > bestAliasLength) {
                        bestAliasLength = normalizedAlias.length();
                        bestSource = i;
                        bestAlias = alias;
                    }
                }
            }
            if (bestSource >= 0) {
                usedSources.add(bestSource);
                byTarget.put(field.key(), new MappingSuggestion(
                        bestSource,
                        headers.get(bestSource),
                        field.key(),
                        0.99,
                        "表头精确匹配「" + bestAlias + "」"
                ));
            }
        }

        // 第二遍：模糊匹配（包含 / 反向包含），只补还没被精确匹配占用的 target/source。
        for (CustomerImportField field : CustomerImportFields.ALL) {
            if (byTarget.containsKey(field.key())) {
                continue;
            }
            int bestSource = -1;
            int bestScore = 0;
            String bestAlias = null;
            boolean exact = false;
            for (int i = 0; i < normalizedHeaders.size(); i++) {
                if (usedSources.contains(i)) {
                    continue;
                }
                String header = normalizedHeaders.get(i);
                if (header.isEmpty()) {
                    continue;
                }
                for (String alias : field.aliases()) {
                    String a = normalize(alias);
                    if (a.isEmpty()) {
                        continue;
                    }
                    int score;
                    boolean isExact;
                    if (header.equals(a)) {
                        score = 1000 + a.length();
                        isExact = true;
                    } else if (header.contains(a)) {
                        score = 100 + a.length();
                        isExact = false;
                    } else if (a.contains(header) && header.length() >= 2) {
                        score = 50 + header.length();
                        isExact = false;
                    } else {
                        continue;
                    }
                    if (score > bestScore) {
                        bestScore = score;
                        bestSource = i;
                        bestAlias = alias;
                        exact = isExact;
                    }
                }
            }
            if (bestSource >= 0) {
                usedSources.add(bestSource);
                byTarget.put(field.key(), new MappingSuggestion(
                        bestSource,
                        headers.get(bestSource),
                        field.key(),
                        exact ? 0.99 : 0.9,
                        "表头" + (exact ? "精确匹配" : "包含") + "「" + bestAlias + "」"
                ));
            }
        }
        return byTarget.values().stream()
                .sorted((a, b) -> Integer.compare(a.sourceIndex(), b.sourceIndex()))
                .toList();
    }

    /** 确定性建议优先；AI 只补未占用的 source/target，非法索引/未知字段丢弃。 */
    private List<MappingSuggestion> mergeSuggestions(List<MappingSuggestion> deterministic,
                                                    CustomerImportAiClient.Result ai,
                                                    List<String> headers) {
        Map<String, MappingSuggestion> byTarget = new LinkedHashMap<>();
        Set<Integer> usedSources = new HashSet<>();
        for (MappingSuggestion s : deterministic) {
            byTarget.put(s.targetField(), s);
            usedSources.add(s.sourceIndex());
        }
        if (ai != null) {
            for (MappingSuggestion s : ai.suggestions()) {
                if (!CustomerImportFields.isSupported(s.targetField())) {
                    continue;
                }
                if (s.sourceIndex() < 0 || s.sourceIndex() >= headers.size()) {
                    continue;
                }
                if (usedSources.contains(s.sourceIndex()) || byTarget.containsKey(s.targetField())) {
                    continue;
                }
                if (s.confidence() < 0.4) {
                    continue;
                }
                double confidence = Math.max(0.0, Math.min(1.0, s.confidence()));
                byTarget.put(s.targetField(), new MappingSuggestion(
                        s.sourceIndex(), headers.get(s.sourceIndex()), s.targetField(), confidence,
                        StringUtils.hasText(s.reason()) ? s.reason() : "AI 建议"));
                usedSources.add(s.sourceIndex());
            }
        }
        return byTarget.values().stream()
                .sorted((a, b) -> Integer.compare(a.sourceIndex(), b.sourceIndex()))
                .toList();
    }

    // ==================== 2. 试运行 / 正式导入 ====================

    public CustomerImportReport preview(MultipartFile file, String mappingJson, boolean updateExisting) {
        ParsedCustomerSheet sheet = parser.parse(file);
        Map<String, Integer> mapping = parseMapping(mappingJson, sheet.headers());
        return evaluate(sheet, mapping, updateExisting, false);
    }

    public CustomerImportReport commit(MultipartFile file, String mappingJson, boolean updateExisting) {
        ParsedCustomerSheet sheet = parser.parse(file);
        Map<String, Integer> mapping = parseMapping(mappingJson, sheet.headers());
        return evaluate(sheet, mapping, updateExisting, true);
    }

    private CustomerImportReport evaluate(ParsedCustomerSheet sheet, Map<String, Integer> mapping,
                                           boolean updateExisting, boolean write) {
        Long tenantId = TenantContext.getTenantId();
        if (tenantId == null) {
            throw BusinessException.validationError("租户上下文缺失，请重新登录");
        }
        List<PreparedRow> rows = prepareRows(sheet, mapping);
        Map<String, String> existingByExternalId = loadExistingByExternalId(tenantId, rows);
        Map<String, String> existingByPhone = loadExistingByPhone(tenantId, rows);

        List<CustomerImportReport.Row> reportRows = new ArrayList<>(rows.size());
        int newCount = 0, updateCount = 0, skipCount = 0, errorCount = 0, warnCount = 0;
        int createdCount = 0, updatedCount = 0, skippedCount = 0, failedCount = 0;

        for (PreparedRow row : rows) {
            String message = row.error;
            String action;
            String customerId = null;
            if (row.error != null) {
                action = write ? "FAILED" : "ERROR";
                if (write) {
                    failedCount++;
                } else {
                    errorCount++;
                }
            } else {
                String existingId = existingByExternalId.get(row.externalId);
                row.existingCustomerId = existingId;
                String phoneOwner = StringUtils.hasText(row.phone) ? existingByPhone.get(row.phone) : null;
                if (phoneOwner != null && !Objects.equals(phoneOwner, existingId)) {
                    action = write ? "FAILED" : "ERROR";
                    message = "手机号已属于另一个客户（ID " + phoneOwner + "），不能静默合并";
                    if (write) {
                        failedCount++;
                    } else {
                        errorCount++;
                    }
                } else if (existingId != null && !updateExisting) {
                    action = write ? "SKIPPED" : "SKIP";
                    message = "已存在（按旧系统客户ID），未更新";
                    customerId = existingId;
                    if (write) {
                        skippedCount++;
                    } else {
                        skipCount++;
                    }
                } else if (existingId != null) {
                    action = write ? "UPDATED" : "UPDATE";
                    customerId = existingId;
                    if (write) {
                        try {
                            customerService.updateCustomer(existingId, toPatch(row));
                            updatedCount++;
                        } catch (Exception e) {
                            action = "FAILED";
                            message = safeMessage(e, "更新失败");
                            failedCount++;
                            customerId = existingId;
                        }
                    } else {
                        updateCount++;
                    }
                } else {
                    action = write ? "CREATED" : "NEW";
                    if (write) {
                        try {
                            CustomerProfile candidate = toCandidate(tenantId, row);
                            CustomerProfileWriter.Result result = CustomerProfileWriter.ensureByExternalId(
                                    customerProfileMapper, candidate, row.externalId);
                            if (result.profile() == null) {
                                action = "FAILED";
                                message = "手机号已被其他客户占用或并发冲突，未写入";
                                failedCount++;
                            } else if (result.created()) {
                                customerId = result.profile().getId();
                                createdCount++;
                            } else {
                                action = "SKIPPED";
                                message = "并发下已存在（按旧系统客户ID），未重复建";
                                customerId = result.profile().getId();
                                skippedCount++;
                            }
                        } catch (Exception e) {
                            action = "FAILED";
                            message = safeMessage(e, "写入失败");
                            failedCount++;
                        }
                    } else {
                        newCount++;
                    }
                }
            }
            if (row.warn && row.error == null && !StringUtils.hasText(row.phone)) {
                warnCount++;
                if (!StringUtils.hasText(message)) {
                    message = "手机号为空（不阻断导入）";
                }
            }
            reportRows.add(CustomerImportReport.Row.builder()
                    .rowNo(row.rowNo)
                    .externalId(row.externalId)
                    .displayName(row.displayName)
                    .phone(row.phone)
                    .action(action)
                    .message(message == null ? "" : message)
                    .customerId(customerId)
                    .build());
        }

        CustomerImportReport report = CustomerImportReport.builder()
                .mode(write ? "commit" : "preview")
                .total(rows.size())
                .newCount(newCount)
                .updateCount(updateCount)
                .skipCount(skipCount)
                .errorCount(errorCount)
                .warnCount(warnCount)
                .createdCount(createdCount)
                .updatedCount(updatedCount)
                .skippedCount(skippedCount)
                .failedCount(failedCount)
                .rows(reportRows)
                .build();
        log.info("[customer-import] {}: tenant={}, total={}, new={}, update={}, skip={}, error={}, "
                        + "created={}, updated={}, skipped={}, failed={}",
                report.getMode(), tenantId, report.getTotal(), newCount, updateCount, skipCount, errorCount,
                createdCount, updatedCount, skippedCount, failedCount);
        return report;
    }

    // ==================== 3. 行准备 / 校验 ====================

    private List<PreparedRow> prepareRows(ParsedCustomerSheet sheet, Map<String, Integer> mapping) {
        List<PreparedRow> rows = new ArrayList<>(sheet.rows().size());
        Map<String, Integer> externalCounts = new HashMap<>();
        Map<String, Set<String>> phoneOwners = new HashMap<>();
        for (int i = 0; i < sheet.rows().size(); i++) {
            List<String> values = sheet.rows().get(i);
            PreparedRow row = new PreparedRow();
            row.rowNo = i + 1;
            row.externalId = value(values, mapping, "externalId");
            row.displayName = value(values, mapping, "displayName");
            row.phone = value(values, mapping, "phone");
            row.province = value(values, mapping, "province");
            row.city = value(values, mapping, "city");
            row.district = value(values, mapping, "district");
            row.address = value(values, mapping, "address");
            row.receiverName = value(values, mapping, "receiverName");
            row.receiverPhone = value(values, mapping, "receiverPhone");
            row.agentNotes = value(values, mapping, "agentNotes");
            String vip = value(values, mapping, "vipLevel");
            row.vipLevel = normalizeVip(vip);
            row.warn = !StringUtils.hasText(row.phone);

            row.error = validate(row, vip);
            if (StringUtils.hasText(row.externalId)) {
                externalCounts.merge(row.externalId, 1, Integer::sum);
            }
            if (StringUtils.hasText(row.phone)) {
                phoneOwners.computeIfAbsent(row.phone, k -> new HashSet<>()).add(row.externalId);
            }
            rows.add(row);
        }
        for (PreparedRow row : rows) {
            if (row.error == null && externalCounts.getOrDefault(row.externalId, 0) > 1) {
                row.error = "旧系统客户ID 在文件内重复，请合并成一行后再导入";
            }
            if (row.error == null && StringUtils.hasText(row.phone)
                    && phoneOwners.getOrDefault(row.phone, Set.of()).size() > 1) {
                row.error = "手机号在文件内被多行使用，请先核对";
            }
        }
        return rows;
    }

    private String validate(PreparedRow row, String rawVip) {
        if (!StringUtils.hasText(row.externalId)) {
            return "缺少旧系统客户ID（externalId，幂等键）";
        }
        if (!StringUtils.hasText(row.displayName)) {
            return "缺少客户名称（displayName）";
        }
        if (tooLong(row.externalId, 128)) {
            return "旧系统客户ID 超过 128 字符";
        }
        if (tooLong(row.displayName, 128)) {
            return "客户名称超过 128 字符";
        }
        if (tooLong(row.phone, 32)) {
            return "手机号超过 32 字符";
        }
        if (tooLong(row.province, 64) || tooLong(row.city, 64) || tooLong(row.district, 64)) {
            return "省/市/区县超过 64 字符";
        }
        if (tooLong(row.receiverName, 100)) {
            return "收货人超过 100 字符";
        }
        if (tooLong(row.receiverPhone, 20)) {
            return "收货电话超过 20 字符";
        }
        if (tooLong(row.address, 2000)) {
            return "地址超过 2000 字符";
        }
        if (tooLong(row.agentNotes, 2000)) {
            return "备注超过 2000 字符";
        }
        if (StringUtils.hasText(rawVip) && row.vipLevel == null) {
            return "客户等级只能是 normal / vip1 / vip2 / vip3";
        }
        return null;
    }

    private static boolean tooLong(String value, int max) {
        return value != null && value.length() > max;
    }

    private static String normalizeVip(String value) {
        if (!StringUtils.hasText(value)) {
            return "normal";
        }
        String normalized = value.trim().toLowerCase(Locale.ROOT);
        return VIP_LEVELS.contains(normalized) ? normalized : null;
    }

    // ==================== 4. 既有客户批量查找 ====================

    private Map<String, String> loadExistingByExternalId(Long tenantId, List<PreparedRow> rows) {
        List<String> ids = rows.stream()
                .map(r -> r.externalId)
                .filter(StringUtils::hasText)
                .distinct()
                .toList();
        Map<String, String> result = new HashMap<>();
        for (List<String> chunk : chunk(ids)) {
            List<CustomerImportKey> keys = customerProfileMapper.findKeysByExternalIds(tenantId, chunk);
            if (keys == null) {
                continue;
            }
            for (CustomerImportKey key : keys) {
                if (key.getExternalId() != null && key.getId() != null) {
                    result.put(key.getExternalId(), key.getId());
                }
            }
        }
        return result;
    }

    private Map<String, String> loadExistingByPhone(Long tenantId, List<PreparedRow> rows) {
        List<String> phones = rows.stream()
                .map(r -> r.phone)
                .filter(StringUtils::hasText)
                .distinct()
                .toList();
        Map<String, String> result = new HashMap<>();
        for (List<String> chunk : chunk(phones)) {
            List<CustomerProfile> existing = customerProfileMapper.selectList(
                    Wrappers.<CustomerProfile>lambdaQuery()
                            .eq(CustomerProfile::getTenantId, tenantId)
                            .in(CustomerProfile::getPhone, chunk));
            if (existing == null) {
                continue;
            }
            for (CustomerProfile profile : existing) {
                if (profile.getPhone() != null && profile.getId() != null) {
                    result.putIfAbsent(profile.getPhone(), profile.getId());
                }
            }
        }
        return result;
    }

    private static <T> List<List<T>> chunk(List<T> source) {
        if (source.isEmpty()) {
            return List.of();
        }
        List<List<T>> chunks = new ArrayList<>();
        for (int i = 0; i < source.size(); i += CHUNK_SIZE) {
            chunks.add(source.subList(i, Math.min(i + CHUNK_SIZE, source.size())));
        }
        return chunks;
    }

    // ==================== 5. 实体构造 ====================

    private CustomerProfile toCandidate(Long tenantId, PreparedRow row) {
        return CustomerProfileWriter.candidate(tenantId)
                .wechatNickname(row.displayName)
                .phone(nullIfBlank(row.phone))
                .regionProvince(nullIfBlank(row.province))
                .regionCity(nullIfBlank(row.city))
                .regionDistrict(nullIfBlank(row.district))
                .defaultReceiverName(nullIfBlank(row.receiverName))
                .defaultReceiverPhone(nullIfBlank(row.receiverPhone))
                .defaultReceiverAddress(nullIfBlank(row.address))
                .vipLevel(row.vipLevel)
                .agentNotes(nullIfBlank(row.agentNotes))
                .sourceChannel(SOURCE_CHANNEL_MIGRATION)
                .build();
    }

    private CustomerProfile toPatch(PreparedRow row) {
        CustomerProfile patch = new CustomerProfile();
        if (StringUtils.hasText(row.displayName)) {
            patch.setWechatNickname(row.displayName);
        }
        if (StringUtils.hasText(row.phone)) {
            patch.setPhone(row.phone);
        }
        if (StringUtils.hasText(row.province)) {
            patch.setRegionProvince(row.province);
        }
        if (StringUtils.hasText(row.city)) {
            patch.setRegionCity(row.city);
        }
        if (StringUtils.hasText(row.district)) {
            patch.setRegionDistrict(row.district);
        }
        if (StringUtils.hasText(row.receiverName)) {
            patch.setDefaultReceiverName(row.receiverName);
        }
        if (StringUtils.hasText(row.receiverPhone)) {
            patch.setDefaultReceiverPhone(row.receiverPhone);
        }
        if (StringUtils.hasText(row.address)) {
            patch.setDefaultReceiverAddress(row.address);
        }
        if (StringUtils.hasText(row.vipLevel)) {
            patch.setVipLevel(row.vipLevel);
        }
        if (StringUtils.hasText(row.agentNotes)) {
            patch.setAgentNotes(row.agentNotes);
        }
        return patch;
    }

    private static String nullIfBlank(String value) {
        return StringUtils.hasText(value) ? value : null;
    }

    // ==================== 6. mapping / 工具 ====================

    private Map<String, Integer> parseMapping(String mappingJson, List<String> headers) {
        if (!StringUtils.hasText(mappingJson)) {
            throw BusinessException.validationError("缺少列映射；请先分析并确认映射");
        }
        Map<String, Integer> raw;
        try {
            raw = objectMapper.readValue(mappingJson, new TypeReference<Map<String, Integer>>() {
            });
        } catch (Exception e) {
            throw BusinessException.validationError("列映射不是合法 JSON");
        }
        if (raw == null || raw.isEmpty()) {
            throw BusinessException.validationError("列映射为空");
        }
        Map<String, Integer> mapping = new LinkedHashMap<>();
        Set<Integer> usedSources = new HashSet<>();
        for (Map.Entry<String, Integer> entry : raw.entrySet()) {
            String target = entry.getKey();
            Integer source = entry.getValue();
            if (!CustomerImportFields.isSupported(target)) {
                throw BusinessException.validationError("未知目标字段：" + target);
            }
            if (source == null || source < 0 || source >= headers.size()) {
                throw BusinessException.validationError("列映射下标越界：" + target);
            }
            if (!usedSources.add(source)) {
                throw BusinessException.validationError("同一源列不能映射到多个目标字段");
            }
            mapping.put(target, source);
        }
        for (CustomerImportField field : CustomerImportFields.ALL) {
            if (field.required() && !mapping.containsKey(field.key())) {
                throw BusinessException.validationError("缺少必填字段映射：" + field.label() + "（" + field.key() + "）");
            }
        }
        return mapping;
    }

    private static String value(List<String> row, Map<String, Integer> mapping, String key) {
        Integer index = mapping.get(key);
        if (index == null || index < 0 || index >= row.size()) {
            return "";
        }
        String value = row.get(index);
        return value == null ? "" : value.trim();
    }

    private static String safeMessage(Exception e, String fallback) {
        String message = e.getMessage();
        if (!StringUtils.hasText(message)) {
            return fallback;
        }
        return message.length() > 200 ? message.substring(0, 200) : message;
    }

    private static String normalize(String value) {
        if (!StringUtils.hasText(value)) {
            return "";
        }
        String normalized = Normalizer.normalize(value.trim(), Normalizer.Form.NFKC)
                .toLowerCase(Locale.ROOT);
        return normalized.replaceAll("[\\s_\\-—（）()\\[\\]【】:：*/,，.。]+", "");
    }

    /** 一行的解析/校验中间态；只在本次请求内使用。 */
    private static final class PreparedRow {
        int rowNo;
        String externalId;
        String displayName;
        String phone;
        String province;
        String city;
        String district;
        String address;
        String receiverName;
        String receiverPhone;
        String vipLevel;
        String agentNotes;
        boolean warn;
        String error;
        String existingCustomerId;
    }
}
