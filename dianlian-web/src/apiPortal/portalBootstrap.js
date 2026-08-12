import { mapOfficeSnapshotResponse, mapSessionResponse } from "./adapters.js";
import { MODEL_PERMISSIONS } from "./modelManagementAdapters.js";

export const PLATFORM_TEMPLATE_READ_PERMISSION = "platform.employee.template.read";
export const PLATFORM_TEMPLATE_PUBLISH_PERMISSION = "platform.employee.template.publish";
export const ENTERPRISE_EMPLOYEE_READ_PERMISSION = "enterprise.employee.read";
export const ENTERPRISE_EMPLOYEE_MANAGEMENT_PERMISSIONS = Object.freeze([
  "enterprise.employee.hire",
  "enterprise.employee.configure",
  "enterprise.employee.activate",
]);

export function canAccessEnterpriseEmployeeManagement(permissions = []) {
  return permissions.includes(ENTERPRISE_EMPLOYEE_READ_PERMISSION)
    && ENTERPRISE_EMPLOYEE_MANAGEMENT_PERMISSIONS.some((permission) => permissions.includes(permission));
}

export function resolvePortalSessionScope(session) {
  if (session.tenant) return "tenant";
  if (session.permissions.includes(PLATFORM_TEMPLATE_READ_PERMISSION)
      || session.permissions.includes(MODEL_PERMISSIONS.READ)) return "platform";
  return "no-tenant";
}

export async function loadPortalBootstrap(dataSource, {
  isActive = () => true,
  onTenantSession = () => {},
} = {}) {
  const session = mapSessionResponse(await dataSource.getSession());
  if (!isActive()) return null;

  const scope = resolvePortalSessionScope(session);
  if (scope === "platform") {
    return { phase: "ready", session, office: null, officeEtag: null, error: null };
  }
  if (scope === "no-tenant") {
    return { phase: "no-tenant", session, office: null, officeEtag: null, error: null };
  }

  onTenantSession(session);
  const officeResponse = await dataSource.getOfficeSnapshot();
  if (!isActive()) return null;
  if (officeResponse.notModified || !officeResponse.snapshot) {
    throw new Error("Initial office request returned no snapshot");
  }
  return {
    phase: "ready",
    session,
    office: mapOfficeSnapshotResponse(officeResponse.snapshot),
    officeEtag: officeResponse.etag,
    error: null,
  };
}
