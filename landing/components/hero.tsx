"use client"

import { Button } from "@/components/ui/button"
import { ArrowRight, Play } from "lucide-react"
import { useRouter } from "next/navigation"

export function Hero() {
  const router = useRouter()

  const handleGithubClick = () => {
    // Logic for the Github button click goes here
    console.log("Github button clicked!")
    // Example: Navigate to a new page
    router.push("https://git.hubp.de/HectorPulido/pequeroku")
  }

  return (
    <section className="relative overflow-hidden pt-32 pb-20 md:pt-40 md:pb-32">
      <div className="container mx-auto px-4">
        <div className="mx-auto max-w-5xl text-center">
          <h1 className="text-balance font-sans text-5xl font-bold leading-tight tracking-tight text-foreground md:text-7xl lg:text-8xl">
            Full OS Development Environments. Instantly. In Your Browser.
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-pretty text-lg leading-relaxed text-muted-foreground md:text-xl">
            PequeRoku lets you launch, share, and run virtualized machines in the browser — with the power of a real
            computer, open-source, and hackable. 
          </p>

          <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Button
              onClick={handleGithubClick}
              size="lg"
              className="bg-primary text-primary-foreground hover:bg-primary/90 text-base px-8"
            >
              Github
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
            <Button size="lg" variant="outline" className="text-base px-8 bg-transparent">
              Join the Waitlist
            </Button>
          </div>

          {/* Visual placeholder for demo */}
          <div className="mt-16 rounded-xl border border-border bg-card p-2 shadow-2xl">
            <div className="aspect-video rounded-lg bg-secondary/50 flex items-center justify-center">
              <div className="text-center">
                <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-accent/20">
                  <Play className="h-8 w-8 text-accent" />
                </div>
                <p className="text-sm text-muted-foreground">
                  Demo: VM booting → VSCode editor → terminal → app running
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Subtle background decoration */}
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-1/2 top-0 h-[600px] w-[600px] -translate-x-1/2 rounded-full bg-accent/5 blur-3xl" />
      </div>
    </section>
  )
}
