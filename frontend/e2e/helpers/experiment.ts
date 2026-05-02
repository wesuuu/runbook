import { type Page } from '@playwright/test';
import { API_BASE } from './apiBase';

export const SEED = {
  PROJECT_MAB_ID: '40000000-0000-0000-0000-000000000001',
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

/** Create an experiment via API */
export async function createExperimentViaApi(
  page: Page,
  name: string,
  projectId: string,
  description?: string,
): Promise<string> {
  const { status, data } = await apiRequest(page, 'POST', '/science/experiments', {
    name,
    project_id: projectId,
    description: description ?? null,
  });
  if (status !== 201) {
    throw new Error(`Failed to create experiment: ${status} ${JSON.stringify(data)}`);
  }
  return data.id as string;
}

/** Create a run via API */
export async function createRunViaApi(
  page: Page,
  name: string,
  projectId: string,
  protocolId: string,
  experimentId?: string,
): Promise<string> {
  const body: Record<string, unknown> = {
    name,
    project_id: projectId,
    protocol_id: protocolId,
  };
  if (experimentId) {
    body.experiment_id = experimentId;
  }
  const { status, data } = await apiRequest(page, 'POST', '/science/runs', body);
  if (status !== 201) {
    throw new Error(`Failed to create run: ${status} ${JSON.stringify(data)}`);
  }
  return data.id as string;
}

/** Get protocols for a project via API */
export async function getProjectProtocols(
  page: Page,
  projectId: string,
): Promise<Array<{ id: string; name: string }>> {
  const { data } = await apiRequest(page, 'GET', `/science/projects/${projectId}/protocols`);
  return data as unknown as Array<{ id: string; name: string }>;
}

/** Force-cleanup: delete experiments and unlink runs via direct API calls */
export async function forceCleanupExperiment(page: Page, experimentId: string): Promise<void> {
  // Unlink all runs first
  const { data: exp } = await apiRequest(page, 'GET', `/science/experiments/${experimentId}`);
  const runs = (exp as any)?.runs ?? [];
  for (const run of runs) {
    await apiRequest(page, 'DELETE', `/science/experiments/${experimentId}/runs/${run.id}`);
  }
  // Hard-delete via API (archive) — we'll use psql in the test for full cleanup
}

/**
 * Clean up all E2E experiments and their runs from the project.
 * Uses the API to list experiments, unlink runs, then archive.
 * Also deletes any E2E-named runs.
 */
export async function cleanupE2eExperiments(
  page: Page,
  projectId: string,
): Promise<void> {
  try {
    // Get all experiments for the project
    const { data: experiments } = await apiRequest(
      page, 'GET', `/science/projects/${projectId}/experiments`,
    );
    const expList = (experiments as unknown as any[]) ?? [];

    for (const exp of expList) {
      if (!exp.name?.startsWith('E2E ')) continue;

      // Get full experiment with runs
      try {
        const { data: full } = await apiRequest(page, 'GET', `/science/experiments/${exp.id}`);
        const runs = ((full as any)?.runs ?? []) as Array<{ id: string }>;

        // Unlink all runs
        for (const run of runs) {
          await apiRequest(page, 'DELETE', `/science/experiments/${exp.id}/runs/${run.id}`);
        }
      } catch {
        // ignore
      }

      // Archive the experiment
      await apiRequest(page, 'DELETE', `/science/experiments/${exp.id}`);
    }

    // Also clean up any standalone E2E runs
    const { data: runs } = await apiRequest(
      page, 'GET', `/science/projects/${projectId}/runs`,
    );
    const runList = (runs as unknown as any[]) ?? [];
    for (const run of runList) {
      if (run.name?.startsWith('E2E ') && run.status !== 'ARCHIVED') {
        await apiRequest(page, 'PUT', `/science/runs/${run.id}`, { status: 'ARCHIVED' });
      }
    }
  } catch {
    // best-effort
  }
}
