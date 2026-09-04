# Apsis API documentation

Apsis provides a small public-post API at `/api/apsis/`.

## Posts

`posts/` supports the standard Django REST Framework list, retrieve, create,
update, and delete operations and uses trailing slashes.

| Field | Description |
|---|---|
| `files` | Client-managed JSON file metadata. |
| `author` | Read-only user ID; set to the authenticated caller on create. |
| `geolocation` | Optional free-text location. |
| `content` | Post body. |
| `name` | Optional post name/title. |
| `created_at` | Read-only creation time. |

Listing and reading posts are public. Creating a post requires authentication.
Only its author or a staff user may change or delete an existing post.
