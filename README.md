# PequeRoku

> Your own always-on, self-hosted cloud lab: real, root-access VMs in the browser, with an AI agent that operates the machine.

<p align="center">
  <a href="https://github.com/HectorPulido/pequeroku/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/github/license/HectorPulido/pequeroku?color=blue"></a>
  <a href="https://github.com/HectorPulido/pequeroku/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/HectorPulido/pequeroku?style=flat"></a>
  <a href="https://github.com/HectorPulido/pequeroku/issues"><img alt="Issues" src="https://img.shields.io/github/issues/HectorPulido/pequeroku"></a>
  <a href="https://github.com/HectorPulido/pequeroku/pulls"><img alt="PRs Welcome" src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg"></a>
  <img alt="Self-hosted" src="https://img.shields.io/badge/self--hosted-%E2%9C%94-success">
</p>


## Demo

<p align="center">
  <img src="img/demo.gif" alt="PequeRoku Demo" width="800"><br>
  <em>Open a real Linux VM from any device: laptop, tablet, or phone. No setup, no waiting.</em>
</p>


## What Is It?

PequeRoku is an open-source, self-hosted alternative to Replit, Codespaces, and Gitpod. Instead of a locked-down container, you get a real virtual machine (QEMU/KVM) with full root, a browser IDE, and a built-in [AI agent](./AI.md) that reads your code, runs commands, brings services up, and fixes things inside the box.

It is always on, with no cold starts, no sandbox, and no per-seat billing. The only limits are the ones your own hardware sets.

```
git clone  →  docker compose up  →  http://localhost:8000  →  start coding
```


## The Problem

Every developer knows the ritual:

| | |
|---|---|
| **Time wasted** | 25 to 50 minutes lost on every environment switch, days lost onboarding |
| **Dependency hell** | version conflicts, missing packages, mismatched OS versions |
| **Context switching** | cloning repos and rebuilding state for every project |
| **"Works on my machine"** | environments that drift the moment you look away |

Cloud IDEs promised a fix. In practice they are limited, vendor-locked, and their cost scales with your team. You should not have to choose between power and convenience.


## Why PequeRoku Is Different

* **Real root on a real VM.** Install Docker, run `systemd`, build a kernel. It is a Linux machine, not a sandbox.
* **Always on.** Your workspace is ready when you are, with no boot and no cold start.
* **An agent with real tools.** [Pequenin](#meet-pequenin-the-ai-that-operates-your-vm) edits files, runs your tests, starts servers, and verifies them live inside the VM. See the internals in [AI.md](./AI.md).
* **Reachable from anywhere.** The IDE is responsive, so you can work from a laptop, tablet, or phone.
* **Open source and hackable.** It runs on your own infrastructure under the MIT license, and every layer is extensible.
* **Affordable to self-host.** It is built to run on modest hardware, including a homelab.

> I built PequeRoku because I could not find a remote dev platform that was open, root-accessible, always-on, reachable from anywhere, and affordable to run myself. So I made one.


## Meet Pequenin, the AI That Operates Your VM

<p align="center">
  <img src="img/AI.gif" alt="Pequenin, the AI agent, working inside a VM" width="800"><br>
  <em>Pequenin does not just suggest. It edits, runs, and verifies inside your VM.</em>
</p>

Pequenin is an agentic coding agent that operates your environment. It lives in the IDE chat and works through real tools. The full breakdown lives in [AI.md](./AI.md):

* **Reads, writes, and edits files** with whitespace-tolerant, surgical edits.
* **Searches your code** with glob and grep, directly on the VM.
* **Runs shell commands**, both foreground and long-running background jobs it can monitor.
* **Brings services up** and checks that they respond.
* **Searches the web and fetches URLs** when it needs documentation.
* **Spawns subagents** to explore in parallel, and keeps multiple switchable conversations per VM.
* **OpenAI-compatible**, so you bring your own provider: Groq for speed, OpenAI for quality, or HuggingFace for flexibility.

The result is not a snippet to copy. Pequenin creates the files, installs the dependencies, starts the server, and confirms it responds. For the agent loop, tools, and event protocol, read [AI.md](./AI.md).


## Features

| Capability | Description |
|---|---|
| **Real VMs** | QEMU/KVM with strong per-developer isolation |
| **Browser IDE** | Monaco editor and Xterm.js terminal, fully responsive |
| **Agentic AI** | Pequenin operates the VM: files, shell, services, and web ([AI.md](./AI.md)) |
| **Live preview** | Built-in mini-browser proxies your app straight from the VM |
| **Persistent and always-on** | Your workspace survives, with no cold starts |
| **Disposable workspaces** | Reset to a clean slate while keeping your config |
| **Full root** | Install anything, with no guardrails in the way |
| **Quotas and roles** | Per-user resource limits for team deployments |


## How It Works

Three services and your VM work together:

```
Browser            React IDE (Monaco + Xterm.js)
   |
   |  HTTPS / WebSocket
   v
web_service        Django, DRF, Channels
   |               auth, quotas, templates, Pequenin (the AI brain)
   |  HTTP
   v
vm_service         FastAPI
   |               VM lifecycle (QEMU), SSH pool, live terminal
   |  SSH / SFTP
   v
Your VM            Debian, full root, /app workspace
```

The brain (the AI and agentic loop, detailed in [AI.md](./AI.md)) runs in `web_service`. The hands (files, exec, terminal) are SSH operations that `vm_service` executes inside the VM. The front end only ever talks to `web_service`.

**Stack:** Django · DRF · Channels · FastAPI · QEMU/KVM · React · Monaco · Xterm.js · Postgres · Redis · Docker

Full architecture and setup: [Wiki](https://github.com/HectorPulido/pequeroku/wiki). Deep dive on the AI engine: [AI.md](./AI.md).


## Quick Start

```bash
git clone https://github.com/HectorPulido/pequeroku.git
cd pequeroku/source
docker compose up   # Docker Compose supported out of the box
```

1. Open `http://localhost:8000`.
2. Log in and create your first VM.
3. Start coding, or ask Pequenin to scaffold the project for you.

> Detailed walkthrough: [Wiki, Getting Started](https://github.com/HectorPulido/pequeroku/wiki/Getting-Started).

That gives you a self-hosted, Replit-style workspace under your control.


## How It Compares

| | **PequeRoku** | Replit / Codespaces / Gitpod |
|---|:---:|:---:|
| Hosting | Self-hosted, your hardware | Their cloud |
| Compute | Real VM (QEMU/KVM) | Containers |
| Root access | Full root | Limited |
| Cold starts | None, always-on | Boot and wait |
| AI | Agent that operates the box | Mostly autocomplete or chat |
| Source | Open source (MIT) | Proprietary |
| Cost | Your hardware | Per-seat or usage |


## Roadmap

* Fast snapshots and one-click rollback
* Richer multi-user roles and guardrails
* Automations: a push triggers tests in the active VM
* Better UI for managing multiple instances
* gRPC internal transport and a standalone AI microservice (see the roadmap in [AI.md](./AI.md))
* More Pequenin capabilities


## Contribute

PequeRoku is open to ideas, bug reports, and pull requests.

* Browse the [Issues](https://github.com/HectorPulido/pequeroku/issues).
* Share feedback, ideas, or problems. I reply to everything.
* Deploy it in your homelab and tell me how it went.


## Support the Project

If PequeRoku resonates with you:

* Star the repo. It helps others discover it.
* Spread the word.
* Run it in your homelab and share your setup.

> PequeRoku is not the ultimate platform. It is your platform, a small way to take back control.


## Links

* [pequeroku.net](https://pequeroku.net)
* [GitHub Wiki](https://github.com/HectorPulido/pequeroku/wiki)
* [Medium Article](https://medium.com/p/19bc757c735d)
* License: MIT. See the [LICENSE](./LICENSE) file for details.


<div align="center">
<h3 align="center">Let's connect</h3>
</div>
<p align="center">
<a href="https://www.linkedin.com/in/hector-pulido-17547369/" target="blank">
<img align="center" width="30px" alt="Hector's LinkedIn" src="https://www.vectorlogo.zone/logos/linkedin/linkedin-icon.svg"/></a> &nbsp; &nbsp;
<a href="https://twitter.com/Hector_Pulido_" target="blank">
<img align="center" width="30px" alt="Hector's Twitter" src="https://www.vectorlogo.zone/logos/twitter/twitter-official.svg"/></a> &nbsp; &nbsp;
<a href="https://www.twitch.tv/hector_pulido_" target="blank">
<img align="center" width="30px" alt="Hector's Twitch" src="https://www.vectorlogo.zone/logos/twitch/twitch-icon.svg"/></a> &nbsp; &nbsp;
<a href="https://www.youtube.com/channel/UCS_iMeH0P0nsIDPvBaJckOw" target="blank">
<img align="center" width="30px" alt="Hector's Youtube" src="https://www.vectorlogo.zone/logos/youtube/youtube-icon.svg"/></a> &nbsp; &nbsp;
<a href="https://pequesoft.net/" target="blank">
<img align="center" width="30px" alt="Pequesoft website" src="https://github.com/HectorPulido/HectorPulido/blob/master/img/pequesoft-favicon.png?raw=true"/></a> &nbsp; &nbsp;
</p>
