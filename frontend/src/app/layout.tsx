import type { Metadata, Viewport } from 'next'

import { getLocale } from '@/i18n/server'

import './globals.css'

export const metadata: Metadata = {
  title: { default: 'AI Newsroom', template: '%s · AI Newsroom' },
  robots: { index: false, follow: false },
}
export const viewport: Viewport = { width: 'device-width', initialScale: 1 }

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale()
  return (
    <html lang={locale}>
      <body className="min-h-screen">{children}</body>
    </html>
  )
}
