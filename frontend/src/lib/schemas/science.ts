import { z } from 'zod';

export const UnitOpDefinitionSchema = z.object({
    id: z.string().uuid(),
    name: z.string(),
    category: z.string().default('General'),
    description: z.string().nullable().optional(),
    param_schema: z.record(z.string(), z.unknown()).default({}),
    result_schema: z.record(z.string(), z.unknown()).default({}),
    library_slug: z.string().nullable().optional(),  // F-0075: identifies JSON library origin
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type UnitOpDefinition = z.infer<typeof UnitOpDefinitionSchema>;

export const UnitOpDefinitionListSchema = z.array(UnitOpDefinitionSchema);
export type UnitOpDefinitionList = z.infer<typeof UnitOpDefinitionListSchema>;

export const EquipmentStatusSchema = z.enum(['ACTIVE', 'MAINTENANCE', 'RETIRED']);
export type EquipmentStatus = z.infer<typeof EquipmentStatusSchema>;

export const EquipmentSchema = z.object({
    id: z.string(),
    organization_id: z.string(),
    site_id: z.string(),
    name: z.string(),
    description: z.string().nullable().optional(),
    equipment_type: z.string().nullable().optional(),
    location: z.string().nullable().optional(),
    room: z.string().nullable().optional(),
    tags: z.array(z.string()).default([]),
    manufacturer: z.string().nullable().optional(),
    model: z.string().nullable().optional(),
    serial_number: z.string().nullable().optional(),
    status: EquipmentStatusSchema,
    install_date: z.string().nullable().optional(),
    last_calibration_date: z.string().nullable().optional(),
    next_calibration_due: z.string().nullable().optional(),
    archived_at: z.string().nullable().optional(),
    archived_by_id: z.string().nullable().optional(),
    created_by_id: z.string().nullable().optional(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();
export type Equipment = z.infer<typeof EquipmentSchema>;

export const EquipmentListSchema = z.array(EquipmentSchema);

export const EquipmentCreateSchema = z.object({
    name: z.string().min(1).max(255),
    site_id: z.string(),
    description: z.string().optional(),
    equipment_type: z.string().max(120).optional(),
    location: z.string().max(255).optional(),
    room: z.string().max(120).optional(),
    tags: z.array(z.string()).default([]),
    manufacturer: z.string().max(120).optional(),
    model: z.string().max(120).optional(),
    serial_number: z.string().max(120).optional(),
    status: EquipmentStatusSchema.default('ACTIVE'),
    install_date: z.string().optional(),
    last_calibration_date: z.string().optional(),
    next_calibration_due: z.string().optional(),
});
export type EquipmentCreate = z.infer<typeof EquipmentCreateSchema>;

export const EquipmentUpdateSchema = EquipmentCreateSchema.partial();
export type EquipmentUpdate = z.infer<typeof EquipmentUpdateSchema>;

export const EquipmentAttachmentSchema = z.object({
    id: z.string(),
    equipment_id: z.string(),
    original_filename: z.string(),
    mime_type: z.string(),
    size_bytes: z.number(),
    uploaded_by_id: z.string(),
    created_at: z.string(),
}).passthrough();
export type EquipmentAttachment = z.infer<typeof EquipmentAttachmentSchema>;

export const EquipmentAttachmentListSchema = z.array(EquipmentAttachmentSchema);
