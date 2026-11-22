"use client"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from "@/components/ui/breadcrumb"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"

const TITLES: Record<string, string> = {
  "": "Overview", tenants: "Tenants", onboarding: "Onboarding", offboarding: "Move-outs", rooms: "Rooms", ledger: "Rent ledger", activity: "Activity log", whatsapp: "WhatsApp agent",
}

export function AppHeader() {
  const [section = "", child] = usePathname().split("/").filter(Boolean)
  const title = TITLES[section] ?? section
  return (
    <header className="sticky top-0 z-10 flex h-14 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur md:px-8">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="h-5" />
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem><BreadcrumbLink render={<Link href="/" />}>Nele</BreadcrumbLink></BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>{child ? <BreadcrumbLink render={<Link href={`/${section}`} />}>{title}</BreadcrumbLink> : <BreadcrumbPage>{title}</BreadcrumbPage>}</BreadcrumbItem>
          {child && <><BreadcrumbSeparator /><BreadcrumbItem><BreadcrumbPage>Details</BreadcrumbPage></BreadcrumbItem></>}
        </BreadcrumbList>
      </Breadcrumb>
      <div className="ml-auto text-sm text-muted-foreground">{new Date().toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })}</div>
    </header>
  )
}
