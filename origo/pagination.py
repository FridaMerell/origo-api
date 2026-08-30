from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """Page-number pagination that also honours a ``page_size`` query param."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200
