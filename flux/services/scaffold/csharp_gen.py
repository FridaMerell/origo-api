"""C# target: entity classes, DbContext and API controllers."""

from .common import namespace, pascal

_TYPES = {
    "string": "string",
    "text": "string",
    "int": "int",
    "bigint": "long",
    "decimal": "decimal",
    "float": "double",
    "bool": "bool",
    "date": "DateOnly",
    "datetime": "DateTime",
    "time": "TimeOnly",
    "uuid": "Guid",
    "json": "JsonElement",
    "email": "string",
    "url": "string",
}
_REFERENCE_TYPES = {"string", "text", "email", "url"}
_DELETE_BEHAVIOR = {"cascade": "Cascade", "protect": "Restrict", "set_null": "SetNull"}
_USINGS = "using System;\nusing System.Collections.Generic;\nusing System.Text.Json;\n"


def _class_source(entity, ns):
    name = pascal(entity["name"])
    lines = [_USINGS, "#nullable enable", f"namespace {ns}.Models;", ""]
    if entity.get("description"):
        lines += ["/// <summary>", f"/// {entity['description'].strip().splitlines()[0]}", "/// </summary>"]
    lines += [f"public class {name}", "{", "    public int Id { get; set; }"]
    for field in entity["fields"]:
        cs_type = _TYPES[field["type"]]
        prop = pascal(field["name"])
        if field["nullable"]:
            lines.append(f"    public {cs_type}? {prop} {{ get; set; }}")
        elif field["type"] in _REFERENCE_TYPES:
            lines.append(f"    public {cs_type} {prop} {{ get; set; }} = string.Empty;")
        else:
            lines.append(f"    public {cs_type} {prop} {{ get; set; }}")
    for relation in entity["relations"]:
        target, prop = pascal(relation["target"]), pascal(relation["name"])
        if relation["kind"] == "m2m":
            lines.append(f"    public ICollection<{target}> {prop} {{ get; set; }} = new List<{target}>();")
        elif relation["nullable"] or relation["on_delete"] == "set_null":
            lines.append(f"    public int? {prop}Id {{ get; set; }}")
            lines.append(f"    public {target}? {prop} {{ get; set; }}")
        else:
            lines.append(f"    public int {prop}Id {{ get; set; }}")
            lines.append(f"    public {target}? {prop} {{ get; set; }}")
    lines += ["}", ""]
    return "\n".join(lines)


def _context_source(spec, ns):
    lines = [
        "using Microsoft.EntityFrameworkCore;",
        f"using {ns}.Models;",
        "",
        f"namespace {ns}.Data;",
        "",
        "public class AppDbContext : DbContext",
        "{",
        "    public AppDbContext(DbContextOptions<AppDbContext> options) : base(options) { }",
        "",
    ]
    for entity in spec["entities"]:
        name = pascal(entity["name"])
        lines.append(f"    public DbSet<{name}> {name}s => Set<{name}>();")
    relation_lines = []
    for entity in spec["entities"]:
        source = pascal(entity["name"])
        for relation in entity["relations"]:
            prop = pascal(relation["name"])
            builder = f"        modelBuilder.Entity<{source}>()"
            if relation["kind"] == "m2m":
                relation_lines.append(f"{builder}.HasMany(e => e.{prop}).WithMany();")
                continue
            behavior = _DELETE_BEHAVIOR[relation["on_delete"]]
            if relation["kind"] == "o2o":
                relation_lines.append(
                    f"{builder}.HasOne(e => e.{prop}).WithOne().HasForeignKey<{source}>(e => e.{prop}Id)"
                    f".OnDelete(DeleteBehavior.{behavior});"
                )
            else:
                relation_lines.append(
                    f"{builder}.HasOne(e => e.{prop}).WithMany().HasForeignKey(e => e.{prop}Id)"
                    f".OnDelete(DeleteBehavior.{behavior});"
                )
    if relation_lines:
        lines += ["", "    protected override void OnModelCreating(ModelBuilder modelBuilder)", "    {", *relation_lines, "    }"]
    lines += ["}", ""]
    return "\n".join(lines)


def _controller_source(resource, ns, authorize):
    name = pascal(resource["entity"])
    dbset = f"{name}s"
    operations = resource["operations"]
    lines = [
        "using System.Collections.Generic;",
        "using System.Threading.Tasks;",
        "using Microsoft.AspNetCore.Authorization;",
        "using Microsoft.AspNetCore.Mvc;",
        "using Microsoft.EntityFrameworkCore;",
        f"using {ns}.Data;",
        f"using {ns}.Models;",
        "",
        f"namespace {ns}.Controllers;",
        "",
        "[ApiController]",
        *(["[Authorize]"] if authorize else []),
        f'[Route("api/{resource["path"].strip("/")}")]',
        f"public class {name}Controller : ControllerBase",
        "{",
        "    private readonly AppDbContext _db;",
        "",
        f"    public {name}Controller(AppDbContext db) => _db = db;",
    ]
    if "list" in operations:
        lines += ["", "    [HttpGet]", f"    public async Task<ActionResult<List<{name}>>> List() =>", f"        await _db.{dbset}.ToListAsync();"]
    if "retrieve" in operations:
        lines += [
            "",
            '    [HttpGet("{id:int}")]',
            f"    public async Task<ActionResult<{name}>> Retrieve(int id)",
            "    {",
            f"        var item = await _db.{dbset}.FindAsync(id);",
            "        return item is null ? NotFound() : item;",
            "    }",
        ]
    if "create" in operations:
        created = (
            "        return CreatedAtAction(nameof(Retrieve), new { id = item.Id }, item);"
            if "retrieve" in operations
            else f'        return Created($"api/{resource["path"].strip("/")}/{{item.Id}}", item);'
        )
        lines += [
            "",
            "    [HttpPost]",
            f"    public async Task<ActionResult<{name}>> Create({name} item)",
            "    {",
            f"        _db.{dbset}.Add(item);",
            "        await _db.SaveChangesAsync();",
            created,
            "    }",
        ]
    if "update" in operations:
        lines += [
            "",
            '    [HttpPut("{id:int}")]',
            f"    public async Task<IActionResult> Update(int id, {name} item)",
            "    {",
            "        if (id != item.Id) return BadRequest();",
            "        _db.Entry(item).State = EntityState.Modified;",
            "        await _db.SaveChangesAsync();",
            "        return NoContent();",
            "    }",
        ]
    if "delete" in operations:
        lines += [
            "",
            '    [HttpDelete("{id:int}")]',
            "    public async Task<IActionResult> Delete(int id)",
            "    {",
            f"        var item = await _db.{dbset}.FindAsync(id);",
            "        if (item is null) return NotFound();",
            f"        _db.{dbset}.Remove(item);",
            "        await _db.SaveChangesAsync();",
            "        return NoContent();",
            "    }",
        ]
    lines += ["}", ""]
    return "\n".join(lines)


def generate(spec):
    ns = namespace(spec)
    files = [{"path": f"Models/{pascal(e['name'])}.cs", "content": _class_source(e, ns)} for e in spec["entities"]]
    if spec["entities"]:
        files.append({"path": "Data/AppDbContext.cs", "content": _context_source(spec, ns)})
    if spec["resources"]:
        files += [
            {
                "path": f"Controllers/{pascal(r['entity'])}Controller.cs",
                "content": _controller_source(r, ns, spec["stack"]["auth_method"] != "none"),
            }
            for r in spec["resources"]
        ]
    return files
