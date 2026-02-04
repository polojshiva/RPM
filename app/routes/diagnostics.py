"""
Diagnostic endpoints for troubleshooting
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.models.api import ApiResponse
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diagnostics", tags=["Diagnostics"])


@router.get("/validation-code-check")
async def check_validation_code():
    """
    Diagnostic endpoint to check if the running service is using the updated validation code.
    This helps verify if the service was restarted and is using the new code.
    """
    try:
        from app.services.field_validation_service import (
            REQUIRED_DIAGNOSIS_PROCEDURES,
            validate_diagnosis_code_requirement
        )
        
        # Check if N3941 is in the allowed list
        n3941_in_vagus = 'N3941' in REQUIRED_DIAGNOSIS_PROCEDURES['vagus_nerve_stimulation']['required_diagnosis_codes']
        n3941_in_sacral = 'N3941' in REQUIRED_DIAGNOSIS_PROCEDURES['sacral_nerve_stimulation']['required_diagnosis_codes']
        n3941_in_skin = 'N3941' in REQUIRED_DIAGNOSIS_PROCEDURES['skin_substitutes']['required_diagnosis_codes']
        
        # Test validation
        test_errors = validate_diagnosis_code_requirement(
            diagnosis_code='N3941',
            procedure_codes=['64561'],
            part_type='PART_B'
        )
        
        # Get the actual code location to verify it's the right file
        import inspect
        validation_file = inspect.getfile(validate_diagnosis_code_requirement)
        
        # Check a few codes around N3941 to verify the list
        vagus_codes = REQUIRED_DIAGNOSIS_PROCEDURES['vagus_nerve_stimulation']['required_diagnosis_codes']
        n3941_index = vagus_codes.index('N3941') if 'N3941' in vagus_codes else -1
        surrounding_codes = []
        if n3941_index >= 0:
            start = max(0, n3941_index - 2)
            end = min(len(vagus_codes), n3941_index + 3)
            surrounding_codes = vagus_codes[start:end]
        
        return JSONResponse(content={
            "success": True,
            "data": {
                "n3941_in_allowed_list": {
                    "vagus_nerve_stimulation": n3941_in_vagus,
                    "sacral_nerve_stimulation": n3941_in_sacral,
                    "skin_substitutes": n3941_in_skin
                },
                "validation_test": {
                    "diagnosis_code": "N3941",
                    "procedure_code": "64561",
                    "errors": test_errors,
                    "is_accepted": len(test_errors) == 0
                },
                "code_location": validation_file,
                "surrounding_codes": surrounding_codes,
                "fix_status": "WORKING" if (n3941_in_vagus and len(test_errors) == 0) else "NOT_WORKING",
                "message": "N3941 fix is working correctly" if (n3941_in_vagus and len(test_errors) == 0) else "N3941 fix is NOT working - service may need restart"
            }
        })
    except Exception as e:
        logger.error(f"Error in validation code check: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e),
                "message": "Failed to check validation code"
            }
        )
