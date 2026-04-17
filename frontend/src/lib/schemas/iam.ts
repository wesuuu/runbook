import { z } from 'zod';

export const OrganizationSchema = z.object({
    id: z.string().uuid(),
    name: z.string(),
    subscription_tier: z.string().default('essentials'),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type Organization = z.infer<typeof OrganizationSchema>;

export const OrgMemberSchema = z.object({
    id: z.string().uuid(),
    user_id: z.string().uuid(),
    organization_id: z.string().uuid(),
    role: z.string(),
    email: z.string().nullable().optional(),
    full_name: z.string().nullable().optional(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type OrgMember = z.infer<typeof OrgMemberSchema>;

export const TeamSchema = z.object({
    id: z.string().uuid(),
    name: z.string(),
    organization_id: z.string().uuid(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type Team = z.infer<typeof TeamSchema>;

export const TeamMemberSchema = z.object({
    id: z.string().uuid(),
    user_id: z.string().uuid(),
    team_id: z.string().uuid(),
    role: z.string(),
    email: z.string().nullable().optional(),
    full_name: z.string().nullable().optional(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type TeamMember = z.infer<typeof TeamMemberSchema>;

export const UserSearchSchema = z.object({
    id: z.string().uuid(),
    email: z.string(),
    full_name: z.string().nullable().optional(),
}).passthrough();

export type UserSearch = z.infer<typeof UserSearchSchema>;

export const PermissionSchema = z.object({
    id: z.string().uuid(),
    principal_type: z.string(),
    principal_id: z.string().uuid(),
    object_type: z.string(),
    object_id: z.string().uuid(),
    permission_level: z.string(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type Permission = z.infer<typeof PermissionSchema>;
