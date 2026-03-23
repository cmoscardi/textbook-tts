/**
 * Local JWT verification using Web Crypto API.
 * Eliminates the network call to GoTrue (supabase.auth.getUser),
 * which becomes a bottleneck under load.
 *
 * Supports both HS256 (hosted Supabase) and ES256 (local Supabase CLI).
 */

const encoder = new TextEncoder()

function base64UrlDecode(str: string): Uint8Array {
  let base64 = str.replace(/-/g, '+').replace(/_/g, '/')
  while (base64.length % 4 !== 0) {
    base64 += '='
  }
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes
}

// Cache imported keys to avoid re-importing on every request
let _hmacKey: CryptoKey | null = null
const _ecKeys = new Map<string, CryptoKey>()

async function getHmacKey(): Promise<CryptoKey> {
  if (_hmacKey) return _hmacKey

  // SUPABASE_JWT_SECRET is auto-injected on hosted Supabase;
  // MY_JWT_SECRET is the fallback for local dev (supabase CLI blocks SUPABASE_* from --env-file)
  const secret = Deno.env.get('SUPABASE_JWT_SECRET') ?? Deno.env.get('MY_JWT_SECRET')
  if (!secret) {
    throw new Error('No HMAC JWT secret configured')
  }

  _hmacKey = await crypto.subtle.importKey(
    'raw',
    encoder.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['verify'],
  )
  return _hmacKey
}

async function getEcKey(kid: string): Promise<CryptoKey | null> {
  if (_ecKeys.has(kid)) return _ecKeys.get(kid)!

  // SUPABASE_INTERNAL_JWT_KEYS is set by newer Supabase CLI; fall back to MY_JWT_KEYS for local dev
  const keysJson = Deno.env.get('SUPABASE_INTERNAL_JWT_KEYS') ?? Deno.env.get('MY_JWT_KEYS')
  if (!keysJson) return null

  try {
    const keys: Array<JsonWebKey & { kid?: string }> = JSON.parse(keysJson)
    const jwk = keys.find(k => k.kid === kid)
    if (!jwk) return null

    // Import as public key: keep only the fields WebCrypto needs
    const publicJwk = { kty: jwk.kty, crv: jwk.crv, x: jwk.x, y: jwk.y }
    const key = await crypto.subtle.importKey(
      'jwk',
      publicJwk,
      { name: 'ECDSA', namedCurve: 'P-256' },
      false,
      ['verify'],
    )
    _ecKeys.set(kid, key)
    return key
  } catch {
    return null
  }
}

/**
 * Verify a Supabase JWT and return the user info.
 * Returns { id: string } on success, or null on failure.
 */
export async function verifyJwt(
  token: string,
): Promise<{ id: string } | null> {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null

    const [headerB64, payloadB64, signatureB64] = parts

    // Parse header to determine algorithm
    const header = JSON.parse(new TextDecoder().decode(base64UrlDecode(headerB64)))
    const signedData = encoder.encode(`${headerB64}.${payloadB64}`)
    const signature = base64UrlDecode(signatureB64)

    let valid = false

    if (header.alg === 'ES256') {
      const key = await getEcKey(header.kid)
      if (!key) return null

      valid = await crypto.subtle.verify(
        { name: 'ECDSA', hash: 'SHA-256' },
        key,
        signature,
        signedData,
      )
    } else if (header.alg === 'HS256') {
      const key = await getHmacKey()
      valid = await crypto.subtle.verify('HMAC', key, signature, signedData)
    } else {
      return null
    }

    if (!valid) return null

    const payload = JSON.parse(new TextDecoder().decode(base64UrlDecode(payloadB64)))

    if (payload.exp && payload.exp < Math.floor(Date.now() / 1000)) {
      return null
    }

    if (!payload.sub) return null

    return { id: payload.sub }
  } catch {
    return null
  }
}
