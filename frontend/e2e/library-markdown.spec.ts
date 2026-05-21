import { test, expect } from '@playwright/test';
import { loginViaApi } from './helpers/auth';
import {
    uploadDocumentViaApi,
    uploadBinaryDocumentViaApi,
    deleteDocumentViaApi,
    waitForIndexed,
} from './helpers/library';
import { libraryUrl, libraryDocUrl } from './helpers/slug-urls';
import path from 'path';

test.describe('Document Markdown Rendering', () => {
    const createdDocumentIds: string[] = [];

    test.afterEach(async ({ page }) => {
        for (const id of createdDocumentIds) {
            try {
                await deleteDocumentViaApi(page, id);
            } catch {
                // Ignore cleanup errors
            }
        }
        createdDocumentIds.length = 0;
    });

    test('PDF renders with Markdown formatting', async ({ page }) => {
        test.slow(); // PDF processing may take time
        await loginViaApi(page, 'admin');
        await page.goto(await libraryUrl(page));
        await page.waitForLoadState('networkidle');

        // Upload sample PDF
        const fixturePath = path.resolve(__dirname, 'fixtures/sample.pdf');
        const doc = await uploadBinaryDocumentViaApi(
            page,
            'Markdown PDF Test',
            fixturePath,
            'sample.pdf',
            'application/pdf',
        );
        createdDocumentIds.push(doc.id);

        // Wait for processing to complete
        await waitForIndexed(page, doc.id);

        // Navigate to detail page
        await page.goto(await libraryDocUrl(page, doc.id));
        await page.waitForLoadState('networkidle');

        // Verify title is visible
        await expect(page.getByText('Markdown PDF Test')).toBeVisible();

        // Verify the content renders (PDF chunks should be visible)
        // The prose container should be present for markdown content
        const proseContainer = page.locator('.prose');
        await expect(proseContainer.first()).toBeVisible({ timeout: 10000 });

        // Verify actual text from the PDF is present
        await expect(page.getByText('Sample Document')).toBeVisible();
    });

    test('plain text document renders without Markdown', async ({ page }) => {
        await loginViaApi(page, 'admin');
        await page.goto(await libraryUrl(page));
        await page.waitForLoadState('networkidle');

        // Upload a plain text document
        const doc = await uploadDocumentViaApi(
            page,
            'Plain Text Test',
            'This is plain text content.\nNo markdown here.\nJust regular text.',
        );
        createdDocumentIds.push(doc.id);

        // Wait for processing
        await waitForIndexed(page, doc.id);

        // Navigate to detail page
        await page.goto(await libraryDocUrl(page, doc.id));
        await page.waitForLoadState('networkidle');

        // Verify title
        await expect(page.getByText('Plain Text Test')).toBeVisible();

        // Plain text should render with whitespace-pre-wrap class, not prose
        const plainContainer = page.locator('.whitespace-pre-wrap');
        await expect(plainContainer.first()).toBeVisible({ timeout: 10000 });

        // Verify content is present
        await expect(page.getByText('This is plain text content.')).toBeVisible();

        // Should NOT have markdown-rendered heading elements from the content
        const headings = page.locator('.prose h1, .prose h2, .prose h3');
        await expect(headings).toHaveCount(0);
    });
});
