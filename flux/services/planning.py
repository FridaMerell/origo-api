"""Generate a starter milestone/task backlog from a project's design."""

from django.db import transaction

from flux.models import ApiProjection, Integration, Milestone, Resource, Task


def generate_tasks(project):
    """Create a compact, idempotent delivery backlog from a project's design."""

    entities = list(project.entities.order_by("name"))
    resources = list(Resource.objects.filter(entity__project=project).order_by("path"))
    projections = list(ApiProjection.objects.filter(project=project))
    screens = list(project.screens.order_by("route"))
    integrations = list(Integration.objects.filter(project=project).order_by("name"))
    plan = []
    if entities:
        plan.append(("Datamodell", [("Implementera datamodellen", f"Implementera {len(entities)} entities, deras fält, relationer och migrationer.")]))
    if resources or projections:
        detail = f"Implementera {len(resources)} resurser"
        if projections:
            detail += f" och {len(projections)} API-projektioner"
        plan.append(("API", [("Implementera API-kontrakten", detail + ".")]))
    if project.roles.exists():
        plan.append(("Behörigheter", [("Implementera appens roller", "Implementera den definierade behörighetsmatrisen och scopereglerna.")]))
    if screens or (project.include_identity and project.identity_id):
        detail = f"Implementera {len(screens)} skärmar"
        if project.include_identity and project.identity_id:
            detail += f" enligt identiteten {project.identity.name}"
        plan.append(("Gränssnitt", [("Implementera gränssnittet", detail + ".")]))
    if integrations:
        plan.append(("Integrationer", [("Implementera integrationerna", f"Konfigurera och verifiera {len(integrations)} integrationer, inklusive synk där den är aktiverad.")]))
    if entities or resources or projections:
        plan.append(("Kvalitet", [("Verifiera designkontrakten", "Verifiera datamodell, API-kontrakt, behörigheter och integrationsflöden mot Flux-designen.")]))
    created = []
    with transaction.atomic():
        for milestone_title, items in plan:
            if not items:
                continue
            milestone = Milestone.objects.filter(project=project, title=milestone_title).order_by("id").first()
            if milestone is None:
                milestone = Milestone.objects.create(
                    project=project, title=milestone_title, description="Genererad från projektets design."
                )
            for title, description in items:
                if Task.objects.filter(project=project, milestone=milestone, title=title).exists():
                    continue
                created.append(Task.objects.create(project=project, milestone=milestone, title=title, description=description))
    return created
