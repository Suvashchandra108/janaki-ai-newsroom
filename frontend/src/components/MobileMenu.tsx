'use client'

import { usePathname } from 'next/navigation'
import { useEffect, useRef } from 'react'

/** The phone menu. Closes itself after navigating, so the next tap opens it again. */
export function MobileMenu({ label, children }: { label: string; children: React.ReactNode }) {
  const ref = useRef<HTMLDetailsElement>(null)
  const path = usePathname()
  useEffect(() => {
    if (ref.current) ref.current.open = false
  }, [path])
  return (
    <details ref={ref} className="relative lg:hidden">
      <summary className="btn-secondary cursor-pointer list-none">☰ {label}</summary>
      <div className="absolute top-12 left-0 flex w-64 flex-col rounded-xl bg-brand shadow-xl">
        {children}
      </div>
    </details>
  )
}
