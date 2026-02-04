"""
Clinical Case Converter
Convert internal clinical case data to DTOs
"""
from typing import List, Optional
from app.models.clinical_dto import (
    ClinicalCaseItemDTO,
    CaseDataDTO,
    CaseStatus,
    DecisionSupportAnswerDTO,
)



def case_to_item_dto(case: dict) -> ClinicalCaseItemDTO:
    """Convert internal case dict to ClinicalCaseItemDTO for dashboard"""
    status = case.get("status")
    if isinstance(status, str):
        # Convert string to enum
        status = CaseStatus(status)
    
    return ClinicalCaseItemDTO(
        uniqueId=case["uniqueId"],
        caseId=case["caseId"],
        patientName=case["patientName"],
        memberId=case["memberId"],
        docId=case["docId"],
        dateAdded=case["dateAdded"],
        dateCompleted=case.get("dateCompleted"),
        status=status,
        statusColor=_get_status_color(status),
        priority=case.get("priority"),
        reviewType=case.get("reviewType"),
        assignedTo=case["assignedTo"],
        serviceType=case["serviceType"],
        hcpcs=case["hcpcs"],
        nurseRecommendation=case.get("nurseRecommendation"),
        decision=case.get("decision"),
        daysInReview=case.get("daysInReview", 0),
        expedited=case.get("expedited", False),
        letterType=case.get("letterType"),
        packetId=case["packetId"],
    )


def case_to_detail_dto(case: dict) -> CaseDataDTO:
    """Convert internal case dict to CaseDataDTO for detail view"""
    # Convert decision support answers
    decision_support = []
    for dsa in case.get("decisionSupportAnswers", []):
        decision_support.append(
            DecisionSupportAnswerDTO(
                question=dsa.get("question", ""),
                answer=dsa.get("answer", ""),
                critical=dsa.get("critical", False),
            )
        )
    
    # Determine nurse recommendation (use detail field if available, otherwise dashboard field)
    nurse_rec = case.get("nurseRecommendation_detail") or case.get("nurseRecommendation")
    if nurse_rec:
        # Map to expected literal type
        if nurse_rec.lower() in ["approve", "approved"]:
            nurse_rec = "Approve"
        elif nurse_rec.lower() in ["deny", "denied"]:
            nurse_rec = "Deny"
        elif nurse_rec.lower() in ["partial"]:
            nurse_rec = "Partial"
        else:
            nurse_rec = "Approve"  # Default
    else:
        nurse_rec = "Approve"  # Default
    
    return CaseDataDTO(
        uniqueId=case["uniqueId"],
        caseId=case["caseId"],
        patientName=case["patientName"],
        memberId=case["memberId"],
        dateOfBirth=case.get("dateOfBirth"),
        age=case.get("age"),
        patientAddress=case.get("patientAddress"),
        serviceType=case["serviceType"],
        hcpcs=case["hcpcs"],
        diagnosisCodes=case.get("diagnosisCodes", []),
        providerName=case.get("providerName", ""),
        providerNPI=case.get("providerNPI", ""),
        providerAddress=case.get("providerAddress"),
        providerPhone=case.get("providerPhone"),
        providerFax=case.get("providerFax"),
        dateAdded=case["dateAdded"],
        dateOfService=case.get("dateOfService"),
        daysInReview=case.get("daysInReview", 0),
        priority=case.get("priority"),
        expedited=case.get("expedited", False),
        nurseReviewer=case.get("nurseReviewer", ""),
        nurseReviewDate=case.get("nurseReviewDate", ""),
        nurseRecommendation=nurse_rec,
        nurseNotes=case.get("nurseNotes", ""),
        decisionSupportAnswers=decision_support,
        documentsReviewed=case.get("documentsReviewed", []),
        packetId=case["packetId"],
        intakeChannel=case.get("intakeChannel"),
        mdReviewer=case.get("mdReviewer"),
        reviewDate=case.get("reviewDate"),
        decision=case.get("decision_detail") or case.get("decision"),
    )


def cases_to_item_dto_list(cases: List[dict]) -> List[ClinicalCaseItemDTO]:
    """Convert list of internal cases to DTO list"""
    return [case_to_item_dto(case) for case in cases]

