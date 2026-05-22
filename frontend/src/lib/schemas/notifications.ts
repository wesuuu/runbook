import { z } from 'zod';

export const NotificationSchema = z
    .object({
        id: z.string(),
        user_id: z.string(),
        event_type: z.string(),
        entity_type: z.string(),
        entity_id: z.string(),
        title: z.string(),
        message: z.string(),
        read_at: z.string().nullable(),
        created_at: z.string(),
    })
    .passthrough();
export type NotificationItem = z.infer<typeof NotificationSchema>;

export const NotificationListResponseSchema = z
    .object({
        items: z.array(NotificationSchema),
        total: z.number(),
    })
    .passthrough();
export type NotificationListResponse = z.infer<
    typeof NotificationListResponseSchema
>;

export const UnreadCountResponseSchema = z
    .object({
        count: z.number(),
    })
    .passthrough();
export type UnreadCountResponse = z.infer<typeof UnreadCountResponseSchema>;
