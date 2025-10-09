export function Stack() {
  const stackItems = [
    {
      category: "Virtualization",
      tech: "QEMU, KVM (with ARM/x86 support)",
    },
    {
      category: "Backend (VM Service)",
      tech: "FastAPI + Paramiko + psutil",
    },
    {
      category: "Backend (Web Service)",
      tech: "Django + Django Rest Framework + Channels",
    },
    {
      category: "State",
      tech: "Redis",
    },
    {
      category: "Database",
      tech: "PostgreSQL",
    },
    {
      category: "Frontend",
      tech: "Vanilla JS, Monaco Editor, Xterm.js, Chart.js, CSS themes",
    },
    {
      category: "Orchestration",
      tech: "Docker Compose, Nginx",
    },
  ]

  return (
    <section id="stack">
      <h2 className="mb-8 text-3xl font-bold tracking-tight text-foreground">Technology Stack</h2>
      <div className="rounded-lg border border-border bg-card">
        <div className="divide-y divide-border">
          {stackItems.map((item, index) => (
            <div key={index} className="flex flex-col gap-2 p-6 sm:flex-row sm:items-center sm:gap-8">
              <div className="min-w-[180px] font-semibold text-foreground">{item.category}</div>
              <div className="font-mono text-sm text-muted-foreground">{item.tech}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
