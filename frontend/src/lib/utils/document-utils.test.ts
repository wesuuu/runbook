import { describe, it, expect } from 'vitest';
import {
    isAllowedFileType,
    isFileSizeValid,
    extractTitleFromFilename,
    formatFileSize,
    getFileTypeLabel,
    getStatusColor,
    sanitizeHighlight,
    MAX_FILE_SIZE_BYTES,
} from './document-utils';

describe('isAllowedFileType', () => {
    it('accepts application/pdf', () => {
        expect(isAllowedFileType('application/pdf')).toBe(true);
    });

    it('accepts docx mime type', () => {
        expect(
            isAllowedFileType(
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            ),
        ).toBe(true);
    });

    it('accepts text/plain', () => {
        expect(isAllowedFileType('text/plain')).toBe(true);
    });

    it('accepts text/markdown', () => {
        expect(isAllowedFileType('text/markdown')).toBe(true);
    });

    it('accepts image/jpeg', () => {
        expect(isAllowedFileType('image/jpeg')).toBe(true);
    });

    it('accepts image/png', () => {
        expect(isAllowedFileType('image/png')).toBe(true);
    });

    it('rejects application/octet-stream', () => {
        expect(isAllowedFileType('application/octet-stream')).toBe(false);
    });

    it('rejects video/mp4', () => {
        expect(isAllowedFileType('video/mp4')).toBe(false);
    });

    it('rejects application/zip', () => {
        expect(isAllowedFileType('application/zip')).toBe(false);
    });
});

describe('isFileSizeValid', () => {
    it('accepts 0 bytes', () => {
        expect(isFileSizeValid(0)).toBe(true);
    });

    it('accepts 1 MB', () => {
        expect(isFileSizeValid(1024 * 1024)).toBe(true);
    });

    it('accepts 49 MB', () => {
        expect(isFileSizeValid(49 * 1024 * 1024)).toBe(true);
    });

    it('accepts exactly 50 MB', () => {
        expect(isFileSizeValid(MAX_FILE_SIZE_BYTES)).toBe(true);
    });

    it('rejects 50 MB + 1 byte', () => {
        expect(isFileSizeValid(MAX_FILE_SIZE_BYTES + 1)).toBe(false);
    });

    it('rejects 100 MB', () => {
        expect(isFileSizeValid(100 * 1024 * 1024)).toBe(false);
    });
});

describe('extractTitleFromFilename', () => {
    it('extracts title from "report.pdf"', () => {
        expect(extractTitleFromFilename('report.pdf')).toBe('report');
    });

    it('extracts title from "my document.v2.docx"', () => {
        expect(extractTitleFromFilename('my document.v2.docx')).toBe('my document.v2');
    });

    it('handles "noextension"', () => {
        expect(extractTitleFromFilename('noextension')).toBe('noextension');
    });

    it('handles empty string', () => {
        expect(extractTitleFromFilename('')).toBe('');
    });
});

describe('formatFileSize', () => {
    it('formats 0 as "0 B"', () => {
        expect(formatFileSize(0)).toBe('0 B');
    });

    it('formats 512 as "512 B"', () => {
        expect(formatFileSize(512)).toBe('512 B');
    });

    it('formats 1024 as "1.0 KB"', () => {
        expect(formatFileSize(1024)).toBe('1.0 KB');
    });

    it('formats 1536 as "1.5 KB"', () => {
        expect(formatFileSize(1536)).toBe('1.5 KB');
    });

    it('formats 1048576 as "1.0 MB"', () => {
        expect(formatFileSize(1048576)).toBe('1.0 MB');
    });
});

describe('getFileTypeLabel', () => {
    it('returns "PDF" for application/pdf', () => {
        expect(getFileTypeLabel('application/pdf')).toBe('PDF');
    });

    it('returns "DOCX" for docx mime', () => {
        expect(
            getFileTypeLabel(
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            ),
        ).toBe('DOCX');
    });

    it('returns "TXT" for text/plain', () => {
        expect(getFileTypeLabel('text/plain')).toBe('TXT');
    });

    it('returns "MD" for text/markdown', () => {
        expect(getFileTypeLabel('text/markdown')).toBe('MD');
    });

    it('returns "Image" for image/jpeg', () => {
        expect(getFileTypeLabel('image/jpeg')).toBe('Image');
    });
});

describe('sanitizeHighlight', () => {
    it('preserves <mark> tags', () => {
        expect(sanitizeHighlight('hello <mark>world</mark>')).toBe(
            'hello <mark>world</mark>',
        );
    });

    it('strips non-mark HTML tags', () => {
        expect(sanitizeHighlight('<b>bold</b> <mark>match</mark>')).toBe(
            'bold <mark>match</mark>',
        );
    });

    it('escapes HTML entities in text', () => {
        expect(sanitizeHighlight('a < b & c > d')).toBe('a &lt; b &amp; c &gt; d');
    });

    it('strips script tags', () => {
        expect(sanitizeHighlight('<script>alert("xss")</script> <mark>safe</mark>')).toBe(
            'alert(&quot;xss&quot;) <mark>safe</mark>',
        );
    });

    it('handles empty string', () => {
        expect(sanitizeHighlight('')).toBe('');
    });

    it('handles text with no marks', () => {
        expect(sanitizeHighlight('plain text')).toBe('plain text');
    });

    it('handles multiple marks', () => {
        expect(sanitizeHighlight('<mark>a</mark> and <mark>b</mark>')).toBe(
            '<mark>a</mark> and <mark>b</mark>',
        );
    });
});

describe('getStatusColor', () => {
    it('returns "secondary" for UPLOADED', () => {
        expect(getStatusColor('UPLOADED')).toBe('secondary');
    });

    it('returns "secondary" for PROCESSING', () => {
        expect(getStatusColor('PROCESSING')).toBe('secondary');
    });

    it('returns "default" for INDEXED', () => {
        expect(getStatusColor('INDEXED')).toBe('default');
    });

    it('returns "destructive" for FAILED', () => {
        expect(getStatusColor('FAILED')).toBe('destructive');
    });
});
