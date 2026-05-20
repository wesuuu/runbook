import { describe, expect, it } from 'vitest';
import { resolveOrgSlug } from './org-routing';

const acme = { id: 'o1', name: 'Acme', slug: 'acme' };
const koch = { id: 'o2', name: 'Koch', slug: 'koch' };

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
    expect(resolveOrgSlug('zeta', acme, [acme, koch])).toEqual({ kind: 'notfound' });
  });

  it('returns notfound when there is no current org', () => {
    expect(resolveOrgSlug('acme', null, [])).toEqual({ kind: 'notfound' });
  });
});
