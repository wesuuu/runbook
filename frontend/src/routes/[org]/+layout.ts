import { error } from '@sveltejs/kit';
import {
  ensureInitialized,
  getCurrentOrg,
  getOrgs,
  switchOrg,
} from '$lib/auth.svelte';
import { resolveOrgSlug } from '$lib/org-routing';
import type { LayoutLoad } from './$types';

/**
 * Guards every `/[org]/...` route. Validates the org segment against the
 * user's memberships; switches org if the URL points at a different one;
 * 404s if it points at none. Runs client-side (the app is a SPA).
 */
export const load: LayoutLoad = async ({ params }) => {
  await ensureInitialized();
  const resolution = resolveOrgSlug(params.org, getCurrentOrg(), getOrgs());
  if (resolution.kind === 'notfound') {
    error(404, 'Organization not found');
  }
  if (resolution.kind === 'switch') {
    await switchOrg(resolution.org);
  }
  return { orgSlug: params.org };
};
