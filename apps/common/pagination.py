from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    """
    Page-number pagination with a client-controlled size.

    Capped, because a farmer on a slow connection benefits from small pages and
    nothing good comes from letting a caller ask for ten thousand rows.
    """

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100
