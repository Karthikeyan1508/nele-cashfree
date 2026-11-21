"use client"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { PageHeader } from "@/components/page-header"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { StatusBadge } from "@/components/status-badge"
import { Config, LANG, inr, monthLabel, post, useApi } from "@/lib/api"

type Activity = {
  payments: { id: number; name: string; room: string; month: string; amount: number; paid: number; method: string; status: string; paid_ts: string | null; ts: string; txn_id: string | null; receipt_no: string | null }[]
  payouts: { id: number; payee: string; amount: number; reason: string; kind: string; status: string; day: string }[]
  tickets: { id: number; name: string; room: string; issue: string; status: string; ts: string }[]
  calls: { id: number; name: string; room: string; language: string; status: string; outcome: string | null; ts: string; transcript: string | null; reason: string | null; promise_date: string | null }[]
  audit: { ts: string; actor: string; action: string; payload: string }[]
}

export default function ActivityPage() {
  const { data: a, reload } = useApi<Activity>("/activity", 4000)
  const { data: cfg } = useApi<Config>("/config")
  const [said, setSaid] = useState<Record<number, string>>({})
  if (!a) return <p className="text-muted-foreground">Loading…</p>
  const say = async (id: number) => { await post(`/dev/simulate-call/${id}?said=${encodeURIComponent(said[id] ?? "")}`); setSaid({ ...said, [id]: "" }); reload() }
  return (
    <>
      <PageHeader title="Activity log" description="Payments, payouts, tickets, calls and audit trail" />
      <Tabs defaultValue="payments">
        <TabsList variant="line">
          <TabsTrigger value="payments">Rent payments</TabsTrigger><TabsTrigger value="payouts">Payouts</TabsTrigger>
          <TabsTrigger value="tickets">Tickets</TabsTrigger><TabsTrigger value="calls">Calls</TabsTrigger><TabsTrigger value="audit">Audit log</TabsTrigger>
        </TabsList>
        <Card className="mt-4"><CardContent className="px-0">
          <TabsContent value="payments">
            <Table>
              <TableHeader><TableRow><TableHead>When</TableHead><TableHead>Room</TableHead><TableHead>Tenant</TableHead><TableHead>Month</TableHead><TableHead>Amount</TableHead><TableHead>Method</TableHead><TableHead>Status</TableHead><TableHead>Transaction ID</TableHead><TableHead>Receipt</TableHead></TableRow></TableHeader>
              <TableBody>{a.payments.map((p) => (
                <TableRow key={p.id}><TableCell>{p.paid_ts ?? `link created ${p.ts}`}</TableCell><TableCell>{p.room}</TableCell><TableCell>{p.name}</TableCell><TableCell>{monthLabel(p.month)}</TableCell><TableCell>{inr(p.paid || p.amount)}</TableCell><TableCell className="uppercase">{p.method}</TableCell><TableCell><StatusBadge status={p.status} /></TableCell><TableCell className="font-mono text-xs">{p.txn_id ?? "—"}</TableCell><TableCell>{p.receipt_no ? <a className="underline" target="_blank" href={`/api/receipt/${p.receipt_no}`}>{p.receipt_no}</a> : "—"}</TableCell></TableRow>
              ))}</TableBody>
            </Table>
          </TabsContent>
          <TabsContent value="payouts">
            <Table>
              <TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Payee</TableHead><TableHead>Amount</TableHead><TableHead>Reason</TableHead><TableHead>Type</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
              <TableBody>{a.payouts.map((p) => (
                <TableRow key={p.id}><TableCell>{p.day}</TableCell><TableCell>{p.payee}</TableCell><TableCell>{inr(p.amount)}</TableCell><TableCell>{p.reason}</TableCell><TableCell>{p.kind}</TableCell><TableCell><StatusBadge status={p.status} /></TableCell></TableRow>
              ))}</TableBody>
            </Table>
          </TabsContent>
          <TabsContent value="tickets">
            <Table>
              <TableHeader><TableRow><TableHead>Raised</TableHead><TableHead>Room</TableHead><TableHead>Tenant</TableHead><TableHead>Issue</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
              <TableBody>{a.tickets.map((k) => (
                <TableRow key={k.id}><TableCell>{k.ts}</TableCell><TableCell>{k.room}</TableCell><TableCell>{k.name}</TableCell><TableCell>{k.issue}</TableCell><TableCell><StatusBadge status={k.status} /></TableCell></TableRow>
              ))}</TableBody>
            </Table>
          </TabsContent>
          <TabsContent value="calls">
            <Table>
              <TableHeader><TableRow><TableHead>Time</TableHead><TableHead>Tenant</TableHead><TableHead>Status</TableHead><TableHead>Outcome</TableHead><TableHead>Reason</TableHead><TableHead>Pays on</TableHead><TableHead>What they said</TableHead></TableRow></TableHeader>
              <TableBody>{a.calls.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="whitespace-nowrap">{c.ts}</TableCell><TableCell className="whitespace-nowrap">{c.room} · {c.name} <span className="text-muted-foreground">({LANG[c.language]})</span></TableCell><TableCell><StatusBadge status={c.status} /></TableCell>
                  <TableCell>{c.outcome?.replace(/_/g, " ") ?? "—"}</TableCell><TableCell className="max-w-48">{c.reason ?? "—"}</TableCell><TableCell>{c.promise_date ?? "—"}</TableCell>
                  <TableCell className="max-w-sm whitespace-pre-wrap text-xs">
                    {c.transcript?.trim() || (cfg && !cfg.twilio && !cfg.voice && !c.outcome ? (
                      <span className="flex gap-1"><Input className="h-8" placeholder="Type what the tenant says…" value={said[c.id] ?? ""} onChange={(e) => setSaid({ ...said, [c.id]: e.target.value })} /><Button size="sm" variant="outline" onClick={() => say(c.id)}>Send</Button></span>
                    ) : "—")}
                  </TableCell>
                </TableRow>
              ))}</TableBody>
            </Table>
            {cfg && !cfg.twilio && !cfg.voice && <p className="pt-3 text-xs text-muted-foreground">Mock mode: no phone provider configured, so calls are simulated. Type what the tenant would say, e.g. &quot;salary not came, I will pay on the 25th&quot; or &quot;I can pay now&quot;.</p>}
          </TabsContent>
          <TabsContent value="audit">
            <Table>
              <TableHeader><TableRow><TableHead>Time</TableHead><TableHead>Actor</TableHead><TableHead>Action</TableHead><TableHead>Details</TableHead></TableRow></TableHeader>
              <TableBody>{a.audit.map((x, i) => (
                <TableRow key={i}><TableCell className="whitespace-nowrap">{x.ts.slice(0, 19).replace("T", " ")}</TableCell><TableCell>{x.actor}</TableCell><TableCell>{x.action}</TableCell><TableCell className="max-w-xl truncate font-mono text-xs">{x.payload}</TableCell></TableRow>
              ))}</TableBody>
            </Table>
          </TabsContent>
        </CardContent></Card>
      </Tabs>
    </>
  )
}
