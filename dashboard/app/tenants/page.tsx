"use client"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"
import { toast } from "sonner"
import { Eye, LogOut, MoreHorizontal, PhoneCall, Plus, Search, Wallet } from "lucide-react"
import { PageHeader } from "@/components/page-header"
import { PersonAvatar } from "@/components/person-avatar"
import { Pick } from "@/components/pick"
import { StatusBadge } from "@/components/status-badge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { LANG, Tenant, inr, post, useApi } from "@/lib/api"

const LANGS = Object.entries(LANG).map(([value, label]) => ({ value, label }))

function AddTenant({ onDone }: { onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({ name: "", phone: "", room: "", language: "hi" })
  const [err, setErr] = useState("")
  async function save() {
    try {
      const r = await post<{ error?: string }>("/tools/add_tenant", f)
      if (r.error) throw new Error(r.error)
      toast.success(`${f.name} added to room ${f.room}`)
      setOpen(false); setErr(""); setF({ name: "", phone: "", room: "", language: "hi" }); onDone()
    } catch (e) { setErr(String(e).replace("Error: ", "")) }
  }
  return (
    <>
      <Button className="h-9 rounded-xl" onClick={() => setOpen(true)}><Plus /> Add tenant</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Add tenant</DialogTitle>
            <DialogDescription>Rent and deposit come from the room: ₹11,000 (2-sharing), ₹9,000 (3-sharing), ₹7,000 (4-sharing). Deposit is 2 months of rent.</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2 space-y-2"><Label>Name</Label><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
            <div className="space-y-2"><Label>Phone</Label><Input inputMode="numeric" placeholder="10 digits" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></div>
            <div className="space-y-2"><Label>Room</Label><Input placeholder="e.g. 201" value={f.room} onChange={(e) => setF({ ...f, room: e.target.value })} /></div>
            <div className="col-span-2 space-y-2"><Label>Language for calls</Label><Pick className="w-full" value={f.language} onChange={(v) => setF({ ...f, language: v })} options={LANGS} /></div>
          </div>
          {err && <p className="text-sm text-destructive">{err}</p>}
          <DialogFooter><Button onClick={save} disabled={!f.name || !f.phone || !f.room}>Add tenant</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function RecordPayment({ t, onClose }: { t: Tenant | null; onClose: () => void }) {
  const [amount, setAmount] = useState("")
  const [method, setMethod] = useState("cash")
  const [err, setErr] = useState("")
  async function save() {
    try {
      const r = await post<{ error?: string }>("/tools/record_payment", { tenant_id: t!.id, amount: +amount, method })
      if (r.error) throw new Error(r.error)
      toast.success(`Recorded ${inr(+amount)} from ${t!.name}. Receipt sent.`)
      setAmount(""); setErr(""); onClose()
    } catch (e) { setErr(String(e).replace("Error: ", "")) }
  }
  return (
    <Dialog open={!!t} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Record payment</DialogTitle>
          <DialogDescription>{t?.name} · Room {t?.room} · pending {inr((t?.due ?? 0) - (t?.paid ?? 0))}</DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2"><Label>Amount (₹)</Label><Input inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder={String((t?.due ?? 0) - (t?.paid ?? 0))} /></div>
          <div className="space-y-2"><Label>Method</Label><Pick className="w-full" value={method} onChange={setMethod} options={[{ value: "cash", label: "Cash" }, { value: "upi", label: "UPI (direct)" }]} /></div>
        </div>
        {err && <p className="text-sm text-destructive">{err}</p>}
        <DialogFooter><Button onClick={save} disabled={!amount}>Save payment</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default function Tenants() {
  const router = useRouter()
  const { data, reload } = useApi<Tenant[]>("/tenants/all", 5000)
  const [q, setQ] = useState("")
  const [rec, setRec] = useState<Tenant | null>(null)
  const rows = (data ?? []).filter((t) => (t.name + t.room + t.phone).toLowerCase().includes(q.toLowerCase()))

  async function call(t: Tenant) {
    try {
      const r = await post<{ calls: unknown[] }>("/tools/send_reminders", { tenant_ids: [t.id] })
      r.calls.length ? toast.success(`Calling ${t.name}…`) : toast.info(`${t.name} has no pending rent`)
      reload()
    } catch (e) { toast.error(String(e)) }
  }

  return (
    <>
      <PageHeader title="Tenants" description={`${rows.length} active tenants`}>
        <div className="relative">
          <Search className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="h-9 w-64 rounded-xl bg-card pl-9 shadow-xs" placeholder="Search name, room, phone" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <AddTenant onDone={reload} />
      </PageHeader>
      <Card>
        <CardContent className="px-0">
          <Table>
            <TableHeader><TableRow>
              <TableHead>Tenant</TableHead><TableHead>Room</TableHead><TableHead>Language</TableHead><TableHead>Rent</TableHead>
              <TableHead>Deposit</TableHead><TableHead>This month</TableHead><TableHead className="w-12" />
            </TableRow></TableHeader>
            <TableBody>
              {!data && Array.from({ length: 5 }).map((_, i) => <TableRow key={i}><TableCell colSpan={7}><Skeleton className="h-8 w-full" /></TableCell></TableRow>)}
              {rows.map((t) => (
                <TableRow key={t.id} className="cursor-pointer" onClick={() => router.push(`/tenants/${t.id}`)}>
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <PersonAvatar name={t.name} className="size-9" />
                      <div className="leading-tight"><div className="font-medium">{t.name}</div><div className="text-xs text-muted-foreground">{t.phone}</div></div>
                    </div>
                  </TableCell>
                  <TableCell>{t.room}</TableCell>
                  <TableCell><Badge variant="outline" className="rounded-full font-normal">{LANG[t.language]}</Badge></TableCell>
                  <TableCell>{inr(t.rent)}</TableCell><TableCell>{inr(t.deposit)}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2"><StatusBadge status={t.rent_status} /><span className="text-xs text-muted-foreground">{inr(t.paid)} / {inr(t.due)}</span></div>
                  </TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <DropdownMenu>
                      <DropdownMenuTrigger render={<Button variant="ghost" size="icon" className="size-8 rounded-lg" aria-label="Actions" />}><MoreHorizontal /></DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-48 rounded-xl p-1.5">
                        <DropdownMenuGroup>
                          <DropdownMenuLabel>{t.name}</DropdownMenuLabel>
                          <DropdownMenuItem className="rounded-lg py-2" render={<Link href={`/tenants/${t.id}`} />}><Eye /> View details</DropdownMenuItem>
                        </DropdownMenuGroup>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem className="rounded-lg py-2" disabled={t.rent_status === "paid"} onClick={() => call(t)}><PhoneCall /> Call about rent</DropdownMenuItem>
                        <DropdownMenuItem className="rounded-lg py-2" disabled={t.rent_status === "paid"} onClick={() => setRec(t)}><Wallet /> Record payment</DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem className="rounded-lg py-2" onClick={() => router.push(`/offboarding?start=${t.id}`)}><LogOut /> Start move-out</DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))}
              {data && !rows.length && <TableRow><TableCell colSpan={7} className="py-10 text-center text-muted-foreground">No tenants match.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <RecordPayment t={rec} onClose={() => { setRec(null); reload() }} />
    </>
  )
}
