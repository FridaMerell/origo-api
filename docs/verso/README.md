# Verso API documentation

Verso is Origo's shared-house API. It covers homes, bookings, checkout notes,
maintenance ventures, venture tasks, expenses, and activity updates.

Base prefix: `/api/verso/`. All endpoints require authentication and use
trailing slashes. A user can only see data belonging to a house they are a
member of; inaccessible rows appear as `404` on detail requests.

## Resources

| Resource | Purpose | Filters |
|---|---|---|
| `houses/` | House name, address, position, and members | `members` |
| `bookings/` | Visits to a house | `house`, `future` |
| `booking-requests/` | Proposed visits | `house`, `status` |
| `check-outs/` | Checkout timestamp, notes, and file metadata | `booking`, `booking__house` |
| `ventures/` | House maintenance/projects | `house` |
| `venture-tasks/` | Tasks within a venture | `venture`, `completed`, `venture__house` |
| `expenses/` | Expenses tied to a house and/or venture | `house`, `venture` |
| `updates/` | Updates for a house, venture, or venture task | `venture`, `task`, `author`, `house` |

Each resource supports the standard list, retrieve, create, update, and delete
operations. Creating a house automatically adds the caller as a member.

## Rules and relationships

- Bookings, booking requests, ventures, and house-level expenses must belong
  to a house the caller belongs to.
- A venture must belong to a house. Venture tasks belong to a venture.
- An expense must have a house, a venture, or both. When both are supplied,
  the venture must belong to that house.
- An update must relate to at least one of a house, venture, or task. If more
  than one is supplied, they must resolve to the same house. The API sets its
  `author` to the caller on creation.
- `files` fields contain client-managed JSON file metadata; they are not file
  upload endpoints.

## Summary endpoints

| Path | Method | Purpose |
|---|---|---|
| `houses/dashboard/?house=<id>&year=<year>` | GET | Return the selected (or first accessible) house plus its bookings, requests, checkouts, ventures, tasks, expenses, updates, and yearly expense total. |
| `expenses/year_expenses/?house_id=<id>&year=<year>` | GET | Return the total expenses for the house in the requested year. |

`year` defaults to the current year. `bookings/?future=true` returns bookings
whose start date is today or later; `future=false` returns earlier bookings.
