// case_ids: MIG-004

package com.migao.admin.service;

import com.migao.admin.dto.CustomerImportField;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 客户迁移 canonical 字段目录（issue #8295）：必填字段、唯一 key、常见旧 ERP 别名。
 */
class CustomerImportFieldsTest {

    @Test
    void onlyExternalIdAndDisplayNameAreRequired() {
        assertThat(CustomerImportFields.ALL.stream()
                .filter(CustomerImportField::required)
                .map(CustomerImportField::key)
                .toList())
                .containsExactly("externalId", "displayName");
    }

    @Test
    void keysAreUniqueAndLookupWorks() {
        assertThat(CustomerImportFields.ALL).extracting(CustomerImportField::key).doesNotHaveDuplicates();
        assertThat(CustomerImportFields.byKey("phone")).isPresent();
        assertThat(CustomerImportFields.byKey("noSuchField")).isEmpty();
        assertThat(CustomerImportFields.isSupported("agentNotes")).isTrue();
        assertThat(CustomerImportFields.isSupported("creditLimit")).isFalse();
    }

    @Test
    void specificOldErpAliasesCoverCustomerPhoneLevelAndNotes() {
        assertThat(alias("phone")).contains("客户电话", "联系方式", "手机号");
        assertThat(alias("vipLevel")).contains("客户等级");
        assertThat(alias("agentNotes")).contains("客户备注");
        assertThat(alias("address")).contains("客户地址", "送货地点");
    }

    private static List<String> alias(String key) {
        return CustomerImportFields.byKey(key).orElseThrow().aliases();
    }
}
