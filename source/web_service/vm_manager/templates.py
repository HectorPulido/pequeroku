from .models import Container, FileTemplate
from .vm_client import VMServiceClient, VMUploadFiles, VMFile


def apply_template(
    container: Container,
    template: FileTemplate,
    dest_path: str = "/app",
    clean: bool = True,
):
    """
    Apply a template to a container
    """
    client = VMServiceClient(container.node)

    files = []
    for it in template.items.all().order_by("order", "path"):
        files.append(
            VMFile(
                mode=it.mode,
                path=it.path,
                text=it.content,
            )
        )

    response = client.upload_files(
        str(container.container_id),
        VMUploadFiles(dest_path=dest_path, clean=clean, files=files),
    )

    return response


def first_start_of_container(instance: Container):
    """Seed a brand-new workspace with the "default" welcome template, once.

    Triggered when the IDE filesystem WebSocket first connects to a container.
    It MUST NEVER destroy existing files: containers created and populated through
    the public API / MCP keep ``first_start=True`` until their first IDE connect,
    so a destructive seed here would wipe an agent's already-populated ``/app``
    (the exact "MCP deletes /app after a reboot / at random" bug). The template is
    therefore applied with ``clean=False`` — it only adds the welcome files, it
    never ``rm -rf``s the directory. Fresh IDE containers still get seeded on an
    empty ``/app``; the visible result is identical.
    """

    if not instance.first_start:
        return

    if instance.status != "running":
        return

    instance.first_start = False
    default_template = FileTemplate.objects.filter(slug="default").first()
    if not default_template:
        return

    _ = apply_template(instance, default_template, clean=False)
    instance.save()
