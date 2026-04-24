import { z } from 'zod';

export const SubscriptionStateSchema = z.object({
    tier: z.enum(['essentials', 'pro', 'enterprise']),
    status: z.string().nullable(),
    trial_end: z.string().nullable(),
    days_remaining_in_trial: z.number().int().nullable(),
    current_period_end: z.string().nullable(),
    cancel_at_period_end: z.boolean(),
    has_payment_method: z.boolean(),
    is_locked_out: z.boolean(),
    seat_count: z.number().int(),
    seat_limit: z.number().int().nullable(),
    seat_limit_exceeded: z.boolean(),
}).passthrough();

export type SubscriptionState = z.infer<typeof SubscriptionStateSchema>;

export const PortalSessionResponseSchema = z.object({
    url: z.string().url(),
}).passthrough();

export type PortalSessionResponse = z.infer<typeof PortalSessionResponseSchema>;
