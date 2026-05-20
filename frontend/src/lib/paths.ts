/**
 * GitHub-style URL builders (F-0091). Every routed object lives under the
 * current organization's slug; runs and experiments nest under their project.
 * The org slug is read from the auth store, so call sites never pass it.
 */
import { getCurrentOrg } from '$lib/auth.svelte';

function orgSlug(): string {
  const org = getCurrentOrg();
  if (!org) {
    throw new Error('paths: no current organization in the auth store');
  }
  return org.slug;
}

export const paths = {
  home: (): string => '/',
  protocol: (slug: string): string => `/${orgSlug()}/protocols/${slug}`,
  projects: (): string => `/${orgSlug()}/projects`,
  project: (slug: string): string => `/${orgSlug()}/projects/${slug}`,
  run: (projectSlug: string, slug: string): string =>
    `/${orgSlug()}/projects/${projectSlug}/runs/${slug}`,
  experiment: (projectSlug: string, slug: string): string =>
    `/${orgSlug()}/projects/${projectSlug}/experiments/${slug}`,
  library: (): string => `/${orgSlug()}/library`,
  libraryDoc: (slug: string): string => `/${orgSlug()}/library/${slug}`,
  libraryDocRefine: (slug: string): string =>
    `/${orgSlug()}/library/documents/${slug}/refine`,
};
