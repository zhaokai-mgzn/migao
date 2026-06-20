package com.migao.admin.controller;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class ControllerSmokeTest {
    @Test void notificationControllerExists() { assertNotNull(NotificationController.class); }
    @Test void registrationControllerExists() { assertNotNull(RegistrationController.class); }
    @Test void processingCategoryControllerExists() { assertNotNull(ProcessingCategoryController.class); }
    @Test void quickReplyControllerExists() { assertNotNull(QuickReplyController.class); }
    @Test void agentSessionControllerExists() { assertNotNull(AgentSessionController.class); }
    @Test void uploadControllerExists() { assertNotNull(UploadController.class); }
    @Test void knowledgeControllerExists() { assertNotNull(KnowledgeController.class); }
    @Test void authControllerExists() { assertNotNull(AuthController.class); }
}
