"""ResidentialHeating connection and a live proxy to its log API."""
import requests
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from verso.models import ResidentialHeating
from verso.serializers import ResidentialHeatingSerializer


class ResidentialHeatingViewSet(viewsets.ModelViewSet):
    serializer_class = ResidentialHeatingSerializer
    permission_classes = [permissions.IsAuthenticated]
    filterset_fields = ['house']

    def get_queryset(self):
        return ResidentialHeating.objects.filter(house__members=self.request.user)

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """Fetch one page (?page=, newest first) of the house device's external logs with its token; nothing is stored.

        The external next/previous URLs are replaced by page numbers so its host never reaches the client.
        """
        heating = self.get_object()
        try:
            page = int(request.query_params.get('page', 1))
        except ValueError:
            return Response({'detail': 'page must be an integer.'}, status=status.HTTP_400_BAD_REQUEST)
        url = f"{heating.base_url.rstrip('/')}/log/"
        try:
            response = requests.get(
                url, params={'device': heating.device, 'page': page}, headers={'Authorization': f'Token {heating.token}'}, timeout=15
            )
        except requests.RequestException as exc:
            return Response({'detail': f'Could not reach {url}: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)
        if response.status_code == status.HTTP_404_NOT_FOUND:
            return Response({'detail': f'Page {page} does not exist.'}, status=status.HTTP_404_NOT_FOUND)
        if not response.ok:
            return Response(
                {'detail': f'{url} responded {response.status_code}: {response.text[:300]}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        try:
            payload = response.json()
            return Response({
                'count': payload['count'],
                'page': page,
                'next_page': page + 1 if payload['next'] else None,
                'previous_page': page - 1 if payload['previous'] else None,
                'results': payload['results'],
            })
        except (ValueError, KeyError, TypeError):
            return Response(
                {'detail': f'{url} did not return a paginated log list: {response.text[:300]}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
