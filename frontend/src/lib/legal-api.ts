import { api } from './api';
import {
    CurrentLegalVersionSchema,
    LegalDocumentSchema,
    type CurrentLegalVersion,
    type LegalDocument,
    type LegalDocType,
} from '$lib/schemas/legal';

export type { CurrentLegalVersion, LegalDocument, LegalDocType };

export async function fetchCurrentLegalVersion(): Promise<CurrentLegalVersion> {
    return await api.get<CurrentLegalVersion>('/legal/current', {
        schema: CurrentLegalVersionSchema,
    });
}

export async function fetchLegalDocument(
    version: string,
    doc: LegalDocType,
): Promise<LegalDocument> {
    return await api.get<LegalDocument>(`/legal/versions/${version}/${doc}`, {
        schema: LegalDocumentSchema,
    });
}

export async function acceptTos(): Promise<unknown> {
    return await api.post('/auth/accept-tos', undefined);
}
