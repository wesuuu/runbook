import { z } from 'zod';

export const QueueActorRefSchema = z.object({
    id: z.string(),
    name: z.string(),
    email: z.string(),
}).passthrough();
export type QueueActorRef = z.infer<typeof QueueActorRefSchema>;

export const SignoffRequestItemSchema = z
    .object({
        type: z.enum(['run', 'protocol']),
        request_id: z.string().nullable().optional(),
        target_id: z.string(),
        target_name: z.string(),
        role: z.string().nullable().optional(),
        project_id: z.string().nullable().optional(),
        assigned: z.boolean(),
        requested_by: QueueActorRefSchema.nullable().optional(),
        created_at: z.string().nullable().optional(),
    })
    .passthrough();
export type SignoffRequestItem = z.infer<typeof SignoffRequestItemSchema>;

export const SignoffRequestListSchema = z.array(SignoffRequestItemSchema);
export type SignoffRequestList = z.infer<typeof SignoffRequestListSchema>;
