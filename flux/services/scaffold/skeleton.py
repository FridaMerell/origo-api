"""Repository skeleton target: README, env, Docker, CI and base project files."""

from .common import app_label, namespace
from .identity_gen import styleguide

_DB_URLS = {
    "postgresql": "postgres://app:app@db:5432/app",
    "mysql": "mysql://app:app@db:3306/app",
    "sqlite": "sqlite:///db.sqlite3",
    "sqlserver": "mssql://sa:Your_password123@db:1433/app",
}
_CS_CONNECTIONS = {
    "postgresql": "Host=db;Port=5432;Database=app;Username=app;Password=app",
    "mysql": "Server=db;Port=3306;Database=app;User=app;Password=app",
    "sqlite": "Data Source=app.db",
    "sqlserver": "Server=db,1433;Database=app;User Id=sa;Password=Your_password123;TrustServerCertificate=True",
}
_DB_IMAGES = {
    "postgresql": ("postgres:16", {"POSTGRES_USER": "app", "POSTGRES_PASSWORD": "app", "POSTGRES_DB": "app"}),
    "mysql": ("mysql:8", {"MYSQL_USER": "app", "MYSQL_PASSWORD": "app", "MYSQL_DATABASE": "app", "MYSQL_ROOT_PASSWORD": "root"}),
    "sqlserver": ("mcr.microsoft.com/mssql/server:2022-latest", {"ACCEPT_EULA": "Y", "MSSQL_SA_PASSWORD": "Your_password123"}),
}
_DJANGO_DRIVERS = {"postgresql": "psycopg[binary]", "mysql": "mysqlclient", "sqlite": None, "sqlserver": "mssql-django"}
_EF_PROVIDERS = {
    "postgresql": ("Npgsql.EntityFrameworkCore.PostgreSQL", "options.UseNpgsql(connectionString)"),
    "mysql": ("Pomelo.EntityFrameworkCore.MySql", "options.UseMySql(connectionString, ServerVersion.AutoDetect(connectionString))"),
    "sqlite": ("Microsoft.EntityFrameworkCore.Sqlite", "options.UseSqlite(connectionString)"),
    "sqlserver": ("Microsoft.EntityFrameworkCore.SqlServer", "options.UseSqlServer(connectionString)"),
}


def _backend(spec):
    targets = spec["stack"]["targets"]
    return "django" if "django" in targets else "csharp" if "csharp" in targets else None


def env_example(spec):
    stack = spec["stack"]
    backend = _backend(spec)
    if backend == "csharp":
        lines = [f"ConnectionStrings__Default={_CS_CONNECTIONS[stack['database']]}"]
    else:
        lines = [f"DATABASE_URL={_DB_URLS[stack['database']]}"]
    if backend == "django":
        lines += ["DJANGO_SECRET_KEY=change-me", "DJANGO_DEBUG=true"]
    if stack["auth_method"] == "jwt" or (stack["auth_method"] == "token" and backend == "csharp"):
        lines.append("AUTH_SECRET=change-me-to-a-long-random-string-of-at-least-32-characters")
    if "typescript" in stack["targets"]:
        lines.append("NEXT_PUBLIC_API_URL=http://localhost:8000/api")
    for integration in spec["integrations"]:
        lines += ["", f"# {integration['name']} ({integration['kind']})"]
        lines += [f"{name}=" for name in integration["env_vars"]]
    return "\n".join(lines) + "\n"


def requirements(spec):
    stack = spec["stack"]
    packages = ["Django", "djangorestframework", "django-filter", "dj-database-url"]
    driver = _DJANGO_DRIVERS[stack["database"]]
    if driver:
        packages.append(driver)
    if stack["auth_method"] == "jwt":
        packages.append("djangorestframework-simplejwt")
    if stack["api_naming"] == "camel_case":
        packages.append("djangorestframework-camel-case")
    if _has_operations(spec):
        packages.append("requests")
    if _has_scheduled_sync(spec):
        packages += ["django-tasks", "django-tasks-db"]
    return "\n".join(packages) + "\n"


def _operations(spec):
    return [op for integration in spec["integrations"] for op in integration.get("operations", [])]


def _has_operations(spec):
    return bool(_operations(spec))


def _has_scheduled_sync(spec):
    return any(op.get("sync") and op.get("sync_interval_minutes") for op in _operations(spec))


def dockerfile(spec):
    if _backend(spec) == "django":
        return (
            "FROM python:3.12-slim\n"
            "WORKDIR /app\n"
            "COPY requirements.txt .\n"
            "RUN pip install --no-cache-dir -r requirements.txt\n"
            "COPY . .\n"
            'CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]\n'
        )
    return (
        "FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build\n"
        "WORKDIR /src\n"
        "COPY . .\n"
        "RUN dotnet publish -c Release -o /out\n\n"
        "FROM mcr.microsoft.com/dotnet/aspnet:8.0\n"
        "WORKDIR /app\n"
        "COPY --from=build /out .\n"
        f'ENTRYPOINT ["dotnet", "{namespace(spec)}.dll"]\n'
    )


def compose(spec):
    database = spec["stack"]["database"]
    port = "8080:8080" if _backend(spec) == "csharp" else "8000:8000"
    lines = ["services:", "  app:", "    build: .", "    env_file: .env", "    ports:", f'      - "{port}"']
    if database in _DB_IMAGES:
        image, environment = _DB_IMAGES[database]
        lines += ["    depends_on:", "      - db", "  db:", f"    image: {image}", "    environment:"]
        lines += [f"      {key}: {value}" for key, value in environment.items()]
    return "\n".join(lines) + "\n"


def ci(spec):
    backend = _backend(spec)
    steps = ["      - uses: actions/checkout@v4"]
    if backend == "django":
        steps += [
            "      - uses: actions/setup-python@v5",
            "        with:",
            '          python-version: "3.12"',
            "      - run: pip install -r requirements.txt",
            "      - run: python manage.py test",
        ]
    elif backend == "csharp":
        steps += [
            "      - uses: actions/setup-dotnet@v4",
            "        with:",
            '          dotnet-version: "8.0.x"',
            "      - run: dotnet build",
        ]
    lines = ["name: CI", "on: [push, pull_request]", "jobs:", "  test:", "    runs-on: ubuntu-latest", "    steps:", *steps]
    if "typescript" in spec["stack"]["targets"]:
        lines += [
            "  frontend:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            "      - uses: actions/setup-node@v4",
            "        with:",
            '          node-version: "20"',
            "      - run: npm ci",
            "      - run: npm run build",
        ]
    return "\n".join(lines) + "\n"


def gitignore(spec):
    lines = [".env", ".DS_Store"]
    if _backend(spec) == "django":
        lines += ["__pycache__/", "*.pyc", "db.sqlite3", ".venv/"]
    if _backend(spec) == "csharp":
        lines += ["bin/", "obj/", "*.db"]
    if "typescript" in spec["stack"]["targets"]:
        lines += ["node_modules/", ".next/"]
    return "\n".join(lines) + "\n"


def readme(spec):
    project = spec["project"]
    lines = [f"# {project['name']}", ""]
    if project.get("description"):
        lines += [project["description"], ""]
    lines += ["## Entities", ""]
    lines += [f"- **{e['name']}**" + (f": {e['description']}" if e.get("description") else "") for e in spec["entities"]]
    if spec["screens"]:
        lines += ["", "## Screens", ""]
        lines += [f"- `{s['route']}` {s['name']}" for s in spec["screens"]]
    if spec.get("identity"):
        lines += ["", "## Visual identity", "", "See `identity/STYLEGUIDE.md`; the design tokens come from the `design` scaffold target."]
    lines += ["", "## Getting started", "", "1. Copy `.env.example` to `.env` and fill in the values.", "2. `docker compose up --build`", ""]
    if _backend(spec) == "django" and spec["stack"]["api_naming"] == "camel_case":
        lines += ["The API uses camelCase through `djangorestframework-camel-case` (configured in `config/settings.py`).", ""]
    return "\n".join(lines)


def django_project_files(spec):
    stack = spec["stack"]
    label = app_label(spec)
    apps = [
        '    "django.contrib.admin",',
        '    "django.contrib.auth",',
        '    "django.contrib.contenttypes",',
        '    "django.contrib.sessions",',
        '    "django.contrib.messages",',
        '    "django.contrib.staticfiles",',
        '    "rest_framework",',
        '    "django_filters",',
    ]
    if stack["auth_method"] == "token":
        apps.append('    "rest_framework.authtoken",')
    if _has_scheduled_sync(spec):
        apps += ['    "django_tasks",', '    "django_tasks_db",']
    apps.append(f'    "{label}",')
    authentication = {
        "session": "rest_framework.authentication.SessionAuthentication",
        "token": "rest_framework.authentication.TokenAuthentication",
        "jwt": "rest_framework_simplejwt.authentication.JWTAuthentication",
    }.get(stack["auth_method"])
    rest = ["REST_FRAMEWORK = {"]
    if authentication:
        rest.append(f'    "DEFAULT_AUTHENTICATION_CLASSES": ["{authentication}"],')
        rest.append('    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],')
    else:
        rest.append('    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],')
    rest.append(
        '    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend", '
        '"rest_framework.filters.OrderingFilter"],'
    )
    if stack["api_naming"] == "camel_case":
        rest.append('    "DEFAULT_RENDERER_CLASSES": ["djangorestframework_camel_case.render.CamelCaseJSONRenderer"],')
        rest.append('    "DEFAULT_PARSER_CLASSES": ["djangorestframework_camel_case.parser.CamelCaseJSONParser"],')
    rest.append("}")

    settings = "\n".join(
        [
            "import os",
            "from pathlib import Path",
            "",
            "import dj_database_url",
            "",
            "BASE_DIR = Path(__file__).resolve().parent.parent",
            'SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "change-me")',
            'DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"',
            'ALLOWED_HOSTS = ["*"] if DEBUG else []',
            "",
            "INSTALLED_APPS = [",
            *apps,
            "]",
            "",
            "MIDDLEWARE = [",
            '    "django.middleware.security.SecurityMiddleware",',
            '    "django.contrib.sessions.middleware.SessionMiddleware",',
            '    "django.middleware.common.CommonMiddleware",',
            '    "django.middleware.csrf.CsrfViewMiddleware",',
            '    "django.contrib.auth.middleware.AuthenticationMiddleware",',
            '    "django.contrib.messages.middleware.MessageMiddleware",',
            "]",
            "",
            'ROOT_URLCONF = "config.urls"',
            "",
            "TEMPLATES = [",
            "    {",
            '        "BACKEND": "django.template.backends.django.DjangoTemplates",',
            '        "APP_DIRS": True,',
            '        "OPTIONS": {',
            '            "context_processors": [',
            '                "django.template.context_processors.request",',
            '                "django.contrib.auth.context_processors.auth",',
            '                "django.contrib.messages.context_processors.messages",',
            "            ],",
            "        },",
            "    },",
            "]",
            "",
            "DATABASES = {",
            '    "default": dj_database_url.config(default=f"sqlite:///{BASE_DIR / \'db.sqlite3\'}", conn_max_age=600),',
            "}",
            "",
            *rest,
            "",
            *(
                [
                    "# Scheduled integration syncs; run a worker with `python manage.py db_worker`.",
                    "TASKS = {",
                    '    "default": {"BACKEND": os.environ.get("TASKS_BACKEND", "django_tasks_db.DatabaseBackend")},',
                    "}",
                    "",
                ]
                if _has_scheduled_sync(spec)
                else []
            ),
            'STATIC_URL = "static/"',
            'DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"',
            "USE_TZ = True",
            "",
        ]
    )
    urls = ["from django.contrib import admin", "from django.urls import include, path"]
    auth_paths = []
    if stack["auth_method"] == "jwt":
        urls.append("from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView")
        auth_paths = [
            '    path("api/auth/token/", TokenObtainPairView.as_view()),',
            '    path("api/auth/token/refresh/", TokenRefreshView.as_view()),',
        ]
    elif stack["auth_method"] == "token":
        urls.append("from rest_framework.authtoken.views import obtain_auth_token")
        auth_paths = ['    path("api/auth/token/", obtain_auth_token),']
    elif stack["auth_method"] == "session":
        auth_paths = ['    path("api-auth/", include("rest_framework.urls")),']
    urls += ["", "urlpatterns = [", '    path("admin/", admin.site.urls),', *auth_paths]
    if spec["resources"]:
        urls.append(f'    path("api/", include("{label}.urls")),')
    urls += ["]", ""]
    manage = (
        "#!/usr/bin/env python\n"
        "import os\n"
        "import sys\n\n\n"
        "def main():\n"
        '    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")\n'
        "    from django.core.management import execute_from_command_line\n\n"
        "    execute_from_command_line(sys.argv)\n\n\n"
        'if __name__ == "__main__":\n'
        "    main()\n"
    )
    return [
        {"path": "manage.py", "content": manage},
        {"path": "config/__init__.py", "content": ""},
        {"path": "config/settings.py", "content": settings},
        {"path": "config/urls.py", "content": "\n".join(urls)},
    ]


def csharp_project_files(spec):
    stack = spec["stack"]
    ns = namespace(spec)
    provider, use_database = _EF_PROVIDERS[stack["database"]]
    packages = ['    <PackageReference Include="Microsoft.EntityFrameworkCore" Version="8.*" />', f'    <PackageReference Include="{provider}" Version="8.*" />']
    if stack["auth_method"] in ("jwt", "token"):
        packages.append('    <PackageReference Include="Microsoft.AspNetCore.Authentication.JwtBearer" Version="8.*" />')
    csproj = "\n".join(
        [
            '<Project Sdk="Microsoft.NET.Sdk.Web">',
            "  <PropertyGroup>",
            "    <TargetFramework>net8.0</TargetFramework>",
            "    <Nullable>enable</Nullable>",
            "    <ImplicitUsings>enable</ImplicitUsings>",
            "  </PropertyGroup>",
            "  <ItemGroup>",
            *packages,
            "  </ItemGroup>",
            "</Project>",
            "",
        ]
    )
    if spec["entities"]:
        program = [
            "using Microsoft.EntityFrameworkCore;",
            f"using {ns}.Data;",
            "",
            "var builder = WebApplication.CreateBuilder(args);",
            'var connectionString = builder.Configuration.GetConnectionString("Default")!;',
            f"builder.Services.AddDbContext<AppDbContext>(options => {use_database});",
        ]
    else:
        program = ["var builder = WebApplication.CreateBuilder(args);"]
    program.append("builder.Services.AddControllers();")
    auth = stack["auth_method"]
    if auth in ("jwt", "token"):
        program += [
            "builder.Services.AddAuthentication(\"Bearer\").AddJwtBearer(options =>",
            "{",
            '    var secret = builder.Configuration["AUTH_SECRET"]!;',
            "    options.TokenValidationParameters = new Microsoft.IdentityModel.Tokens.TokenValidationParameters",
            "    {",
            "        ValidateIssuer = false,",
            "        ValidateAudience = false,",
            "        IssuerSigningKey = new Microsoft.IdentityModel.Tokens.SymmetricSecurityKey(System.Text.Encoding.UTF8.GetBytes(secret)),",
            "    };",
            "});",
        ]
    elif auth == "session":
        program.append("builder.Services.AddAuthentication(\"Cookies\").AddCookie(\"Cookies\");")
    if auth != "none":
        program.append("builder.Services.AddAuthorization();")
    program += ["", "var app = builder.Build();"]
    if auth != "none":
        program += ["app.UseAuthentication();", "app.UseAuthorization();"]
    program += ["app.MapControllers();", "app.Run();", ""]
    return [
        {"path": f"{ns}.csproj", "content": csproj},
        {"path": "Program.cs", "content": "\n".join(program)},
    ]


def generate(spec):
    files = [
        {"path": "README.md", "content": readme(spec)},
        {"path": ".env.example", "content": env_example(spec)},
        {"path": ".gitignore", "content": gitignore(spec)},
        {"path": "docker-compose.yml", "content": compose(spec)},
        {"path": ".github/workflows/ci.yml", "content": ci(spec)},
    ]
    if spec.get("identity"):
        files.append({"path": "identity/STYLEGUIDE.md", "content": styleguide(spec)})
    backend = _backend(spec)
    if backend:
        files.append({"path": "Dockerfile", "content": dockerfile(spec)})
    if backend == "django":
        files.append({"path": "requirements.txt", "content": requirements(spec)})
        files += django_project_files(spec)
    if backend == "csharp":
        files += csharp_project_files(spec)
    return files
