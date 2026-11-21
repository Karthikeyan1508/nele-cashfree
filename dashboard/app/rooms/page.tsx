"use client"
import Link from "next/link"
import { Plus } from "lucide-react"
import { PageHeader } from "@/components/page-header"
import { PersonAvatar } from "@/components/person-avatar"
import { StatusBadge } from "@/components/status-badge"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { LANG, inr, useApi } from "@/lib/api"
import { cn } from "@/lib/utils"

type Occupant = { id: number; name: string; language: string; rent_status: string | null; pending: number | null }
type Room = { room: string; floor: number; sharing: number; rent: number; occupants: Occupant[] }

const ORD = ["", "1st", "2nd", "3rd"]

export default function Rooms() {
  const { data } = useApi<Room[]>("/rooms", 5000)
  const rooms = data ?? []
  const beds = rooms.reduce((a, r) => a + r.sharing, 0)
  const filled = rooms.reduce((a, r) => a + r.occupants.length, 0)
  const withDues = rooms.filter((r) => r.occupants.some((o) => (o.pending ?? 0) > 0)).length

  return (
    <>
      <PageHeader
        title="Rooms"
        description={data ? `${beds} beds · ${filled} occupied · ${beds - filled} vacant${withDues ? ` · ${withDues} room with rent due` : ""}` : "Loading…"}
      />
      {!data && <Skeleton className="h-64 w-full rounded-xl" />}

      {[1, 2, 3].map((f) => {
        const fr = rooms.filter((r) => r.floor === f)
        if (!fr.length) return null
        return (
          <section key={f} className="space-y-3">
            <div className="flex flex-wrap items-end justify-between gap-4 border-b pb-3">
              <div className="flex items-center gap-3">
                <h2 className="text-xl font-semibold tracking-tight">{ORD[f]} floor</h2>
                <Badge variant="secondary" className="rounded-full px-2.5">{f + 1}-sharing</Badge>
              </div>
              <div className="flex items-center gap-5">
                <div className="text-right leading-tight">
                  <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Rent per bed</div>
                  <div className="text-base font-semibold text-primary">{inr(fr[0].rent)}<span className="text-xs font-normal text-muted-foreground"> /mo</span></div>
                </div>
                <Separator orientation="vertical" className="h-8" />
                <div className="text-right leading-tight">
                  <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Deposit</div>
                  <div className="text-base font-semibold">{inr(fr[0].rent * 2)}</div>
                </div>
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {fr.map((r) => {
                const dues = r.occupants.some((o) => (o.pending ?? 0) > 0)
                return (
                  <Card key={r.room} className={cn("gap-3", dues && "ring-red-300 dark:ring-red-900")}>
                    <CardHeader className="flex-row items-center justify-between">
                      <CardTitle className="text-lg font-semibold">Room {r.room}</CardTitle>
                      <span className="text-xs text-muted-foreground">{r.occupants.length} / {r.sharing} beds</span>
                    </CardHeader>
                    <CardContent className="space-y-1">
                      {r.occupants.map((o) => (
                        <Link key={o.id} href={`/tenants/${o.id}`} className="flex items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-muted/60">
                          <PersonAvatar name={o.name} className="size-8" />
                          <div className="min-w-0 flex-1 leading-tight">
                            <div className="truncate text-sm font-medium">{o.name}</div>
                            <div className="text-xs text-muted-foreground">{LANG[o.language]}</div>
                          </div>
                          <StatusBadge status={o.rent_status} />
                        </Link>
                      ))}
                      {Array.from({ length: r.sharing - r.occupants.length }).map((_, i) => (
                        <div key={i} className="flex items-center gap-3 px-2 py-2 text-sm text-muted-foreground">
                          <span className="flex size-8 items-center justify-center rounded-full border border-dashed"><Plus className="size-4" /></span>Vacant
                        </div>
                      ))}
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          </section>
        )
      })}
    </>
  )
}
