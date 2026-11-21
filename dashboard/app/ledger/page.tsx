"use client"
import { useEffect, useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { PageHeader } from "@/components/page-header"
import { Pick } from "@/components/pick"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { StatusBadge } from "@/components/status-badge"
import { LedgerRow, inr, monthLabel, useApi } from "@/lib/api"

type Ledger = { month: string; months: string[]; rows: LedgerRow[] }

function Matrix({ months }: { months: string[] }) {
  const [all, setAll] = useState<Record<string, LedgerRow[]>>({})
  useEffect(() => {
    const load = () =>
      Promise.all(months.map((m) => fetch(`/api/ledger?month=${m}`).then((r) => r.json() as Promise<Ledger>))).then((ls) =>
        setAll(Object.fromEntries(ls.map((l) => [l.month, l.rows]))))
    load()
    const t = setInterval(load, 8000)
    return () => clearInterval(t)
  }, [months])
  const ordered = [...months].reverse()
  const tenants = (all[months[0]] ?? []).map((r) => ({ id: r.tenant_id, name: r.name, room: r.room }))
  return (
    <Table>
      <TableHeader><TableRow><TableHead>Tenant</TableHead>{ordered.map((m) => <TableHead key={m}>{monthLabel(m)}</TableHead>)}</TableRow></TableHeader>
      <TableBody>
        {tenants.map((t) => (
          <TableRow key={t.id}>
            <TableCell className="whitespace-nowrap">{t.room} · {t.name}</TableCell>
            {ordered.map((m) => {
              const r = all[m]?.find((x) => x.tenant_id === t.id)
              return (
                <TableCell key={m}>{r ? <div className="space-y-1"><StatusBadge status={r.status} /><div className="text-xs text-muted-foreground">{inr(r.paid)} / {inr(r.due)}</div></div> : "—"}</TableCell>
              )
            })}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

export default function LedgerPage() {
  const [month, setMonth] = useState("")
  const { data } = useApi<Ledger>(`/ledger${month ? `?month=${month}` : ""}`, 5000)
  const rows = data?.rows ?? []
  const sum = (k: "due" | "paid" | "pending") => rows.reduce((a, r) => a + r[k], 0)
  return (
    <>
      <PageHeader title="Rent ledger" description={`Due ${inr(sum("due"))} · Collected ${inr(sum("paid"))} · Pending ${inr(sum("pending"))}`}>
        <Pick value={month || data?.month || ""} onChange={setMonth} options={(data?.months ?? []).map((m) => ({ value: m, label: monthLabel(m) }))} />
      </PageHeader>
      <Tabs defaultValue="month">
        <TabsList variant="line"><TabsTrigger value="month">Selected month</TabsTrigger><TabsTrigger value="all">All months</TabsTrigger></TabsList>
        <Card className="mt-4"><CardContent className="px-0">
          <TabsContent value="month">
            <Table>
              <TableHeader><TableRow><TableHead>Room</TableHead><TableHead>Tenant</TableHead><TableHead>Due</TableHead><TableHead>Paid</TableHead><TableHead>Pending</TableHead><TableHead>Status</TableHead><TableHead>Paid on</TableHead><TableHead>Method</TableHead><TableHead>Promise</TableHead></TableRow></TableHeader>
              <TableBody>{rows.map((r) => (
                <TableRow key={r.tenant_id}>
                  <TableCell>{r.room}</TableCell><TableCell>{r.name}</TableCell><TableCell>{inr(r.due)}</TableCell><TableCell>{inr(r.paid)}</TableCell><TableCell>{inr(r.pending)}</TableCell>
                  <TableCell><StatusBadge status={r.status} /></TableCell><TableCell>{r.paid_on ?? "—"}</TableCell><TableCell className="uppercase">{r.method ?? "—"}</TableCell><TableCell>{r.promise_date ?? "—"}</TableCell>
                </TableRow>
              ))}</TableBody>
            </Table>
          </TabsContent>
          <TabsContent value="all">{data && <Matrix months={data.months} />}</TabsContent>
        </CardContent></Card>
      </Tabs>
    </>
  )
}
