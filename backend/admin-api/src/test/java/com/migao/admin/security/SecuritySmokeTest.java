package com.migao.admin.security;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class SecuritySmokeTest {

    @Test
    void jwtTokenProvider_classExists() {
        assertNotNull(JwtTokenProvider.class);
    }

    @Test
    void jwtAuthenticationFilter_classExists() {
        assertNotNull(JwtAuthenticationFilter.class);
    }

    @Test
    void serviceTokenFilter_classExists() {
        assertNotNull(ServiceTokenFilter.class);
    }

    @Test
    void permissionInterceptor_classExists() {
        assertNotNull(PermissionInterceptor.class);
    }
}
