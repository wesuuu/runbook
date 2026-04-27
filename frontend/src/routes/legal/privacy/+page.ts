import { fetchCurrentLegalVersion, fetchLegalDocument } from '$lib/legal-api';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async () => {
    const { version } = await fetchCurrentLegalVersion();
    const doc = await fetchLegalDocument(version, 'privacy');
    return { doc };
};
