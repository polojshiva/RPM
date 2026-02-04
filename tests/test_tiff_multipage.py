"""
Comprehensive Unit Tests for Multi-Page TIFF Handling

Tests both pdf_merger and document_splitter to ensure all TIFF frames
are correctly processed into PDF pages.

Test scenarios:
- Single-page TIFF (1 page)
- Two-page TIFF (2 pages)
- Multi-page TIFFs (4, 7, 9, 18, 23 pages)
- Multiple TIFF documents with multiple pages
"""

import pytest
import tempfile
import shutil
from pathlib import Path
import io

# Check if PIL is available
try:
    from PIL import Image, ImageSequence
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None
    ImageSequence = None
    pytestmark = pytest.mark.skipif(True, reason="PIL/Pillow not available")
else:
    pytestmark = pytest.mark.skipif(False, reason="")

from app.services.pdf_merger import PDFMerger, PDFMergeError
from app.services.document_splitter import DocumentSplitter, DocumentSplitError


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files"""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def pdf_merger(temp_dir):
    """Create PDFMerger instance"""
    return PDFMerger(temp_dir=str(temp_dir))


@pytest.fixture
def document_splitter(temp_dir):
    """Create DocumentSplitter instance"""
    return DocumentSplitter(temp_dir=str(temp_dir))


def create_multi_page_tiff(output_path: Path, num_pages: int) -> Path:
    """
    Create a multi-page TIFF file with specified number of pages.
    Each page is a simple colored rectangle with page number text.
    """
    images = []
    
    for page_num in range(num_pages):
        # Create a simple image for each page (different colors to distinguish)
        img = Image.new('RGB', (800, 600), color=(
            (page_num * 30) % 255,
            (page_num * 50) % 255,
            (page_num * 70) % 255
        ))
        images.append(img)
    
    # Save as multi-page TIFF
    if images:
        images[0].save(
            str(output_path),
            format='TIFF',
            save_all=True,
            append_images=images[1:] if len(images) > 1 else []
        )
    
    return output_path


def verify_tiff_frame_count(tiff_path: Path) -> int:
    """Verify actual frame count in TIFF using Pillow's ImageSequence"""
    img = Image.open(tiff_path)
    img.load()  # Ensure frames are loaded
    frames = list(ImageSequence.Iterator(img))
    img.close()
    return len(frames)


def verify_pdf_page_count(pdf_path: Path) -> int:
    """Verify page count in PDF"""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        page_count = len(doc)
        doc.close()
        return page_count
    except ImportError:
        try:
            import pypdf
            with open(pdf_path, 'rb') as f:
                reader = pypdf.PdfReader(f)
                return len(reader.pages)
        except ImportError:
            pytest.skip("No PDF library available for verification")


class TestPDFMergerMultiPageTIFF:
    """Test PDFMerger with multi-page TIFFs"""
    
    def test_single_page_tiff(self, pdf_merger, temp_dir):
        """Test single-page TIFF conversion"""
        tiff_path = temp_dir / "single_page.tiff"
        create_multi_page_tiff(tiff_path, 1)
        
        output_path = temp_dir / "output.pdf"
        page_count = pdf_merger.merge_documents(
            input_paths=[str(tiff_path)],
            mime_types=["image/tiff"],
            output_path=str(output_path)
        )
        
        assert page_count == 1
        assert output_path.exists()
        assert verify_pdf_page_count(output_path) == 1
    
    def test_two_page_tiff(self, pdf_merger, temp_dir):
        """Test two-page TIFF conversion"""
        tiff_path = temp_dir / "two_page.tiff"
        create_multi_page_tiff(tiff_path, 2)
        
        # Verify TIFF has 2 frames
        assert verify_tiff_frame_count(tiff_path) == 2
        
        output_path = temp_dir / "output.pdf"
        page_count = pdf_merger.merge_documents(
            input_paths=[str(tiff_path)],
            mime_types=["image/tiff"],
            output_path=str(output_path)
        )
        
        assert page_count == 2
        assert output_path.exists()
        assert verify_pdf_page_count(output_path) == 2
    
    def test_four_page_tiff(self, pdf_merger, temp_dir):
        """Test four-page TIFF conversion"""
        tiff_path = temp_dir / "four_page.tiff"
        create_multi_page_tiff(tiff_path, 4)
        
        assert verify_tiff_frame_count(tiff_path) == 4
        
        output_path = temp_dir / "output.pdf"
        page_count = pdf_merger.merge_documents(
            input_paths=[str(tiff_path)],
            mime_types=["image/tiff"],
            output_path=str(output_path)
        )
        
        assert page_count == 4
        assert output_path.exists()
        assert verify_pdf_page_count(output_path) == 4
    
    def test_seven_page_tiff(self, pdf_merger, temp_dir):
        """Test seven-page TIFF conversion"""
        tiff_path = temp_dir / "seven_page.tiff"
        create_multi_page_tiff(tiff_path, 7)
        
        assert verify_tiff_frame_count(tiff_path) == 7
        
        output_path = temp_dir / "output.pdf"
        page_count = pdf_merger.merge_documents(
            input_paths=[str(tiff_path)],
            mime_types=["image/tiff"],
            output_path=str(output_path)
        )
        
        assert page_count == 7
        assert output_path.exists()
        assert verify_pdf_page_count(output_path) == 7
    
    def test_nine_page_tiff(self, pdf_merger, temp_dir):
        """Test nine-page TIFF conversion"""
        tiff_path = temp_dir / "nine_page.tiff"
        create_multi_page_tiff(tiff_path, 9)
        
        assert verify_tiff_frame_count(tiff_path) == 9
        
        output_path = temp_dir / "output.pdf"
        page_count = pdf_merger.merge_documents(
            input_paths=[str(tiff_path)],
            mime_types=["image/tiff"],
            output_path=str(output_path)
        )
        
        assert page_count == 9
        assert output_path.exists()
        assert verify_pdf_page_count(output_path) == 9
    
    def test_eighteen_page_tiff(self, pdf_merger, temp_dir):
        """Test eighteen-page TIFF conversion"""
        tiff_path = temp_dir / "eighteen_page.tiff"
        create_multi_page_tiff(tiff_path, 18)
        
        assert verify_tiff_frame_count(tiff_path) == 18
        
        output_path = temp_dir / "output.pdf"
        page_count = pdf_merger.merge_documents(
            input_paths=[str(tiff_path)],
            mime_types=["image/tiff"],
            output_path=str(output_path)
        )
        
        assert page_count == 18
        assert output_path.exists()
        assert verify_pdf_page_count(output_path) == 18
    
    def test_twenty_three_page_tiff(self, pdf_merger, temp_dir):
        """Test twenty-three-page TIFF conversion"""
        tiff_path = temp_dir / "twenty_three_page.tiff"
        create_multi_page_tiff(tiff_path, 23)
        
        assert verify_tiff_frame_count(tiff_path) == 23
        
        output_path = temp_dir / "output.pdf"
        page_count = pdf_merger.merge_documents(
            input_paths=[str(tiff_path)],
            mime_types=["image/tiff"],
            output_path=str(output_path)
        )
        
        assert page_count == 23
        assert output_path.exists()
        assert verify_pdf_page_count(output_path) == 23
    
    def test_multiple_tiff_documents(self, pdf_merger, temp_dir):
        """Test merging multiple multi-page TIFF documents"""
        # Create multiple TIFFs with different page counts
        tiff1 = temp_dir / "tiff1.tiff"
        tiff2 = temp_dir / "tiff2.tiff"
        tiff3 = temp_dir / "tiff3.tiff"
        
        create_multi_page_tiff(tiff1, 4)
        create_multi_page_tiff(tiff2, 7)
        create_multi_page_tiff(tiff3, 9)
        
        assert verify_tiff_frame_count(tiff1) == 4
        assert verify_tiff_frame_count(tiff2) == 7
        assert verify_tiff_frame_count(tiff3) == 9
        
        output_path = temp_dir / "merged_output.pdf"
        page_count = pdf_merger.merge_documents(
            input_paths=[str(tiff1), str(tiff2), str(tiff3)],
            mime_types=["image/tiff", "image/tiff", "image/tiff"],
            output_path=str(output_path)
        )
        
        # Total pages should be 4 + 7 + 9 = 20
        assert page_count == 20
        assert output_path.exists()
        assert verify_pdf_page_count(output_path) == 20


class TestDocumentSplitterMultiPageTIFF:
    """Test DocumentSplitter with multi-page TIFFs"""
    
    def test_single_page_tiff_split(self, document_splitter, temp_dir):
        """Test splitting single-page TIFF"""
        tiff_path = temp_dir / "single_page.tiff"
        create_multi_page_tiff(tiff_path, 1)
        
        assert verify_tiff_frame_count(tiff_path) == 1
        
        result = document_splitter.split_document(
            input_path=str(tiff_path),
            unique_id="test-001",
            document_unique_identifier="doc-001",
            original_file_name="single_page.tiff",
            mime_type="image/tiff"
        )
        
        assert result.page_count == 1
        assert len(result.pages) == 1
        assert result.pages[0].page_number == 1
        assert Path(result.pages[0].local_path).exists()
    
    def test_two_page_tiff_split(self, document_splitter, temp_dir):
        """Test splitting two-page TIFF"""
        tiff_path = temp_dir / "two_page.tiff"
        create_multi_page_tiff(tiff_path, 2)
        
        assert verify_tiff_frame_count(tiff_path) == 2
        
        result = document_splitter.split_document(
            input_path=str(tiff_path),
            unique_id="test-002",
            document_unique_identifier="doc-002",
            original_file_name="two_page.tiff",
            mime_type="image/tiff"
        )
        
        assert result.page_count == 2
        assert len(result.pages) == 2
        for i, page in enumerate(result.pages, 1):
            assert page.page_number == i
            assert Path(page.local_path).exists()
            # Verify each page is a valid PDF
            assert verify_pdf_page_count(Path(page.local_path)) == 1
    
    def test_four_page_tiff_split(self, document_splitter, temp_dir):
        """Test splitting four-page TIFF"""
        tiff_path = temp_dir / "four_page.tiff"
        create_multi_page_tiff(tiff_path, 4)
        
        assert verify_tiff_frame_count(tiff_path) == 4
        
        result = document_splitter.split_document(
            input_path=str(tiff_path),
            unique_id="test-004",
            document_unique_identifier="doc-004",
            original_file_name="four_page.tiff",
            mime_type="image/tiff"
        )
        
        assert result.page_count == 4
        assert len(result.pages) == 4
        for i, page in enumerate(result.pages, 1):
            assert page.page_number == i
            assert Path(page.local_path).exists()
            assert verify_pdf_page_count(Path(page.local_path)) == 1
    
    def test_seven_page_tiff_split(self, document_splitter, temp_dir):
        """Test splitting seven-page TIFF"""
        tiff_path = temp_dir / "seven_page.tiff"
        create_multi_page_tiff(tiff_path, 7)
        
        assert verify_tiff_frame_count(tiff_path) == 7
        
        result = document_splitter.split_document(
            input_path=str(tiff_path),
            unique_id="test-007",
            document_unique_identifier="doc-007",
            original_file_name="seven_page.tiff",
            mime_type="image/tiff"
        )
        
        assert result.page_count == 7
        assert len(result.pages) == 7
        for i, page in enumerate(result.pages, 1):
            assert page.page_number == i
            assert Path(page.local_path).exists()
            assert verify_pdf_page_count(Path(page.local_path)) == 1
    
    def test_nine_page_tiff_split(self, document_splitter, temp_dir):
        """Test splitting nine-page TIFF"""
        tiff_path = temp_dir / "nine_page.tiff"
        create_multi_page_tiff(tiff_path, 9)
        
        assert verify_tiff_frame_count(tiff_path) == 9
        
        result = document_splitter.split_document(
            input_path=str(tiff_path),
            unique_id="test-009",
            document_unique_identifier="doc-009",
            original_file_name="nine_page.tiff",
            mime_type="image/tiff"
        )
        
        assert result.page_count == 9
        assert len(result.pages) == 9
        for i, page in enumerate(result.pages, 1):
            assert page.page_number == i
            assert Path(page.local_path).exists()
            assert verify_pdf_page_count(Path(page.local_path)) == 1
    
    def test_eighteen_page_tiff_split(self, document_splitter, temp_dir):
        """Test splitting eighteen-page TIFF"""
        tiff_path = temp_dir / "eighteen_page.tiff"
        create_multi_page_tiff(tiff_path, 18)
        
        assert verify_tiff_frame_count(tiff_path) == 18
        
        result = document_splitter.split_document(
            input_path=str(tiff_path),
            unique_id="test-018",
            document_unique_identifier="doc-018",
            original_file_name="eighteen_page.tiff",
            mime_type="image/tiff"
        )
        
        assert result.page_count == 18
        assert len(result.pages) == 18
        for i, page in enumerate(result.pages, 1):
            assert page.page_number == i
            assert Path(page.local_path).exists()
            assert verify_pdf_page_count(Path(page.local_path)) == 1
    
    def test_twenty_three_page_tiff_split(self, document_splitter, temp_dir):
        """Test splitting twenty-three-page TIFF"""
        tiff_path = temp_dir / "twenty_three_page.tiff"
        create_multi_page_tiff(tiff_path, 23)
        
        assert verify_tiff_frame_count(tiff_path) == 23
        
        result = document_splitter.split_document(
            input_path=str(tiff_path),
            unique_id="test-023",
            document_unique_identifier="doc-023",
            original_file_name="twenty_three_page.tiff",
            mime_type="image/tiff"
        )
        
        assert result.page_count == 23
        assert len(result.pages) == 23
        for i, page in enumerate(result.pages, 1):
            assert page.page_number == i
            assert Path(page.local_path).exists()
            assert verify_pdf_page_count(Path(page.local_path)) == 1


class TestEndToEndMultiPageTIFF:
    """End-to-end tests: Merge then Split workflow"""
    
    def test_merge_then_split_workflow(self, pdf_merger, document_splitter, temp_dir):
        """Test complete workflow: merge multi-page TIFFs, then split the result"""
        # Create multiple multi-page TIFFs
        tiff1 = temp_dir / "tiff1.tiff"
        tiff2 = temp_dir / "tiff2.tiff"
        
        create_multi_page_tiff(tiff1, 4)
        create_multi_page_tiff(tiff2, 7)
        
        # Step 1: Merge TIFFs into consolidated PDF
        merged_pdf = temp_dir / "merged.pdf"
        page_count = pdf_merger.merge_documents(
            input_paths=[str(tiff1), str(tiff2)],
            mime_types=["image/tiff", "image/tiff"],
            output_path=str(merged_pdf)
        )
        
        assert page_count == 11  # 4 + 7
        assert verify_pdf_page_count(merged_pdf) == 11
        
        # Step 2: Split the merged PDF
        split_result = document_splitter.split_document(
            input_path=str(merged_pdf),
            unique_id="test-e2e",
            document_unique_identifier="doc-e2e",
            original_file_name="merged.pdf",
            mime_type="application/pdf"
        )
        
        assert split_result.page_count == 11
        assert len(split_result.pages) == 11
        for i, page in enumerate(split_result.pages, 1):
            assert page.page_number == i
            assert Path(page.local_path).exists()
            assert verify_pdf_page_count(Path(page.local_path)) == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
