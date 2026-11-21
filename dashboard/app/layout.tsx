import type { Metadata } from "next"
import { Geist, Geist_Mono } from "next/font/google"
import "./globals.css"
import { AppSidebar } from "@/components/app-sidebar"
import { AppHeader } from "@/components/app-header"
import { Toaster } from "@/components/ui/sonner"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] })
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] })

export const metadata: Metadata = {
  title: "Kiraya Mitra",
  description: "PG rent dashboard",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="min-h-full">
        <SidebarProvider>
          <AppSidebar />
          <SidebarInset>
            <AppHeader />
            <main className="mx-auto w-full max-w-7xl flex-1 space-y-8 p-4 md:p-8">{children}</main>
          </SidebarInset>
        </SidebarProvider>
        <Toaster richColors position="top-right" />
      </body>
    </html>
  )
}
