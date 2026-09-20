package com.migao.admin.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.migao.admin.entity.WorkerReportAudit;
import org.apache.ibatis.annotations.Mapper;

/**
 * 报工身份旁路账 Mapper（V98，issue #4733，**只追加**）。
 */
@Mapper
public interface WorkerReportAuditMapper extends BaseMapper<WorkerReportAudit> {
}
