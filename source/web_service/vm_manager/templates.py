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
    """
    Apply first template
    """

    if not instance.first_start:
        return

    if instance.status != "running":
        return

    instance.first_start = False
    default_template = FileTemplate.objects.filter(slug="default").first()
    if not default_template:
        return

    _ = apply_template(instance, default_template)
    instance.save()
