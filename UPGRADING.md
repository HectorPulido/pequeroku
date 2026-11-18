# Upgrading & SSH key notes

Details that used to live in the README's Quick Start. None of this is needed
for a fresh install — `start.sh` handles everything.

## Isolated browser previews and runtime secrets

To enable browser previews, set the following in `source/.env`:

```dotenv
PREVIEW_ORIGIN_TEMPLATE=https://{preview}.preview.example.com
```

Point wildcard DNS for `*.preview.example.com` at the PequeRoku ingress and
use a TLS certificate covering those hosts. Preserve the original Host and
forward the HTTPS scheme. Use a separate HTTPS panel hostname on the same site,
for example `panel.example.com`. Each VM and port gets its own preview origin and
host-only cookie. Browser previews require this configuration. API clients can
still fetch the raw response with their Bearer key against the usual endpoint.

Run `source/setup.sh` before rebuilding. It generates or adopts the token for
the local base node and passes it separately to Django and the node at runtime.
Keep distinct tokens for remote nodes in their runtime configuration. The
Compose files use optional `env_file` entries (Docker Compose 2.24 or later).
Rebuild images that previously included service `.env` files, and rotate the
credentials from any copy that was shared. For a suspected preview incident,
review previously registered service workers on the panel origin in affected
browsers. Moving previews to a new origin leaves existing registrations in
place until they are removed.

## Bring your own SSH key

`vm_service` generates its own SSH keypair in the persistent `vm_data` volume,
so VMs work with zero key setup. To bring your own key instead, set `VM_SSH_KEY`
to an absolute path in `source/.env` and uncomment the key mounts in
`docker-compose.yaml`.

## Golden image internals

`./vm_service/scripts/build-golden.sh` writes a self-describing `*.meta.json`
sidecar next to the image; `vm_service` detects it automatically, so no env
edits are needed. `--force` replaces the auto-downloaded base image.

## Upgrading a checkout that predates `start.sh`

The compose file no longer hard-mounts a host SSH key. Your existing base image
keeps working untouched — an image with no `*.meta.json` sidecar is auto-detected
as a golden (cloud-init stays off), so there is nothing to backfill.

But that golden baked a specific public key, so keep using the matching private
key — otherwise `vm_service` generates a new one and existing VMs/goldens become
unreachable. Drop your key into the persistent volume (no compose edits needed):

```bash
mkdir -p source/vm_data/keys
cp ~/.ssh/id_ed25519     source/vm_data/keys/id_vm_pequeroku
cp ~/.ssh/id_ed25519.pub source/vm_data/keys/id_vm_pequeroku.pub
chmod 600 source/vm_data/keys/id_vm_pequeroku
```

Or set `VM_SSH_KEY` to the key's absolute path in `source/.env` and uncomment
the key mounts in `docker-compose.yaml`.
