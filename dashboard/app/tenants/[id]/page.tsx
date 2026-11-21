"use client"
import { useState } from "react"
import { useParams } from "next/navigation"
import { toast } from "sonner"
import { AlertTriangle, CheckCircle, Copy, ExternalLink, RefreshCw, Zap } from "lucide-react"
import { PersonAvatar } from "@/components/person-avatar"
import { Skeleton } from "@/components/ui/skeleton"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Button } from "@/components/ui/button"
import { StatusBadge } from "@/components/status-badge"
import { LANG, Tenant, inr, monthLabel, post, useApi } from "@/lib/api"

type Detail = {
  tenant: Tenant
  ledger: { month: string; due: number; paid: number; pending: number; status: string; promise_date: string | null }[]
  payments: { amount: number; paid: number; month: string; method: string; status: string; paid_ts: string | null; ts: string; txn_id: string | null; receipt_no: string | null }[]
  promises: { amount: number; date: string; reason: string | null; ts: string }[]
  tickets: { id: number; issue: string; status: string; ts: string }[]
  profile: { id: number; form_json: string; has_aadhaar: number; has_photo: number } | null
  calls: { id: number; month: string; status: string; outcome: string | null; ts: string; transcript: string | null; reason: string | null; promise_date: string | null }[]
  subscription?: {
    id: number
    subscription_id: string
    plan_id: string
    amount: number
    status: string
    auth_url: string
    created: string
    activated_at: string | null
    last_charged_at: string | null
    last_error: string | null
    recovery_count: number
  } | null
}

const Empty = ({ n }: { n: number }) => (n ? null : <p className="py-4 text-sm text-muted-foreground">Nothing yet.</p>)

export default function TenantPage() {
  const { id } = useParams<{ id: string }>()
  const { data: d, error, reload } = useApi<Detail>(`/tenants/${id}`, 5000)
  const [busy, setBusy] = useState(false)

  if (error) return <p className="text-red-600">{error}</p>
  if (!d) return <div className="space-y-6"><Skeleton className="h-16 w-72" /><Skeleton className="h-64 w-full rounded-xl" /></div>

  const t = d.tenant
  const sub = d.subscription
  const info = [
    ["Room", t.room], ["Phone", t.phone], ["Language", LANG[t.language]], ["Monthly rent", inr(t.rent)], ["Deposit held", inr(t.deposit)],
  ]

  async function act(endpoint: string, successMsg: string) {
    setBusy(true)
    try {
      await post(endpoint)
      toast.success(successMsg)
      reload()
    } catch (e) {
      toast.error(String(e).replace("Error: ", ""))
    }
    setBusy(false)
  }

  return (
    <>
      <div className="flex items-center gap-4">
        <PersonAvatar name={t.name} className="size-14" />
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">{t.name}</h1>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            Room {t.room} · {t.phone}
            <StatusBadge status={t.rent_status ?? d.ledger[0]?.status ?? null} />
            {sub && <span className="inline-flex items-center gap-1 text-xs text-muted-foreground font-medium border rounded-md px-2 py-0.5"><Zap className="size-3 text-amber-500 fill-amber-500" /> AutoPay: {sub.status.replace(/_/g, " ")}</span>}
          </div>
        </div>
      </div>

      <div className="grid gap-5 sm:grid-cols-3 lg:grid-cols-5">
        {info.map(([k, v]) => (
          <Card key={k}><CardHeader><CardDescription className="text-xs font-medium uppercase tracking-wide">{k}</CardDescription><CardTitle className="text-xl font-semibold tracking-tight">{v}</CardTitle></CardHeader></Card>
        ))}
      </div>

      {d.profile && (() => {
        const p = JSON.parse(d.profile.form_json) as Record<string, string>
        const rows: [string, string][] = [
          ["Email", p.email], ["WhatsApp", p.whatsapp], ["Date of birth", p.dob], ["Gender", p.gender],
          [p.occupation === "student" ? "College" : "Company", `${p.org_name}, ${p.org_role}`],
          ["Languages", [p.primary_language, p.secondary_language].filter(Boolean).join(", ")],
          ["Emergency contact", `${p.emergency_name} (${p.emergency_relation}) ${p.emergency_phone}`],
          ["Food", p.food], ["Address", p.address]
        ]
        return (
          <Card>
            <CardHeader><CardTitle>Profile</CardTitle><CardDescription>From the onboarding form</CardDescription></CardHeader>
            <CardContent className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
              {rows.filter(([, v]) => v).map(([k, v]) => <div key={k}><div className="text-xs text-muted-foreground">{k}</div>{v}</div>)}
              <div className="flex gap-3 sm:col-span-2 lg:col-span-3">
                {d.profile.has_aadhaar ? <a className="underline underline-offset-4" target="_blank" href={`/api/onboarding/${d.profile.id}/file/aadhaar`}>View Aadhaar</a> : null}
                {d.profile.has_photo ? <a className="underline underline-offset-4" target="_blank" href={`/api/onboarding/${d.profile.id}/file/photo`}>View photo</a> : null}
              </div>
            </CardContent>
          </Card>
        )
      })()}

      <Tabs defaultValue="rent">
        <TabsList variant="line">
          <TabsTrigger value="rent">Rent log</TabsTrigger>
          <TabsTrigger value="payments">Payments</TabsTrigger>
          <TabsTrigger value="autopay" className="gap-1.5"><Zap className="size-3.5" /> AutoPay (Relay)</TabsTrigger>
          <TabsTrigger value="promises">Promises</TabsTrigger>
          <TabsTrigger value="tickets">Tickets</TabsTrigger>
          <TabsTrigger value="calls">Calls</TabsTrigger>
        </TabsList>

        <Card className="mt-4">
          <CardContent className="px-0">
            <TabsContent value="rent">
              <Table>
                <TableHeader><TableRow><TableHead>Month</TableHead><TableHead>Due</TableHead><TableHead>Paid</TableHead><TableHead>Pending</TableHead><TableHead>Status</TableHead><TableHead>Promise</TableHead></TableRow></TableHeader>
                <TableBody>{d.ledger.map((l) => (
                  <TableRow key={l.month}><TableCell>{monthLabel(l.month)}</TableCell><TableCell>{inr(l.due)}</TableCell><TableCell>{inr(l.paid)}</TableCell><TableCell>{inr(l.pending)}</TableCell><TableCell><StatusBadge status={l.status} /></TableCell><TableCell>{l.promise_date ?? "—"}</TableCell></TableRow>
                ))}</TableBody>
              </Table>
            </TabsContent>

            <TabsContent value="payments">
              <Table>
                <TableHeader><TableRow><TableHead>Paid on</TableHead><TableHead>For month</TableHead><TableHead>Amount</TableHead><TableHead>Method</TableHead><TableHead>Status</TableHead><TableHead>Transaction ID</TableHead><TableHead>Receipt</TableHead></TableRow></TableHeader>
                <TableBody>{d.payments.map((p, i) => (
                  <TableRow key={i}><TableCell>{p.paid_ts ?? `link created ${p.ts}`}</TableCell><TableCell>{monthLabel(p.month)}</TableCell><TableCell>{inr(p.paid || p.amount)}</TableCell><TableCell className="uppercase">{p.method}</TableCell><TableCell><StatusBadge status={p.status} /></TableCell><TableCell className="font-mono text-xs">{p.txn_id ?? "—"}</TableCell><TableCell>{p.receipt_no ? <a className="underline" target="_blank" href={`/api/receipt/${p.receipt_no}`}>{p.receipt_no}</a> : "—"}</TableCell></TableRow>
                ))}</TableBody>
              </Table><Empty n={d.payments.length} />
            </TabsContent>

            <TabsContent value="autopay" className="px-6 py-4 space-y-6">
              {!sub ? (
                <div className="space-y-4 max-w-xl">
                  <div className="flex items-center gap-3">
                    <div className="p-2.5 rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-950 dark:text-blue-400"><Zap className="size-6" /></div>
                    <div>
                      <h3 className="font-semibold text-base">Cashfree Relay AutoPay Not Set Up</h3>
                      <p className="text-sm text-muted-foreground">Enable UPI AutoPay recurring mandate for monthly rent. Cashfree Relay Super Agent will monitor and automatically recover failed debits.</p>
                    </div>
                  </div>
                  <Button disabled={busy} onClick={() => act(`/tenants/${t.id}/autopay`, `AutoPay mandate link sent to ${t.name} on WhatsApp`)} className="rounded-xl">
                    <Zap className="mr-1.5 size-4" /> Set Up AutoPay for {inr(t.rent)}/mo
                  </Button>
                </div>
              ) : (
                <div className="space-y-6 max-w-2xl">
                  <div className="flex flex-wrap items-center justify-between gap-4 border-b pb-4">
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="font-semibold text-lg">UPI AutoPay Mandate</h3>
                        <StatusBadge status={sub.status} />
                      </div>
                      <p className="text-xs text-muted-foreground mt-0.5">Subscription ID: <code className="font-mono">{sub.subscription_id}</code></p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button variant="outline" size="sm" onClick={() => { navigator.clipboard.writeText(sub.auth_url); toast.success("Mandate link copied") }}>
                        <Copy className="size-3.5 mr-1" /> Copy Link
                      </Button>
                      <Button variant="outline" size="sm" render={<a href={sub.auth_url} target="_blank" rel="noreferrer" />}>
                        <ExternalLink className="size-3.5 mr-1" /> Open Auth Page
                      </Button>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                    <div><div className="text-xs text-muted-foreground">Monthly Amount</div><div className="font-semibold text-base">{inr(sub.amount)}</div></div>
                    <div><div className="text-xs text-muted-foreground">Frequency</div><div className="font-medium">Monthly (5th)</div></div>
                    <div><div className="text-xs text-muted-foreground">Activated On</div><div className="font-medium">{sub.activated_at ?? "Pending authorization"}</div></div>
                    <div><div className="text-xs text-muted-foreground">Last Auto-Debited</div><div className="font-medium">{sub.last_charged_at ?? "Not charged yet"}</div></div>
                  </div>

                  {sub.status === "recovery_in_progress" && (
                    <div className="rounded-xl border border-amber-200 bg-amber-50/80 p-4 text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-200 space-y-2">
                      <div className="flex items-center gap-2 font-semibold">
                        <AlertTriangle className="size-4 text-amber-600" />
                        <span>Cashfree Relay Recovery Active (Attempt #{sub.recovery_count})</span>
                      </div>
                      <p className="text-xs">
                        The recurring debit encountered an issue ({sub.last_error?.replace(/_/g, " ") ?? "declined"}). The Cashfree Relay agent sent an automated WhatsApp recovery note with a retry payment link to {t.name}.
                      </p>
                    </div>
                  )}

                  {sub.status === "active" && (
                    <div className="rounded-xl border border-emerald-200 bg-emerald-50/80 p-4 text-emerald-900 dark:border-emerald-900/50 dark:bg-emerald-950/40 dark:text-emerald-200 flex items-center gap-3">
                      <CheckCircle className="size-5 text-emerald-600 shrink-0" />
                      <div className="text-xs">
                        Mandate is active. Monthly rent of <strong>{inr(sub.amount)}</strong> will automatically debit. Protected by Cashfree Relay Autonomous Dunning.
                      </div>
                    </div>
                  )}

                  <div className="pt-2 border-t space-y-3">
                    <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Simulation & Operations</div>
                    <div className="flex flex-wrap gap-2">
                      {sub.status !== "active" && (
                        <Button size="sm" variant="default" disabled={busy} onClick={() => act(`/tenants/${t.id}/autopay/simulate-activate`, "Simulated mandate activation")}>
                          <CheckCircle className="mr-1.5 size-4" /> Simulate Mandate Activation
                        </Button>
                      )}
                      <Button size="sm" variant="outline" disabled={busy} onClick={() => act(`/tenants/${t.id}/autopay/simulate-charge`, `Simulated successful auto-debit of ${inr(sub.amount)}`)}>
                        <Zap className="mr-1.5 size-4 text-emerald-600" /> Simulate Auto-Debit (Success)
                      </Button>
                      <Button size="sm" variant="destructive" disabled={busy} onClick={() => act(`/tenants/${t.id}/autopay/simulate-failure`, "Triggered failed debit -> Cashfree Relay recovery agent")}>
                        <AlertTriangle className="mr-1.5 size-4" /> Simulate Debit Failure (Relay Recovery)
                      </Button>
                      <Button size="sm" variant="ghost" disabled={busy} onClick={() => act(`/tenants/${t.id}/autopay`, "Mandate link resent on WhatsApp")}>
                        <RefreshCw className="mr-1.5 size-4" /> Resend Mandate Link
                      </Button>
                    </div>
                  </div>
                </div>
              )}
            </TabsContent>

            <TabsContent value="promises">
              <Table>
                <TableHeader><TableRow><TableHead>Noted on</TableHead><TableHead>Will pay on</TableHead><TableHead>Amount</TableHead><TableHead>Reason</TableHead></TableRow></TableHeader>
                <TableBody>{d.promises.map((p, i) => <TableRow key={i}><TableCell>{p.ts}</TableCell><TableCell>{p.date}</TableCell><TableCell>{inr(p.amount)}</TableCell><TableCell>{p.reason ?? "—"}</TableCell></TableRow>)}</TableBody>
              </Table><Empty n={d.promises.length} />
            </TabsContent>

            <TabsContent value="tickets">
              <Table>
                <TableHeader><TableRow><TableHead>Raised</TableHead><TableHead>Issue</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
                <TableBody>{d.tickets.map((k) => <TableRow key={k.id}><TableCell>{k.ts}</TableCell><TableCell>{k.issue}</TableCell><TableCell><StatusBadge status={k.status} /></TableCell></TableRow>)}</TableBody>
              </Table><Empty n={d.tickets.length} />
            </TabsContent>

            <TabsContent value="calls">
              <Table>
                <TableHeader><TableRow><TableHead>Time</TableHead><TableHead>Month</TableHead><TableHead>Outcome</TableHead><TableHead>Reason</TableHead><TableHead>Pays on</TableHead><TableHead>What they said</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
                <TableBody>{d.calls.map((c) => <TableRow key={c.id}><TableCell>{c.ts}</TableCell><TableCell>{monthLabel(c.month)}</TableCell><TableCell>{c.outcome?.replace(/_/g, " ") ?? "—"}</TableCell><TableCell>{c.reason ?? "—"}</TableCell><TableCell>{c.promise_date ?? "—"}</TableCell><TableCell className="max-w-xs whitespace-pre-wrap text-xs">{c.transcript?.trim() || "—"}</TableCell><TableCell><StatusBadge status={c.status} /></TableCell></TableRow>)}</TableBody>
              </Table><Empty n={d.calls.length} />
            </TabsContent>
          </CardContent>
        </Card>
      </Tabs>
    </>
  )
}
