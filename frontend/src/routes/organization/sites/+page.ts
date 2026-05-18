import { api } from '$lib/api';
import { SiteListSchema, type Site } from '$lib/schemas/sites';
import { EquipmentListSchema, type Equipment } from '$lib/schemas/science';
import type { PageLoad } from './$types';

export const ssr = false;
export const prerender = false;

export const load: PageLoad = async (): Promise<{
    sites: Site[];
    equipment: Equipment[];
    tags: string[];
}> => {
    const [sites, equipment, tags] = await Promise.all([
        api.get<Site[]>('/sites', { schema: SiteListSchema }),
        api.get<Equipment[]>('/equipment', { schema: EquipmentListSchema }),
        api.get<string[]>('/equipment/tags'),
    ]);
    return { sites, equipment, tags };
};
