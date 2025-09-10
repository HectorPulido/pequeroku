from .models import Container, FileTemplate, Node
from .vm_client import VMServiceClient, VMCreate, VMAction, VMUploadFiles, VMFile


def apply_template(
    container: Container, template: FileTemplate, dest_path="/app", clean=True
):
    """
    Apply a template to a container
    """
    node: Node = container.node
    client = VMServiceClient(
        base_url=str(node.node_host),
        token=str(node.auth_token),
    )

    files = []
    for it in template.items.all().order_by("order", "path"):
        files.append(
            VMFile(
                mode=it.mode,
                path=it.path,
                content=it.content,
            )
        )

    response = client.upload_files(
        str(container.container_id),
        VMUploadFiles(dest_path=dest_path, clean=clean, files=files),
    )

    return response


def first_start_of_container(instance):
    """
    Apply first template
    """

    if not instance.first_start:
        return

    if instance.status != "running":
        return

    instance.first_start = False
    default_template = FileTemplate.objects.filter(slug="default").first()
    apply_template(instance, default_template)
    instance.save()


def apply_ai_generated_project(
    container: Container, content: str, dest_path="/app", clean=True
):
    import os
    from django.conf import settings

    node: Node = container.node
    client = VMServiceClient(
        base_url=str(node.node_host),
        token=str(node.auth_token),
    )

    # Getting the script
    route = os.path.join(
        settings.BASE_DIR, "ai_services", "gencode_scripts", "build_from_gencode.py"
    )

    code = ""
    with open(route, "r", encoding="utf-8") as f:
        code = f.read()

    # Uploading files
    response = client.upload_files(
        str(container.container_id),
        VMUploadFiles(
            dest_path=dest_path,
            clean=clean,
            files=[
                VMFile(
                    mode=0o644,
                    path="build_from_gencode.py",
                    content=code,
                ),
                VMFile(
                    mode=0o644,
                    path="gencode.txt",
                    content=content,
                ),
            ],
        ),
    )

    if not response:
        print("Could not upload files...")

    # Execute
    response = client.execute_sh(
        str(container.container_id), f"cd {dest_path} && python3 build_from_gencode.py"
    )

    if not response:
        print("Could not executing the code...")
