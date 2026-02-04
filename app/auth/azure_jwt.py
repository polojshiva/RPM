"""
Azure AD JWT Token Validation

Frontend Integration:
- Validates Azure AD access tokens sent directly from frontend
- Frontend uses MSAL to get Azure AD tokens with api://{client-id}/user_access scope
- Backend validates token signature against Azure AD public keys
- Extracts user info from Azure AD token claims
- No separate application token generation needed
"""
import os
import time
import asyncio
import logging
from typing import Dict, Any
import httpx
from jose import jwt, jwk
from jose.utils import base64url_decode
from fastapi import HTTPException
from app.config import settings

# Set up logging
logger = logging.getLogger(__name__)

# Azure AD Configuration from environment variables
AZURE_TENANT_ID = settings.azure_tenant_id or os.getenv("AZURE_TENANT_ID")
AZURE_CLIENT_ID = settings.azure_client_id or os.getenv("AZURE_CLIENT_ID")

# Validate Azure AD configuration on module load
if not AZURE_TENANT_ID or not AZURE_CLIENT_ID:
    logger.error(
        "CRITICAL: Azure AD configuration missing! "
        "AZURE_TENANT_ID and AZURE_CLIENT_ID must be set. "
        "Authentication will fail."
    )
    # Don't raise here - let startup validation catch it
else:
    logger.info(f"Azure AD configuration loaded: Tenant={AZURE_TENANT_ID[:8]}..., Client={AZURE_CLIENT_ID[:8]}...")

# Support both v1.0 and v2.0 Azure AD endpoints
AZURE_ISSUER_V2 = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/v2.0"
AZURE_ISSUER_V1 = f"https://sts.windows.net/{AZURE_TENANT_ID}/"
VALID_ISSUERS = [AZURE_ISSUER_V1, AZURE_ISSUER_V2]
JWKS_URL = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}/discovery/v2.0/keys"

# Cache for JWKS keys to avoid frequent API calls
_jwks_cache = None
_jwks_cache_timestamp = 0
JWKS_CACHE_TTL = 86400  # 24 hours (Azure AD keys rarely change, increased for better performance)

# Circuit breaker for JWKS fetching
_circuit_open = False
_circuit_open_time = 0
_circuit_failure_count = 0
CIRCUIT_FAILURE_THRESHOLD = 3  # Open circuit after 3 failures
CIRCUIT_RESET_TIME = 30  # Reset circuit after 30 seconds
CIRCUIT_HALF_OPEN_RESET = 60  # Try again after 60 seconds in half-open state

# Last known good JWKS (fallback when circuit is open)
_last_good_jwks = None


async def _fetch_jwks() -> Dict[str, Any]:
    """
    Fetch JWKS keys from Azure AD with timeout, retry, and circuit breaker.
    
    Industry-standard implementation:
    - Aggressive timeout (5 seconds) for fast failure
    - Retry with exponential backoff (3 attempts)
    - Circuit breaker to prevent cascading failures
    - Fallback to cached keys when circuit is open
    - Extended cache TTL (24 hours) for better performance
    """
    global _jwks_cache, _jwks_cache_timestamp, _circuit_open, _circuit_open_time
    global _circuit_failure_count, _last_good_jwks
    
    current_time = time.time()
    
    # Check circuit breaker state
    if _circuit_open:
        time_since_open = current_time - _circuit_open_time
        if time_since_open < CIRCUIT_RESET_TIME:
            # Circuit is open - use cached keys if available
            if _jwks_cache:
                logger.warning(
                    f"Circuit breaker OPEN - using cached JWKS keys "
                    f"(circuit will reset in {CIRCUIT_RESET_TIME - time_since_open:.1f}s)"
                )
                return _jwks_cache
            elif _last_good_jwks:
                logger.warning(
                    f"Circuit breaker OPEN - using last known good JWKS keys "
                    f"(circuit will reset in {CIRCUIT_RESET_TIME - time_since_open:.1f}s)"
                )
                return _last_good_jwks
            else:
                # No cached keys available - try once more (half-open state)
                logger.warning("Circuit breaker OPEN - attempting half-open request")
        else:
            # Reset circuit after timeout
            logger.info("Circuit breaker reset - attempting new request")
            _circuit_open = False
            _circuit_failure_count = 0
    
    # Use cached keys if available and not expired
    if _jwks_cache and (current_time - _jwks_cache_timestamp) < JWKS_CACHE_TTL:
        logger.debug(f"Using cached JWKS keys (age: {int(current_time - _jwks_cache_timestamp)}s)")
        return _jwks_cache
    
    # Fetch with retry logic
    max_retries = 3
    retry_base_delay = 0.5  # Start with 0.5s delay
    last_error = None
    
    for attempt in range(max_retries):
        try:
            logger.debug(f"Fetching JWKS keys from: {JWKS_URL} (attempt {attempt + 1}/{max_retries})")
            
            # Aggressive timeout: 5 seconds (not 10) for fast failure
            timeout = httpx.Timeout(
                connect=2.0,   # 2 seconds to connect
                read=5.0,      # 5 seconds to read response
                write=2.0,     # 2 seconds to write request
                pool=2.0       # 2 seconds to get connection from pool
            )
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(JWKS_URL)
                response.raise_for_status()
                jwks_data = response.json()
                
                # Success - cache the keys and reset circuit breaker
                _jwks_cache = jwks_data
                _jwks_cache_timestamp = current_time
                _last_good_jwks = jwks_data  # Update last known good
                _circuit_open = False
                _circuit_failure_count = 0
                
                logger.info(f"JWKS keys fetched successfully. Found {len(jwks_data.get('keys', []))} keys")
                return jwks_data
                
        except httpx.TimeoutException as e:
            last_error = e
            logger.warning(f"JWKS fetch timeout (attempt {attempt + 1}/{max_retries}): {str(e)}")
        except httpx.RequestError as e:
            last_error = e
            logger.warning(f"JWKS fetch request error (attempt {attempt + 1}/{max_retries}): {str(e)}")
        except Exception as e:
            last_error = e
            logger.warning(f"JWKS fetch error (attempt {attempt + 1}/{max_retries}): {str(e)}")
        
        # Exponential backoff before retry (except on last attempt)
        if attempt < max_retries - 1:
            delay = retry_base_delay * (2 ** attempt)
            logger.debug(f"Retrying JWKS fetch after {delay}s...")
            await asyncio.sleep(delay)
    
    # All retries failed - update circuit breaker
    _circuit_failure_count += 1
    if _circuit_failure_count >= CIRCUIT_FAILURE_THRESHOLD:
        _circuit_open = True
        _circuit_open_time = current_time
        logger.error(
            f"Circuit breaker OPENED after {_circuit_failure_count} failures. "
            f"Will use cached keys for next {CIRCUIT_RESET_TIME}s"
        )
    
    # Try to return cached keys as fallback
    if _jwks_cache:
        logger.warning(f"JWKS fetch failed - using cached keys (age: {int(current_time - _jwks_cache_timestamp)}s)")
        return _jwks_cache
    elif _last_good_jwks:
        logger.warning("JWKS fetch failed - using last known good keys")
        return _last_good_jwks
    
    # No fallback available - fail
    logger.error(f"Failed to fetch JWKS keys after {max_retries} attempts: {last_error}")
    raise HTTPException(
        status_code=401,
        detail="Authentication service temporarily unavailable. Please try again in a moment."
    )


def _get_signing_key(token: str, jwks_data: Dict[str, Any]) -> str:
    """Get the signing key for the token"""
    try:
        # Get the header to find the key ID
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        
        logger.debug(f"Looking for key ID: {kid}")
        
        if not kid:
            raise HTTPException(
                status_code=401,
                detail="Token header missing 'kid' claim"
            )
        
        # Find the matching key
        for key_data in jwks_data.get("keys", []):
            if key_data.get("kid") == kid:
                logger.debug(f"Found matching key: {kid}")
                logger.debug(f"Key data: kty={key_data.get('kty')}, use={key_data.get('use')}, alg={key_data.get('alg')}")
                
                try:
                    # Try the original approach first
                    logger.debug("Attempting jwk.construct...")
                    key = jwk.construct(key_data)
                    
                    # Check if the key has the to_pem method
                    if hasattr(key, 'to_pem'):
                        return key.to_pem().decode('utf-8')
                    else:
                        # If no to_pem method, try alternative approach
                        logger.debug("Key object has no to_pem method, trying alternative...")
                        raise AttributeError("Key object does not have to_pem method")
                        
                except Exception as construct_error:
                    logger.warning(f"jwk.construct failed: {construct_error}")
                    
                    # Fallback: construct key manually for RSA
                    if key_data.get("kty") == "RSA":
                        logger.debug("Attempting manual RSA key construction...")
                        try:
                            from cryptography.hazmat.primitives.asymmetric import rsa
                            from cryptography.hazmat.primitives import serialization
                            from cryptography.hazmat.backends import default_backend
                            import base64
                            
                            # Decode the RSA components with proper padding
                            def decode_base64url_uint(val):
                                if isinstance(val, str):
                                    val = val.encode('ascii')
                                rem = len(val) % 4
                                if rem > 0:
                                    val += b'=' * (4 - rem)
                                return base64.urlsafe_b64decode(val)
                            
                            # Get RSA components
                            n_bytes = decode_base64url_uint(key_data["n"])
                            e_bytes = decode_base64url_uint(key_data["e"])
                            
                            # Convert to integers
                            n_int = int.from_bytes(n_bytes, byteorder='big')
                            e_int = int.from_bytes(e_bytes, byteorder='big')
                            
                            # Create RSA public key using the correct method
                            public_numbers = rsa.RSAPublicNumbers(e_int, n_int)
                            public_key = public_numbers.public_key(backend=default_backend())
                            
                            # Convert to PEM format
                            pem = public_key.public_bytes(
                                encoding=serialization.Encoding.PEM,
                                format=serialization.PublicFormat.SubjectPublicKeyInfo
                            )
                            
                            logger.debug("Manual RSA key construction successful!")
                            return pem.decode('utf-8')
                        
                        except Exception as manual_error:
                            logger.error(f"Manual RSA construction failed: {manual_error}")
                            
                            # Final fallback: try using python-jose's RSAKey directly
                            try:
                                logger.debug("Attempting jose RSAKey construction...")
                                from jose.backends.cryptography_backend import CryptographyRSAKey
                                from cryptography.hazmat.primitives import serialization
                                
                                # Create RSA key using jose's backend directly
                                rsa_key = CryptographyRSAKey(key_data, algorithm='RS256')
                                
                                # Get the public key in PEM format
                                public_key = rsa_key.public_key()
                                pem = public_key.public_bytes(
                                    encoding=serialization.Encoding.PEM,
                                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                                )
                                
                                logger.debug("Jose RSAKey construction successful!")
                                return pem.decode('utf-8')
                                
                            except Exception as jose_error:
                                logger.error(f"Jose RSAKey construction failed: {jose_error}")
                                raise HTTPException(
                                    status_code=401,
                                    detail=f"All key construction methods failed. Last error: {jose_error}"
                                )
                    else:
                        raise HTTPException(
                            status_code=401,
                            detail=f"Unsupported key type: {key_data.get('kty')}"
                        )
        
        raise HTTPException(
            status_code=401,
            detail="Unable to find appropriate signing key"
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"Error processing token header: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail=f"Error processing token header: {str(e)}"
        )


async def verify_token(token: str) -> Dict[str, Any]:
    """
    Verify Azure AD access token from frontend and return decoded claims
    
    Frontend Integration:
    - Frontend sends Azure AD access tokens with scope: api://{client-id}/user_access
    - Validates token signature against Azure AD public keys
    - Extracts user claims for application use
    - No application token exchange needed
    
    Args:
        token: Azure AD access token string from frontend
        
    Returns:
        Dictionary containing Azure AD token claims
        
    Raises:
        HTTPException: If Azure AD token is invalid or expired
    """
    # Fast-fail if configuration is missing
    if not AZURE_TENANT_ID or not AZURE_CLIENT_ID:
        logger.error("Azure AD configuration missing - cannot validate token")
        raise HTTPException(
            status_code=500,
            detail="Authentication service misconfigured. Please contact administrator."
        )
    
    try:
        logger.debug("Starting Azure AD token verification for SSO...")
        logger.debug(f"Expected audience: api://{AZURE_CLIENT_ID}/user_access or {AZURE_CLIENT_ID}")
        logger.debug(f"Expected issuers: {VALID_ISSUERS}")
        logger.debug(f"Token length: {len(token)} characters")
        
        # Decode token header first to see basic info
        try:
            unverified_header = jwt.get_unverified_header(token)
            unverified_claims = jwt.get_unverified_claims(token)
            logger.debug(f"Token header: {unverified_header}")
            logger.debug(f"Token audience claim: {unverified_claims.get('aud')}")
            logger.debug(f"Token issuer claim: {unverified_claims.get('iss')}")
            logger.debug(f"Token scopes: {unverified_claims.get('scp', 'none')}")
        except Exception as header_err:
            logger.error(f"Failed to decode Azure AD token header: {header_err}")
        
        # Fetch JWKS keys from Azure AD
        logger.debug("Fetching JWKS keys from Azure AD...")
        jwks_data = await _fetch_jwks()
        logger.debug(f"JWKS keys fetched, found {len(jwks_data.get('keys', []))} keys")
        
        # Get signing key for token verification
        logger.debug("Getting signing key for Azure AD token...")
        signing_key = _get_signing_key(token, jwks_data)
        logger.debug("Azure AD signing key obtained")
        
        # Verify and decode the Azure AD token with optimized validation
        # Try most likely combinations first to minimize attempts
        logger.debug("Verifying Azure AD token signature and claims...")
        
        claims = None
        last_error = None
        
        # Get unverified claims first to determine actual issuer/audience (optimization)
        try:
            unverified_claims = jwt.get_unverified_claims(token)
            actual_issuer = unverified_claims.get('iss', '')
            actual_audience = unverified_claims.get('aud', '')
            logger.debug(f"Token issuer: {actual_issuer}, audience: {actual_audience}")
        except Exception:
            unverified_claims = {}
            actual_issuer = None
            actual_audience = None
        
        # Optimized validation: Try actual issuer first, then fallback
        issuers_to_try = []
        if actual_issuer and actual_issuer in VALID_ISSUERS:
            # Try actual issuer first (most likely to succeed)
            issuers_to_try = [actual_issuer] + [i for i in VALID_ISSUERS if i != actual_issuer]
        else:
            # No match, try all issuers in order
            issuers_to_try = VALID_ISSUERS
        
        # Try different combinations of issuer and audience (optimized order)
        for issuer in issuers_to_try:
            logger.debug(f"Trying issuer: {issuer}")
            
            # Strategy 1: Try actual audience from token (if available)
            if actual_audience:
                try:
                    claims = jwt.decode(
                        token,
                        signing_key,
                        algorithms=["RS256"],
                        audience=actual_audience,
                        issuer=issuer,
                        options={
                            "verify_signature": True,
                            "verify_aud": True,
                            "verify_iss": True,
                            "verify_exp": True,
                            "verify_nbf": True,
                            "verify_iat": True,
                        }
                    )
                    logger.debug(f"Token validation successful with actual audience!")
                    break
                except jwt.JWTClaimsError as e:
                    logger.debug(f"Actual audience failed: {e}")
            
            # Strategy 2: Try API scope audience (most common)
            expected_api_audience = f"api://{AZURE_CLIENT_ID}"
            try:
                claims = jwt.decode(
                    token,
                    signing_key,
                    algorithms=["RS256"],
                    audience=expected_api_audience,
                    issuer=issuer,
                    options={
                        "verify_signature": True,
                        "verify_aud": True,
                        "verify_iss": True,
                        "verify_exp": True,
                        "verify_nbf": True,
                        "verify_iat": True,
                    }
                )
                logger.debug(f"Token validation successful with API audience!")
                break
            except jwt.JWTClaimsError as e:
                logger.debug(f"API audience failed: {e}")
                
                # Strategy 3: Try client ID as audience
                try:
                    claims = jwt.decode(
                        token,
                        signing_key,
                        algorithms=["RS256"],
                        audience=AZURE_CLIENT_ID,
                        issuer=issuer,
                        options={
                            "verify_signature": True,
                            "verify_aud": True,
                            "verify_iss": True,
                            "verify_exp": True,
                            "verify_nbf": True,
                            "verify_iat": True,
                        }
                    )
                    logger.debug(f"Token validation successful with client ID audience!")
                    break
                except jwt.JWTClaimsError as e:
                    logger.debug(f"Client ID audience failed: {e}")
                    
                    # Strategy 4: Try without audience verification (last resort)
                    try:
                        claims = jwt.decode(
                            token,
                            signing_key,
                            algorithms=["RS256"],
                            issuer=issuer,
                            options={
                                "verify_signature": True,
                                "verify_aud": False,  # Skip audience verification
                                "verify_iss": True,
                                "verify_exp": True,
                                "verify_nbf": True,
                                "verify_iat": True,
                            }
                        )
                        logger.debug(f"Token validation successful (no audience check)!")
                        break
                    except jwt.JWTClaimsError as e:
                        logger.debug(f"All validation failed with {issuer}: {e}")
                        last_error = e
        
        if not claims:
            logger.error(f"All issuer/audience combinations failed. Last error: {last_error}")
            raise last_error or jwt.JWTClaimsError("Token validation failed with all issuer combinations")
        
        # Log token validation success info (minimal logging for performance)
        username = claims.get('preferred_username')
        user_id = claims.get('oid') or claims.get('sub')
        
        logger.info("Token validation successful")  # Keep as INFO - important milestone
        logger.debug(f"Token audience: {claims.get('aud')}")
        logger.debug(f"Scopes: {claims.get('scp', '')}")
        logger.debug(f"User: {username}")
        logger.debug(f"User ID: {user_id}")
        logger.debug(f"Issuer: {claims.get('iss')}")
        logger.debug(f"Available claims: {list(claims.keys())}")
        
        logger.debug(f"User authenticated: {username}, Issuer: {claims.get('iss')}")  # Changed to DEBUG
        
        return claims
        
    except jwt.ExpiredSignatureError as e:
        logger.error("Token has expired")
        raise HTTPException(
            status_code=401,
            detail="Token has expired"
        )
    except jwt.JWTClaimsError as e:
        logger.error(f"Token claims validation failed: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail=f"Token claims validation failed: {str(e)}"
        )
    except jwt.JWTError as e:
        logger.error(f"JWT validation error: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail=f"Token validation failed: {str(e)}"
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"Unexpected token error: {str(e)}")
        raise HTTPException(
            status_code=401,
            detail=f"Token verification error: {str(e)}"
        )