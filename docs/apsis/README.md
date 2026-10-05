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
| `svenska_kyrkan_place_id` | Optional ID of the church in Svenska kyrkan's PlatserAPI. |
| `created_at` | Read-only creation time. |

Listing and reading posts are public. Creating, changing and deleting require
authentication; any authenticated user may change or delete any post.

## Svenska kyrkan places

A post stores only the Platser place ID. Details are read live from Svenska
kyrkan's PlatserAPI v4 (`SVENSKAKYRKAN_TOKEN`) and cached: a place for 24
hours, a search for one hour.

| Endpoint | Access | Description |
|---|---|---|
| `GET places/?q=<name>` | Authenticated | Up to 10 churches and chapels whose name contains every word in `q`. |
| `GET places/summaries/?ids=<id>,<id>` | Public | The places behind a list of posts as an object keyed by ID, fetched upstream in one request. Unknown IDs are left out; at most 200 IDs. |
| `GET places/<id>/` | Public | One place; `404` when it does not exist. |

All return the same summary: `id`, `name`, `owner_name`, `municipality`,
`county`, `latitude`, `longitude`, `short_description`, `long_description`
(Markdown), `address`, `postal_code`, `city`, `url`, `email`, `phone`,
`categories`, `tags`, `open_hours` (the period valid today, as runs of days
`mo`–`su` sharing the same hours), `facilities` (`toilet`,
`accessible_toilet`, `cafe`, `wifi`, `parking`, `charging_station`,
`hearing_loop`, `ramp`) and `links`. Platser's images, audio and video require
a special permission the key does not have.

`places/<id>/` additionally returns `building`: the church's record in
Kyrkobyggnadsregistret (KBR API v1) exactly as KBR returned it, or `null`.
Platser and KBR share no ID, so the building is the KBR church with the same
name within 500 m of the place.

A missing key answers `503`; an upstream failure answers `502`.
