"""Upload handlers that keep Opus document imports out of local storage."""

from django.core.files.uploadhandler import MemoryFileUploadHandler, StopUpload


class MemoryOnlyUploadHandler(MemoryFileUploadHandler):
    """Keep the complete upload in memory and reject files over the limit."""

    def __init__(self, request, max_file_size):
        super().__init__(request)
        self.max_file_size = max_file_size

    def handle_raw_input(self, input_data, meta, content_length, boundary, encoding=None):
        self.activated = True

    def receive_data_chunk(self, raw_data, start):
        if start + len(raw_data) > self.max_file_size:
            raise StopUpload(connection_reset=False)
        return super().receive_data_chunk(raw_data, start)
