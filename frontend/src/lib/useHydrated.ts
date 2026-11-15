'use client'

import { useSyncExternalStore } from 'react'

const noop = () => () => {}

/** False during server rendering and before hydration; true once buttons can actually work. */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    noop,
    () => true,
    () => false,
  )
}
