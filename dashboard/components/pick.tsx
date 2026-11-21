"use client"
import type { LucideIcon } from "lucide-react"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { cn } from "@/lib/utils"

export type Option = { value: string; label: string }

/** shadcn Select with a simple value/label API and an optional leading icon. */
export function Pick({ value, onChange, options, className, placeholder, icon: Icon }: {
  value: string; onChange: (v: string) => void; options: Option[]; className?: string; placeholder?: string; icon?: LucideIcon
}) {
  return (
    <Select value={value} onValueChange={(v) => v != null && onChange(String(v))} items={options}>
      <SelectTrigger className={cn("h-9 min-w-40 rounded-xl bg-card px-3 shadow-xs hover:bg-accent/50", className)}>
        {Icon && <Icon className="text-muted-foreground" />}
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent alignItemWithTrigger={false} align="start" sideOffset={6}>
        {options.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
      </SelectContent>
    </Select>
  )
}
