import { type Page } from '@playwright/test';
import { API_BASE } from './apiBase';

/** Well-known seed IDs from backend/app/db/seed.py */
export const SEED = {
  PROJECT_MAB_ID: '40000000-0000-0000-0000-000000000001',
  PROJECT_VACCINE_ID: '40000000-0000-0000-0000-000000000002',
} as const;

/**
 * Authenticated API helper — reads auth token from page localStorage.
 */
async function apiRequest(
  page: Page,
  method: string,
  path: string,
  body?: Record<string, unknown>,
): Promise<{ status: number; data: Record<string, unknown> }> {
  const token = await page.evaluate(() => localStorage.getItem('auth_token'));
  const options: Parameters<Page['request']['fetch']>[1] = {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  };
  if (body !== undefined) {
    options.data = body;
  }
  const resp = await page.request.fetch(`${API_BASE}${path}`, options);
  let data: Record<string, unknown> = {};
  try {
    data = await resp.json();
  } catch {
    // some endpoints return no body
  }
  return { status: resp.status(), data };
}

/** Create a protocol via the API and return its full response. */
export async function createProtocolViaApi(
  page: Page,
  projectId: string,
  name: string,
): Promise<Record<string, unknown>> {
  const { status, data } = await apiRequest(page, 'POST', '/protocols', {
    name,
    project_id: projectId,
    description: '',
  });
  if (status !== 200 && status !== 201) {
    throw new Error(`Failed to create protocol "${name}": ${status} ${JSON.stringify(data)}`);
  }
  return data;
}

/** Fetch a protocol by ID. */
export async function getProtocolViaApi(
  page: Page,
  protocolId: string,
): Promise<Record<string, unknown>> {
  const { status, data } = await apiRequest(page, 'GET', `/protocols/${protocolId}`);
  if (status !== 200) {
    throw new Error(`Failed to get protocol ${protocolId}: ${status}`);
  }
  return data;
}

/** Fetch a protocol by slug within the caller's current org. */
export async function getProtocolBySlugViaApi(
  page: Page,
  slug: string,
): Promise<Record<string, unknown>> {
  const { status, data } = await apiRequest(
    page,
    'GET',
    `/protocols/by-slug/${slug}`,
  );
  if (status !== 200) {
    throw new Error(`Failed to get protocol by slug ${slug}: ${status}`);
  }
  return data;
}

/** Update a protocol's graph via the API. */
export async function updateProtocolGraph(
  page: Page,
  protocolId: string,
  graph: Record<string, unknown>,
  saveDraft = false,
): Promise<Record<string, unknown>> {
  const qs = saveDraft ? '?save_as_draft=true' : '';
  const { status, data } = await apiRequest(
    page,
    'PUT',
    `/protocols/${protocolId}${qs}`,
    { graph },
  );
  if (status !== 200) {
    throw new Error(`Failed to update protocol graph: ${status} ${JSON.stringify(data)}`);
  }
  return data;
}

/** Submit a protocol for approval via API. */
export async function submitForApprovalViaApi(
  page: Page,
  protocolId: string,
): Promise<Record<string, unknown>> {
  const { status, data } = await apiRequest(
    page,
    'POST',
    `/protocols/${protocolId}/submit-for-approval`,
  );
  if (status !== 200) {
    throw new Error(`Failed to submit for approval: ${status} ${JSON.stringify(data)}`);
  }
  return data;
}

/** Approve a protocol via API. */
export async function approveProtocolViaApi(
  page: Page,
  protocolId: string,
  comment = '',
): Promise<Record<string, unknown>> {
  const { status, data } = await apiRequest(
    page,
    'POST',
    `/protocols/${protocolId}/approve`,
    { comment },
  );
  if (status !== 200) {
    throw new Error(`Failed to approve: ${status} ${JSON.stringify(data)}`);
  }
  return data;
}

/** Reject a protocol via API. */
export async function rejectProtocolViaApi(
  page: Page,
  protocolId: string,
  comment = '',
): Promise<Record<string, unknown>> {
  const { status, data } = await apiRequest(
    page,
    'POST',
    `/protocols/${protocolId}/reject`,
    { comment },
  );
  if (status !== 200) {
    throw new Error(`Failed to reject: ${status} ${JSON.stringify(data)}`);
  }
  return data;
}

/** Unarchive a protocol via API. */
export async function unarchiveProtocolViaApi(
  page: Page,
  protocolId: string,
): Promise<void> {
  const { status, data } = await apiRequest(
    page,
    'PUT',
    `/protocols/${protocolId}/unarchive`,
  );
  if (status !== 200) {
    throw new Error(`Failed to unarchive: ${status} ${JSON.stringify(data)}`);
  }
}

/** Delete a protocol via API (hard delete if empty graph + no runs, else archives). */
export async function deleteProtocolViaApi(
  page: Page,
  protocolId: string,
): Promise<{ action: string }> {
  const { status, data } = await apiRequest(
    page,
    'DELETE',
    `/protocols/${protocolId}`,
  );
  if (status !== 200) {
    throw new Error(`Failed to delete protocol: ${status} ${JSON.stringify(data)}`);
  }
  return data as { action: string };
}

/**
 * Force-cleanup a protocol regardless of its current state.
 * Resets status → clears graph → hard deletes.
 * Safe to call even if protocol no longer exists.
 */
export async function forceCleanupProtocol(
  page: Page,
  protocolId: string,
): Promise<void> {
  try {
    // 1. Fetch current status
    const proto = await getProtocolViaApi(page, protocolId);
    const status = proto.status as string;

    // 2. Reset to DRAFT if needed
    if (status === 'PENDING_APPROVAL') {
      await rejectProtocolViaApi(page, protocolId, 'E2E cleanup');
    } else if (status === 'ARCHIVED') {
      await unarchiveProtocolViaApi(page, protocolId);
    }

    // 3. Clear graph so hard delete is possible (also reverts APPROVED → DRAFT)
    await updateProtocolGraph(page, protocolId, {
      nodes: [],
      edges: [],
      layout: 'horizontal',
      handleOrientation: 'horizontal',
    });

    // 4. Hard delete (empty graph + no runs = hard delete)
    await deleteProtocolViaApi(page, protocolId);
  } catch {
    // Protocol may already be deleted or in an unexpected state — ignore
  }
}

/** Update a project's settings JSONB. */
export async function updateProjectSettings(
  page: Page,
  projectId: string,
  settings: Record<string, unknown>,
): Promise<void> {
  const { status, data } = await apiRequest(
    page,
    'PUT',
    `/projects/${projectId}`,
    { settings },
  );
  if (status !== 200) {
    throw new Error(`Failed to update project settings: ${status} ${JSON.stringify(data)}`);
  }
}

/** Create a protocol role via API. */
export async function createRoleViaApi(
  page: Page,
  protocolId: string,
  name: string,
  color: string,
): Promise<Record<string, unknown>> {
  const { status, data } = await apiRequest(
    page,
    'POST',
    `/protocols/${protocolId}/roles`,
    { name, color, sort_order: 0 },
  );
  if (status !== 200 && status !== 201) {
    throw new Error(`Failed to create role: ${status} ${JSON.stringify(data)}`);
  }
  return data;
}

/**
 * Build a minimal graph with N unit-op nodes for testing.
 * Returns the graph object and the node IDs.
 */
export function buildTestGraph(nodeCount: number): {
  graph: Record<string, unknown>;
  nodeIds: string[];
} {
  const nodeIds: string[] = [];
  const nodes: Array<Record<string, unknown>> = [];
  const processStartId = `e2e-ps-${Date.now()}`;
  nodes.push({
    id: processStartId,
    type: 'processStart',
    position: { x: 50, y: 200 },
    data: { label: 'Process Start' },
  });
  for (let i = 0; i < nodeCount; i++) {
    const id = `e2e-node-${i}-${Date.now()}`;
    nodeIds.push(id);
    nodes.push({
      id,
      type: 'unitOp',
      position: { x: 200 + i * 250, y: 200 },
      data: {
        label: `Test Step ${i + 1}`,
        unitOpId: null,
        category: 'Analytics',
        duration_min: 30,
        params: {},
        paramSchema: { properties: {} },
      },
    });
  }

  const edges: Array<Record<string, string>> = [];
  if (nodeIds.length > 0) {
    edges.push({
      id: `e2e-edge-ps-${Date.now()}`,
      source: processStartId,
      target: nodeIds[0],
    });
  }
  for (let i = 0; i < nodeCount - 1; i++) {
    edges.push({
      id: `e2e-edge-${i}-${Date.now()}`,
      source: nodeIds[i],
      target: nodeIds[i + 1],
    });
  }

  return {
    graph: {
      nodes,
      edges,
      layout: 'horizontal',
      handleOrientation: 'horizontal',
      timeEnabled: false,
      pixelsPerHour: 100,
    },
    nodeIds,
  };
}
