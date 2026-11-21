"use client"
import { useState } from "react"
import { toast } from "sonner"
import { Check, Copy, ExternalLink, FileText, Plus, RefreshCw, Repeat2, X } from "lucide-react"
import { PageHeader } from "@/components/page-header"
import { PersonAvatar } from "@/components/person-avatar"
import { Pick } from "@/components/pick"
import { StatusBadge } from "@/components/status-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { LANG, inr, post, useApi } from "@/lib/api"

type Row = { id: number; name: string; phone: string; room: string; sharing: number; status: string; call_outcome: string | null; created: string; submitted_at: string | null; tenant_id: number | null; autopay_status: string }
type Detail = Row & { rent: number; deposit: number; whatsapp: string | null; link: string; has_aadhaar: boolean; has_photo: boolean; form: Record<string, string>; autopay: { status: string; first_charge: string; last_payment_status: string | null } | null }
type Room = { room: string; sharing: number; rent: number; occupants: unknown[] }

const FIELDS: [string, string][] = [
  ["email", "Email"], ["dob", "Date of birth"], ["gender", "Gender"], ["occupation", "Student or working"], ["org_name", "College / company"],
  ["org_role", "Course / designation"], ["org_location", "City / work location"], ["primary_language", "Primary language"],
  ["secondary_language", "Secondary language"], ["address", "Permanent address"], ["emergency_name", "Emergency contact"],
  ["emergency_relation", "Relation"], ["emergency_phone", "Emergency phone"], ["move_in", "Move-in date"], ["food", "Food preference"],
  ["health_notes", "Medical notes"], ["vehicle", "Vehicle"],
]

function Start({ onDone }: { onDone: () => void }) {
  const { data: rooms } = useApi<Room[]>("/rooms")
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({ name: "", phone: "", room: "", language: "hi", call: "yes" })
  const [busy, setBusy] = useState(false)
  const free = (rooms ?? []).filter((r) => r.sharing - r.occupants.length > 0)
  async function go() {
    setBusy(true)
    try {
      const r = await post<{ status?: string }>("/onboarding/start", { name: f.name, phone: f.phone, room: f.room, language: f.language, call: f.call === "yes" })
      toast.success(r.status === "calling" ? `Calling ${f.name} to confirm details` : `Form sent to ${f.name} on WhatsApp`)
      setOpen(false); setF({ name: "", phone: "", room: "", language: "hi", call: "yes" }); onDone()
    } catch (e) { toast.error(String(e).replace("Error: ", "")) }
    setBusy(false)
  }
  return (
    <>
      <Button className="h-9 rounded-xl" onClick={() => setOpen(true)}><Plus /> Start onboarding</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Start onboarding</DialogTitle>
            <DialogDescription>The agent confirms name, phone and WhatsApp on a call, then sends the details form on WhatsApp.</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2 space-y-2"><Label>Name</Label><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
            <div className="space-y-2"><Label>Phone</Label><Input inputMode="numeric" placeholder="10 digits" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></div>
            <div className="space-y-2"><Label>Room</Label>
              <Pick className="w-full" value={f.room} onChange={(v) => setF({ ...f, room: v })} placeholder="Choose a room"
                options={free.map((r) => ({ value: r.room, label: `${r.room} · ${r.sharing}-sharing · ${inr(r.rent)}` }))} /></div>
            <div className="space-y-2"><Label>Language for the call</Label>
              <Pick className="w-full" value={f.language} onChange={(v) => setF({ ...f, language: v })} options={Object.entries(LANG).map(([value, label]) => ({ value, label }))} /></div>
            <div className="space-y-2"><Label>How to reach</Label>
              <Pick className="w-full" value={f.call} onChange={(v) => setF({ ...f, call: v })} options={[{ value: "yes", label: "Call, then send form" }, { value: "no", label: "Send form only" }]} /></div>
          </div>
          <DialogFooter><Button disabled={busy || !f.name || f.phone.length < 10 || !f.room} onClick={go}>{f.call === "yes" ? "Call now" : "Send form"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function Review({ id, onClose, onChange }: { id: number | null; onClose: () => void; onChange: () => void }) {
  const { data: d, reload } = useApi<Detail>(id ? `/onboarding/${id}` : null, 5000)
  async function act(path: string, ok: string) {
    try {
      const result = await post<{ autopay_status?: string }>(`/onboarding/${id}/${path}`)
      if (result.autopay_status === "setup_failed") toast.warning(`${ok}, but Cashfree AutoPay could not be started`)
      else toast.success(ok)
      reload(); onChange()
    } catch (e) { toast.error(String(e).replace("Error: ", "")) }
  }
  return (
    <Sheet open={!!id} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        {!d ? <Skeleton className="m-6 h-40" /> : (
          <>
            <SheetHeader>
              <div className="flex items-center gap-3">
                <PersonAvatar name={d.name} className="size-11" />
                <div><SheetTitle>{d.name}</SheetTitle><SheetDescription>Room {d.room} · {d.sharing}-sharing · rent {inr(d.rent)} · deposit {inr(d.deposit)}</SheetDescription></div>
              </div>
            </SheetHeader>
            <div className="space-y-5 px-4 pb-6 text-sm">
              <div className="flex flex-wrap items-center gap-2"><StatusBadge status={d.status} />
                {d.call_outcome && <span className="text-muted-foreground">Call: {d.call_outcome.replace(/_/g, " ")}</span>}</div>
              <div className="grid grid-cols-2 gap-3">
                <div><div className="text-xs text-muted-foreground">Phone</div>{d.phone}</div>
                <div><div className="text-xs text-muted-foreground">WhatsApp</div>{d.whatsapp ?? "Same as phone"}</div>
              </div>
              {(d.form.autopay === "yes" || d.autopay) && (
                <div className="flex items-start gap-3 rounded-xl bg-teal-50 p-3 text-teal-950 dark:bg-teal-950 dark:text-teal-50">
                  <Repeat2 className="mt-0.5 size-4 shrink-0" />
                  <div className="min-w-0 flex-1"><div className="font-medium">Monthly rent AutoPay</div>
                    <div className="text-xs text-teal-800 dark:text-teal-200">
                      {d.autopay ? `Cashfree mandate: ${d.autopay.status.replace(/_/g, " ")} · first charge ${new Date(d.autopay.first_charge).toLocaleDateString("en-IN")}` : "Requested by tenant; setup begins after approval"}
                    </div>
                  </div>
                  {d.autopay && <StatusBadge status={d.autopay.status} />}
                </div>
              )}
              <Separator />
              {d.status === "submitted" || d.status === "approved" ? (
                <>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-3">
                    {FIELDS.filter(([k]) => d.form[k]).map(([k, label]) => (
                      <div key={k} className={k === "address" ? "col-span-2" : ""}><div className="text-xs text-muted-foreground">{label}</div><div className="capitalize-none">{d.form[k]}</div></div>
                    ))}
                  </div>
                  <Separator />
                  <div className="flex items-center gap-4">
                    {d.has_photo && /* eslint-disable-next-line @next/next/no-img-element */ <img src={`/api/onboarding/${d.id}/file/photo`} alt="Passport photo" className="size-24 rounded-xl border object-cover" />}
                    {d.has_aadhaar && <Button variant="outline" render={<a href={`/api/onboarding/${d.id}/file/aadhaar`} target="_blank" rel="noreferrer" />}><FileText /> View Aadhaar <ExternalLink /></Button>}
                  </div>
                </>
              ) : <p className="text-muted-foreground">The form has not been submitted yet. Link: <span className="break-all">{d.link}</span></p>}
              <div className="flex flex-wrap gap-2 pt-2">
                {d.status === "submitted" && <Button onClick={() => act("approve", `${d.name} added as a tenant`)}><Check /> Approve and add tenant</Button>}
                {["invited", "link_sent", "submitted"].includes(d.status) && <Button variant="outline" onClick={() => act("reject", "Rejected")}><X /> Reject</Button>}
                {["invited", "link_sent"].includes(d.status) && <Button variant="outline" onClick={() => act("resend", "Form link sent again")}><RefreshCw /> Resend link</Button>}
                <Button variant="ghost" onClick={() => { navigator.clipboard.writeText(d.link); toast.success("Link copied") }}><Copy /> Copy link</Button>
              </div>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

export default function Onboarding() {
  const { data, reload } = useApi<Row[]>("/onboarding", 5000)
  const [open, setOpen] = useState<number | null>(null)
  const waiting = (data ?? []).filter((r) => r.status === "submitted").length
  return (
    <>
      <PageHeader title="Onboarding" description={data ? `${data.length} total · ${waiting} waiting for your approval` : "Loading…"}><Start onDone={reload} /></PageHeader>
      <Card>
        <CardContent className="px-0">
          <Table>
            <TableHeader><TableRow><TableHead>Person</TableHead><TableHead>Room</TableHead><TableHead>Status</TableHead><TableHead>AutoPay</TableHead><TableHead>Call</TableHead><TableHead>Started</TableHead></TableRow></TableHeader>
            <TableBody>
              {!data && Array.from({ length: 3 }).map((_, i) => <TableRow key={i}><TableCell colSpan={6}><Skeleton className="h-8 w-full" /></TableCell></TableRow>)}
              {(data ?? []).map((r) => (
                <TableRow key={r.id} className="cursor-pointer" onClick={() => setOpen(r.id)}>
                  <TableCell><div className="flex items-center gap-3"><PersonAvatar name={r.name} className="size-9" /><div className="leading-tight"><div className="font-medium">{r.name}</div><div className="text-xs text-muted-foreground">{r.phone}</div></div></div></TableCell>
                  <TableCell>{r.room} <span className="text-xs text-muted-foreground">{r.sharing}-sharing</span></TableCell>
                  <TableCell><StatusBadge status={r.status} /></TableCell>
                  <TableCell><StatusBadge status={r.autopay_status} /></TableCell>
                  <TableCell className="capitalize text-muted-foreground">{r.call_outcome?.replace(/_/g, " ") ?? "—"}</TableCell>
                  <TableCell className="text-muted-foreground">{r.created}</TableCell>
                </TableRow>
              ))}
              {data && !data.length && <TableRow><TableCell colSpan={6} className="py-10 text-center text-muted-foreground">No onboarding yet. Start one for a new tenant.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Review id={open} onClose={() => setOpen(null)} onChange={reload} />
    </>
  )
}
