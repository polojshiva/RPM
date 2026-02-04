"""
Conftest for ESMD Payload Generator tests
Mocks blob storage to avoid Azure dependency
"""
import sys
from unittest.mock import Mock, MagicMock

# Mock blob storage before any imports
mock_blob_storage = Mock()
mock_blob_storage.resolve_blob_url = Mock(return_value="https://example.com/blob.pdf")

# Create a mock module for blob_storage
mock_blob_module = MagicMock()
mock_blob_module.BlobStorageClient = Mock(return_value=mock_blob_storage)

# Inject into sys.modules before app.services.esmd_payload_generator imports it
if 'app.services.blob_storage' not in sys.modules:
    sys.modules['app.services.blob_storage'] = mock_blob_module

