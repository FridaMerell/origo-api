"""Code scaffolding from a project's design. Generators are pure functions over a spec dict."""

from . import csharp_gen, django_gen, identity_gen, integration_gen, skeleton, typescript_gen

TARGETS = {
    "django": django_gen.generate,
    "typescript": typescript_gen.generate,
    "csharp": csharp_gen.generate,
    "design": identity_gen.generate,
    "integration": integration_gen.generate,
    "skeleton": skeleton.generate,
}


class ScaffoldError(ValueError):
    """Raised when a target is unknown or the design cannot be scaffolded."""


def generate_files(spec, target):
    if target not in TARGETS:
        raise ScaffoldError(f"Unknown target: {target}. Choose one of: {', '.join(TARGETS)}.")
    try:
        return TARGETS[target](spec)
    except (KeyError, ValueError) as exc:
        raise ScaffoldError(f"Cannot generate {target}: {exc}") from exc
