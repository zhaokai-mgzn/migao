package com.migao.admin.service;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ServiceSmokeTest {
    @Test void quickReplyTemplateExists() { assertNotNull(QuickReplyTemplateService.class); }
    @Test void processingCategoryExists() { assertNotNull(ProcessingCategoryService.class); }
    @Test void agentSessionExists() { assertNotNull(AgentSessionService.class); }
    @Test void authServiceExists() { assertNotNull(AuthService.class); }
    @Test void notificationServiceExists() { assertNotNull(NotificationService.class); }
    @Test void customerServiceExists() { assertNotNull(CustomerService.class); }
    @Test void productServiceExists() { assertNotNull(ProductService.class); }
}
