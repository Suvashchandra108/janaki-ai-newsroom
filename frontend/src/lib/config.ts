/** Server-side configuration. Never imported by client components. */
export const API_URL = (process.env.NEWSROOM_API_URL || 'http://localhost:8000').replace(/\/$/, '')
export const IS_PROD = process.env.NODE_ENV === 'production'
/**
 * Session cookies are `Secure` in production. Set COOKIE_SECURE=false only to test a production
 * build over plain http on your own machine; never on a public server.
 */
export const COOKIE_SECURE = IS_PROD && process.env.COOKIE_SECURE !== 'false'
