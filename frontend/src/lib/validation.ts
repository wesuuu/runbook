import { z, type ZodSchema, type ZodError, type ZodIssue } from 'zod';

export type FieldErrors = Record<string, string[]>;

export interface ValidationResult<T> {
  success: boolean;
  data?: T;
  errors: FieldErrors;
}

export function validate<T>(schema: ZodSchema<T>, data: unknown): ValidationResult<T> {
  const result = schema.safeParse(data);
  if (result.success) {
    return { success: true, data: result.data, errors: {} };
  }
  return { success: false, errors: flattenErrors(result.error) };
}

export function flattenErrors(error: ZodError): FieldErrors {
  const fieldErrors: FieldErrors = {};
  for (const issue of error.issues) {
    const key = issue.path.length > 0 ? issue.path.join('.') : '_root';
    if (!fieldErrors[key]) {
      fieldErrors[key] = [];
    }
    fieldErrors[key].push(issue.message);
  }
  return fieldErrors;
}

export function firstError(errors: FieldErrors, field: string): string | undefined {
  return errors[field]?.[0];
}

export function hasErrors(errors: FieldErrors): boolean {
  return Object.keys(errors).length > 0;
}

export function clearFieldError(errors: FieldErrors, field: string): FieldErrors {
  const { [field]: _, ...rest } = errors;
  return rest;
}

interface JsonSchemaProperty {
  type?: string;
  title?: string;
  unit?: string;
  enum?: string[];
}

interface JsonSchema {
  type?: string;
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
}

export function buildResultValidator(resultSchema: JsonSchema): ZodSchema | null {
  if (!resultSchema?.properties) return null;

  const required = new Set(resultSchema.required || []);
  const shape: Record<string, z.ZodTypeAny> = {};

  for (const [key, prop] of Object.entries(resultSchema.properties)) {
    const label = prop.title || key;
    let field: z.ZodTypeAny;

    if (prop.type === 'number' || prop.type === 'integer') {
      field = z.number({ error: `${label} must be a number` });
    } else if (prop.enum) {
      field = z.enum(prop.enum as [string, ...string[]], {
        error: `${label} is required`,
      });
    } else {
      field = z.string().min(1, `${label} is required`);
    }

    if (!required.has(key)) {
      field = field.optional();
    }

    shape[key] = field;
  }

  return z.object(shape);
}
