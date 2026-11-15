'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

export type NavItem = { href: string; label: string; icon: string }

export function NavLinks({ items }: { items: NavItem[] }) {
  const path = usePathname()
  return (
    <ul className="flex flex-col gap-0.5">
      {items.map((it) => {
        const active = it.href === '/' ? path === '/' : path.startsWith(it.href)
        return (
          <li key={it.href}>
            <Link
              href={it.href}
              aria-current={active ? 'page' : undefined}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${
                active
                  ? 'bg-white/15 font-semibold text-white'
                  : 'text-white/75 hover:bg-white/10 hover:text-white'
              }`}
            >
              <span aria-hidden className="w-5 text-center">
                {it.icon}
              </span>
              {it.label}
            </Link>
          </li>
        )
      })}
    </ul>
  )
}
