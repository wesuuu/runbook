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

export type OrgResolution<T extends OrgLike = OrgLike> =
  | { kind: 'current'; org: T }
  | { kind: 'switch'; org: T }
  | { kind: 'notfound' };

/**
 * The org slug to use in a URL. The backend computes each org's slug
 * independently as `slugify(name)`, so two orgs the same user belongs to can
 * collide on one slug ("Acme Bio" and "Acme, Bio." both → `acme-bio`). When
 * that happens, every org in the colliding group gets a short, stable
 * org-id suffix so each URL is unambiguous; a non-colliding org keeps its
 * bare slug. The result is deterministic and independent of the order of
 * `orgs`, so URL generation (`paths.ts`) and resolution (`resolveOrgSlug`)
 * always agree.
 */
export function disambiguatedOrgSlug<T extends OrgLike>(
  org: T,
  orgs: T[],
): string {
  const collides = orgs.some((o) => o.id !== org.id && o.slug === org.slug);
  return collides ? `${org.slug}-${org.id.slice(0, 8)}` : org.slug;
}

export function resolveOrgSlug<T extends OrgLike>(
  urlSlug: string,
  currentOrg: T | null,
  orgs: T[],
): OrgResolution<T> {
  if (currentOrg && disambiguatedOrgSlug(currentOrg, orgs) === urlSlug) {
    return { kind: 'current', org: currentOrg };
  }
  const match = orgs.find((o) => disambiguatedOrgSlug(o, orgs) === urlSlug);
  if (match) {
    return { kind: 'switch', org: match };
  }
  return { kind: 'notfound' };
}
