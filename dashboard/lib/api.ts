"use client"
import { useCallback, useEffect, useState } from "react"

export function useApi<T>(path: string | null, every = 0) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => {
    if (!path) return
    try {
      const r = await fetch("/api" + path)
      if (!r.ok) throw new Error((await r.text()).slice(0, 200))
      setData(await r.json())
      setError(null)
    } catch (e) {
      setError(String(e))
    }
  }, [path])
  useEffect(() => {
    load()
    if (!every) return
    const t = setInterval(load, every)
    return () => clearInterval(t)
  }, [load, every])
  return { data, error, reload: load }
}

export async function post<T = unknown>(path: string, body?: unknown): Promise<T> {
  const r = await fetch("/api" + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  })
  if (!r.ok) throw new Error((await r.json().catch(() => ({ detail: r.statusText }))).detail ?? r.statusText)
  return r.json()
}

export const inr = (n: number | null | undefined) => "₹" + (n ?? 0).toLocaleString("en-IN")

export const monthLabel = (m: string) =>
  new Date(m + "-01").toLocaleString("en-IN", { month: "short", year: "numeric" })

export type Tenant = {
  id: number; name: string; phone: string; room: string; rent: number; deposit: number
  language: string; status: string; due: number | null; paid: number | null
  rent_status: string | null; promise_date: string | null
}
export type LedgerRow = {
  tenant_id: number; name: string; room: string; language: string; due: number; paid: number
  pending: number; status: string; promise_date: string | null; paid_on: string | null; method: string | null
}
export type Config = { mock_cashfree: boolean; sarvam: boolean; whatsapp: boolean; twilio: boolean; voice: boolean; owner_phone: string }

export const LANG: Record<string, string> = { kn: "Kannada", hi: "Hindi", bn: "Bengali", ml: "Malayalam", en: "English" }
