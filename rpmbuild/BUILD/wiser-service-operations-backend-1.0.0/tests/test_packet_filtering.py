"""
Unit tests for packet list filtering functionality
Tests server-side filtering for all filter types
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.models.packet_db import PacketDB
from app.models.channel_type import ChannelType
from app.main import app


@pytest.fixture
def client():
    """Create test client"""
    return TestClient(app)


@pytest.fixture
def mock_user():
    """Mock user for authentication"""
    user = Mock()
    user.email = "test@example.com"
    user.id = "user-123"
    user.token = "mock-token"
    return user


@pytest.fixture
def db_session():
    """Mock database session"""
    from unittest.mock import MagicMock
    session = MagicMock(spec=Session)
    session.query = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.flush = MagicMock()
    session.refresh = MagicMock()
    return session


@pytest.fixture
def sample_packets(db_session: Session):
    """Create sample packets with different attributes for testing filters"""
    packets = []
    
    # Packet 1: Portal, Expedited, Clinical Review
    packet1 = PacketDB(
        external_id="SVC-2026-000001",
        decision_tracking_id="11111111-1111-1111-1111-111111111111",
        beneficiary_name="John Doe",
        beneficiary_mbi="1AB2CD3EF45",
        provider_name="Test Hospital",
        provider_npi="1234567890",
        service_type="Prior Authorization",
        submission_type="Expedited",
        detailed_status="Clinical Review",
        channel_type_id=ChannelType.GENZEON_PORTAL,
        received_date=datetime(2026, 1, 10, 0, 0, 0, tzinfo=timezone.utc),
        due_date=datetime(2026, 1, 12, 0, 0, 0, tzinfo=timezone.utc),
    )
    db_session.add(packet1)
    packets.append(packet1)
    
    # Packet 2: Fax, Standard, Intake Validation
    packet2 = PacketDB(
        external_id="SVC-2026-000002",
        decision_tracking_id="22222222-2222-2222-2222-222222222222",
        beneficiary_name="Jane Smith",
        beneficiary_mbi="2BC3DE4FG56",
        provider_name="Another Clinic",
        provider_npi="0987654321",
        service_type="Prior Authorization",
        submission_type="Standard",
        detailed_status="Intake Validation",
        channel_type_id=ChannelType.GENZEON_FAX,
        received_date=datetime(2026, 1, 9, 0, 0, 0, tzinfo=timezone.utc),
        due_date=datetime(2026, 1, 12, 0, 0, 0, tzinfo=timezone.utc),
    )
    db_session.add(packet2)
    packets.append(packet2)
    
    # Packet 3: ESMD, Expedited, Manual Review
    packet3 = PacketDB(
        external_id="SVC-2026-000003",
        decision_tracking_id="33333333-3333-3333-3333-333333333333",
        beneficiary_name="Bob Johnson",
        beneficiary_mbi="3CD4EF5GH67",
        provider_name="ESMD Provider",
        provider_npi="1122334455",
        service_type="Prior Authorization",
        submission_type="Expedited",
        detailed_status="Manual Review",
        channel_type_id=ChannelType.ESMD,
        received_date=datetime(2026, 1, 8, 0, 0, 0, tzinfo=timezone.utc),
        due_date=datetime(2026, 1, 10, 0, 0, 0, tzinfo=timezone.utc),
    )
    db_session.add(packet3)
    packets.append(packet3)
    
    # Packet 4: Portal, Standard, Closed - Delivered
    packet4 = PacketDB(
        external_id="SVC-2026-000004",
        decision_tracking_id="44444444-4444-4444-4444-444444444444",
        beneficiary_name="Alice Brown",
        beneficiary_mbi="4DE5FG6HI78",
        provider_name="Portal Hospital",
        provider_npi="5566778899",
        service_type="Prior Authorization",
        submission_type="Standard",
        detailed_status="Closed - Delivered",
        channel_type_id=ChannelType.GENZEON_PORTAL,
        received_date=datetime(2026, 1, 7, 0, 0, 0, tzinfo=timezone.utc),
        due_date=datetime(2026, 1, 10, 0, 0, 0, tzinfo=timezone.utc),
    )
    db_session.add(packet4)
    packets.append(packet4)
    
    db_session.commit()
    return packets


class TestPacketFiltering:
    """Test packet list filtering functionality"""
    
    def test_list_packets_no_filters(self, client, db_session, sample_packets, mock_user):
        """Test listing packets without filters returns all packets"""
        with patch('app.auth.dependencies.get_current_user', return_value=mock_user):
            response = client.get("/api/packets?page=1&page_size=10")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["data"]) >= 4  # At least our 4 test packets
        assert data["total"] >= 4
    
    def test_filter_by_high_level_status(self, client, db_session, sample_packets, mock_user):
        """Test filtering by high_level_status (Clinical Review)"""
        response = client.get(
            "/api/packets?page=1&page_size=10&high_level_status=Clinical Review",
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return packets with Clinical Review status
        for packet in data["data"]:
            assert "Clinical" in packet.get("highLevelStatus", "") or "Review" in packet.get("highLevelStatus", "")
    
    def test_filter_by_detailed_status(self, client, db_session, sample_packets, mock_user):
        """Test filtering by detailed_status (Intake Validation)"""
        response = client.get(
            "/api/packets?page=1&page_size=10&detailed_status=Intake Validation",
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return only packets with Intake Validation
        for packet in data["data"]:
            assert packet.get("detailedStatus") == "Intake Validation"
    
    def test_filter_by_channel_portal(self, client, db_session, sample_packets, mock_user):
        """Test filtering by channel (Portal)"""
        response = client.get(
            "/api/packets?page=1&page_size=10&channel=Portal",
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return only Portal packets
        for packet in data["data"]:
            assert packet.get("channel") == "Portal"
    
    def test_filter_by_channel_fax(self, client, db_session, sample_packets, mock_user):
        """Test filtering by channel (Fax)"""
        response = client.get(
            "/api/packets?page=1&page_size=10&channel=Fax",
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return only Fax packets
        for packet in data["data"]:
            assert packet.get("channel") == "Fax"
    
    def test_filter_by_channel_esmd(self, client, db_session, sample_packets, mock_user):
        """Test filtering by channel (esMD)"""
        response = client.get(
            "/api/packets?page=1&page_size=10&channel=esMD",
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return only ESMD packets
        for packet in data["data"]:
            assert packet.get("channel") == "esMD"
    
    def test_filter_by_priority_expedited(self, client, db_session, sample_packets, mock_user):
        """Test filtering by priority (Expedited)"""
        response = client.get(
            "/api/packets?page=1&page_size=10&priority=Expedited",
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return only Expedited packets (submission_type = 'Expedited')
        for packet in data["data"]:
            assert packet.get("submissionType") == "Expedited"
    
    def test_filter_by_priority_standard(self, client, db_session, sample_packets, mock_user):
        """Test filtering by priority (Standard)"""
        response = client.get(
            "/api/packets?page=1&page_size=10&priority=Standard",
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return only Standard packets (submission_type = 'Standard')
        for packet in data["data"]:
            assert packet.get("submissionType") == "Standard"
    
    def test_search_by_packet_id(self, client, db_session, sample_packets, mock_user):
        """Test search by packet ID"""
        response = client.get(
            "/api/packets?page=1&page_size=10&search=SVC-2026-000001",
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return packet with matching ID
        assert len(data["data"]) >= 1
        assert any(p.get("id") == "SVC-2026-000001" for p in data["data"])
    
    def test_search_by_beneficiary_name(self, client, db_session, sample_packets, mock_user):
        """Test search by beneficiary name"""
        response = client.get(
            "/api/packets?page=1&page_size=10&search=John",
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return packets with "John" in beneficiary name
        for packet in data["data"]:
            assert "John" in packet.get("beneficiaryName", "").lower()
    
    def test_search_by_provider_npi(self, client, db_session, sample_packets, mock_user):
        """Test search by provider NPI"""
        response = client.get(
            "/api/packets?page=1&page_size=10&search=1234567890",
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return packet with matching NPI
        assert any("1234567890" in p.get("providerNpi", "") for p in data["data"])
    
    def test_combined_filters(self, client, db_session, sample_packets, mock_user):
        """Test combining multiple filters"""
        response = client.get(
            "/api/packets?page=1&page_size=10&channel=Portal&priority=Expedited&high_level_status=Clinical Review",
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should return only Portal + Expedited + Clinical Review packets
        for packet in data["data"]:
            assert packet.get("channel") == "Portal"
            assert packet.get("submissionType") == "Expedited"
            assert "Clinical" in packet.get("highLevelStatus", "") or "Review" in packet.get("highLevelStatus", "")
    
    def test_pagination_with_filters(self, client, db_session, sample_packets, mock_user):
        """Test pagination works correctly with filters"""
        # Get first page
        response1 = client.get(
            "/api/packets?page=1&page_size=2&channel=Portal",
            )
        
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["success"] is True
        assert len(data1["data"]) <= 2
        assert data1["page"] == 1
        
        # Get second page
        if data1["total"] > 2:
            response2 = client.get(
                "/api/packets?page=2&page_size=2&channel=Portal",
                headers={"Authorization": f"Bearer {mock_user.token}"}
            )
            
            assert response2.status_code == 200
            data2 = response2.json()
            assert data2["success"] is True
            assert data2["page"] == 2
            # Should have different packets
            ids1 = {p.get("id") for p in data1["data"]}
            ids2 = {p.get("id") for p in data2["data"]}
            assert ids1.isdisjoint(ids2)  # No overlap
    
    def test_total_count_with_filters(self, client, db_session, sample_packets, mock_user):
        """Test total count reflects filtered results"""
        # Get all Portal packets
        response = client.get(
            "/api/packets?page=1&page_size=100&channel=Portal",
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # Total should match the number of Portal packets
        portal_count = sum(1 for p in data["data"] if p.get("channel") == "Portal")
        assert data["total"] >= portal_count
    
    def test_sorting_with_filters(self, client, db_session, sample_packets, mock_user):
        """Test sorting works with filters"""
        response = client.get(
            "/api/packets?page=1&page_size=10&channel=Portal&sort_by=received_date&sort_order=desc",
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # Verify all are Portal
        for packet in data["data"]:
            assert packet.get("channel") == "Portal"
        
        # Verify sorting (if multiple packets)
        if len(data["data"]) > 1:
            dates = [p.get("receivedDate") for p in data["data"] if p.get("receivedDate")]
            if len(dates) > 1:
                # Should be descending (newest first)
                for i in range(len(dates) - 1):
                    assert dates[i] >= dates[i + 1]

