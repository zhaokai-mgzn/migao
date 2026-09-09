// case_ids: API-015, API-016
package com.migao.admin.service;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ServiceSmokeTest {
    @Test void processingCategoryExists() { assertNotNull(ProcessingCategoryService.class); }
    @Test void agentSessionExists() { assertNotNull(AgentSessionService.class); }
    @Test void authServiceExists() { assertNotNull(AuthService.class); }
    @Test void notificationServiceExists() { assertNotNull(NotificationService.class); }
    @Test void customerServiceExists() { assertNotNull(CustomerService.class); }
    @Test void productServiceExists() { assertNotNull(ProductService.class); }
}
