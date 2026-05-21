import { error, redirect } from '@sveltejs/kit';
import {
  ensureInitialized,
  getCurrentOrg,
  getOrgs,
  isAuthenticated,
  switchOrg,
} from '$lib/auth.svelte';
import { resolveOrgSlug } from '$lib/org-routing';
import type { LayoutLoad } from './$types';

/**
 * Guards every `/[org]/...` route. Requires an authenticated session;
 * validates the org segment against the user's memberships; switches org
 * if the URL points at a different one; 404s if it points at none. Runs
 * client-side (the app is a SPA).
 */
export const load: LayoutLoad = async ({ params, url }) => {
  await ensureInitialized();
  // Auth must be resolved before org resolution: an unauthenticated user
  // has no orgs, so resolveOrgSlug would mis-report a valid org as 404.
  // Send them to login and bring them back to this URL afterwards.
  if (!isAuthenticated()) {
    redirect(302, `/login?next=${encodeURIComponent(url.pathname)}`);
  }
  const resolution = resolveOrgSlug(params.org, getCurrentOrg(), getOrgs());
  if (resolution.kind === 'notfound') {
    error(404, 'Organization not found');
  }
  if (resolution.kind === 'switch') {
    // switchOrg leaves the active org untouched if the backend call fails;
    // surface that as an error page rather than loading the route against
    // a stale-org token.
    try {
      await switchOrg(resolution.org);
    } catch {
      error(503, 'Could not switch to this organization. Please try again.');
    }
  }
  return { orgSlug: params.org };
};
