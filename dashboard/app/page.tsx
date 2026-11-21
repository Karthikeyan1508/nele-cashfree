"use client"
import { useState } from "react"
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts"
import { toast } from "sonner"
import { AlertCircle, BedDouble, CalendarDays, HandCoins, Landmark, PhoneCall, Wallet, Wrench } from "lucide-react"
import { PageHeader } from "@/components/page-header"
import { PersonAvatar } from "@/components/person-avatar"
import { Pick } from "@/components/pick"
import { StatusBadge } from "@/components/status-badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { LedgerRow, inr, monthLabel, post, useApi } from "@/lib/api"

type Overview = {
  summary: { collected: number; pending: number; collection_rate: number; repairs_spent: number; beds_vacant: number; deposits_held: number; wallet_balance: number | null; wallet_status: "live" | "unavailable"; month: string }
  series: { month: string; due: number; paid: number }[]
  statuses: { status: string; n: number }[]
  open_tickets: number
  tenants: number
  recent_calls: { id: number; name: string; room: string; status: string; outcome: string | null; ts: string }[]
}

const chart = {
  due: { label: "Rent due", color: "var(--chart-3)" },
  paid: { label: "Collected", color: "var(--chart-1)" },
} satisfies ChartConfig

export default function Overview() {
  const [month, setMonth] = useState("")
  const q = month ? `?month=${month}` : ""
  const ov = useApi<Overview>(`/overview${q}`, 5000)
  const led = useApi<{ months: string[]; rows: LedgerRow[] }>(`/ledger${q}`, 5000)
  const s = ov.data?.summary
  const late = led.data?.rows.filter((r) => r.pending > 0) ?? []

  async function callAll() {
    const id = toast.loading("Placing reminder calls…")
    try {
      const r = await post<{ calls: unknown[] }>("/tools/send_reminders")
      toast.success(`Placed ${r.calls.length} reminder calls`, { id })
      ov.reload()
    } catch (e) {
      toast.error(String(e), { id })
    }
  }

  const kpis = s && ov.data ? [
    { label: "Collected", value: inr(s.collected), hint: `${s.collection_rate}% of rent due`, icon: Wallet, tone: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300" },
    { label: "Pending", value: inr(s.pending), hint: `${late.length} ${late.length === 1 ? "tenant" : "tenants"} yet to pay`, icon: CalendarDays, tone: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300" },
    { label: "Repairs paid", value: inr(s.repairs_spent), hint: `${ov.data.open_tickets} open tickets`, icon: Wrench, tone: "bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300" },
    { label: "Deposits held", value: inr(s.deposits_held), hint: `from ${ov.data.tenants} tenants`, icon: Landmark, tone: "bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300" },
    { label: "Cashfree wallet", value: s.wallet_balance == null ? "Unavailable" : inr(s.wallet_balance), hint: s.wallet_status === "live" ? "Live available payout balance" : "Connect Cashfree Payouts credentials", icon: HandCoins, tone: "bg-teal-100 text-teal-700 dark:bg-teal-950 dark:text-teal-300" },
    { label: "Beds vacant", value: String(s.beds_vacant), hint: `of ${ov.data.tenants + s.beds_vacant} beds`, icon: BedDouble, tone: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300" },
  ] : []

  return (
    <>
      <PageHeader title="Overview" description="This month's rent at a glance">
        <Pick icon={CalendarDays} value={month || s?.month || ""} onChange={setMonth} options={(led.data?.months ?? []).map((m) => ({ value: m, label: monthLabel(m) }))} />
        <Button className="h-9 rounded-xl" onClick={callAll} disabled={!late.length}><PhoneCall /> Call all late tenants</Button>
      </PageHeader>

      {ov.error && (
        <Alert variant="destructive"><AlertCircle /><AlertTitle>Backend unreachable</AlertTitle><AlertDescription>{ov.error}</AlertDescription></Alert>
      )}

      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {!ov.data && Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-32 rounded-xl" />)}
        {kpis.map(({ label, value, hint, icon: Icon, tone }) => (
          <Card key={label}>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardDescription className="text-xs font-medium uppercase tracking-wide">{label}</CardDescription>
                <div className={`flex size-8 items-center justify-center rounded-lg ${tone}`}><Icon className="size-4" /></div>
              </div>
              <CardTitle className="pt-1 text-3xl font-semibold tracking-tight">{value}</CardTitle>
            </CardHeader>
            <CardContent className="text-xs text-muted-foreground">{hint}</CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Rent by month</CardTitle><CardDescription>Due vs collected, last 6 months</CardDescription></CardHeader>
          <CardContent>
            <ChartContainer config={chart} className="h-64 w-full">
              <BarChart data={(ov.data?.series ?? []).map((x) => ({ ...x, label: monthLabel(x.month) }))} barGap={6}>
                <CartesianGrid vertical={false} strokeDasharray="3 3" />
                <XAxis dataKey="label" tickLine={false} axisLine={false} tickMargin={8} />
                <YAxis tickLine={false} axisLine={false} width={48} tickFormatter={(v) => `${v / 1000}k`} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Bar dataKey="due" fill="var(--color-due)" radius={[6, 6, 0, 0]} />
                <Bar dataKey="paid" fill="var(--color-paid)" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ChartContainer>
          </CardContent>
        </Card>

        <div className="grid gap-5">
          <Card>
            <CardHeader><CardDescription className="text-xs font-medium uppercase tracking-wide">Collection this month</CardDescription>
              <CardTitle className="text-3xl font-semibold tracking-tight">{s?.collection_rate ?? 0}%</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              <Progress value={s?.collection_rate ?? 0} />
              <p className="text-xs text-muted-foreground">{inr(s?.collected)} of {inr((s?.collected ?? 0) + (s?.pending ?? 0))} collected</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Latest reminder calls</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {(ov.data?.recent_calls ?? []).map((c) => (
                <div key={c.id} className="flex items-center gap-3 text-sm">
                  <PersonAvatar name={c.name} className="size-8" />
                  <div className="min-w-0 flex-1 leading-tight">
                    <div className="truncate font-medium">{c.name}</div>
                    <div className="truncate text-xs capitalize text-muted-foreground">{c.outcome?.replace(/_/g, " ") ?? "waiting"}</div>
                  </div>
                  <StatusBadge status={c.status} />
                </div>
              ))}
              {!ov.data?.recent_calls.length && <p className="text-sm text-muted-foreground">No calls yet.</p>}
            </CardContent>
          </Card>
        </div>
      </div>

      <Card>
        <CardHeader><CardTitle>Not paid yet</CardTitle><CardDescription>Tenants with rent pending for the selected month</CardDescription></CardHeader>
        <CardContent className="px-0">
          <Table>
            <TableHeader><TableRow><TableHead>Tenant</TableHead><TableHead>Room</TableHead><TableHead>Pending</TableHead><TableHead>Status</TableHead><TableHead>Will pay on</TableHead></TableRow></TableHeader>
            <TableBody>
              {late.map((r) => (
                <TableRow key={r.tenant_id}>
                  <TableCell><div className="flex items-center gap-3"><PersonAvatar name={r.name} className="size-8" /><span className="font-medium">{r.name}</span></div></TableCell>
                  <TableCell>{r.room}</TableCell><TableCell className="font-medium">{inr(r.pending)}</TableCell>
                  <TableCell><StatusBadge status={r.status} /></TableCell><TableCell>{r.promise_date ?? "—"}</TableCell>
                </TableRow>
              ))}
              {!late.length && <TableRow><TableCell colSpan={5} className="py-10 text-center text-muted-foreground">Everyone has paid. 🎉</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  )
}
