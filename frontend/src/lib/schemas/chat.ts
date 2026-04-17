import { z } from 'zod';

export const ChatMessageSchema = z.object({
    id: z.string(),
    session_id: z.string(),
    role: z.enum(['user', 'assistant', 'system', 'summary']),
    content: z.string(),
    metadata_: z.record(z.string(), z.unknown()).nullable(),
    created_at: z.string(),
}).passthrough();
export type ChatMessage = z.infer<typeof ChatMessageSchema>;

export const ChatSessionSchema = z.object({
    id: z.string(),
    user_id: z.string(),
    org_id: z.string(),
    title: z.string(),
    status: z.string(),
    context_document_ids: z.array(z.string()).nullable(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();
export type ChatSession = z.infer<typeof ChatSessionSchema>;

export const ChatSessionDetailSchema = ChatSessionSchema.extend({
    messages: z.array(ChatMessageSchema),
}).passthrough();
export type ChatSessionDetail = z.infer<typeof ChatSessionDetailSchema>;

export const ChatSessionListResponseSchema = z.object({
    items: z.array(ChatSessionSchema),
    total: z.number(),
}).passthrough();

export const ChatSourceReferenceSchema = z.object({
    document_id: z.string(),
    document_title: z.string(),
    chunk_id: z.string(),
    chunk_index: z.number(),
    page_number: z.number().nullable(),
    score: z.number(),
    snippet: z.string(),
}).passthrough();
export type ChatSourceReference = z.infer<typeof ChatSourceReferenceSchema>;

export const ChatCompletionResponseSchema = z.object({
    user_message: ChatMessageSchema,
    assistant_message: ChatMessageSchema,
    sources: z.array(ChatSourceReferenceSchema),
}).passthrough();
export type ChatCompletionResponse = z.infer<typeof ChatCompletionResponseSchema>;

export const ChatSkillSchema = z.object({
    name: z.string(),
    description: z.string(),
    icon: z.string(),
}).passthrough();
export type ChatSkill = z.infer<typeof ChatSkillSchema>;

export const ChatSkillListResponseSchema = z.object({
    skills: z.array(ChatSkillSchema),
}).passthrough();

export const ChatConfigSchema = z.object({
    max_message_length: z.number(),
    model_name: z.string(),
    context_window: z.number(),
    compaction_threshold: z.number(),
}).passthrough();
export type ChatConfig = z.infer<typeof ChatConfigSchema>;
