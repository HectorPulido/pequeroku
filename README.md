# Pequeroku

Welcome to **Pequeroku**, your 🎯 go-to MicroVM management platform! Built with Django, QEMU, Docker, Redis, and Nginx, Pequeroku puts the power of containers at your fingertips with a fun and simple SPA frontend. 


## 💡 Motivation
This project was created to give community members a slice of my servers where they can experiment, learn, and innovate in an isolated environment.

![brief animation on how the platform works](img/demo.gif)


## ✨ Features

* 🐳 **Container Management**: Instantly start, stop, and restart QEMU VM with a click! 
* 💻 **Interactive Shell**: Type commands and see real-time logs—just like magic! (AND 100% COMPATIBLE WITH CLOUDFLARE TUNNELS)
* 🎉 **Live coding enviroment**: You can access your files, upload, edit and run without the console
* 👥 **User management** Powered by django there is a powerfull user management admin
* 🛡️ **Resource Quotas**: Keep things fair by limiting CPU, memory, and container counts per user. 
* 📁 **File Upload**: Drag & drop files directly into your running containers. 
* 🔗 **RESTful API**: Automate everything programmatically! 
* 🖥️ **SPA Frontend**: Fast, snappy single-page app written in vanilla JavaScript. 
* 🌐 **Reverse Proxy**: Nginx for static assets + API proxying—rock-solid performance! 
* 🤖 **AI CAPABILITIES**: Agentic mode to generate projects
* 📱 **Mobile compatible**: Responsive UI perfect for phones
* 🥨 **Template system**: Pequeroku comes with a robuts system to generate templates, super useful for rapid iteration or for learning


## 🚀 Services

Configured in `docker-compose.yaml`:

* **web**: Django + Gunicorn 🌟
* **db**: PostgreSQL 16 🗄️ (persistent volume)
* **nginx**: Nginx latest 🌐 (serves SPA + proxies API)

All on network: `pequeroku-net` 🔗


## 🔧 Prerequisites

Before you start, make sure you have:

* 🐳 Docker & Docker Compose
* 🐍 Python 3.13+
* ✒️ GNU Make (optional)
* 📄 A `.env` file with necessary environment variables



## ⚡ Getting Started

### 📥 Clone the Repository

```bash
git clone https://github.com/yourusername/pequeroku.git
cd pequeroku
```

### Create qcow2
# Ubuntu/Debian

1. Install dependencies
```bash
sudo apt-get update
sudo apt-get install -y qemu-kvm qemu-utils cloud-image-utils genisoimage \
                        libvirt-daemon-system libvirt-clients libvirt
```

2. Download the base image
```bash
sudo curl -LO https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-amd64.qcow2
mv debian-12-genericcloud-amd64.qcow2 debian-raw.qcow2
sudo apt-get install -y libguestfs-tools
sudo virt-customize -a debian-raw.qcow2 \
  --update \
  --install ca-certificates,curl,gnupg,lsb-release \
  --run-command 'install -m 0755 -d /etc/apt/keyrings' \
  --run-command 'curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker-ce.gpg' \
  --run-command 'chmod a+r /etc/apt/keyrings/docker-ce.gpg' \
  --run-command 'sh -c "echo \"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker-ce.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable\" > /etc/apt/sources.list.d/docker.list"' \
  --run-command 'apt-get update' \
  --run-command 'apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin' \
  --run-command 'systemctl enable docker' \
  --run-command 'install -m 0755 -d /usr/share/keyrings' \
  --run-command 'curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg' \
  --append-line '/etc/apt/sources.list.d/cloudflared.list:deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
  --run-command 'apt-get update && apt-get install -y cloudflared' \
  --install python3,python3-pip,git

sudo qemu-img convert -O qcow2 debian-raw.qcow2 debian12-golden.qcow2
```

3. Then move the debian12-golden.qcow2 to "source/vm_data/base/"

4. Edit the docker-compose.yaml
Add the ssh_authorized_keys on the docker-compose.yaml
Adjust also the packages, activate the kvm, etc.

### Create qcow2 ARM (Raspberry Pi or Orange pi)

1. Install dependencies (Ubuntu ARM64)

```bash
sudo apt-get update
sudo apt-get install -y \
    qemu-utils qemu-system-arm libguestfs-tools \
    util-linux kpartx curl gnupg ca-certificates
```


2. Download the debian12 cloud image

```bash
curl -LO https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-arm64.qcow2
mv debian-12-genericcloud-arm64.qcow2 debian-raw.qcow2
```

3. Generate the chroot

```bash
# Load the NBD kernel module with partition support
sudo modprobe nbd max_part=16

# Attach the qcow2 image to /dev/nbd0
sudo qemu-nbd -c /dev/nbd0 debian-raw.qcow2

# Get the root partition, it's usually `/dev/nbd0p1`.
lsblk /dev/nbd0 -o NAME,SIZE,TYPE,MOUNTPOINTS

sudo mkdir -p /mnt/img
sudo mount /dev/nbd0p1 /mnt/img

# Prepare the chroot environment
sudo mount --bind /dev  /mnt/img/dev
sudo mount --bind /proc /mnt/img/proc
sudo mount --bind /sys  /mnt/img/sys
sudo mount --bind /run  /mnt/img/run
sudo cp /etc/resolv.conf /mnt/img/etc/resolv.conf
sudo chroot /mnt/img /bin/bash
```

4. Now you’re **inside the Debian guest**. Run your customizations there:

```bash
set -e

apt-get update
apt-get install -y ca-certificates curl gnupg lsb-release

# Docker
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker-ce.gpg
chmod a+r /etc/apt/keyrings/docker-ce.gpg
sh -c 'echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker-ce.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list'

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable docker || true 

# Cloudflared
install -m 0755 -d /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' > /etc/apt/sources.list.d/cloudflared.list

apt-get update
apt-get install -y cloudflared

# Extra tools
apt-get install -y python3 python3-pip git

exit
```

5. Clean up and detach, generate and optimize

```bash
sudo umount -R /mnt/img
sudo qemu-nbd -d /dev/nbd0
sudo qemu-img convert -O qcow2 debian-raw.qcow2 debian12-golden.qcow2
```

6. Continue with the same path


### 🔑 Environment Variables

Create a `.env` file in the source/web_service folder:

```env
SECRET_KEY=CHANGEME
DB_NAME=mydb
DB_USER=myuser
DB_PASSWORD=mypassword
DB_HOST=db
DB_PORT=5432
DJANGO_SUPERUSER_PASSWORD=testpassword
DJANGO_SUPERUSER_EMAIL=example@example.com
DJANGO_SUPERUSER_USERNAME=admin
DEBUG=1  # 0 for production
```

### 🏗️ Build and Run

```bash
docker-compose build
docker-compose up -d
```

* 🔍 Visit `http://localhost` to explore Pequeroku!
* 🔐 Admin: `http://localhost/admin/`

On the admin add Templates, User, Quotas and Configs

## 🎮 Usage

When you are ready now you can create new container, each container is a complete Debian setup where you can break things on a super secure manner, for example, here I created a discord server super easy:

![brief animation on how create a discord server on Pequeroku](img/DiscordExample.gif)

Also Pequeroku is ready to get request from phones by design

![Pequeroku demo on a phone](img/Mobile.gif)


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
