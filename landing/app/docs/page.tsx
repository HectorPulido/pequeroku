import { Header } from "@/components/header"
import { Features } from "@/components/docs/features"
import { Stack } from "@/components/docs/stack"
import { SelfHosting } from "@/components/docs/self-hosting"
import { SidebarNav } from "@/components/docs/sidebar-nav"

export default function DocsPage() {
  return (
    <main className="min-h-screen bg-background">
      <Header />
      <div className="container mx-auto px-4 pt-24 pb-16">
        <div className="mx-auto max-w-7xl">
          <div className="mb-12">
            <h1 className="mb-4 text-4xl font-bold tracking-tight text-foreground">Documentation</h1>
            <p className="text-lg text-muted-foreground">
              Everything you need to know about PequeRoku - features, stack, and self-hosting guide.
            </p>
          </div>

          <div className="flex gap-12">
            {/* Sidebar Navigation */}
            <aside className="hidden lg:block w-64 shrink-0">
              <div className="sticky top-24">
                <SidebarNav />
              </div>
            </aside>

            {/* Main Content */}
            <div className="flex-1 min-w-0">
              <div className="space-y-16">
                <Features />
                <Stack />
                <SelfHosting />
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>
  )
}
