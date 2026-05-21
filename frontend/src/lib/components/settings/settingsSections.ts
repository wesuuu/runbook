import type { Component } from 'svelte';
import {
    Building2,
    Users,
    MapPin,
    Sparkles,
    FileText,
    CreditCard,
    User,
    Palette,
    Bell,
    Scale,
} from '@lucide/svelte';

// `id` is `string` (not the narrower SettingsTabId) on purpose: SettingsTabId
// is derived from `SECTIONS satisfies readonly SettingsSection[]` below, so a
// narrower `id` here would make the type circular. Consumers that need the
// narrow union read it off `SECTIONS` directly via SettingsTabId.
export interface SettingsSection {
    id: string;
    label: string;
    group: 'workspace' | 'account';
    icon: Component;
    admin: boolean;
}

// SECTIONS is the single source of truth. `as const satisfies` gives both
// field-shape validation and exact string-literal id inference, so the
// SettingsTabId type below cannot drift from this list.
export const SECTIONS = [
    { id: 'organization',  label: 'Organization',      group: 'workspace', icon: Building2,   admin: false },
    { id: 'teams',         label: 'Teams',             group: 'workspace', icon: Users,       admin: false },
    { id: 'sites',         label: 'Sites & Equipment', group: 'workspace', icon: MapPin,      admin: false },
    { id: 'ai',            label: 'AI Models',         group: 'workspace', icon: Sparkles,    admin: true  },
    { id: 'templates',     label: 'Templates',         group: 'workspace', icon: FileText,    admin: true  },
    { id: 'billing',       label: 'Billing',           group: 'workspace', icon: CreditCard,  admin: true  },
    { id: 'profile',       label: 'Profile',           group: 'account',   icon: User,        admin: false },
    { id: 'appearance',    label: 'Appearance',        group: 'account',   icon: Palette,     admin: false },
    { id: 'notifications', label: 'Notifications',     group: 'account',   icon: Bell,        admin: false },
    { id: 'legal',         label: 'Legal',             group: 'account',   icon: Scale,       admin: false },
] as const satisfies readonly SettingsSection[];

export type SettingsTabId = (typeof SECTIONS)[number]['id'];

// Narrow element type of SECTIONS: each entry's `id` is the exact string
// literal (SettingsTabId), unlike the `SettingsSection` interface whose `id`
// is widened to `string` to avoid a circular reference. Consumers that read
// an entry's `id` should type the entry as `SettingsSectionEntry`.
export type SettingsSectionEntry = (typeof SECTIONS)[number];

export const SETTINGS_TAB_IDS: readonly SettingsTabId[] = SECTIONS.map(
    (s) => s.id,
);

export const ADMIN_TAB_IDS: readonly SettingsTabId[] = SECTIONS.filter(
    (s) => s.admin,
).map((s) => s.id);

export const GROUP_LABELS: Record<SettingsSection['group'], string> = {
    workspace: 'Workspace',
    account: 'Account',
};

export const DEFAULT_TAB: SettingsTabId = 'organization';
