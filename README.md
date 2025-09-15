
# PequeRoku

PequeRoku is a lightweight platform to **run and share disposable development environments** in the browser.
It combines **QEMU-based virtual machines**, a **FastAPI control service**, a **Django web backend**, and a **browser-based IDE** with Monaco Editor and Xterm.js.

Think of it as a “mini Heroku + VS Code + Playground”, self-hosted and hackable. 🚀

## 💡 Motivation
This project was created to give community members a slice of my servers where they can experiment, learn, and innovate in an isolated environment.

![brief animation on how the platform works](img/demo.gif)

## ✨ Features

* 🔒 **Secure virtual machines** (QEMU/KVM) managed via FastAPI and Redis.
* 🖥️ **Web IDE** with:

  * Monaco Editor (syntax highlighting, themes).
  * Integrated terminal (xterm.js).
  * File tree, upload/download, templates.
* 📊 **Metrics dashboard** (Chart.js) for CPU, memory, threads.
* 🤖 **AI-assisted scaffolding**: generate code templates from natural language prompts.
* 📂 **Repository cloning** from GitHub.
* 🐳 **Containerized stack** with Docker Compose.
* 🧩 **Pluggable architecture** (Redis state store, Django/DRF APIs, FastAPI VM manager).


## 🛠️ Technology Stack

* **Virtualization**: QEMU, KVM (with ARM/x86 support).
* **Backend (VM Service)**: FastAPI + Paramiko + psutil.
* **Backend (Web Service)**: Django + Django Rest Framework + Channels.
* **State**: Redis.
* **Database**: PostgreSQL.
* **Frontend**: Vanilla JS, Monaco Editor, Xterm.js, Chart.js, CSS themes.
* **Orchestration**: Docker Compose, Nginx.


## 📦 Installation

### Prerequisites

* Linux host (Ubuntu/Debian recommended).
* Docker & Docker Compose installed.
* At least one prepared **base qcow2 image**.

### 1. Prepare base qcow2 image

For **Debian 12 (x86)**:

```bash
sudo apt-get update
sudo apt-get install -y qemu-kvm qemu-utils cloud-image-utils genisoimage \
                        libvirt-daemon-system libvirt-clients libvirt libguestfs-tools
curl -LO https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-amd64.qcow2
mv debian-12-genericcloud-amd64.qcow2 debian-raw.qcow2
sudo virt-customize -a debian-raw.qcow2 --install docker-ce,python3,git
sudo qemu-img convert -O qcow2 debian-raw.qcow2 debian12-golden.qcow2
```

For **ARM64 boards (Raspberry Pi, Orange Pi, etc.)**, follow [ARM qcow2 creation steps](docs/ARM.md) (similar to above, but using `qemu-system-arm`).

Finally, move your golden image to:

```bash
mv debian12-golden.qcow2 ./vm_data/base/
```

### 2. Clone the repository

```bash
git clone https://github.com/yourname/pequeroku.git
cd pequeroku
```

### 3. Configure environment

* Copy `.env.example` to `.env` and adjust values (DB credentials, auth token, allowed hosts).
* Ensure your SSH key is mounted in `docker-compose.yaml`.

### 4. Start services

```bash
docker compose up --build
```

![Pequeroku demo on a phone](img/Mobile.gif)

The stack includes:

* VM manager (FastAPI).
* Web service (Django + DRF).
* Redis + Postgres.
* Nginx (serves frontend + static files).



## 🚀 Usage

![brief animation on how create a discord server on Pequeroku](img/DiscordExample.gif)

1. Open the web UI at [http://localhost](http://localhost).
2. Login with your user (create via Django superuser or API).
3. Create a container (VM).
4. Open it in the IDE:
   * Edit code with Monaco.
   * Run commands in the terminal.
   * Upload/download files.
   * Clone from GitHub.
5. Open **Metrics dashboard** to monitor CPU, memory, threads.
6. Optionally, use the **AI Generator** to scaffold new projects.


## 🤖 AI Features

Pequeroku is capable to generate complete projects from scratch using OpenAI compatible services. More ways to use the AI comming soon...

![brief animation on how the AI part works](img/AI.gif)


## 🤝 Contributing

We 💖 contributions!

1. Fork the repo 🍴
2. Create feature branch: `git checkout -b feature/awesome` 🌟
3. Commit your changes: `git commit -m "Add awesome feature"` ✏️
4. Push: `git push origin feature/awesome` 📤
5. Open a Pull Request 🚀



## License

This project is distributed under the MIT License. See the `LICENSE` file for details.

<div align="center">
<h3 align="center">Let's connect 😋</h3>
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
