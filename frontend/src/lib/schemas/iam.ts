import { z } from 'zod';
import { uuidString } from '$lib/schemas/common';

export const OrganizationSchema = z.object({
    id: uuidString(),
    name: z.string(),
    subscription_tier: z.string().default('essentials'),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type Organization = z.infer<typeof OrganizationSchema>;

export const OrgMemberSchema = z.object({
    id: uuidString(),
    user_id: uuidString(),
    organization_id: uuidString(),
    role: z.string(),
    email: z.string().nullable().optional(),
    full_name: z.string().nullable().optional(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type OrgMember = z.infer<typeof OrgMemberSchema>;

export const TeamSchema = z.object({
    id: uuidString(),
    name: z.string(),
    organization_id: uuidString(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type Team = z.infer<typeof TeamSchema>;

export const TeamMemberSchema = z.object({
    id: uuidString(),
    user_id: uuidString(),
    team_id: uuidString(),
    role: z.string(),
    email: z.string().nullable().optional(),
    full_name: z.string().nullable().optional(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type TeamMember = z.infer<typeof TeamMemberSchema>;

export const UserSearchSchema = z.object({
    id: uuidString(),
    email: z.string(),
    full_name: z.string().nullable().optional(),
}).passthrough();

export type UserSearch = z.infer<typeof UserSearchSchema>;

export const PermissionSchema = z.object({
    id: uuidString(),
    principal_type: z.string(),
    principal_id: uuidString(),
    object_type: z.string(),
    object_id: uuidString(),
    permission_level: z.string(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type Permission = z.infer<typeof PermissionSchema>;
