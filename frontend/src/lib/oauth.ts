/**
 * OAuth 2.0 / OIDC utilities for PKCE and code exchange.
 */

/**
 * Generate PKCE code_verifier (random 32 bytes, base64url-encoded).
 */
export function generateCodeVerifier(): string {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return base64UrlEncode(bytes);
}

/**
 * Generate PKCE code_challenge from code_verifier (S256).
 */
export async function generateCodeChallenge(codeVerifier: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(codeVerifier);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  return base64UrlEncode(new Uint8Array(hashBuffer));
}

/**
 * Encode bytes as base64url (RFC 4648 - no padding).
 */
function base64UrlEncode(bytes: Uint8Array): string {
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

/**
 * Decode base64url string to bytes.
 */
function base64UrlDecode(str: string): Uint8Array {
  let binary = atob(str.replace(/-/g, '+').replace(/_/g, '/'));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

/**
 * Parse JWT payload (without verification).
 */
export function parseJwt(token: string): Record<string, unknown> {
  const parts = token.split('.');
  if (parts.length !== 3) {
    throw new Error('Invalid JWT format');
  }

  try {
    const payload = base64UrlDecode(parts[1]);
    const json = new TextDecoder().decode(payload);
    return JSON.parse(json) as Record<string, unknown>;
  } catch (e) {
    throw new Error(`Failed to decode JWT: ${e}`);
  }
}

/**
 * Generate random state token.
 */
export function generateState(): string {
  return generateCodeVerifier();
}
