"use client"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { Activity, BedDouble, Building2, CalendarDays, LayoutDashboard, MessageCircle, UserPlus, Users } from "lucide-react"
import { PersonAvatar } from "@/components/person-avatar"
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarHeader,
  SidebarMenu, SidebarMenuBadge, SidebarMenuButton, SidebarMenuItem, SidebarRail, SidebarSeparator,
} from "@/components/ui/sidebar"
import { Config, useApi } from "@/lib/api"
import { cn } from "@/lib/utils"

const GROUPS = [
  { label: "Dashboard", items: [{ href: "/", label: "Overview", icon: LayoutDashboard }] },
  { label: "Property", items: [
    { href: "/tenants", label: "Tenants", icon: Users },
    { href: "/onboarding", label: "Onboarding", icon: UserPlus },
    { href: "/rooms", label: "Rooms", icon: BedDouble },
    { href: "/ledger", label: "Rent ledger", icon: CalendarDays },
  ] },
  { label: "Assistant", items: [
    { href: "/whatsapp", label: "WhatsApp agent", icon: MessageCircle },
    { href: "/activity", label: "Activity log", icon: Activity },
  ] },
]

function Dot({ on, label, hint }: { on: boolean; label: string; hint: string }) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="flex items-center gap-2 text-sidebar-foreground/80">
        <span className={cn("size-2 rounded-full", on ? "bg-emerald-500" : "bg-amber-400")} />{label}
      </span>
      <span className="text-muted-foreground">{hint}</span>
    </div>
  )
}

export function AppSidebar() {
  const path = usePathname()
  const { data: cfg } = useApi<Config>("/config", 30000)
  const { data: late } = useApi<{ dues: unknown[] }>("/dues?all=0", 10000)
  const { data: onb } = useApi<{ status: string }[]>("/onboarding", 10000)
  const waiting = onb?.filter((o) => o.status === "submitted").length ?? 0
  const badge = (href: string) => (href === "/tenants" && late?.dues.length ? String(late.dues.length) : href === "/onboarding" && waiting ? String(waiting) : null)

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="p-4">
        <div className="flex items-center gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm"><Building2 className="size-5" /></div>
          <div className="leading-tight group-data-[collapsible=icon]:hidden">
            <div className="font-semibold tracking-tight">Kiraya Mitra</div>
            <div className="text-xs text-muted-foreground">Sai Residency · 36 beds</div>
          </div>
        </div>
      </SidebarHeader>
      <SidebarSeparator className="mx-0" />
      <SidebarContent className="px-2 py-2">
        {GROUPS.map((g) => (
          <SidebarGroup key={g.label}>
            <SidebarGroupLabel className="text-[11px] font-medium uppercase tracking-wider">{g.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu className="gap-1">
                {g.items.map(({ href, label, icon: Icon }) => (
                  <SidebarMenuItem key={href}>
                    <SidebarMenuButton
                      size="lg" tooltip={label} render={<Link href={href} />}
                      isActive={href === "/" ? path === "/" : path.startsWith(href)}
                      className="h-10 rounded-xl px-3 data-active:bg-primary/10 data-active:font-medium data-active:text-primary"
                    >
                      <Icon className="size-[18px]" /><span>{label}</span>
                    </SidebarMenuButton>
                    {badge(href) && <SidebarMenuBadge className="rounded-full bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300">{badge(href)}</SidebarMenuBadge>}
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter className="gap-3 p-3">
        <div className="space-y-2 rounded-xl border bg-card p-3 group-data-[collapsible=icon]:hidden">
          <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Connections</div>
          <Dot on={!!cfg?.whatsapp} label="WhatsApp" hint={cfg?.whatsapp ? "Live" : "Off"} />
          <Dot on={!!(cfg?.voice || cfg?.twilio)} label="Phone calls" hint={cfg?.voice ? "Sarvam" : cfg?.twilio ? "Twilio" : "Simulated"} />
          <Dot on={!!cfg && !cfg.mock_cashfree} label="Payments" hint={cfg && !cfg.mock_cashfree ? "Live" : "Mock"} />
        </div>
        <div className="flex items-center gap-3 rounded-xl p-2">
          <PersonAvatar name="Owner" className="size-9" />
          <div className="min-w-0 leading-tight group-data-[collapsible=icon]:hidden">
            <div className="truncate text-sm font-medium">Property owner</div>
            <div className="truncate text-xs text-muted-foreground">+91 {cfg?.owner_phone ?? "—"}</div>
          </div>
        </div>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
