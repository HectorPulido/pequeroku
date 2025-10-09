import { Alert, AlertDescription } from "@/components/ui/alert"
import { Info } from "lucide-react"

export function SelfHosting() {
  return (
    <section id="self-hosting">
      <h2 className="mb-8 text-3xl font-bold tracking-tight text-foreground">Self-Hosting Guide</h2>

      <div className="prose prose-neutral max-w-none dark:prose-invert">
        {/* Prerequisites */}
        <div className="mb-8">
          <h3 className="mb-4 text-xl font-semibold text-foreground">Prerequisites</h3>
          <ul className="space-y-2 text-muted-foreground">
            <li>Linux host (Ubuntu/Debian recommended)</li>
            <li>Docker & Docker Compose installed</li>
            <li>
              At least one prepared <strong>base qcow2 image</strong>
            </li>
          </ul>
        </div>

        {/* Step 1 */}
        <div className="mb-8">
          <h3 className="mb-4 text-xl font-semibold text-foreground">1. Prepare base qcow2 image</h3>
          <p className="mb-4 text-muted-foreground">
            Follow the qcow2 creation steps if you don't already have a qcow2 image.
          </p>
          <p className="mb-3 text-sm text-muted-foreground">
            Move your image into{" "}
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">source/vm_data/base/</code> (relative to
            the repository root):
          </p>
          <pre className="overflow-x-auto rounded-lg border border-border bg-muted p-4">
            <code className="font-mono text-sm text-foreground">mv debian12-golden.qcow2 ./source/vm_data/base/</code>
          </pre>
        </div>

        {/* Step 2 */}
        <div className="mb-8">
          <h3 className="mb-4 text-xl font-semibold text-foreground">2. Clone the repository</h3>
          <pre className="overflow-x-auto rounded-lg border border-border bg-muted p-4">
            <code className="font-mono text-sm text-foreground">
              {`git clone https://git.hubp.de/HectorPulido/pequeroku.git
cd pequeroku`}
            </code>
          </pre>
        </div>

        {/* Step 3 */}
        <div className="mb-8">
          <h3 className="mb-4 text-xl font-semibold text-foreground">3. Configure environment</h3>
          <ul className="mb-4 space-y-2 text-muted-foreground">
            <li>
              Per service, copy the env template to{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">.env</code> and adjust values:
              <ul className="ml-6 mt-2 space-y-1">
                <li>
                  <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
                    source/web_service/.env.template
                  </code>{" "}
                  → <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">source/web_service/.env</code>{" "}
                  (DB credentials, allowed hosts, auth, etc.)
                </li>
                <li>
                  <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
                    source/vm_service/.env.template
                  </code>{" "}
                  → <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">source/vm_service/.env</code>{" "}
                  (AUTH_TOKEN, Redis, base image overrides, etc.)
                </li>
              </ul>
            </li>
            <li>
              Ensure your SSH key mapping in{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">source/docker-compose.yaml</code> under{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">vm_services</code> matches your host
              key path.
            </li>
          </ul>
        </div>

        {/* Step 4 */}
        <div className="mb-8">
          <h3 className="mb-4 text-xl font-semibold text-foreground">4. Start services</h3>
          <pre className="overflow-x-auto rounded-lg border border-border bg-muted p-4">
            <code className="font-mono text-sm text-foreground">
              {`cd source
docker compose up --build`}
            </code>
          </pre>
          <p className="mt-4 text-sm text-muted-foreground">The stack includes:</p>
          <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
            <li>VM manager (FastAPI)</li>
            <li>Web service (Django + DRF)</li>
            <li>Redis + Postgres</li>
            <li>
              Nginx (serves frontend + static files; routes{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">/</code> to dashboard,{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">/ide/</code> to IDE,{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">/metrics/</code> to metrics)
            </li>
          </ul>
        </div>

        {/* Usage */}
        <div className="mb-8">
          <h3 className="mb-4 text-xl font-semibold text-foreground">Usage</h3>
          <ol className="space-y-3 text-muted-foreground">
            <li>
              1. Open the web UI at{" "}
              <a href="http://localhost" className="text-accent hover:underline">
                http://localhost
              </a>
            </li>
            <li>
              2. Log in with your user. If you don't have one, create an admin in the web container:
              <pre className="mt-2 overflow-x-auto rounded-lg border border-border bg-muted p-4">
                <code className="font-mono text-sm text-foreground">
                  {`cd source
docker compose exec web python manage.py createsuperuser`}
                </code>
              </pre>
            </li>
            <li>3. Create a container (VM)</li>
            <li>
              4. Open it in the IDE (or navigate directly to{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">/ide/</code> for the IDE,{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">/metrics/</code> for metrics):
              <ul className="ml-6 mt-2 space-y-1">
                <li>Edit code with Monaco</li>
                <li>Run commands in the terminal</li>
                <li>Upload/download files</li>
                <li>Clone from GitHub</li>
              </ul>
            </li>
            <li>
              5. Open <strong>Metrics dashboard</strong> to monitor CPU, memory, threads
            </li>
            <li>
              6. Optionally, use the <strong>AI Generator</strong> to scaffold new projects
            </li>
          </ol>
        </div>

        <Alert className="border-accent/50 bg-accent/5">
          <Info className="h-4 w-4 text-accent" />
          <AlertDescription className="text-sm text-muted-foreground">
            For more detailed information and troubleshooting, visit the{" "}
            <a href="https://git.hubp.de/HectorPulido/pequeroku" className="font-medium text-accent hover:underline">
              GitHub repository
            </a>
            .
          </AlertDescription>
        </Alert>
      </div>
    </section>
  )
}
