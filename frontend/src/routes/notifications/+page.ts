import type { PageLoad } from './$types';

/**
 * `offset` lives in the URL so browser back/forward restores the page
 * position. Non-numeric or negative values clamp to 0.
 */
export const load: PageLoad = ({ url }) => {
    const raw = Number(url.searchParams.get('offset') ?? '0');
    const offset = Number.isFinite(raw) && raw > 0 ? Math.floor(raw) : 0;
    return { offset };
};
