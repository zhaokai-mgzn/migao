package com.migao.admin.service;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ServiceOtherSmokeTest {
    @Test void wechatServiceExists() { assertNotNull(WechatService.class); }
    @Test void permissionServiceExists() { assertNotNull(PermissionService.class); }
    @Test void roleServiceExists() { assertNotNull(RoleService.class); }
    @Test void ossServiceExists() { assertNotNull(OssService.class); }
}
