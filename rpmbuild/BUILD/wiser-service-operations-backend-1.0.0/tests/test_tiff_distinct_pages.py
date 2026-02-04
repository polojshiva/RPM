"""
Unit Tests for Multi-Page TIFF Distinct Pages (No Duplicates)

Tests that multi-page TIFFs produce distinct PDF pages, not duplicate pages.
This verifies the seek+copy fix that prevents ImageSequence.Iterator from
yielding shared references that cause all pages to show the same image.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
import hashlib
from typing import Tuple

# Check if PIL is available
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None
    ImageDraw = None
    ImageFont = None
    pytestmark = pytest.mark.skipif(True, reason="PIL/Pillow not available")
else:
    pytestmark = pytest.mark.skipif(False, reason="")


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files"""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


def create_distinct_multi_page_tiff(output_path: Path, num_pages: int) -> Path:
    """
    Create a multi-page TIFF with clearly distinct content on each page.
    Each page has unique text and colors to make duplicates obvious.
    """
    images = []
    
    for page_num in range(num_pages):
        # Create image with distinct background color
        img = Image.new('RGB', (800, 600), color=(
            (page_num * 40) % 255,
            ((page_num * 40) + 50) % 255,
            ((page_num * 40) + 100) % 255
        ))
        
        # Draw distinct text on each page
        draw = ImageDraw.Draw(img)
        text = f"PAGE {page_num + 1} of {num_pages}"
        
        # Try to use a font, fallback to default if not available
        try:
            # Try to use a system font
            font = ImageFont.truetype("arial.ttf", 60)
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 60)
            except (OSError, IOError):
                font = ImageFont.load_default()
        
        # Get text bounding box
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Center text
        position = ((800 - text_width) // 2, (600 - text_height) // 2)
        draw.text(position, text, fill=(255, 255, 255), font=font)
        
        # Draw a unique pattern (rectangle) on each page
        rect_color = (
            (page_num * 60) % 255,
            ((page_num * 60) + 80) % 255,
            ((page_num * 60) + 160) % 255
        )
        draw.rectangle(
            [100 + page_num * 10, 100 + page_num * 10, 
             300 + page_num * 10, 200 + page_num * 10],
            fill=rect_color,
            outline=(0, 0, 0),
            width=3
        )
        
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


def extract_pdf_page_as_image(pdf_path: Path, page_num: int, output_path: Path) -> Path:
    """Extract a PDF page as a PNG image for comparison"""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        if page_num >= len(doc):
            doc.close()
            raise ValueError(f"Page {page_num} does not exist in PDF")
        
        page = doc[page_num]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom for better quality
        pix.save(str(output_path))
        doc.close()
        return output_path
    except ImportError:
        # Fallback: try pypdf + pdf2image if available
        try:
            from pdf2image import convert_from_path
            images = convert_from_path(str(pdf_path), first_page=page_num + 1, last_page=page_num + 1)
            if images:
                images[0].save(str(output_path), "PNG")
                return output_path
        except ImportError:
            pytest.skip("No PDF library available for page extraction")
    raise RuntimeError("Could not extract PDF page")


def calculate_image_hash(image_path: Path) -> str:
    """Calculate SHA256 hash of image file for comparison"""
    with open(image_path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def compare_images_pixel_diff(img1_path: Path, img2_path: Path, threshold: float = 0.01) -> Tuple[bool, float]:
    """
    Compare two images and return (are_different, difference_ratio).
    Returns True if images are different (difference > threshold).
    """
    try:
        img1 = Image.open(img1_path)
        img2 = Image.open(img2_path)
        
        # Convert to same mode and size
        if img1.mode != img2.mode:
            img2 = img2.convert(img1.mode)
        if img1.size != img2.size:
            img2 = img2.resize(img1.size, Image.Resampling.LANCZOS)
        
        # Calculate pixel difference
        import numpy as np
        arr1 = np.array(img1)
        arr2 = np.array(img2)
        
        diff = np.abs(arr1.astype(int) - arr2.astype(int))
        total_diff = np.sum(diff)
        total_pixels = arr1.size
        diff_ratio = total_diff / (total_pixels * 255.0)  # Normalize to 0-1
        
        return diff_ratio > threshold, diff_ratio
    except ImportError:
        # If numpy not available, use simple hash comparison
        hash1 = calculate_image_hash(img1_path)
        hash2 = calculate_image_hash(img2_path)
        return hash1 != hash2, 1.0 if hash1 != hash2 else 0.0


class TestTIFFDistinctPages:
    """Test that multi-page TIFFs produce distinct pages, not duplicates"""
    
    def test_3_page_tiff_produces_distinct_pages(self, temp_dir):
        """Test that a 3-page TIFF produces 3 distinct PDF pages"""
        from app.services.pdf_merger import PDFMerger
        
        merger = PDFMerger(temp_dir=str(temp_dir))
        
        # Create 3-page TIFF with distinct content
        tiff_path = temp_dir / "test_3page.tiff"
        create_distinct_multi_page_tiff(tiff_path, 3)
        
        # Convert to PDF
        output_path = temp_dir / "output.pdf"
        page_count = merger.merge_documents(
            input_paths=[str(tiff_path)],
            mime_types=["image/tiff"],
            output_path=str(output_path)
        )
        
        assert page_count == 3, f"Expected 3 pages, got {page_count}"
        assert output_path.exists()
        
        # Extract each page as image
        page_images = []
        for i in range(3):
            page_img_path = temp_dir / f"page_{i}.png"
            extract_pdf_page_as_image(output_path, i, page_img_path)
            page_images.append(page_img_path)
        
        # Verify pages are distinct by comparing hashes
        hashes = [calculate_image_hash(img) for img in page_images]
        unique_hashes = set(hashes)
        
        # All pages should have different hashes (distinct content)
        assert len(unique_hashes) == 3, \
            f"Expected 3 distinct pages, but found {len(unique_hashes)} unique hashes. " \
            f"Some pages may be duplicates."
        
        # Verify pages are visually different (pixel comparison)
        try:
            are_diff_01, diff_01 = compare_images_pixel_diff(page_images[0], page_images[1])
            are_diff_02, diff_02 = compare_images_pixel_diff(page_images[0], page_images[2])
            are_diff_12, diff_12 = compare_images_pixel_diff(page_images[1], page_images[2])
            
            assert are_diff_01, f"Page 0 and 1 are too similar (diff: {diff_01:.4f})"
            assert are_diff_02, f"Page 0 and 2 are too similar (diff: {diff_02:.4f})"
            assert are_diff_12, f"Page 1 and 2 are too similar (diff: {diff_12:.4f})"
        except ImportError:
            # numpy not available, skip pixel comparison but hash check is sufficient
            pass
    
    def test_5_page_tiff_produces_distinct_pages(self, temp_dir):
        """Test that a 5-page TIFF produces 5 distinct PDF pages"""
        from app.services.pdf_merger import PDFMerger
        
        merger = PDFMerger(temp_dir=str(temp_dir))
        
        # Create 5-page TIFF with distinct content
        tiff_path = temp_dir / "test_5page.tiff"
        create_distinct_multi_page_tiff(tiff_path, 5)
        
        # Convert to PDF
        output_path = temp_dir / "output.pdf"
        page_count = merger.merge_documents(
            input_paths=[str(tiff_path)],
            mime_types=["image/tiff"],
            output_path=str(output_path)
        )
        
        assert page_count == 5, f"Expected 5 pages, got {page_count}"
        
        # Extract each page as image
        page_images = []
        for i in range(5):
            page_img_path = temp_dir / f"page_{i}.png"
            extract_pdf_page_as_image(output_path, i, page_img_path)
            page_images.append(page_img_path)
        
        # Verify all pages have distinct hashes
        hashes = [calculate_image_hash(img) for img in page_images]
        unique_hashes = set(hashes)
        
        assert len(unique_hashes) == 5, \
            f"Expected 5 distinct pages, but found {len(unique_hashes)} unique hashes. " \
            f"Duplicate pages detected: {[i for i, h in enumerate(hashes) if hashes.count(h) > 1]}"
    
    def test_9_page_tiff_produces_distinct_pages(self, temp_dir):
        """Test that a 9-page TIFF produces 9 distinct PDF pages (common problematic case)"""
        from app.services.pdf_merger import PDFMerger
        
        merger = PDFMerger(temp_dir=str(temp_dir))
        
        # Create 9-page TIFF with distinct content
        tiff_path = temp_dir / "test_9page.tiff"
        create_distinct_multi_page_tiff(tiff_path, 9)
        
        # Convert to PDF
        output_path = temp_dir / "output.pdf"
        page_count = merger.merge_documents(
            input_paths=[str(tiff_path)],
            mime_types=["image/tiff"],
            output_path=str(output_path)
        )
        
        assert page_count == 9, f"Expected 9 pages, got {page_count}"
        
        # Extract each page as image
        page_images = []
        for i in range(9):
            page_img_path = temp_dir / f"page_{i}.png"
            extract_pdf_page_as_image(output_path, i, page_img_path)
            page_images.append(page_img_path)
        
        # Verify all pages have distinct hashes
        hashes = [calculate_image_hash(img) for img in page_images]
        unique_hashes = set(hashes)
        
        assert len(unique_hashes) == 9, \
            f"Expected 9 distinct pages, but found {len(unique_hashes)} unique hashes. " \
            f"This indicates duplicate pages were created."
        
        # Check that no two consecutive pages are identical
        for i in range(8):
            hash_i = hashes[i]
            hash_next = hashes[i + 1]
            assert hash_i != hash_next, \
                f"Page {i} and page {i+1} are identical (same hash). Duplicate detected!"
    
    def test_18_page_tiff_produces_distinct_pages(self, temp_dir):
        """Test that an 18-page TIFF produces 18 distinct PDF pages (another problematic case)"""
        from app.services.pdf_merger import PDFMerger
        
        merger = PDFMerger(temp_dir=str(temp_dir))
        
        # Create 18-page TIFF with distinct content
        tiff_path = temp_dir / "test_18page.tiff"
        create_distinct_multi_page_tiff(tiff_path, 18)
        
        # Convert to PDF
        output_path = temp_dir / "output.pdf"
        page_count = merger.merge_documents(
            input_paths=[str(tiff_path)],
            mime_types=["image/tiff"],
            output_path=str(output_path)
        )
        
        assert page_count == 18, f"Expected 18 pages, got {page_count}"
        
        # Extract sample pages (first, middle, last) to verify distinctness
        # Full extraction of 18 pages would be slow, so we sample
        sample_indices = [0, 8, 17]  # First, middle, last
        page_images = []
        for i in sample_indices:
            page_img_path = temp_dir / f"page_{i}.png"
            extract_pdf_page_as_image(output_path, i, page_img_path)
            page_images.append(page_img_path)
        
        # Verify sample pages are distinct
        hashes = [calculate_image_hash(img) for img in page_images]
        unique_hashes = set(hashes)
        
        assert len(unique_hashes) == 3, \
            f"Expected 3 distinct sample pages (first, middle, last), " \
            f"but found {len(unique_hashes)} unique hashes. Duplicate pages detected!"
    
    def test_split_tiff_produces_distinct_pages(self, temp_dir):
        """Test that splitting a multi-page TIFF produces distinct single-page PDFs"""
        from app.services.document_splitter import DocumentSplitter
        
        splitter = DocumentSplitter(temp_dir=str(temp_dir))
        
        # Create 4-page TIFF with distinct content
        tiff_path = temp_dir / "test_4page.tiff"
        create_distinct_multi_page_tiff(tiff_path, 4)
        
        # Split TIFF
        result = splitter.split_document(
            input_path=str(tiff_path),
            unique_id="test-split",
            document_unique_identifier="doc-split",
            original_file_name="test_4page.tiff",
            mime_type="image/tiff"
        )
        
        assert result.page_count == 4
        assert len(result.pages) == 4
        
        # Verify each split page is a valid PDF
        for page in result.pages:
            assert Path(page.local_path).exists()
            # Verify page count
            try:
                import fitz
                doc = fitz.open(page.local_path)
                assert len(doc) == 1, f"Split page should have 1 page, got {len(doc)}"
                doc.close()
            except ImportError:
                try:
                    import pypdf
                    with open(page.local_path, 'rb') as f:
                        reader = pypdf.PdfReader(f)
                        assert len(reader.pages) == 1
                except ImportError:
                    pass  # Skip if no PDF library
        
        # Extract images from split PDFs and verify they're distinct
        page_images = []
        for i, page in enumerate(result.pages):
            page_img_path = temp_dir / f"split_page_{i}.png"
            extract_pdf_page_as_image(Path(page.local_path), 0, page_img_path)
            page_images.append(page_img_path)
        
        # Verify all split pages have distinct hashes
        hashes = [calculate_image_hash(img) for img in page_images]
        unique_hashes = set(hashes)
        
        assert len(unique_hashes) == 4, \
            f"Expected 4 distinct split pages, but found {len(unique_hashes)} unique hashes. " \
            f"Duplicate pages detected in split operation!"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
