import { describe, expect, it, vi } from 'vitest';

vi.mock('$lib/auth.svelte', () => ({
  getCurrentOrg: () => ({ id: 'o1', name: 'Acme', slug: 'acme' }),
  getOrgs: () => [{ id: 'o1', name: 'Acme', slug: 'acme' }],
}));

import { paths } from './paths';

describe('paths', () => {
  it('builds a protocol path', () => {
    expect(paths.protocol('buffer-prep')).toBe('/acme/protocols/buffer-prep');
  });

  it('builds the projects index path', () => {
    expect(paths.projects()).toBe('/acme/projects');
  });

  it('builds a project path', () => {
    expect(paths.project('cho-line')).toBe('/acme/projects/cho-line');
  });

  it('builds a nested run path', () => {
    expect(paths.run('cho-line', 'seeding')).toBe(
      '/acme/projects/cho-line/runs/seeding',
    );
  });

  it('builds a nested experiment path', () => {
    expect(paths.experiment('cho-line', 'passage-3')).toBe(
      '/acme/projects/cho-line/experiments/passage-3',
    );
  });

  it('builds library paths', () => {
    expect(paths.library()).toBe('/acme/library');
    expect(paths.libraryDoc('sop-one')).toBe('/acme/library/sop-one');
    expect(paths.libraryDocRefine('sop-one')).toBe(
      '/acme/library/documents/sop-one/refine',
    );
  });
});
