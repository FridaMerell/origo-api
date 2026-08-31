# Registrera en Tempus-observation med User token

Skicka en `POST` till `/api/tempus/observations/`. Observationen skapas för
användaren som äger tokenen.

```http
POST /api/tempus/observations/
Authorization: Token <user-token>
Content-Type: application/json

{
  "species": 102822,
  "observed_at": "2026-08-31T10:15:00+02:00",
  "location": { "type": "Point", "coordinates": [14.1567, 56.0294] },
  "count": 2,
  "notes": "Två individer ropade."
}
```

`species` och `observed_at` krävs. `species` kan vara antingen Tempus art-UUID
eller Dyntaxa taxon-id. `location` är valfri; om den skickas ska den vara en
GeoJSON Point med koordinater i ordningen longitud, latitud. Vid lyckat anrop
returneras `201 Created`.

## C#-exempel

```csharp
using System.Net.Http.Headers;
using System.Net.Http.Json;

using var http = new HttpClient
{
    BaseAddress = new Uri("https://tempus.example.se/")
};

using var request = new HttpRequestMessage(HttpMethod.Post,
    "api/tempus/observations/");
request.Headers.Authorization = new AuthenticationHeaderValue("Token", userToken);
request.Content = JsonContent.Create(new
{
    species = dyntaxaTaxonId, // Eller speciesUuid för befintliga Tempus-klienter.
    observed_at = "2026-08-31T10:15:00+02:00",
    location = new { type = "Point", coordinates = new[] { 14.1567, 56.0294 } },
    count = 2,
    notes = "Två individer ropade."
});

using var response = await http.SendAsync(request);
response.EnsureSuccessStatusCode();
```

Tokenen ska hanteras som en hemlighet och får inte loggas.
