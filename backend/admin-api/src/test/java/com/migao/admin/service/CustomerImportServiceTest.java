// case_ids: MIG-003, MIG-004, MIG-005, MIG-006

package com.migao.admin.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.migao.admin.config.TenantContext;
import com.migao.admin.dto.CustomerImportAnalysis;
import com.migao.admin.dto.CustomerImportKey;
import com.migao.admin.dto.CustomerImportReport;
import com.migao.admin.dto.MappingSuggestion;
import com.migao.admin.entity.CustomerProfile;
import com.migao.admin.exception.BusinessException;
import com.migao.admin.mapper.CustomerProfileMapper;
import org.apache.poi.ss.usermodel.Row;
import org.apache.poi.ss.usermodel.Sheet;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.mock.web.MockMultipartFile;

import java.io.ByteArrayOutputStream;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 客户主数据迁移服务（issue #8295）。
 *
 * <p>判据面：任意表头分析（AI 缺失时确定性兜底）、试运行零写入、externalId 幂等、
 * updateExisting 可控更新、手机号冲突不静默合并、mapping 非法显式 422。</p>
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class CustomerImportServiceTest {

    private static final ObjectMapper JSON = new ObjectMapper();

    @Mock
    private CustomerImportAiClient aiClient;

    @Mock
    private CustomerProfileMapper customerProfileMapper;

    @Mock
    private CustomerService customerService;

    private CustomerImportService service;

    @BeforeEach
    void setUp() {
        service = new CustomerImportService(new CustomerImportParser(), aiClient,
                customerProfileMapper, customerService);
        TenantContext.setTenantId(1L);
        when(customerProfileMapper.findKeysByExternalIds(anyLong(), anyList())).thenReturn(List.of());
        when(customerProfileMapper.selectList(any())).thenReturn(List.of());
    }

    @AfterEach
    void tearDown() {
        TenantContext.clear();
    }

    // ==================== analyze ====================

    @Test
    void analyzeFallsBackToDeterministicWhenAiUnavailable() throws Exception {
        when(aiClient.suggest(anyList(), anyList(), anyList())).thenReturn(null);
        MockMultipartFile file = xlsx(
                List.of("客户编号", "客户名称", "手机号", "地址"),
                List.of(List.of("C001", "张三布行", "13800138000", "绍兴市柯桥区")));

        CustomerImportAnalysis analysis = service.analyze(file);

        assertThat(analysis.isAiDegraded()).isTrue();
        assertThat(analysis.getSuggestions()).extracting(MappingSuggestion::targetField)
                .contains("externalId", "displayName", "phone", "address");
        assertThat(analysis.getTotalRows()).isEqualTo(1);
        assertThat(analysis.getSamples()).hasSize(1);
        verify(customerProfileMapper, never()).insertIgnoreByExternalId(any(), anyString());
    }

    @Test
    void analyzeUsesAiForUnknownHeaders() throws Exception {
        when(aiClient.suggest(anyList(), anyList(), anyList())).thenReturn(
                new CustomerImportAiClient.Result(List.of(
                        new MappingSuggestion(0, "往来单位", "displayName", 0.95, "AI"),
                        new MappingSuggestion(1, "联络", "phone", 0.9, "AI"),
                        new MappingSuggestion(2, "落脚点", "address", 0.9, "AI"),
                        new MappingSuggestion(9, "越界", "externalId", 0.9, "AI"),
                        new MappingSuggestion(0, "重复源", "agentNotes", 0.9, "AI"),
                        new MappingSuggestion(1, "未知目标", "noSuchField", 0.9, "AI")
                ), false, ""));
        MockMultipartFile file = xlsx(
                List.of("往来单位", "联络", "落脚点"),
                List.of(List.of("张三布行", "13800138000", "绍兴市柯桥区")));

        CustomerImportAnalysis analysis = service.analyze(file);

        assertThat(analysis.isAiDegraded()).isFalse();
        assertThat(analysis.getSuggestions()).extracting(MappingSuggestion::targetField)
                .containsExactly("displayName", "phone", "address");
    }

    @Test
    void analyzePrefersSpecificAliasOverGenericCustomerAlias() throws Exception {
        when(aiClient.suggest(anyList(), anyList(), anyList())).thenReturn(null);
        MockMultipartFile file = xlsx(
                List.of("客户等级", "客户电话", "客户备注"),
                List.of(List.of("vip1", "13800138000", "老客户")));

        CustomerImportAnalysis analysis = service.analyze(file);

        assertThat(analysis.getSuggestions()).extracting(MappingSuggestion::targetField)
                .containsExactly("vipLevel", "phone", "agentNotes");
        assertThat(analysis.getSuggestions()).extracting(MappingSuggestion::targetField)
                .doesNotContain("displayName");
    }

    // ==================== preview ====================

    @Test
    void previewNeverWrites() throws Exception {
        MockMultipartFile file = xlsx(
                List.of("客户编号", "客户名称", "手机号", "地址"),
                List.of(List.of("C001", "张三布行", "13800138000", "绍兴市柯桥区")));

        CustomerImportReport report = service.preview(file, mapping(), false);

        assertThat(report.getMode()).isEqualTo("preview");
        assertThat(report.getNewCount()).isEqualTo(1);
        assertThat(report.getRows()).hasSize(1);
        assertThat(report.getRows().get(0).getAction()).isEqualTo("NEW");
        verify(customerProfileMapper, never()).insertIgnoreByExternalId(any(), anyString());
        verify(customerService, never()).updateCustomer(anyString(), any());
    }

    @Test
    void previewRejectsMissingExternalIdAndDuplicateExternalId() throws Exception {
        MockMultipartFile missing = xlsx(
                List.of("客户编号", "客户名称"),
                List.of(List.of("", "张三布行")));
        CustomerImportReport missingReport = service.preview(missing, mapping2(), false);
        assertThat(missingReport.getErrorCount()).isEqualTo(1);
        assertThat(missingReport.getRows().get(0).getMessage()).contains("旧系统客户ID");

        MockMultipartFile duplicate = xlsx(
                List.of("客户编号", "客户名称"),
                List.of(List.of("C001", "张三布行"), List.of("C001", "李四纺织")));
        CustomerImportReport duplicateReport = service.preview(duplicate, mapping2(), false);
        assertThat(duplicateReport.getErrorCount()).isEqualTo(2);
        assertThat(duplicateReport.getRows()).allMatch(r -> r.getMessage().contains("重复"));
        verify(customerProfileMapper, never()).insertIgnoreByExternalId(any(), anyString());
    }

    @Test
    void previewRejectsPhoneBelongingToAnotherCustomer() throws Exception {
        when(customerProfileMapper.selectList(any())).thenReturn(List.of(
                CustomerProfile.builder().id("other-customer").phone("13800138000").build()));
        MockMultipartFile file = xlsx(
                List.of("客户编号", "客户名称", "手机号"),
                List.of(List.of("C001", "张三布行", "13800138000")));

        CustomerImportReport report = service.preview(file, mapping3(), false);

        assertThat(report.getErrorCount()).isEqualTo(1);
        assertThat(report.getRows().get(0).getMessage()).contains("手机号");
        verify(customerProfileMapper, never()).insertIgnoreByExternalId(any(), anyString());
    }

    @Test
    void previewRejectsDuplicatePhoneWithinFile() throws Exception {
        MockMultipartFile file = xlsx(
                List.of("客户编号", "客户名称", "手机号"),
                List.of(List.of("C001", "张三布行", "13800138000"),
                        List.of("C002", "李四纺织", "13800138000")));

        CustomerImportReport report = service.preview(file, mapping3(), false);

        assertThat(report.getErrorCount()).isEqualTo(2);
        assertThat(report.getRows()).allMatch(r -> r.getMessage().contains("手机号"));
    }

    @Test
    void previewRejectsInvalidVipLevel() throws Exception {
        MockMultipartFile file = xlsx(
                List.of("客户编号", "客户名称", "客户等级"),
                List.of(List.of("C001", "张三布行", "钻石")));
        String mapping = JSON.writeValueAsString(Map.of(
                "externalId", 0, "displayName", 1, "vipLevel", 2));

        CustomerImportReport report = service.preview(file, mapping, false);

        assertThat(report.getErrorCount()).isEqualTo(1);
        assertThat(report.getRows().get(0).getMessage()).contains("客户等级");
    }

    @Test
    void previewLooksUpUnderCurrentTenant() throws Exception {
        TenantContext.setTenantId(42L);
        MockMultipartFile file = xlsx(
                List.of("客户编号", "客户名称", "手机号"),
                List.of(List.of("C001", "张三布行", "13800138000")));

        service.preview(file, mapping3(), false);

        verify(customerProfileMapper).findKeysByExternalIds(eq(42L), anyList());
        verify(customerProfileMapper).selectList(any());
    }

    // ==================== commit / idempotency ====================

    @Test
    void commitCreatesWithExternalIdAndCanonicalFields() throws Exception {
        when(customerProfileMapper.findFirstByExternalId(1L, "C001")).thenReturn(null);
        when(customerProfileMapper.insertIgnoreByExternalId(any(), eq("C001"))).thenReturn(1);
        MockMultipartFile file = xlsx(
                List.of("客户编号", "客户名称", "手机号", "地址"),
                List.of(List.of("C001", "张三布行", "13800138000", "绍兴市柯桥区")));

        CustomerImportReport report = service.commit(file, mapping(), false);

        assertThat(report.getCreatedCount()).isEqualTo(1);
        assertThat(report.getRows().get(0).getAction()).isEqualTo("CREATED");
        ArgumentCaptor<CustomerProfile> captor = ArgumentCaptor.forClass(CustomerProfile.class);
        verify(customerProfileMapper).insertIgnoreByExternalId(captor.capture(), eq("C001"));
        CustomerProfile created = captor.getValue();
        assertThat(created.getTenantId()).isEqualTo(1L);
        assertThat(created.getWechatNickname()).isEqualTo("张三布行");
        assertThat(created.getPhone()).isEqualTo("13800138000");
        assertThat(created.getDefaultReceiverAddress()).isEqualTo("绍兴市柯桥区");
        assertThat(created.getSourceChannel()).isEqualTo("migration");
        assertThat(created.getVipLevel()).isEqualTo("normal");
    }

    @Test
    void rerunSkipsExistingByExternalId() throws Exception {
        when(customerProfileMapper.findKeysByExternalIds(anyLong(), anyList()))
                .thenReturn(List.of(key("C001", "cust-1")));
        MockMultipartFile file = xlsx(
                List.of("客户编号", "客户名称"),
                List.of(List.of("C001", "张三布行")));

        CustomerImportReport report = service.commit(file, mapping2(), false);

        assertThat(report.getSkippedCount()).isEqualTo(1);
        assertThat(report.getRows().get(0).getAction()).isEqualTo("SKIPPED");
        assertThat(report.getRows().get(0).getCustomerId()).isEqualTo("cust-1");
        verify(customerProfileMapper, never()).insertIgnoreByExternalId(any(), anyString());
        verify(customerService, never()).updateCustomer(anyString(), any());
    }

    @Test
    void rerunWithUpdateExistingUpdatesInsteadOfCreating() throws Exception {
        when(customerProfileMapper.findKeysByExternalIds(anyLong(), anyList()))
                .thenReturn(List.of(key("C001", "cust-1")));
        when(customerService.updateCustomer(eq("cust-1"), any())).thenReturn(
                CustomerProfile.builder().id("cust-1").build());
        MockMultipartFile file = xlsx(
                List.of("客户编号", "客户名称", "手机号"),
                List.of(List.of("C001", "张三布行", "13800138000")));

        CustomerImportReport report = service.commit(file, mapping3(), true);

        assertThat(report.getUpdatedCount()).isEqualTo(1);
        assertThat(report.getRows().get(0).getAction()).isEqualTo("UPDATED");
        ArgumentCaptor<CustomerProfile> captor = ArgumentCaptor.forClass(CustomerProfile.class);
        verify(customerService).updateCustomer(eq("cust-1"), captor.capture());
        assertThat(captor.getValue().getWechatNickname()).isEqualTo("张三布行");
        assertThat(captor.getValue().getPhone()).isEqualTo("13800138000");
        verify(customerProfileMapper, never()).insertIgnoreByExternalId(any(), anyString());
    }

    @Test
    void commitRejectsPhoneConflictWithoutWriting() throws Exception {
        when(customerProfileMapper.selectList(any())).thenReturn(List.of(
                CustomerProfile.builder().id("other-customer").phone("13800138000").build()));
        MockMultipartFile file = xlsx(
                List.of("客户编号", "客户名称", "手机号"),
                List.of(List.of("C001", "张三布行", "13800138000")));

        CustomerImportReport report = service.commit(file, mapping3(), false);

        assertThat(report.getFailedCount()).isEqualTo(1);
        assertThat(report.getRows().get(0).getAction()).isEqualTo("FAILED");
        verify(customerProfileMapper, never()).insertIgnoreByExternalId(any(), anyString());
    }

    // ==================== mapping ====================

    @Test
    void invalidMappingIsRejectedBeforeAnyWrite() throws Exception {
        MockMultipartFile file = xlsx(List.of("客户编号", "客户名称"),
                List.of(List.of("C001", "张三布行")));

        assertThatThrownBy(() -> service.preview(file, "{\"externalId\":0}", false))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("客户名称");
        assertThatThrownBy(() -> service.preview(file, "{\"externalId\":0,\"displayName\":9}", false))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("越界");
        assertThatThrownBy(() -> service.preview(file, "{\"externalId\":0,\"displayName\":0}", false))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("同一源列");
        assertThatThrownBy(() -> service.preview(file, "{\"externalId\":0,\"displayName\":1,\"unknown\":0}", false))
                .isInstanceOf(BusinessException.class)
                .hasMessageContaining("未知目标字段");
        verify(customerProfileMapper, never()).insertIgnoreByExternalId(any(), anyString());
    }

    // ==================== helpers ====================

    private static String mapping() throws Exception {
        return JSON.writeValueAsString(Map.of(
                "externalId", 0, "displayName", 1, "phone", 2, "address", 3));
    }

    private static String mapping2() throws Exception {
        return JSON.writeValueAsString(Map.of("externalId", 0, "displayName", 1));
    }

    private static String mapping3() throws Exception {
        return JSON.writeValueAsString(Map.of("externalId", 0, "displayName", 1, "phone", 2));
    }

    private static CustomerImportKey key(String externalId, String id) {
        CustomerImportKey key = new CustomerImportKey();
        key.setExternalId(externalId);
        key.setId(id);
        return key;
    }

    private static MockMultipartFile xlsx(List<String> headers, List<List<String>> rows) throws Exception {
        try (XSSFWorkbook workbook = new XSSFWorkbook(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            Sheet sheet = workbook.createSheet("客户");
            Row header = sheet.createRow(0);
            for (int i = 0; i < headers.size(); i++) {
                header.createCell(i).setCellValue(headers.get(i));
            }
            for (int r = 0; r < rows.size(); r++) {
                Row row = sheet.createRow(r + 1);
                for (int c = 0; c < headers.size(); c++) {
                    List<String> values = rows.get(r);
                    row.createCell(c).setCellValue(c < values.size() ? values.get(c) : "");
                }
            }
            workbook.write(out);
            return new MockMultipartFile("file", "customers.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", out.toByteArray());
        }
    }
}
