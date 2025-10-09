import type React from "react"
import { Server, Code, Blocks, Copy } from "lucide-react"

export function Solution() {
  return (
    <section className="border-t border-border py-20 md:py-32">
      <div className="container mx-auto px-4">
        <div className="mx-auto max-w-4xl">
          <div className="mb-12 text-center">
            <h2 className="text-balance font-sans text-4xl font-bold tracking-tight text-foreground md:text-5xl">
              Meet PequeRoku — Full-Control Cloud Development.
            </h2>
            <p className="mx-auto mt-6 max-w-2xl text-pretty text-lg leading-relaxed text-muted-foreground">
              PequeRoku combines QEMU virtualization, FastAPI orchestration, and a browser IDE to give you real,
              disposable machines that run anywhere and are ready for code. 
            </p>
          </div>

          <div className="grid gap-8 md:grid-cols-2">
            <FeatureCard
              icon={<Server className="h-8 w-8" />}
              title="Real OS Environments"
              description="Launch Linux VMs in seconds — install Docker, run systemd, emulate ARM or x86."
            />
            <FeatureCard
              icon={<Code className="h-8 w-8" />}
              title="Instant Access"
              description="Code, build, and deploy right from your browser with Monaco Editor + Xterm.js."
            />
            <FeatureCard
              icon={<Blocks className="h-8 w-8" />}
              title="Hackable & Self-Hosted"
              description="100% open-source, extensible, and runs on your own infrastructure."
            />
            <FeatureCard
              icon={<Copy className="h-8 w-8" />}
              title="Disposable & Shareable"
              description="Clone, reset, or share environments in one click."
            />
          </div>

          <div className="mt-16 rounded-xl border border-accent/20 bg-accent/5 p-8 text-center">
            <blockquote className="text-pretty text-xl font-medium leading-relaxed text-foreground md:text-2xl">
              "What if your dev environment was as ephemeral and shareable as a Figma file — but ran a full OS?"
            </blockquote>
          </div>
        </div>
      </div>
    </section>
  )
}

function FeatureCard({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode
  title: string
  description: string
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-8 transition-colors hover:border-accent/50">
      <div className="mb-4 text-foreground">{icon}</div>
      <h3 className="mb-3 text-xl font-semibold text-foreground">{title}</h3>
      <p className="leading-relaxed text-muted-foreground">{description}</p>
    </div>
  )
}
