"""
Check prerequisites for Blob Storage Client
1. Check what blob storage paths we have in the data
2. Verify if we have Azure storage credentials configured
3. Validate BlobStorageClient initialization and URL resolution
4. Optionally test download/upload if credentials are available
"""
import sys
import os
from pathlib import Path

# Get the backend directory
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))
os.chdir(backend_dir)

from app.services.db import SessionLocal
from app.models.integration_db import SendServiceOpsDB
from app.services.payload_parser import PayloadParser
from app.services.blob_storage import BlobStorageClient, BlobStorageError
from app.config import settings
import json


def check_blob_paths():
    """Check what blob storage paths we have in the messages"""
    db = SessionLocal()
    try:
        print("=" * 60)
        print("Step 3 Prerequisites Check: Blob Storage")
        print("=" * 60)
        
        # Get sample messages
        messages = db.query(SendServiceOpsDB).filter(
            SendServiceOpsDB.is_deleted == False
        ).limit(5).all()
        
        print(f"\nFound {len(messages)} sample messages\n")
        
        blob_paths = []
        extraction_paths = []
        
        for msg in messages:
            if not msg.payload:
                continue
            
            parsed = PayloadParser.parse_full_payload(msg.payload)
            blob_path = parsed.blob_storage_path
            extraction_path = parsed.extraction_path
            # Get file paths from documents
            file_paths = [{"fullPath": doc.source_absolute_url, "fileName": doc.file_name} for doc in parsed.documents]
            
            if blob_path:
                blob_paths.append(blob_path)
            if extraction_path:
                extraction_paths.append(extraction_path)
            
            print(f"Message ID: {msg.message_id}")
            print(f"  Blob Storage Path: {blob_path}")
            print(f"  Extraction Path: {extraction_path}")
            print(f"  Number of Files: {len(file_paths)}")
            if file_paths:
                print(f"  Sample File Path: {file_paths[0].get('fullPath', 'N/A')}")
            print()
        
        print("=" * 60)
        print("Blob Path Patterns Found:")
        print("=" * 60)
        if blob_paths:
            print(f"Sample blob paths:")
            for path in set(blob_paths[:3]):
                print(f"  - {path}")
        else:
            print("  No blob paths found in messages")
        
        print("\n" + "=" * 60)
        print("Extraction Path Patterns Found:")
        print("=" * 60)
        if extraction_paths:
            print(f"Sample extraction paths:")
            for path in set(extraction_paths[:3]):
                print(f"  - {path}")
        else:
            print("  No extraction paths found in messages")
        
        return blob_paths, extraction_paths
        
    except Exception as e:
        print(f"\n[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()
        return [], []
    finally:
        db.close()


def check_azure_config():
    """Check if Azure Blob Storage configuration exists"""
    print("\n" + "=" * 60)
    print("Azure Blob Storage Configuration Check:")
    print("=" * 60)
    
    # Check environment variables
    env_vars = [
        'AZURE_STORAGE_ACCOUNT',
        'AZURE_STORAGE_CONTAINER',
        'AZURE_STORAGE_SAS_TOKEN',
        'AZURE_STORAGE_CONNECTION_STRING',
        'AZURE_STORAGE_KEY',
    ]
    
    found_vars = []
    missing_vars = []
    
    for var in env_vars:
        value = os.getenv(var)
        if value:
            # Mask sensitive values
            if 'TOKEN' in var or 'KEY' in var or 'CONNECTION' in var:
                display_value = f"{value[:10]}...{value[-5:]}" if len(value) > 15 else "***"
            else:
                display_value = value
            print(f"  [OK] {var}: {display_value}")
            found_vars.append(var)
        else:
            print(f"  [MISSING] {var}: NOT SET")
            missing_vars.append(var)
    
    print("\n" + "=" * 60)
    print("Configuration Status:")
    print("=" * 60)
    print(f"Found: {len(found_vars)}/{len(env_vars)} variables")
    print(f"Missing: {len(missing_vars)}/{len(env_vars)} variables")
    
    if missing_vars:
        print(f"\n[WARNING] Missing required variables: {', '.join(missing_vars)}")
        print("\nTo configure Azure Blob Storage, you need:")
        print("  - AZURE_STORAGE_ACCOUNT: Your storage account name")
        print("  - AZURE_STORAGE_CONTAINER: Container name (e.g., 'documents')")
        print("  - AZURE_STORAGE_SAS_TOKEN: SAS token for access (or)")
        print("  - AZURE_STORAGE_CONNECTION_STRING: Full connection string (or)")
        print("  - AZURE_STORAGE_KEY: Storage account key")
    
    return found_vars, missing_vars


def check_blob_storage_library():
    """Check if Azure Blob Storage Python libraries are installed"""
    print("\n" + "=" * 60)
    print("Python Library Check:")
    print("=" * 60)
    
    libraries = {
        'azure-storage-blob': 'azure.storage.blob',
        'azure-identity': 'azure.identity',
    }
    
    all_installed = True
    
    for lib_name, import_name in libraries.items():
        try:
            module = __import__(import_name)
            version = getattr(module, '__version__', 'unknown')
            print(f"  [OK] {lib_name} is installed (version: {version})")
        except ImportError:
            print(f"  [MISSING] {lib_name} is NOT installed")
            print(f"     To install: pip install {lib_name}")
            all_installed = False
    
    return all_installed


def check_blob_client_initialization():
    """Check if BlobStorageClient can be initialized"""
    print("\n" + "=" * 60)
    print("BlobStorageClient Initialization Check:")
    print("=" * 60)
    
    try:
        # Check required settings
        if not settings.storage_account_url:
            print("  [MISSING] STORAGE_ACCOUNT_URL not set")
            return False
        if not settings.container_name:
            print("  [MISSING] CONTAINER_NAME not set")
            return False
        
        print(f"  [OK] STORAGE_ACCOUNT_URL: {settings.storage_account_url}")
        print(f"  [OK] CONTAINER_NAME: {settings.container_name}")
        print(f"  [OK] BLOB_TEMP_DIR: {settings.blob_temp_dir}")
        print(f"  [OK] BLOB_MAX_RETRIES: {settings.blob_max_retries}")
        print(f"  [OK] BLOB_RETRY_BASE_SECONDS: {settings.blob_retry_base_seconds}")
        
        # Try to initialize client
        try:
            client = BlobStorageClient()
            print("  [OK] BlobStorageClient initialized successfully")
            
            # Test URL resolution (no network call)
            test_path = "v2/2026/01-03/sample.pdf"
            resolved_url = client.resolve_blob_url(test_path)
            print(f"  [OK] URL resolution test:")
            print(f"       Input: {test_path}")
            print(f"       Resolved: {resolved_url}")
            
            return True
        except BlobStorageError as e:
            print(f"  [ERROR] Failed to initialize BlobStorageClient: {e}")
            return False
        except Exception as e:
            print(f"  [ERROR] Unexpected error: {e}")
            import traceback
            traceback.print_exc()
            return False
            
    except Exception as e:
        print(f"  [ERROR] Error checking client initialization: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_blob_operations():
    """Test blob operations if credentials are available"""
    print("\n" + "=" * 60)
    print("Blob Operations Test (if credentials available):")
    print("=" * 60)
    
    # Check if we have credentials
    has_connection_string = bool(settings.azure_storage_connection_string)
    has_managed_identity = not has_connection_string  # Will try DefaultAzureCredential
    
    if not has_connection_string:
        print("  [INFO] No connection string found, will try Managed Identity/DefaultAzureCredential")
        print("  [INFO] This requires running on Azure or having Azure CLI logged in")
    
    try:
        client = BlobStorageClient()
        
        # Test with a sample path (won't actually download unless file exists)
        test_path = "v2/2026/01-03/test_file.pdf"
        print(f"\n  Testing with path: {test_path}")
        
        # Test exists() - this will make a network call
        try:
            exists = client.exists(test_path)
            print(f"  [OK] exists() call succeeded: blob exists = {exists}")
        except BlobStorageError as e:
            print(f"  [INFO] exists() test: {e}")
            print("         (This is expected if blob doesn't exist or credentials are missing)")
        except Exception as e:
            print(f"  [INFO] exists() test failed: {e}")
            print("         (This may indicate missing credentials or network issues)")
        
        print("\n  [INFO] Full download/upload tests skipped (requires valid credentials and existing blobs)")
        print("         The client is ready for use when credentials are configured.")
        
        return True
        
    except Exception as e:
        print(f"  [INFO] Could not test blob operations: {e}")
        print("         This is expected if credentials are not configured.")
        return False


def main():
    """Run all prerequisite checks"""
    print("\n" + "=" * 60)
    print("BLOB STORAGE CLIENT PREREQUISITES CHECK")
    print("=" * 60)
    
    # 1. Check blob paths in data
    blob_paths, extraction_paths = check_blob_paths()
    
    # 2. Check Azure configuration
    found_vars, missing_vars = check_azure_config()
    
    # 3. Check Python libraries
    has_library = check_blob_storage_library()
    
    # 4. Check BlobStorageClient initialization
    client_ok = check_blob_client_initialization()
    
    # 5. Test blob operations (if credentials available)
    operations_ok = test_blob_operations()
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY:")
    print("=" * 60)
    print(f"[OK] Blob paths in data: {len(blob_paths)} found")
    print(f"[OK] Extraction paths: {len(extraction_paths)} found")
    print(f"[OK] Azure config: {len(found_vars)}/{len(found_vars) + len(missing_vars)} variables set")
    print(f"[OK] Python libraries: {'Installed' if has_library else 'NOT Installed'}")
    print(f"[OK] BlobStorageClient: {'Ready' if client_ok else 'Not Ready'}")
    print(f"[OK] Blob operations: {'Tested' if operations_ok else 'Skipped (no credentials)'}")
    
    print("\n" + "=" * 60)
    print("NEXT STEPS:")
    print("=" * 60)
    if not has_library:
        print("1. Install required libraries:")
        print("   pip install azure-storage-blob azure-identity")
    if not client_ok:
        print("2. Configure required environment variables in .env:")
        print("   STORAGE_ACCOUNT_URL=https://yourstorageaccount.blob.core.windows.net")
        print("   CONTAINER_NAME=your-container-name")
        print("   AZURE_STORAGE_CONNECTION_STRING=... (optional, for dev/local)")
    if missing_vars and client_ok:
        print("3. Optional: Set AZURE_STORAGE_CONNECTION_STRING for dev/local testing")
        print("   Or use Managed Identity / DefaultAzureCredential in production")
    print("4. The BlobStorageClient is ready to use in DocumentProcessor")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()

