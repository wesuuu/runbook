export const ALLOWED_MIME_TYPES = new Set([
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'text/plain',
    'text/markdown',
    'application/rtf',
    'image/jpeg',
    'image/png',
    'image/heic',
]);

export const MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024; // 50 MB

export function isAllowedFileType(mime: string): boolean {
    return ALLOWED_MIME_TYPES.has(mime);
}

export function isFileSizeValid(bytes: number): boolean {
    return bytes <= MAX_FILE_SIZE_BYTES;
}

export function extractTitleFromFilename(filename: string): string {
    if (!filename) return '';
    const lastDot = filename.lastIndexOf('.');
    if (lastDot <= 0) return filename;
    return filename.substring(0, lastDot);
}

export function formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const FILE_TYPE_LABELS: Record<string, string> = {
    'application/pdf': 'PDF',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'DOCX',
    'text/plain': 'TXT',
    'text/markdown': 'MD',
    'application/rtf': 'RTF',
    'image/jpeg': 'Image',
    'image/png': 'Image',
    'image/heic': 'Image',
    'text/html': 'HTML',
};

export function getFileTypeLabel(mime: string): string {
    return FILE_TYPE_LABELS[mime] || 'File';
}

const STATUS_COLORS: Record<string, string> = {
    UPLOADED: 'secondary',
    QUEUED: 'secondary',
    PROCESSING: 'secondary',
    INDEXED: 'default',
    ENRICHED: 'default',
    READY: 'default',
    FAILED: 'destructive',
};

export function getStatusColor(status: string): string {
    return STATUS_COLORS[status] || 'secondary';
}

/** Statuses that indicate the document content is viewable. */
export const VIEWABLE_STATUSES = new Set(['INDEXED', 'ENRICHED', 'READY']);

/** Statuses where extraction is considered finished (chunks should exist). */
const FINAL_READY_STATUSES = new Set(['INDEXED', 'ENRICHED', 'READY']);

/**
 * Derived indexing state for a document — combines persistence status
 * with chunk + embedding counts so the UI can distinguish "fully indexed"
 * from "indexed but embeddings failed" (a silent failure mode in
 * document_processor where embedding errors are caught and the doc still
 * lands in READY with zero embeddings).
 */
export type IndexingState =
    | { kind: 'queued'; label: 'Queued' }
    | {
          kind: 'processing';
          label: 'Indexing';
          chunkCount: number;
          embeddedCount: number;
      }
    | { kind: 'indexed'; label: 'Indexed'; coverage: 100 }
    | {
          kind: 'partial';
          label: 'Partially indexed';
          coverage: number;
          missing: number;
      }
    | { kind: 'failed'; label: 'Failed' }
    | { kind: 'unknown'; label: string };

export function deriveIndexingState(doc: {
    status: string;
    chunk_count: number;
    embedded_count: number;
}): IndexingState {
    switch (doc.status) {
        case 'UPLOADED':
        case 'QUEUED':
            return { kind: 'queued', label: 'Queued' };
        case 'PROCESSING':
            return {
                kind: 'processing',
                label: 'Indexing',
                chunkCount: doc.chunk_count,
                embeddedCount: doc.embedded_count,
            };
        case 'FAILED':
            return { kind: 'failed', label: 'Failed' };
        default:
            if (FINAL_READY_STATUSES.has(doc.status)) {
                if (
                    doc.chunk_count > 0 &&
                    doc.embedded_count >= doc.chunk_count
                ) {
                    return { kind: 'indexed', label: 'Indexed', coverage: 100 };
                }
                const coverage =
                    doc.chunk_count > 0
                        ? Math.round((doc.embedded_count / doc.chunk_count) * 100)
                        : 0;
                return {
                    kind: 'partial',
                    label: 'Partially indexed',
                    coverage,
                    missing: Math.max(doc.chunk_count - doc.embedded_count, 0),
                };
            }
            return { kind: 'unknown', label: doc.status || 'Unknown' };
    }
}

export function getStatusLabel(status: string): string {
    switch (status) {
        case 'UPLOADED':
            return 'Uploaded';
        case 'QUEUED':
            return 'Queued';
        case 'PROCESSING':
            return 'Processing';
        case 'INDEXED':
        case 'ENRICHED':
        case 'READY':
            return 'Ready';
        case 'FAILED':
            return 'Failed';
        default:
            return status;
    }
}

export interface SectionNav {
    heading: string;
    chunkIndex: number;
}

export function extractSectionNav(
    chunks: Array<{ chunk_metadata: Record<string, unknown> }>,
): SectionNav[] {
    const sections: SectionNav[] = [];
    const seen = new Set<string>();

    for (let i = 0; i < chunks.length; i++) {
        const heading = chunks[i].chunk_metadata?.section_heading as string | undefined;
        if (heading && !seen.has(heading)) {
            seen.add(heading);
            sections.push({ heading, chunkIndex: i });
        }
    }
    return sections;
}

/**
 * Find chunks that contain the document's Table of Contents.
 * Looks for chunks starting with "Contents" or "Table of Contents"
 * in the first ~15 chunks (TOC is always near the front).
 */
function findTocChunks(
    chunks: Array<{ content: string; chunk_index: number }>,
): Array<{ content: string; chunk_index: number }> {
    const tocChunks: Array<{ content: string; chunk_index: number }> = [];
    const searchRange = Math.min(chunks.length, 15);

    for (let i = 0; i < searchRange; i++) {
        const content = chunks[i].content;
        const firstLines = content.split('\n').slice(0, 5).join('\n').toLowerCase();
        if (
            firstLines.includes('contents') ||
            firstLines.includes('table of contents')
        ) {
            tocChunks.push(chunks[i]);
            // Also grab subsequent chunks that look like TOC continuations
            // (they often start with "CONTENTS" or a section number)
            for (let j = i + 1; j < searchRange; j++) {
                const nextFirst = chunks[j].content.split('\n').slice(0, 3).join('\n');
                if (
                    nextFirst.toLowerCase().includes('contents') ||
                    /^\s*\d+\./.test(nextFirst.trim())
                ) {
                    tocChunks.push(chunks[j]);
                } else {
                    break;
                }
            }
            break;
        }
    }
    return tocChunks;
}

/**
 * Parse TOC entries from identified TOC chunks.
 *
 * Handles the common PDF extraction pattern where section numbers
 * and titles land on separate lines:
 *   "1."
 *   "Introduction, 1"
 *   "1.1."
 *   "Historical Background, 1"
 */
function parseTocEntries(
    tocChunks: Array<{ content: string; chunk_index: number }>,
): SectionNav[] {
    const entries: SectionNav[] = [];
    const seen = new Set<string>();
    // Matches a bare section number like "1." or "1.2." or "1.2.3."
    const sectionNumPattern = /^(\d+(?:\.\d+)*)\.?\s*$/;
    // Matches a title line like "Introduction, 1" or "Historical Background, 1"
    const titlePagePattern = /^([A-Z][A-Za-z\s\u2014\u2013\-—–:;,()]+?)(?:,\s*(\d+|[ivxlcdm]+))\s*$/;

    for (const chunk of tocChunks) {
        const lines = chunk.content.split('\n');

        for (let i = 0; i < lines.length; i++) {
            const trimmed = lines[i].trim();
            if (!trimmed) continue;

            // Pattern 1: Section number on its own line, title on next line
            const numMatch = trimmed.match(sectionNumPattern);
            if (numMatch) {
                const sectionNum = numMatch[1];
                const level = sectionNum.split('.').filter(Boolean).length;
                // Look ahead for the title line
                for (let j = i + 1; j < lines.length && j <= i + 3; j++) {
                    const nextLine = lines[j].trim();
                    if (!nextLine) continue;
                    const titleMatch = nextLine.match(titlePagePattern);
                    if (titleMatch) {
                        // Only include up to 2 levels deep for nav usability
                        if (level <= 2) {
                            const heading = `${sectionNum}. ${titleMatch[1].trim()}`;
                            if (!seen.has(heading)) {
                                seen.add(heading);
                                entries.push({ heading, chunkIndex: chunk.chunk_index });
                            }
                        }
                        i = j; // skip past the title line
                        break;
                    }
                    break; // non-matching non-blank line → stop looking
                }
                continue;
            }

            // Pattern 2: Single-line entry like "1. Introduction, 1"
            const inlineMatch = trimmed.match(
                /^(\d+(?:\.\d+)*)\.?\s+([A-Z][A-Za-z\s\u2014\u2013\-—–:;,()]+?)(?:,\s*(\d+|[ivxlcdm]+))\s*$/,
            );
            if (inlineMatch) {
                const sectionNum = inlineMatch[1];
                const level = sectionNum.split('.').filter(Boolean).length;
                if (level <= 2) {
                    const heading = `${sectionNum}. ${inlineMatch[2].trim()}`;
                    if (!seen.has(heading)) {
                        seen.add(heading);
                        entries.push({ heading, chunkIndex: chunk.chunk_index });
                    }
                }
            }
        }
    }

    return entries;
}

/**
 * Build section navigation for non-enriched documents.
 *
 * Strategy:
 * 1. Find actual TOC pages in the document and parse them
 * 2. If no TOC found, scan body chunks for isolated ALL-CAPS headings
 */
export function extractFallbackSectionNav(
    chunks: Array<{ content: string; chunk_index: number }>,
): SectionNav[] {
    // Strategy 1: Find and parse the actual TOC
    const tocChunks = findTocChunks(chunks);
    if (tocChunks.length > 0) {
        const entries = parseTocEntries(tocChunks);
        if (entries.length > 0) return entries;
    }

    // Strategy 2: Fallback — scan for isolated ALL-CAPS headings in body content
    // Skip the first few chunks (front matter) to avoid noise
    const sections: SectionNav[] = [];
    const seen = new Set<string>();
    const startIdx = Math.min(3, chunks.length);

    for (let ci = startIdx; ci < chunks.length; ci++) {
        const chunk = chunks[ci];
        const lines = chunk.content.split('\n');

        for (let i = 0; i < lines.length; i++) {
            const trimmed = lines[i].trim();
            if (!trimmed || trimmed.startsWith('#') || trimmed.length < 5) continue;

            const letters = trimmed.replace(/[^a-zA-Z]/g, '');
            if (letters.length < 3 || trimmed.length > 80 || letters !== letters.toUpperCase()) continue;

            // Check it's isolated (not part of a cluster)
            let prevCaps = false;
            for (let j = i - 1; j >= 0; j--) {
                if (lines[j].trim() === '') continue;
                const pl = lines[j].trim().replace(/[^a-zA-Z]/g, '');
                prevCaps = pl.length >= 3 && pl === pl.toUpperCase();
                break;
            }
            let nextCaps = false;
            for (let j = i + 1; j < lines.length; j++) {
                if (lines[j].trim() === '') continue;
                const nl = lines[j].trim().replace(/[^a-zA-Z]/g, '');
                nextCaps = nl.length >= 3 && nl === nl.toUpperCase();
                break;
            }
            if (prevCaps || nextCaps) continue;

            const heading = trimmed.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
            if (!seen.has(heading)) {
                seen.add(heading);
                sections.push({ heading, chunkIndex: chunk.chunk_index });
            }
        }

        if (sections.length >= 40) break;
    }

    return sections;
}

/**
 * Sanitize HTML from ts_headline for safe {@html} rendering.
 * Only allows <mark> and </mark> tags; strips everything else.
 */
export function sanitizeHighlight(html: string): string {
    // Replace <mark> and </mark> with placeholders
    let safe = html
        .replace(/<mark>/gi, '\x00MARK_OPEN\x00')
        .replace(/<\/mark>/gi, '\x00MARK_CLOSE\x00');
    // Strip all remaining HTML tags (must start with a letter or /)
    safe = safe.replace(/<\/?[a-zA-Z][^>]*>/g, '');
    // Escape HTML entities in the remaining text
    safe = safe
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    // Restore <mark> tags
    safe = safe
        .replace(/\x00MARK_OPEN\x00/g, '<mark>')
        .replace(/\x00MARK_CLOSE\x00/g, '</mark>');
    return safe;
}
