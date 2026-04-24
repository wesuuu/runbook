import { z } from 'zod';

// Lenient UUID format check. Accepts any 8-4-4-4-12 hex string regardless of
// the RFC-9562 version nibble. Zod v4's built-in `.uuid()` requires version
// 1-8, which rejects the dev seed data (e.g. `20000000-0000-0000-0000-
// 000000000001` has version nibble `0`). Backend Pydantic is the source of
// truth for UUID validity; this schema is just a shape check on responses.
const UUID_REGEX =
    /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

export const uuidString = () =>
    z.string().regex(UUID_REGEX, 'Invalid UUID format');
