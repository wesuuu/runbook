import { z } from 'zod';

export const UnitOpDefinitionSchema = z.object({
    id: z.string().uuid(),
    name: z.string(),
    category: z.string().default('General'),
    description: z.string().nullable().optional(),
    param_schema: z.record(z.string(), z.unknown()).default({}),
    result_schema: z.record(z.string(), z.unknown()).default({}),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type UnitOpDefinition = z.infer<typeof UnitOpDefinitionSchema>;

export const UnitOpDefinitionListSchema = z.array(UnitOpDefinitionSchema);
export type UnitOpDefinitionList = z.infer<typeof UnitOpDefinitionListSchema>;

export const EquipmentSchema = z.object({
    id: z.string().uuid(),
    organization_id: z.string().uuid(),
    name: z.string(),
    description: z.string().nullable().optional(),
    equipment_type: z.string().nullable().optional(),
    location: z.string().nullable().optional(),
    created_at: z.string(),
    updated_at: z.string(),
}).passthrough();

export type Equipment = z.infer<typeof EquipmentSchema>;
