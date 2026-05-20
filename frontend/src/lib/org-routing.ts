/**
 * Resolves the `[org]` URL segment against the user's memberships (F-0091).
 * The org segment is cosmetic — the session identifies the real org — but a
 * URL pointing at a *different* membership triggers an org switch, and a URL
 * pointing at no membership is a 404.
 */
export interface OrgLike {
  id: string;
  name: string;
  slug: string;
}

export type OrgResolution =
  | { kind: 'current'; org: OrgLike }
  | { kind: 'switch'; org: OrgLike }
  | { kind: 'notfound' };

export function resolveOrgSlug(
  urlSlug: string,
  currentOrg: OrgLike | null,
  orgs: OrgLike[],
): OrgResolution {
  if (currentOrg && currentOrg.slug === urlSlug) {
    return { kind: 'current', org: currentOrg };
  }
  const match = orgs.find((o) => o.slug === urlSlug);
  if (match) {
    return { kind: 'switch', org: match };
  }
  return { kind: 'notfound' };
}
