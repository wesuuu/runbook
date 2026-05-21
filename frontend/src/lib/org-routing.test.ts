import { describe, expect, it } from 'vitest';
import { disambiguatedOrgSlug, resolveOrgSlug } from './org-routing';

const acme = { id: 'o1', name: 'Acme', slug: 'acme' };
const koch = { id: 'o2', name: 'Koch', slug: 'koch' };

// Two orgs whose names slugify to the same base slug — the backend computes
// each org's slug independently, so this collision is reachable.
const acmeBioInc = {
  id: 'aaaaaaaa-1111-2222-3333-444444444444',
  name: 'Acme Bio',
  slug: 'acme-bio',
};
const acmeBioLlc = {
  id: 'bbbbbbbb-1111-2222-3333-444444444444',
  name: 'Acme, Bio.',
  slug: 'acme-bio',
};

describe('disambiguatedOrgSlug', () => {
  it('returns the bare slug when no other org collides', () => {
    expect(disambiguatedOrgSlug(acme, [acme, koch])).toBe('acme');
  });

  it('appends a stable org-id suffix to every org in a colliding group', () => {
    expect(disambiguatedOrgSlug(acmeBioInc, [acmeBioInc, acmeBioLlc])).toBe(
      'acme-bio-aaaaaaaa',
    );
    expect(disambiguatedOrgSlug(acmeBioLlc, [acmeBioInc, acmeBioLlc])).toBe(
      'acme-bio-bbbbbbbb',
    );
  });

  it('is independent of the order of the orgs list', () => {
    expect(disambiguatedOrgSlug(acmeBioInc, [acmeBioLlc, acmeBioInc])).toBe(
      'acme-bio-aaaaaaaa',
    );
  });
});

describe('resolveOrgSlug', () => {
  it('returns current when the URL slug is the active org', () => {
    expect(resolveOrgSlug('acme', acme, [acme, koch])).toEqual({
      kind: 'current',
      org: acme,
    });
  });

  it('returns switch when the URL slug is another membership', () => {
    expect(resolveOrgSlug('koch', acme, [acme, koch])).toEqual({
      kind: 'switch',
      org: koch,
    });
  });

  it('returns notfound when no membership matches', () => {
    expect(resolveOrgSlug('zeta', acme, [acme, koch])).toEqual({
      kind: 'notfound',
    });
  });

  it('returns notfound when there is no current org', () => {
    expect(resolveOrgSlug('acme', null, [])).toEqual({ kind: 'notfound' });
  });

  it('resolves a disambiguated URL slug to the right colliding org', () => {
    const orgs = [acmeBioInc, acmeBioLlc];
    expect(resolveOrgSlug('acme-bio-bbbbbbbb', acmeBioInc, orgs)).toEqual({
      kind: 'switch',
      org: acmeBioLlc,
    });
    expect(resolveOrgSlug('acme-bio-aaaaaaaa', acmeBioInc, orgs)).toEqual({
      kind: 'current',
      org: acmeBioInc,
    });
  });

  it('returns notfound for a bare slug that collides between orgs', () => {
    const orgs = [acmeBioInc, acmeBioLlc];
    expect(resolveOrgSlug('acme-bio', acmeBioInc, orgs)).toEqual({
      kind: 'notfound',
    });
  });
});
