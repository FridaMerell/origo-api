# Tempus documentation

Tempus handles species taxonomy, seasonality, observations, checklists, nature
routes, and short-lived BirdNET detections.

## Feature documentation

- [BirdNET](birdnet/README.md)
  - [API contract](birdnet/api.md)
  - [Fake detection data](birdnet/fake-data.md)
- [Phenograms](phenograms.md)
- [Routes and suggested stops](routes.md)
- [Observations and checklists](observations-and-checklists.md)
- [Species and taxonomy](species-and-taxonomy.md)
- [Geography and GeoJSON](geography.md)
- [Background tasks](background-tasks.md)
- [Permissions](permissions.md)
- [API index](api.md)
- [Operations and configuration](operations.md)
- [Artdatabanken and Artportalen](artdatabanken/README.md)
  - [API products](artdatabanken/apis.md)
  - [Authentication](artdatabanken/authentication.md)
  - [SOS observations and phenograms](artdatabanken/observations-and-phenograms.md)
  - [Future Artportalen reporting](artdatabanken/artportalen-write.md)

## Main API prefix

Most Tempus resources are exposed beneath `/api/tempus/` through Django REST
Framework. Authentication and object scoping vary by resource and are described
on each feature page.
