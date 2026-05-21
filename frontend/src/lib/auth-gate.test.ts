import { describe, expect, it } from 'vitest';

import { decideRedirect, sanitizeNextPath } from './auth-gate';

const base = {
    initialized: true,
    authenticated: true,
    emailVerified: true,
    tosCurrent: true,
    pathname: '/',
};

describe('decideRedirect', () => {
    it('returns none when uninitialized', () => {
        expect(decideRedirect({ ...base, initialized: false }).kind).toBe('none');
    });

    it('redirects unauthenticated users to login', () => {
        expect(decideRedirect({ ...base, authenticated: false, pathname: '/projects' }).kind).toBe('login');
    });

    it('lets unauthenticated users view public legal pages', () => {
        expect(decideRedirect({ ...base, authenticated: false, pathname: '/legal/terms' }).kind).toBe('none');
        expect(decideRedirect({ ...base, authenticated: false, pathname: '/legal/privacy' }).kind).toBe('none');
    });

    it('does not force unverified users back to /check-email — backend gates API access', () => {
        // Unverified user navigating to a private page is no longer pulled
        // back to /check-email; they can move freely (the backend middleware
        // restricts which API endpoints actually return data).
        expect(decideRedirect({ ...base, emailVerified: false, pathname: '/projects' }).kind).toBe('none');
        expect(decideRedirect({ ...base, emailVerified: false, pathname: '/settings' }).kind).toBe('none');
    });

    it('redirects authenticated email-verified users with stale ToS to /legal/accept', () => {
        expect(decideRedirect({ ...base, tosCurrent: false, pathname: '/projects' }).kind).toBe('accept-tos');
    });

    it('does not redirect a stale-ToS user already on /legal/accept', () => {
        expect(decideRedirect({ ...base, tosCurrent: false, pathname: '/legal/accept' }).kind).toBe('none');
    });

    it('lets a stale-ToS user view /legal/terms and /legal/privacy', () => {
        expect(decideRedirect({ ...base, tosCurrent: false, pathname: '/legal/terms' }).kind).toBe('none');
        expect(decideRedirect({ ...base, tosCurrent: false, pathname: '/legal/privacy' }).kind).toBe('none');
    });

    it('redirects authenticated users from public auth pages to home', () => {
        expect(decideRedirect({ ...base, pathname: '/login' }).kind).toBe('home');
        expect(decideRedirect({ ...base, pathname: '/register' }).kind).toBe('home');
    });

    it('returns none for fully-authenticated user on a normal page', () => {
        expect(decideRedirect({ ...base, pathname: '/projects' }).kind).toBe('none');
    });
});

describe('sanitizeNextPath', () => {
    it('returns a same-origin absolute path unchanged', () => {
        expect(sanitizeNextPath('/acme/projects')).toBe('/acme/projects');
    });

    it('falls back to / for empty or missing input', () => {
        expect(sanitizeNextPath(null)).toBe('/');
        expect(sanitizeNextPath(undefined)).toBe('/');
        expect(sanitizeNextPath('')).toBe('/');
    });

    it('rejects protocol-relative open-redirect payloads', () => {
        expect(sanitizeNextPath('//evil.com')).toBe('/');
        expect(sanitizeNextPath('/\\evil.com')).toBe('/');
    });

    it('rejects absolute URLs and non-rooted paths', () => {
        expect(sanitizeNextPath('https://evil.com')).toBe('/');
        expect(sanitizeNextPath('evil.com')).toBe('/');
    });
});
