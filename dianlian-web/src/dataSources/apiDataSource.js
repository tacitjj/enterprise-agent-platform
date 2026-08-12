import { officeApi } from "../api/officeApi.js";
import { employeeApi } from "../api/employeeApi.js";
import { sessionApi } from "../api/sessionApi.js";
import { taskApi } from "../api/taskApi.js";
import { authApi } from "../api/authApi.js";
import { employeeManagementApi } from "../api/employeeManagementApi.js";
import { conversationApi } from "../api/conversationApi.js";
import { modelManagementApi } from "../api/modelManagementApi.js";

export function createApiDataSource({
  session = sessionApi,
  office = officeApi,
  employees = employeeApi,
  tasks = taskApi,
  authentication = authApi,
  employeeManagement = employeeManagementApi,
  conversations = conversationApi,
  modelManagement = modelManagementApi,
} = {}) {
  return Object.freeze({
    mode: "api",
    getSession: (options) => session.getSession(options),
    login: (credentials, options) => authentication.login(credentials, options),
    logout: (options) => authentication.logout(options),
    getOfficeSnapshot: (options) => office.getOfficeSnapshot(options),
    getEmployeeWorkspace: (agentId, options) => employees.getEmployeeWorkspace(agentId, options),
    prepareCreateTask: (payload, options) => tasks.prepareCreateTask(payload, options),
    createTask: (payload, options) => tasks.createTask(payload, options),
    getTask: (taskId, options) => tasks.getTask(taskId, options),
    openTaskEvents: (taskId, options) => tasks.openTaskEvents(taskId, options),
    readTaskEvents: (taskId, options) => tasks.readTaskEvents(taskId, options),
    listPlatformVersions: (options) => employeeManagement.listPlatformVersions(options),
    publishPlatformVersion: (payload, options) => employeeManagement.publishPlatformVersion(payload, options),
    listRecruitableVersions: (options) => employeeManagement.listRecruitableVersions(options),
    listEnterpriseAgents: (options) => employeeManagement.listEnterpriseAgents(options),
    getEnterpriseAgent: (agentId, options) => employeeManagement.getEnterpriseAgent(agentId, options),
    hireEnterpriseAgent: (payload, options) => employeeManagement.hireEnterpriseAgent(payload, options),
    createEnterpriseAgentConfigurationVersion: (agentId, payload, options) => employeeManagement.createEnterpriseAgentConfigurationVersion(agentId, payload, options),
    activateEnterpriseAgent: (agentId, payload, options) => employeeManagement.activateEnterpriseAgent(agentId, payload, options),
    listConversations: (options) => conversations.listConversations(options),
    createConversation: (payload, options) => conversations.createConversation(payload, options),
    listConversationMessages: (conversationId, options) => conversations.listConversationMessages(conversationId, options),
    sendConversationMessage: (conversationId, payload, options) => conversations.sendConversationMessage(conversationId, payload, options),
    listModelDefinitions: (options) => modelManagement.listModelDefinitions(options),
    listPlatformDefaultRoutes: (options) => modelManagement.listPlatformDefaultRoutes(options),
    registerModelDefinition: (payload, options) => modelManagement.registerModelDefinition(payload, options),
    setPlatformDefaultRoute: (capabilityType, payload, options) => modelManagement.setPlatformDefaultRoute(capabilityType, payload, options),
  });
}

export const apiDataSource = createApiDataSource();
