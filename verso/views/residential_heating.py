"""ResidentialHeating connection and a live proxy to its log API."""
import requests
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from verso.models import ResidentialHeating
from verso.serializers import ResidentialHeatingSerializer


def fetch_upstream(heating, path, params=None):
    """GET ``{base_url}{path}`` with the house's token.

    Returns ``(response, None)`` when the external API answered with 2xx or 404, otherwise
    ``(None, error_response)`` carrying the real cause as a 502.
    """
    url = f"{heating.base_url.rstrip('/')}{path}"
    try:
        response = requests.get(url, params=params, headers={'Authorization': f'Token {heating.token}'}, timeout=15)
    except requests.RequestException as exc:
        return None, Response({'detail': f'Could not reach {url}: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)
    if not response.ok and response.status_code != status.HTTP_404_NOT_FOUND:
        return None, Response(
            {'detail': f'{url} responded {response.status_code}: {response.text[:300]}'},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    return response, None


def post_upstream(heating, path, data):
    """POST JSON to ``{base_url}{path}`` with the house's token.

    Returns ``(response, None)`` for any answer from the external API (its 2xx and 400 are passed on by the
    caller), otherwise ``(None, error_response)`` carrying the real cause as a 502.
    """
    url = f"{heating.base_url.rstrip('/')}{path}"
    try:
        response = requests.post(url, json=data, headers={'Authorization': f'Token {heating.token}'}, timeout=15)
    except requests.RequestException as exc:
        return None, Response({'detail': f'Could not reach {url}: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)
    if not response.ok and response.status_code != status.HTTP_400_BAD_REQUEST:
        return None, Response(
            {'detail': f'{url} responded {response.status_code}: {response.text[:300]}'},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    return response, None


def delete_upstream(heating, path):
    """DELETE ``{base_url}{path}`` with the house's token.

    The upstream status is returned unchanged so callers can give the user its specific error.
    """
    url = f"{heating.base_url.rstrip('/')}{path}"
    try:
        response = requests.delete(url, headers={'Authorization': f'Token {heating.token}'}, timeout=15)
    except requests.RequestException as exc:
        return None, Response({'detail': f'Could not reach {url}: {exc}'}, status=status.HTTP_502_BAD_GATEWAY)
    return response, None


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
        response, error = fetch_upstream(heating, '/log/', {'device': heating.device, 'page': page})
        if error:
            return error
        if response.status_code == status.HTTP_404_NOT_FOUND:
            return Response({'detail': f'Page {page} does not exist.'}, status=status.HTTP_404_NOT_FOUND)
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
                {'detail': f'{response.url} did not return a paginated log list: {response.text[:300]}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

    @action(detail=True, methods=['get', 'post'])
    def fireplace(self, request, pk=None):
        """GET: one page (?page=, newest first) of the house device's registered fireplace heatings.
        POST ``{start_time}``: register one on the house's device. Nothing is stored in Verso.
        """
        heating = self.get_object()
        if request.method == 'POST':
            start_time = serializers.DateTimeField()
            try:
                start_time = start_time.run_validation(
                    request.data.get('start_time') if isinstance(request.data, dict) else None
                )
            except serializers.ValidationError as exc:
                return Response({'start_time': exc.detail}, status=status.HTTP_400_BAD_REQUEST)
            response, error = post_upstream(
                heating, '/fireplace-heating/', {'device': heating.device, 'start_time': start_time.isoformat()}
            )
            if error:
                return error
            try:
                return Response(response.json(), status=response.status_code)
            except ValueError:
                return Response(
                    {'detail': f'{response.url} did not return JSON: {response.text[:300]}'},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

        try:
            page = int(request.query_params.get('page', 1))
        except ValueError:
            return Response({'detail': 'page must be an integer.'}, status=status.HTTP_400_BAD_REQUEST)
        response, error = fetch_upstream(heating, '/fireplace-heating/', {'device': heating.device, 'page': page})
        if error:
            return error
        if response.status_code == status.HTTP_404_NOT_FOUND:
            return Response({'detail': f'Page {page} does not exist.'}, status=status.HTTP_404_NOT_FOUND)
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
                {'detail': f'{response.url} did not return a paginated list: {response.text[:300]}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

    @action(detail=True, methods=['delete'], url_path=r'fireplace/(?P<fireplace_id>\d+)')
    def delete_fireplace(self, request, pk=None, fireplace_id=None):
        """Remove one fireplace heating, only when it belongs to this house's device."""
        heating = self.get_object()
        not_found = Response({'detail': 'Brasan finns inte.'}, status=status.HTTP_404_NOT_FOUND)

        response, error = fetch_upstream(heating, f'/fireplace-heating/{fireplace_id}/')
        if error:
            return error
        if response.status_code == status.HTTP_404_NOT_FOUND:
            return not_found
        try:
            fireplace = response.json()
            if fireplace['device'] != heating.device:
                return not_found
        except (ValueError, KeyError, TypeError):
            return Response(
                {'detail': f'{response.url} did not return a fireplace heating: {response.text[:300]}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        response, error = delete_upstream(heating, f'/fireplace-heating/{fireplace_id}/')
        if error:
            return error
        if response.status_code == status.HTTP_404_NOT_FOUND:
            return not_found
        if not response.ok:
            try:
                return Response(response.json(), status=response.status_code)
            except ValueError:
                return Response(
                    {'detail': f'{response.url} responded {response.status_code}: {response.text[:300]}'},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'], url_path=r'logs/(?P<log_id>\d+)')
    def log(self, request, pk=None, log_id=None):
        """Fetch one external log with its zones. Logs from another device than the house's are treated as missing."""
        heating = self.get_object()
        response, error = fetch_upstream(heating, f'/log/{log_id}/')
        if error:
            return error
        not_found = Response({'detail': f'Log {log_id} does not exist.'}, status=status.HTTP_404_NOT_FOUND)
        if response.status_code == status.HTTP_404_NOT_FOUND:
            return not_found
        try:
            payload = response.json()
            if payload['device'] != heating.device:
                return not_found
            return Response(payload)
        except (ValueError, KeyError, TypeError):
            return Response(
                {'detail': f'{response.url} did not return a log: {response.text[:300]}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
