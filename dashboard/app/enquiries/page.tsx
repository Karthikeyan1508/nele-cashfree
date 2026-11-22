"use client"
import { toast } from "sonner"
import { Check, Phone } from "lucide-react"
import { PageHeader } from "@/components/page-header"
import { PersonAvatar } from "@/components/person-avatar"
import { StatusBadge } from "@/components/status-badge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { post, useApi } from "@/lib/api"

type Enquiry = { id: number; phone: string; name: string | null; note: string | null; first_msg: string | null; source: string; status: string; msgs: number; created: string }

export default function Enquiries() {
  const { data, reload } = useApi<Enquiry[]>("/enquiries", 5000)
  async function close(e: Enquiry) {
    try { await post(`/enquiries/${e.id}/close`, {}); toast.success("Marked as handled"); reload() } catch (err) { toast.error(String(err)) }
  }
  const open = (data ?? []).filter((e) => e.status === "new").length
  return (
    <>
      <PageHeader title="PG enquiries" description={`${open} waiting · people who messaged or called from a number that is not a tenant`} />
      <Card>
        <CardContent className="px-0">
          <Table>
            <TableHeader><TableRow>
              <TableHead>Who</TableHead><TableHead>Contact</TableHead><TableHead>Looking for</TableHead><TableHead>Via</TableHead><TableHead>Status</TableHead><TableHead className="w-32" />
            </TableRow></TableHeader>
            <TableBody>
              {!data && Array.from({ length: 3 }).map((_, i) => <TableRow key={i}><TableCell colSpan={6}><Skeleton className="h-8 w-full" /></TableCell></TableRow>)}
              {(data ?? []).map((e) => (
                <TableRow key={e.id}>
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <PersonAvatar name={e.name ?? "?"} className="size-9" />
                      <div className="leading-tight"><div className="font-medium">{e.name ?? "Name not given"}</div><div className="text-xs text-muted-foreground">{e.created}</div></div>
                    </div>
                  </TableCell>
                  <TableCell><a className="flex items-center gap-1.5 text-sm hover:underline" href={`tel:+91${e.phone}`}><Phone className="size-3.5" />+91 {e.phone}</a></TableCell>
                  <TableCell className="max-w-sm whitespace-normal text-sm text-muted-foreground">{e.note || e.first_msg || "—"}</TableCell>
                  <TableCell><Badge variant="outline" className="rounded-full font-normal capitalize">{e.source}</Badge></TableCell>
                  <TableCell><StatusBadge status={e.status === "new" ? "open" : "completed"} /></TableCell>
                  <TableCell>{e.status === "new" && <Button size="sm" variant="outline" className="rounded-lg" onClick={() => close(e)}><Check /> Handled</Button>}</TableCell>
                </TableRow>
              ))}
              {data && !data.length && <TableRow><TableCell colSpan={6} className="py-10 text-center text-muted-foreground">No enquiries yet.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  )
}
