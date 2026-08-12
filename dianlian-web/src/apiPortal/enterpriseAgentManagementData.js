export async function loadEnterpriseManagementData(dataSource, { canHire }) {
  const agentsPromise = dataSource.listEnterpriseAgents();
  if (!canHire) {
    const agents = await agentsPromise;
    return { templates: [], agents: agents?.items ?? [] };
  }

  const [catalog, agents] = await Promise.all([
    dataSource.listRecruitableVersions(),
    agentsPromise,
  ]);
  return {
    templates: catalog?.items ?? [],
    agents: agents?.items ?? [],
  };
}

export function buildEnterpriseAgentConfigurationPayload(form) {
  return {
    displayNameSnapshot: String(form?.displayName ?? "").trim(),
    profile: String(form?.profile ?? "").trim(),
    enterpriseInstructions: String(form?.enterpriseInstructions ?? "").trim(),
    modelPolicyMode: "PLATFORM_DEFAULT",
    knowledgeScopeMode: "NONE",
    visibilityScope: "TENANT",
  };
}

export async function refreshActivatedEnterpriseAgentViews({ refreshAgents, refreshOffice }) {
  const warnings = [];
  if (!(await refreshAgents())) warnings.push("员工列表刷新失败");
  try {
    await refreshOffice?.();
  } catch {
    warnings.push("办公室刷新失败");
  }
  return warnings;
}
