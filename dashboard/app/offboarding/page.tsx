"use client"
import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Check, CircleDot, Copy, LogOut, Plus, Send, Trash2, X } from "lucide-react"
import { PageHeader } from "@/components/page-header"
import { PersonAvatar } from "@/components/person-avatar"
import { Pick } from "@/components/pick"
import { StatusBadge } from "@/components/status-badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tenant, inr, post, useApi } from "@/lib/api"

type Row = { id: number; tenant_id: number; name: string; room: string; move_out_date: string; status: string; refund: number; shortfall: number; created: string }
type Ded = { reason: string; amount: number }
type Figures = { deposit: number; deductions: Ded[]; deductions_total: number; unpaid_dues: number; refund: number; shortfall: number }
type Detail = {
  id: number; tenant_id: number; status: string; move_out_date: string; reason: string | null; figures: Figures
  tenant: { name: string; room: string; phone: string }; dispute_note: string | null; link: string | null
  bank: { holder: string; last4: string; ifsc: string } | null; payout: { id: number; amount: number; status: string } | null
}

const STEPS = ["notice", "proposed", "accepted", "refunded"]
const STEP_LABEL = ["Move-out noted", "Settlement sent", "Tenant confirmed", "Refund sent"]
const today = () => new Date().toISOString().slice(0, 10)

function Start({ open, onClose, preset, onDone }: { open: boolean; onClose: () => void; preset: string; onDone: (id: number) => void }) {
  const { data: tenants } = useApi<Tenant[]>("/tenants/all")
  const [f, setF] = useState({ tenant: "", date: "", reason: "" })
  useEffect(() => { if (preset) setF((x) => ({ ...x, tenant: preset })) }, [preset])
  async function go() {
    try {
      const r = await post<{ offboarding_id: number }>("/offboarding/start", { tenant_id: +f.tenant, move_out_date: f.date, reason: f.reason })
      toast.success("Move-out started")
      setF({ tenant: "", date: "", reason: "" }); onDone(r.offboarding_id)
    } catch (e) { toast.error(String(e).replace("Error: ", "")) }
  }
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Start move-out</DialogTitle>
          <DialogDescription>Nothing is sent to the tenant yet. Add any deductions first, then send the settlement.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2"><Label>Tenant</Label>
            <Pick className="w-full" value={f.tenant} onChange={(v) => setF({ ...f, tenant: v })} placeholder="Choose a tenant"
              options={(tenants ?? []).map((t) => ({ value: String(t.id), label: `${t.name} · room ${t.room}` }))} /></div>
          <div className="space-y-2"><Label>Move-out date</Label><Input type="date" min={today()} value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} /></div>
          <div className="space-y-2"><Label>Reason <span className="text-muted-foreground">(optional)</span></Label><Input value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} /></div>
        </div>
        <DialogFooter><Button disabled={!f.tenant || !f.date} onClick={go}>Start move-out</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Review({ id, onClose, onChange }: { id: number | null; onClose: () => void; onChange: () => void }) {
  const { data: d, reload } = useApi<Detail>(id ? `/offboarding/${id}` : null, 4000)
  const [rows, setRows] = useState<Ded[]>([])
  const [reason, setReason] = useState("")
  const [amount, setAmount] = useState("")
  const [pin, setPin] = useState("")
  const [prepared, setPrepared] = useState<string | null>(null)
  useEffect(() => { if (d) setRows(d.figures.deductions) }, [d?.id, d?.status, JSON.stringify(d?.figures.deductions)])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setPrepared(null); setPin("") }, [id])

  async function act(path: string, ok: string, body?: unknown) {
    try {
      const r = await post<{ readback?: string; delivered?: boolean }>(`/offboarding/${id}/${path}`, body)
      toast.success(path === "propose" && r.delivered === false ? "Saved, but WhatsApp could not deliver it. Copy the link and share it." : ok)
      reload(); onChange()
      return r
    } catch (e) { toast.error(String(e).replace("Error: ", "")); return null }
  }
  const addRow = () => {
    if (!reason.trim() || !(+amount > 0)) return
    setRows([...rows, { reason: reason.trim(), amount: +amount }]); setReason(""); setAmount("")
  }
  const editable = d && ["notice", "proposed", "disputed"].includes(d.status)
  const f = d?.figures
  const total = rows.reduce((a, r) => a + r.amount, 0)
  const net = f ? f.deposit - total - f.unpaid_dues : 0
  const changed = !!f && JSON.stringify(rows) !== JSON.stringify(f.deductions)
  const step = d ? STEPS.indexOf(d.status === "disputed" ? "proposed" : d.status === "closed" ? "refunded" : d.status) : 0

  return (
    <Sheet open={!!id} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        {!d || !f ? <Skeleton className="m-6 h-40" /> : (
          <>
            <SheetHeader>
              <div className="flex items-center gap-3">
                <PersonAvatar name={d.tenant.name} className="size-11" />
                <div><SheetTitle>{d.tenant.name}</SheetTitle><SheetDescription>Room {d.tenant.room} · moving out {d.move_out_date}{d.reason ? ` · ${d.reason}` : ""}</SheetDescription></div>
              </div>
            </SheetHeader>
            <div className="space-y-5 px-4 pb-6 text-sm">
              <div className="flex flex-wrap items-center gap-2"><StatusBadge status={d.status} /></div>
              {step >= 0 && !["cancelled"].includes(d.status) && (
                <ol className="grid grid-cols-2 gap-x-2 gap-y-3 text-xs sm:grid-cols-4">
                  {STEP_LABEL.map((s, i) => (
                    <li key={s} className={i <= step ? "font-medium text-primary" : "text-muted-foreground"}>
                      {i < step || ["refunded", "closed"].includes(d.status) ? <Check className="mb-1 size-4" /> : <CircleDot className="mb-1 size-4" />}{s}
                    </li>
                  ))}
                </ol>
              )}
              {d.status === "disputed" && (
                <Alert variant="destructive"><AlertTitle>The tenant disagrees</AlertTitle><AlertDescription>{d.dispute_note}</AlertDescription></Alert>
              )}
              <Separator />
              <div className="space-y-2">
                <div className="flex justify-between"><span>Deposit paid</span><span className="font-medium">{inr(f.deposit)}</span></div>
                {rows.map((r, i) => (
                  <div key={i} className="flex items-center justify-between gap-2">
                    <span className="text-muted-foreground">− {r.reason}</span>
                    <span className="flex items-center gap-1 font-medium">− {inr(r.amount)}
                      {editable && <Button variant="ghost" size="icon" className="size-6" aria-label="Remove" onClick={() => setRows(rows.filter((_, j) => j !== i))}><Trash2 /></Button>}
                    </span>
                  </div>
                ))}
                <div className="flex justify-between"><span className="text-muted-foreground">− Unpaid rent</span><span className="font-medium">− {inr(f.unpaid_dues)}</span></div>
                <Separator />
                <div className="flex justify-between text-base font-semibold">
                  <span>{net < 0 ? "Tenant still owes" : "Refund"}</span>
                  <span className={net < 0 ? "text-red-600" : "text-primary"}>{inr(Math.abs(net))}</span>
                </div>
              </div>
              {editable && (
                <div className="space-y-2 rounded-xl border p-3">
                  <Label>Add a deduction</Label>
                  <div className="flex gap-2">
                    <Input placeholder="Reason, e.g. painting" value={reason} onChange={(e) => setReason(e.target.value)} />
                    <Input className="w-28" inputMode="numeric" placeholder="₹" value={amount} onChange={(e) => setAmount(e.target.value)} />
                    <Button variant="outline" size="icon" aria-label="Add" onClick={addRow}><Plus /></Button>
                  </div>
                  {changed && <Button size="sm" onClick={() => act("deductions", "Deductions saved", { deductions: rows })}>Save deductions</Button>}
                </div>
              )}
              {d.bank && (
                <div className="rounded-xl bg-muted/50 p-3">
                  <div className="text-xs text-muted-foreground">Refund account given by the tenant</div>
                  <div className="font-medium">{d.bank.holder} · account ending {d.bank.last4} · {d.bank.ifsc}</div>
                </div>
              )}
              {d.payout && <div className="text-muted-foreground">Refund of {inr(d.payout.amount)}: {d.payout.status.replace(/_/g, " ")}</div>}

              <div className="flex flex-wrap gap-2 pt-1">
                {editable && <Button disabled={changed} onClick={() => act("propose", "Settlement sent to the tenant on WhatsApp")}><Send /> {d.status === "proposed" ? "Send again" : "Send settlement to tenant"}</Button>}
                {d.status === "accepted" && f.refund > 0 && !prepared && (
                  <Button onClick={async () => { const r = await act("payout", "Refund prepared"); if (r?.readback) setPrepared(r.readback) }}>Prepare refund of {inr(f.refund)}</Button>
                )}
                {d.status === "accepted" && f.refund === 0 && <Button onClick={() => act("complete", "Move-out completed")}><LogOut /> Complete move-out</Button>}
                {["notice", "proposed", "disputed", "accepted"].includes(d.status) && (
                  <Button variant="outline" onClick={() => act("cancel", "Move-out cancelled")}><X /> Cancel move-out</Button>
                )}
                {d.link && <Button variant="ghost" onClick={() => { navigator.clipboard.writeText(d.link!); toast.success("Link copied") }}><Copy /> Copy link</Button>}
              </div>
              {prepared && d.status === "accepted" && (
                <div className="space-y-2 rounded-xl border-2 border-amber-300 p-3">
                  <div className="font-medium">Confirm: {prepared}</div>
                  <div className="flex gap-2">
                    <Input type="password" inputMode="numeric" placeholder="PIN" value={pin} onChange={(e) => setPin(e.target.value)} />
                    <Button disabled={!pin} onClick={async () => { const r = await act("payout/confirm", "Refund sent. The tenant has moved out.", { pin }); if (r) { setPrepared(null); setPin("") } }}>Send refund</Button>
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

export default function Offboarding() {
  const { data, reload } = useApi<Row[]>("/offboarding", 5000)
  const [open, setOpen] = useState<number | null>(null)
  const [start, setStart] = useState(false)
  const [preset, setPreset] = useState("")
  useEffect(() => {  // the tenants page links here as /offboarding?start=<tenant id>
    const s = new URLSearchParams(window.location.search).get("start")
    if (s) { setPreset(s); setStart(true) }
  }, [])
  const waiting = (data ?? []).filter((r) => ["accepted", "disputed"].includes(r.status)).length
  return (
    <>
      <PageHeader title="Move-outs" description={data ? `${data.length} total · ${waiting} need your attention` : "Loading…"}>
        <Button className="h-9 rounded-xl" onClick={() => setStart(true)}><Plus /> Start move-out</Button>
      </PageHeader>
      <Card>
        <CardContent className="px-0">
          <Table>
            <TableHeader><TableRow><TableHead>Tenant</TableHead><TableHead>Room</TableHead><TableHead>Move-out</TableHead><TableHead>Status</TableHead><TableHead>Settlement</TableHead></TableRow></TableHeader>
            <TableBody>
              {!data && Array.from({ length: 3 }).map((_, i) => <TableRow key={i}><TableCell colSpan={5}><Skeleton className="h-8 w-full" /></TableCell></TableRow>)}
              {(data ?? []).map((r) => (
                <TableRow key={r.id} className="cursor-pointer" onClick={() => setOpen(r.id)}>
                  <TableCell><div className="flex items-center gap-3"><PersonAvatar name={r.name} className="size-9" /><span className="font-medium">{r.name}</span></div></TableCell>
                  <TableCell>{r.room}</TableCell><TableCell>{r.move_out_date}</TableCell>
                  <TableCell><StatusBadge status={r.status} /></TableCell>
                  <TableCell>{r.shortfall > 0 && !r.refund ? <span className="text-red-600">Owes {inr(r.shortfall)}</span> : `Refund ${inr(r.refund)}`}</TableCell>
                </TableRow>
              ))}
              {data && !data.length && <TableRow><TableCell colSpan={5} className="py-10 text-center text-muted-foreground">No move-outs yet.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Start open={start} preset={preset} onClose={() => { setStart(false); setPreset("") }} onDone={(id) => { setStart(false); setPreset(""); reload(); setOpen(id) }} />
      <Review id={open} onClose={() => setOpen(null)} onChange={reload} />
    </>
  )
}
