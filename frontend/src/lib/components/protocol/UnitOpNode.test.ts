import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(__dirname, 'UnitOpNode.svelte'), 'utf8');

// jsdom doesn't run real layout, and mounting UnitOpNode requires a
// SvelteFlowProvider + bits-ui ContextMenu context. This fix is a pure
// CSS + template-attribute contract, so we inspect the source file directly.
function extractParamRowTag(src: string): string {
    const m = src.match(/<div\b[^>]*class="param-row"[^>]*>/);
    return m?.[0] ?? '';
}

function extractParamValueTag(src: string): string {
    const m = src.match(/<span\b[^>]*class="param-value"[^>]*>/);
    return m?.[0] ?? '';
}

describe('UnitOpNode time-mode truncation contract', () => {
    it('renders the param row with a title= attr containing both label and value', () => {
        const tag = extractParamRowTag(source);
        expect(tag).not.toBe('');
        expect(tag).toMatch(/\btitle=\{/);
        expect(tag).toMatch(/param\.label/);
        expect(tag).toMatch(/param\.value/);
    });

    it('renders the param value with title={String(param.value)} exactly', () => {
        const tag = extractParamValueTag(source);
        expect(tag).not.toBe('');
        expect(tag).toContain('title={String(param.value)}');
    });

    it('.param-value CSS truncates with ellipsis instead of wrapping', () => {
        const styleBlock = source.match(/<style>[\s\S]*?<\/style>/)?.[0] ?? '';
        const paramValueRule = styleBlock.match(/\.param-value\s*\{[\s\S]*?\}/)?.[0] ?? '';
        expect(paramValueRule).toMatch(/white-space:\s*nowrap/);
        expect(paramValueRule).toMatch(/overflow:\s*hidden/);
        expect(paramValueRule).toMatch(/text-overflow:\s*ellipsis/);
        expect(paramValueRule).toMatch(/min-width:\s*0/);
        expect(paramValueRule).not.toMatch(/word-break:\s*break-word/);
    });

    it('.param-label CSS truncates with ellipsis but caps at 60% so the value shrinks first', () => {
        const styleBlock = source.match(/<style>[\s\S]*?<\/style>/)?.[0] ?? '';
        const paramLabelRule = styleBlock.match(/\.param-label\s*\{[\s\S]*?\}/)?.[0] ?? '';
        expect(paramLabelRule).toMatch(/white-space:\s*nowrap/);
        expect(paramLabelRule).toMatch(/overflow:\s*hidden/);
        expect(paramLabelRule).toMatch(/text-overflow:\s*ellipsis/);
        expect(paramLabelRule).toMatch(/flex-shrink:\s*0/);
        expect(paramLabelRule).toMatch(/max-width:\s*60%/);
    });

    it('.param-row allows its children to shrink (min-width: 0)', () => {
        const styleBlock = source.match(/<style>[\s\S]*?<\/style>/)?.[0] ?? '';
        const paramRowRule = styleBlock.match(/\.param-row\s*\{[\s\S]*?\}/)?.[0] ?? '';
        expect(paramRowRule).toMatch(/min-width:\s*0/);
    });

    it('.node-params hides overflow so narrow nodes do not spill', () => {
        const styleBlock = source.match(/<style>[\s\S]*?<\/style>/)?.[0] ?? '';
        const nodeParamsRule = styleBlock.match(/\.node-params\s*\{[\s\S]*?\}/)?.[0] ?? '';
        expect(nodeParamsRule).toMatch(/overflow:\s*hidden/);
    });
});
