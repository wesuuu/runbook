/**
 * Equipment lifecycle permission helpers (F-0088 decision 4).
 *
 * SITE_MANAGER role on `OrganizationMember.roles` is the *capability* bit;
 * a per-site `site_manager_grants` row is the *authorization*. Both are
 * required to edit regulated metadata for equipment at a site. ADMIN
 * bypasses both checks.
 */

type OrgRole = 'ADMIN' | 'BILLING' | 'MEMBER' | 'PROTOCOL_APPROVER' | 'SITE_MANAGER';

interface CanManageInput {
    roles: OrgRole[];
    managedSiteIds: string[];
    siteId: string;
}

export function canManageEquipmentLifecycle(input: CanManageInput): boolean {
    if (input.roles.includes('ADMIN')) return true;
    if (!input.roles.includes('SITE_MANAGER')) return false;
    return input.managedSiteIds.includes(input.siteId);
}

interface CanMoveInput {
    roles: OrgRole[];
    managedSiteIds: string[];
    fromSiteId: string;
    toSiteId: string;
}

export function canMoveEquipment(input: CanMoveInput): boolean {
    if (input.roles.includes('ADMIN')) return true;
    if (!input.roles.includes('SITE_MANAGER')) return false;
    return input.managedSiteIds.includes(input.fromSiteId)
        && input.managedSiteIds.includes(input.toSiteId);
}
