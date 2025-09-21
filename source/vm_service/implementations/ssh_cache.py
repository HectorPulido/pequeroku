import paramiko
import settings
from qemu_manager.models import VMRecord

cache_data = {}


def clear_cache(vm_id: str):
    cache_data[vm_id] = {}


def clear_all_cache():
    cache_data = {}


def _generate_ssh_and_sftp_by_id(
    container_id,
    ssh_port,
    ssh_user,
):
    print("Generating cache for: ", container_id)
    key = paramiko.Ed25519Key.from_private_key_file(settings.VM_SSH_PRIVKEY)
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    port = ssh_port or 22

    cli.connect(
        "127.0.0.1",
        port=port,
        username=ssh_user,
        pkey=key,
        look_for_keys=False,
    )

    sftp = cli.open_sftp()

    chan = cli.invoke_shell(width=120, height=32)
    chan.settimeout(0.0)

    cache_data[container_id] = {"cli": cli, "sftp": sftp, "chan": chan}

    return cli, sftp, chan


def _generate_ssh_and_sftp(container: VMRecord):
    return _generate_ssh_and_sftp_by_id(
        container.id, container.ssh_port, container.ssh_user
    )


def cache_ssh_and_sftp_by_id(container_id, ssh_port, ssh_user):
    if container_id not in cache_data:
        _generate_ssh_and_sftp_by_id(container_id, ssh_port, ssh_user)
        return cache_data[container_id]

    data = cache_data[container_id]
    if "cli" not in data:
        _generate_ssh_and_sftp_by_id(container_id, ssh_port, ssh_user)
        return cache_data[container_id]
    if "sftp" not in data:
        _generate_ssh_and_sftp_by_id(container_id, ssh_port, ssh_user)
        return cache_data[container_id]

    if data["cli"] is None or data["sftp"] is None:
        _generate_ssh_and_sftp_by_id(container_id, ssh_port, ssh_user)
        return cache_data[container_id]

    try:
        cli = data["cli"]
        cli.exec_command("echo hello")
    except Exception as e:
        print("Exception caching: ", e)
        _generate_ssh_and_sftp_by_id(container_id, ssh_port, ssh_user)
        return cache_data[container_id]

    return data


def cache_ssh_and_sftp(container: VMRecord):
    return cache_ssh_and_sftp_by_id(
        container.id, container.ssh_port, container.ssh_user
    )


def open_ssh_and_sftp(container: VMRecord, open_sftp=False):
    val = cache_ssh_and_sftp(container)
    sftp = val["sftp"]
    cli = val["cli"]

    if not open_sftp:
        return None, cli

    return sftp, cli


def generate_console(container: VMRecord):
    val = cache_ssh_and_sftp(container)
    cli = val["cli"]

    chan = cli.invoke_shell(width=120, height=32)
    chan.settimeout(0.0)

    return cli, chan
