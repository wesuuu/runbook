<script lang="ts">
    import { marked } from 'marked';
    import DOMPurify from 'dompurify';

    let {
        content,
        format = 'plaintext',
        role = 'body',
    }: {
        content: string;
        format?: string;
        role?: string;
    } = $props();

    /**
     * Check if a line qualifies as an ALL-CAPS heading candidate.
     */
    function isAllCapsCandidate(line: string): boolean {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith('#')) return false;
        const letters = trimmed.replace(/[^a-zA-Z]/g, '');
        return letters.length >= 3 && trimmed.length <= 80 && letters === letters.toUpperCase();
    }

    /**
     * Detect isolated ALL-CAPS lines that are likely section headings
     * and prefix them with markdown `## `. Consecutive ALL-CAPS lines
     * (title pages, headers) are left as-is to avoid ugly formatting.
     * Only applied to plaintext content (not already-markdown).
     */
    function detectHeadings(text: string): string {
        const lines = text.split('\n');
        // Pass 1: identify ALL-CAPS candidates
        const isCaps = lines.map((line) => isAllCapsCandidate(line));

        // Pass 2: only promote isolated candidates (not adjacent to other ALL-CAPS)
        return lines
            .map((line, idx) => {
                if (!isCaps[idx]) return line;

                // Look backward for nearest non-blank line
                let prevCaps = false;
                for (let j = idx - 1; j >= 0; j--) {
                    if (lines[j].trim() === '') continue;
                    prevCaps = isCaps[j];
                    break;
                }

                // Look forward for nearest non-blank line
                let nextCaps = false;
                for (let j = idx + 1; j < lines.length; j++) {
                    if (lines[j].trim() === '') continue;
                    nextCaps = isCaps[j];
                    break;
                }

                // Part of a cluster → skip (title page, etc.)
                if (prevCaps || nextCaps) return line;
                return `## ${line.trim()}`;
            })
            .join('\n');
    }

    // Standalone section number: "1.", "1.2.", "4.2.1."
    const SECTION_NUM_RE = /^\d+(?:\.\d+)*\.\s*$/;
    // Title ending with a page number (arabic or roman)
    const TITLE_PAGE_RE = /^.{2,}[,\s]+(?:[xivlcdm]+|\d+)\s*$/i;

    /**
     * Detect whether plaintext content is structured (TOC, index,
     * bibliography) — i.e. most lines are short entries rather than
     * flowing prose.  When true, line breaks should be preserved.
     */
    function isStructuredContent(text: string): boolean {
        const lines = text.split('\n').filter((l) => l.trim());
        if (lines.length < 4) return false;

        let structuredCount = 0;
        for (const line of lines) {
            const t = line.trim();
            if (SECTION_NUM_RE.test(t) || TITLE_PAGE_RE.test(t)) {
                structuredCount++;
            }
        }
        return structuredCount / lines.length > 0.4;
    }

    /**
     * For plaintext TOC/index content, merge orphaned section numbers
     * with their following title lines and convert to markdown list.
     */
    function tocToMarkdown(text: string): string {
        const rawLines = text.split('\n');
        const merged: string[] = [];
        let buf = '';

        for (const line of rawLines) {
            const stripped = line.trim();
            if (!stripped) {
                if (buf) { merged.push(buf); buf = ''; }
                continue;
            }
            if (SECTION_NUM_RE.test(stripped)) {
                if (buf) merged.push(buf);
                buf = stripped;
            } else if (buf) {
                const candidate = buf + ' ' + stripped;
                if (TITLE_PAGE_RE.test(stripped)) {
                    merged.push(candidate);
                    buf = '';
                } else {
                    buf = candidate;
                }
            } else {
                merged.push(stripped);
            }
        }
        if (buf) merged.push(buf);

        return merged
            .map((line) => {
                if (line.startsWith('#')) return line;
                const m = line.match(/^(\d+(?:\.\d+)*)\.\s/);
                const depth = m ? m[1].split('.').length : 0;
                if (depth > 0 || TITLE_PAGE_RE.test(line)) {
                    const indent = '  '.repeat(Math.max(0, depth - 1));
                    return `${indent}- ${line}`;
                }
                return line;
            })
            .join('\n');
    }

    const isStructured = $derived(
        format === 'plaintext' && (role === 'toc' || isStructuredContent(content))
    );

    const processed = $derived.by(() => {
        if (format === 'markdown') return content;
        if (isStructured) return tocToMarkdown(content);
        return detectHeadings(content);
    });

    const useBreaks = $derived(format === 'markdown' || isStructured);

    const html = $derived(
        DOMPurify.sanitize(
            marked.parse(processed, {
                gfm: true,
                breaks: useBreaks,
            }) as string
        )
    );
</script>

<div class="prose prose-sm max-w-none">{@html html}</div>
