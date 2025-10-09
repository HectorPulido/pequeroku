import type React from "react"
import { Timer, PackageX, Shuffle, AlertTriangle } from "lucide-react"

export function Problem() {
  return (
    <section className="border-t border-border py-20 md:py-32">
      <div className="container mx-auto px-4">
        <div className="mx-auto max-w-4xl">
          <div className="mb-12 text-center">
            <h2 className="text-balance font-sans text-4xl font-bold tracking-tight text-foreground md:text-5xl">
              Setting up and switching environments slows teams down.
            </h2>
          </div>

          <div className="space-y-6 text-lg leading-relaxed text-muted-foreground">
            <p>
              Every developer knows the pain: cloning repos, installing dependencies, matching OS versions, debugging
              "it works on my machine" issues.
            </p>
            <p>Cloud IDEs promised a fix — but they're limited, slow, and often vendor-locked.</p>
            <p className="text-xl font-medium text-foreground">
              Developers shouldn't have to choose between power and convenience.
            </p>
          </div>

          <div className="mt-16 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            <ProblemCard
              icon={<Timer className="h-6 w-6" />}
              title="Time Wasted"
              description="Hours spent on environment setup"
            />
            <ProblemCard
              icon={<PackageX className="h-6 w-6" />}
              title="Dependency Hell"
              description="Version conflicts and missing packages"
            />
            <ProblemCard
              icon={<Shuffle className="h-6 w-6" />}
              title="Context Switching"
              description="Slow transitions between projects"
            />
            <ProblemCard
              icon={<AlertTriangle className="h-6 w-6" />}
              title="Works on My Machine"
              description="Environment inconsistencies"
            />
          </div>
        </div>
      </div>
    </section>
  )
}

function ProblemCard({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode
  title: string
  description: string
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <div className="mb-3 text-foreground">{icon}</div>
      <h3 className="mb-2 font-semibold text-foreground">{title}</h3>
      <p className="text-sm text-muted-foreground">{description}</p>
    </div>
  )
}
