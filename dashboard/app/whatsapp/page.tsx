"use client"
import { useEffect, useRef, useState } from "react"
import { Mic, Send, Square, Volume2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { PageHeader } from "@/components/page-header"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Config, useApi } from "@/lib/api"
import { cn } from "@/lib/utils"

type Msg = { id: number; ts: string; direction: "in" | "out"; kind: string; text: string; audio_url: string | null }

const CHIPS = ["Yaaru innu kottilla?", "Ellarigu reminder kalsi", "Electrician Raju ge 800 kodi", "Ee thingala lekka?", "Karthikeyan status", "Karthikeyan cash 2000 received"]

export default function WhatsApp() {
  const { data: msgs, reload } = useApi<Msg[]>("/messages", 2000)
  const { data: cfg } = useApi<Config>("/config")
  const [text, setText] = useState("")
  const [pin, setPin] = useState("")
  const [recording, setRecording] = useState(false)
  const rec = useRef<MediaRecorder | null>(null)
  const end = useRef<HTMLDivElement>(null)
  const spoken = useRef(0)

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }) }, [msgs?.length])

  // Browser TTS stands in for the voice note when the backend has no Sarvam key (audio_url null).
  useEffect(() => {
    if (!msgs) return
    if (!spoken.current) { spoken.current = msgs.at(-1)?.id ?? 0; return }
    for (const m of msgs.filter((m) => m.id > spoken.current && m.direction === "out" && !m.audio_url)) speak(m.text)
    spoken.current = msgs.at(-1)?.id ?? spoken.current
  }, [msgs])

  const speak = (t: string) => {
    const u = new SpeechSynthesisUtterance(t)
    u.lang = "kn-IN"
    speechSynthesis.cancel(); speechSynthesis.speak(u)
  }

  async function send(body: FormData) {
    await fetch("/api/whatsapp/simulate", { method: "POST", body })
    reload()
  }
  const sendText = (t: string) => { if (!t.trim()) return; const f = new FormData(); f.append("text", t); setText(""); send(f) }

  async function toggleMic() {
    if (recording) { rec.current?.stop(); return }
    const s = await navigator.mediaDevices.getUserMedia({ audio: true })
    const chunks: Blob[] = []
    const mr = new MediaRecorder(s)
    mr.ondataavailable = (e) => chunks.push(e.data)
    mr.onstop = () => {
      s.getTracks().forEach((t) => t.stop()); setRecording(false)
      const f = new FormData(); f.append("audio", new Blob(chunks, { type: mr.mimeType }), "voice.webm"); send(f)
    }
    mr.start(); rec.current = mr; setRecording(true)
  }

  return (
    <>
      <PageHeader title="WhatsApp agent" description="Talk to the owner assistant, same as on the real number" />
      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Owner chat · Nele</CardTitle>
            <CardDescription>
              {cfg?.whatsapp ? "Live WhatsApp number connected. This window is a simulator and does not message your phone." : "WhatsApp not connected (no token): simulator mode."}
              {" "}Speak or type in Kannada/English. The agent answers with a voice note.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="h-[420px] space-y-2 overflow-auto rounded-lg bg-muted/50 p-3">
              {(msgs ?? []).map((m) => (
                <div key={m.id} className={cn("flex", m.direction === "in" ? "justify-end" : "justify-start")}>
                  <div className={cn("max-w-[80%] space-y-1 rounded-xl px-3 py-2 text-sm", m.direction === "in" ? "bg-emerald-600 text-white" : "bg-background border")}>
                    {m.audio_url && <audio controls className="h-8 max-w-full" src={"/api" + m.audio_url} />}
                    {m.kind === "audio" && m.direction === "in" && <div className="text-xs opacity-80">🎤 voice note</div>}
                    <div>{m.text}</div>
                    {!m.audio_url && m.direction === "out" && (
                      <Button variant="ghost" size="xs" className="-ml-2 h-6 text-xs text-muted-foreground" onClick={() => speak(m.text)}><Volume2 className="size-3" /> Play</Button>
                    )}
                  </div>
                </div>
              ))}
              {!msgs?.length && <p className="text-sm text-muted-foreground">No messages yet. Try a suggestion below.</p>}
              <div ref={end} />
            </div>
            <div className="flex flex-wrap gap-2">
              {CHIPS.map((c) => <Button key={c} size="sm" variant="outline" onClick={() => sendText(c)}>{c}</Button>)}
            </div>
            <div className="flex gap-2">
              <Button variant={recording ? "destructive" : "outline"} onClick={toggleMic}>{recording ? <Square /> : <Mic />}</Button>
              <Input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && sendText(text)} placeholder="Type or record a voice note…" />
              <Button onClick={() => sendText(text)}><Send /></Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Confirm a payout</CardTitle><CardDescription>Voice reads the amount back; the PIN is always typed, never spoken.</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            <div className="flex gap-2">
              <Input type="password" inputMode="numeric" placeholder="PIN" value={pin} onChange={(e) => setPin(e.target.value)} />
              <Button onClick={() => { sendText(`CONFIRM ${pin}`); setPin("") }} disabled={!pin}>Confirm</Button>
            </div>
            <p className="text-xs text-muted-foreground">Same as typing <code>CONFIRM &lt;PIN&gt;</code> in the WhatsApp chat after the agent reads back the payee and amount.</p>
            <hr />
            <div className="space-y-1 text-sm">
              <div className="font-medium">What the owner can ask</div>
              <ul className="list-disc pl-5 text-muted-foreground">
                <li>Who hasn&apos;t paid / monthly accounts</li>
                <li>Anything about one tenant</li>
                <li>Call all late tenants</li>
                <li>Pay a saved vendor (PIN to confirm)</li>
                <li>Record cash received</li>
              </ul>
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  )
}
