/**
 * F-0091 slug-based browser-URL builders for e2e specs.
 *
 * Object read/mutation APIs stay UUID-keyed, so each builder fetches the
 * object by id, reads its `slug` (and `project_slug` for nested objects),
 * and assembles the new `/[org]/...` path. The org slug comes from
 * `GET /iam/organizations`.
 */
import { type Page } from '@playwright/test';
import { API_BASE } from './apiBase';

async function authGet(page: Page, path: string): Promise<Record<string, unknown>> {
  const token = await page.evaluate(() => localStorage.getItem('auth_token'));
  const resp = await page.request.fetch(`${API_BASE}${path}`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok()) {
    throw new Error(`GET ${path} failed: ${resp.status()}`);
  }
  return resp.json();
}

/** Slug of the test user's current organization. */
export async function orgSlug(page: Page): Promise<string> {
  const orgs = (await authGet(page, '/iam/organizations')) as unknown as Array<{
    slug: string;
  }>;
  if (!orgs.length) {
    throw new Error('slug-urls: test user has no organizations');
  }
  return orgs[0].slug;
}

export async function projectsUrl(page: Page): Promise<string> {
  return `/${await orgSlug(page)}/projects`;
}

export async function libraryUrl(page: Page): Promise<string> {
  return `/${await orgSlug(page)}/library`;
}

export async function protocolUrl(page: Page, protocolId: string): Promise<string> {
  const [org, proto] = await Promise.all([
    orgSlug(page),
    authGet(page, `/protocols/${protocolId}`),
  ]);
  return `/${org}/protocols/${proto.slug}`;
}

export async function projectUrl(page: Page, projectId: string): Promise<string> {
  const [org, proj] = await Promise.all([
    orgSlug(page),
    authGet(page, `/projects/${projectId}`),
  ]);
  return `/${org}/projects/${proj.slug}`;
}

export async function runUrl(page: Page, runId: string): Promise<string> {
  const [org, run] = await Promise.all([
    orgSlug(page),
    authGet(page, `/runs/${runId}`),
  ]);
  return `/${org}/projects/${run.project_slug}/runs/${run.slug}`;
}

export async function experimentUrl(page: Page, experimentId: string): Promise<string> {
  const [org, exp] = await Promise.all([
    orgSlug(page),
    authGet(page, `/experiments/${experimentId}`),
  ]);
  return `/${org}/projects/${exp.project_slug}/experiments/${exp.slug}`;
}

export async function libraryDocUrl(page: Page, documentId: string): Promise<string> {
  const [org, doc] = await Promise.all([
    orgSlug(page),
    authGet(page, `/library/documents/${documentId}`),
  ]);
  return `/${org}/library/${doc.slug}`;
}
