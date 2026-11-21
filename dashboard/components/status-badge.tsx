import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

const TONE: Record<string, string> = {
  paid: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  success: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  completed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  partial: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  promised: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  pending_confirm: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  ringing: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  simulated: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  submitted: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  approved: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  link_sent: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  invited: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  rejected: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  declined: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  due: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  open: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
}

export function StatusBadge({ status }: { status: string | null }) {
  const s = status ?? "—"
  return <Badge variant="secondary" className={cn("gap-1.5 rounded-full px-2.5 capitalize", TONE[s])}><span className="size-1.5 rounded-full bg-current" />{s.replace(/_/g, " ")}</Badge>
}
