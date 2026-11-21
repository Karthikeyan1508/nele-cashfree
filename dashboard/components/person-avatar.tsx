import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { cn } from "@/lib/utils"

const TONES = [
  "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  "bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-300",
  "bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300",
]

export function PersonAvatar({ name, className }: { name: string; className?: string }) {
  const tone = TONES[[...name].reduce((a, c) => a + c.charCodeAt(0), 0) % TONES.length]
  return (
    <Avatar className={className}>
      <AvatarFallback className={cn("text-xs font-semibold", tone)}>{name.slice(0, 2).toUpperCase()}</AvatarFallback>
    </Avatar>
  )
}
