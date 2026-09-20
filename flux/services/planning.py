"""Generate a starter milestone/task backlog from a project's design."""

from django.db import transaction

from flux.models import IntegrationOperation, Milestone, Resource, Task


def generate_tasks(project):
    """Create missing standard tasks per entity, resource, role and screen. Returns the created tasks."""
    entities = list(project.entities.order_by("name"))
    plan = [
        ("Datamodell", [(f"Modell: {e.name}", "Fält, relationer och migration.") for e in entities]),
        (
            "API",
            [
                (f"API: {r.path}", f"Operationer: {', '.join(r.operations) or 'inga'}.")
                for r in Resource.objects.filter(entity__project=project).order_by("path")
            ],
        ),
        ("Behörigheter", [(f"Roll: {r.name}", "Behörighetsmatris och scope-kontroller.") for r in project.roles.order_by("name")]),
        (
            "Gränssnitt",
            [(f"Skärm: {s.name}", f"Route {s.route}.") for s in project.screens.order_by("route")]
            + (
                [(f"Identitet: {project.identity.name}", "Tillämpa tokens, typsnitt, logotyp och ikoner enligt STYLEGUIDE.md.")]
                if project.include_identity and project.identity_id
                else []
            ),
        ),
        (
            "Integrationer",
            [
                (
                    f"Integration: {op.integration.name}.{op.name}",
                    "Verifiera mot live-API:t, kontrollera mappningen och kör de genererade testerna."
                    + (" Sätt upp schemalagd synk." if op.sync else ""),
                )
                for op in IntegrationOperation.objects.filter(integration__project=project)
                .select_related("integration")
                .order_by("integration__name", "name")
            ],
        ),
        ("Tester", [(f"Tester: {e.name}", "Modell-, API- och behörighetstester.") for e in entities]),
    ]
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
