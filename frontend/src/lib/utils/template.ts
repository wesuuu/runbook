/**
 * Substitute {{key}} placeholders in a template string with formatted
 * param values. Missing / empty values leave the raw {{key}} in place
 * so the user can see what still needs filling (mirrors backend
 * `_render_template` in app/services/pdf_base.py).
 */
export function renderTemplate(
    template: string,
    params: Record<string, unknown> | null | undefined,
): string {
    if (!template) return '';
    if (!params) return template;

    return template.replace(/\{\{(\w+)\}\}/g, (match, key: string) => {
        const val = params[key];
        if (
            val === undefined
            || val === null
            || val === ''
            || (Array.isArray(val) && val.length === 0)
        ) {
            return match;
        }
        if (typeof val === 'boolean') return val ? 'Yes' : 'No';
        if (Array.isArray(val)) return val.join(', ');
        return String(val);
    });
}
