import { Shield, Code, BarChart3, Sparkles, GitBranch, Box, Puzzle } from "lucide-react"

export function Features() {
  const features = [
    {
      icon: Shield,
      title: "Secure virtual machines",
      description: "QEMU/KVM managed via FastAPI and Redis",
    },
    {
      icon: Code,
      title: "Web IDE",
      description:
        "Monaco Editor with syntax highlighting, themes, integrated terminal (xterm.js), file tree, upload/download, and templates",
    },
    {
      icon: BarChart3,
      title: "Metrics dashboard",
      description: "Chart.js visualization for CPU, memory, and threads",
    },
    {
      icon: Sparkles,
      title: "AI-assisted scaffolding",
      description: "Generate code templates from natural language prompts",
    },
    {
      icon: GitBranch,
      title: "Repository cloning",
      description: "Clone projects directly from GitHub",
    },
    {
      icon: Box,
      title: "Containerized stack",
      description: "Full Docker Compose orchestration",
    },
    {
      icon: Puzzle,
      title: "Pluggable architecture",
      description: "Redis state store, Django/DRF APIs, FastAPI VM manager",
    },
  ]

  return (
    <section id="features">
      <h2 className="mb-8 text-3xl font-bold tracking-tight text-foreground">Features</h2>
      <div className="grid gap-6 sm:grid-cols-2">
        {features.map((feature, index) => (
          <div
            key={index}
            className="rounded-lg border border-border bg-card p-6 transition-colors hover:border-accent/50"
          >
            <div className="mb-4 flex items-center gap-3">
              <div className="rounded-lg bg-accent/10 p-2">
                <feature.icon className="h-5 w-5 text-foreground" />
              </div>
              <h3 className="font-semibold text-foreground">{feature.title}</h3>
            </div>
            <p className="text-sm leading-relaxed text-muted-foreground">{feature.description}</p>
          </div>
        ))}
      </div>
    </section>
  )
}
