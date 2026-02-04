"""
Document Splitter Service
Splits documents into per-page PDFs regardless of input type.

All output is standardized to PDF format:
- PDF input -> N PDFs (one per page)
- TIFF input -> N PDFs (one per frame/page)
- PNG/JPG input -> 1 PDF (single page)
- TXT input -> 1 PDF (rendered text)

Output files are temporary only. They must be uploaded to Azure Blob Storage
by the DocumentProcessor after splitting.
"""
import os
import hashlib
import logging
import tempfile
from pathlib import Path
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# PDF handling - prefer PyMuPDF (fitz) for production-ready form field preservation
# Fallback to pypdf if PyMuPDF is not available
try:
    import fitz  # PyMuPDF
    PDF_LIB = "PyMuPDF"
except ImportError:
    try:
        import pypdf
        PDF_LIB = "pypdf"
    except ImportError:
        try:
            import PyPDF2 as pypdf
            PDF_LIB = "PyPDF2"
        except ImportError:
            PDF_LIB = None

# Image handling
try:
    from PIL import Image
    from PIL import ImageSequence
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    ImageSequence = None

# Text-to-PDF rendering
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


class DocumentSplitError(Exception):
    """Custom exception for document splitting operations"""
    pass


class SplitPage(BaseModel):
    """Metadata for a single split page"""
    page_number: int = Field(..., description="Page number (1-based)")
    local_path: str = Field(..., description="Temporary local path of generated split PDF")
    dest_blob_path: str = Field(..., description="Relative blob path where this page will be uploaded")
    content_type: str = Field(default="application/pdf", description="MIME type (always application/pdf)")
    file_size_bytes: int = Field(..., description="File size in bytes")
    sha256: Optional[str] = Field(None, description="SHA256 hash of the file (optional)")


class SplitResult(BaseModel):
    """Result of document splitting operation"""
    processing_path: str = Field(..., description="Base processing path (relative blob path)")
    page_count: int = Field(..., description="Total number of pages")
    pages: List[SplitPage] = Field(..., description="List of split page metadata")
    local_paths: List[str] = Field(..., description="List of all local file paths (for cleanup)")
    
    @property
    def pages_metadata(self) -> Dict[str, Any]:
        """Get pages_metadata in format ready for DB storage"""
        return {
            "page_count": self.page_count,
            "pages": [
                {
                    "page_number": page.page_number,
                    "file_name": os.path.basename(page.local_path),
                    "relative_path": page.dest_blob_path,
                    "is_coversheet": False,  # Will be set by coversheet detection logic
                    "content_type": page.content_type,
                    "file_size_bytes": page.file_size_bytes,
                    "sha256": page.sha256,
                }
                for page in self.pages
            ]
        }


class DocumentSplitter:
    """
    Splits documents into per-page PDFs regardless of input type.
    
    All output is standardized to PDF format for consistent UI preview and OCR processing.
    """
    
    def __init__(self, temp_dir: Optional[str] = None):
        """
        Initialize document splitter.
        
        Args:
            temp_dir: Base directory for temporary files. If None, uses system temp directory.
        """
        if temp_dir:
            self.temp_dir = Path(temp_dir)
            self.temp_dir.mkdir(parents=True, exist_ok=True)
        else:
            # Use system temp directory
            self.temp_dir = Path(tempfile.gettempdir()) / "service_ops_split"
            self.temp_dir.mkdir(parents=True, exist_ok=True)
    
    def split_document(
        self,
        *,
        input_path: str,
        unique_id: str,
        document_unique_identifier: str,
        original_file_name: str,
        mime_type: str
    ) -> SplitResult:
        """
        Split a document into per-page PDFs.
        
        Args:
            input_path: Local file path to the input document
            unique_id: Unique identifier for the message/packet
            document_unique_identifier: Unique identifier for the document
            original_file_name: Original file name
            mime_type: MIME type of the input file
            
        Returns:
            SplitResult with metadata for all split pages
            
        Raises:
            DocumentSplitError: If splitting fails or file type is unsupported
        """
        input_path_obj = Path(input_path)
        
        if not input_path_obj.exists():
            raise DocumentSplitError(f"Input file does not exist: {input_path}")
        
        # Determine processing path
        processing_path = f"service_ops_processing/{unique_id}/{document_unique_identifier}/"
        
        # Create work directory for this document
        work_dir = self.temp_dir / unique_id / document_unique_identifier
        work_dir.mkdir(parents=True, exist_ok=True)
        pages_dir = work_dir / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # Route to appropriate handler based on MIME type
            mime_lower = mime_type.lower().strip()
            
            # Handle various PDF MIME type formats: "pdf", "application/pdf", "image/pdf", etc.
            if (mime_lower == "pdf" or 
                mime_lower == "application/pdf" or 
                mime_lower.endswith("/pdf")):
                pages = self._split_pdf(input_path_obj, pages_dir, processing_path)
            elif mime_lower in ["image/tiff", "image/tif"]:
                pages = self._split_tiff(input_path_obj, pages_dir, processing_path)
            elif mime_lower in ["image/jpeg", "image/jpg", "image/png"]:
                pages = self._split_image(input_path_obj, pages_dir, processing_path)
            elif mime_lower == "text/plain" or mime_lower.endswith("/plain"):
                pages = self._split_text(input_path_obj, pages_dir, processing_path)
            else:
                raise DocumentSplitError(
                    f"Unsupported MIME type: {mime_type}. "
                    f"Supported types: PDF, TIFF, JPEG, PNG, TXT"
                )
            
            # Collect all local paths
            local_paths = [page.local_path for page in pages]
            
            return SplitResult(
                processing_path=processing_path,
                page_count=len(pages),
                pages=pages,
                local_paths=local_paths
            )
            
        except DocumentSplitError:
            # Re-raise DocumentSplitError as-is
            raise
        except Exception as e:
            # Wrap other exceptions
            raise DocumentSplitError(f"Failed to split document: {e}") from e
    
    def _split_pdf(self, input_path: Path, output_dir: Path, processing_path: str) -> List[SplitPage]:
        """Split PDF into per-page PDFs, preserving form fields and annotations"""
        if PDF_LIB is None:
            raise DocumentSplitError(
                "PDF library not available. Install PyMuPDF (recommended) or pypdf: pip install PyMuPDF"
            )
        
        pages = []
        
        try:
            if PDF_LIB == "PyMuPDF":
                # Use PyMuPDF (fitz) - production-ready, preserves form fields and annotations
                doc = fitz.open(input_path)
                total_pages = len(doc)
                
                for page_num in range(total_pages):
                    # CRITICAL: Flatten form fields by rendering the page
                    # Form field values are stored in AcroForm dictionary, not as visible text.
                    # We need to render the page (which shows form field values) and save that rendered version.
                    page = doc[page_num]
                    
                    # Render page to image at high resolution to capture form field values as visible text
                    # Then convert back to PDF - this "flattens" form fields into actual page content
                    mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better quality
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    
                    # Create new single-page document from the rendered image
                    single_page_doc = fitz.open()  # Create new empty document
                    # Insert the rendered page as a new page
                    single_page_doc.new_page(width=page.rect.width, height=page.rect.height)
                    new_page = single_page_doc[0]
                    # Insert the rendered image
                    new_page.insert_image(new_page.rect, pixmap=pix)
                    
                    # Output file path
                    page_filename = f"page_{page_num + 1:04d}.pdf"
                    output_path = output_dir / page_filename
                    
                    # Save the single-page PDF with flattened form fields (now as visible text/image)
                    single_page_doc.save(output_path, deflate=True, garbage=4)
                    single_page_doc.close()
                    pix = None  # Free memory
                    
                    # Get file size and hash
                    file_size = output_path.stat().st_size
                    sha256 = self._calculate_sha256(output_path)
                    
                    # Destination blob path
                    dest_blob_path = f"{processing_path}pages/{page_filename}"
                    
                    pages.append(SplitPage(
                        page_number=page_num + 1,
                        local_path=str(output_path),
                        dest_blob_path=dest_blob_path,
                        content_type="application/pdf",
                        file_size_bytes=file_size,
                        sha256=sha256
                    ))
                
                doc.close()
                
            else:
                # Fallback to pypdf (has form field preservation issues)
                with open(input_path, 'rb') as input_file:
                    pdf_reader = pypdf.PdfReader(input_file)
                    total_pages = len(pdf_reader.pages)
                    
                    for page_num in range(total_pages):
                        # Create single-page PDF
                        pdf_writer = pypdf.PdfWriter()
                        page = pdf_reader.pages[page_num]
                        pdf_writer.add_page(page)
                        
                        # Try to preserve annotations (pypdf has limitations with form fields)
                        try:
                            if "/Annots" in page:
                                if len(pdf_writer.pages) > 0:
                                    pdf_writer.pages[0]["/Annots"] = page["/Annots"]
                        except Exception as preserve_error:
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.warning(
                                f"Could not preserve annotations/form fields for page {page_num + 1}: {preserve_error}. "
                                f"Consider using PyMuPDF for better form field preservation."
                            )
                        
                        # Output file path
                        page_filename = f"page_{page_num + 1:04d}.pdf"
                        output_path = output_dir / page_filename
                        
                        # Write single-page PDF
                        with open(output_path, 'wb') as output_file:
                            pdf_writer.write(output_file)
                        
                        # Get file size and hash
                        file_size = output_path.stat().st_size
                        sha256 = self._calculate_sha256(output_path)
                        
                        # Destination blob path
                        dest_blob_path = f"{processing_path}pages/{page_filename}"
                        
                        pages.append(SplitPage(
                            page_number=page_num + 1,
                            local_path=str(output_path),
                            dest_blob_path=dest_blob_path,
                            content_type="application/pdf",
                            file_size_bytes=file_size,
                            sha256=sha256
                        ))
        
        except Exception as e:
            # Clean up any created files
            for page in pages:
                if Path(page.local_path).exists():
                    try:
                        Path(page.local_path).unlink()
                    except Exception:
                        pass
            raise DocumentSplitError(f"Failed to split PDF: {e}") from e
        
        return pages
    
    def _split_tiff(self, input_path: Path, output_dir: Path, processing_path: str) -> List[SplitPage]:
        """
        Split multi-page TIFF into per-frame PDFs.
        
        Uses seek+copy pattern to ensure each frame has independent pixel data.
        ImageSequence.Iterator can yield shared references, causing duplicate pages.
        Each TIFF frame becomes one separate PDF file.
        """
        if not PIL_AVAILABLE:
            raise DocumentSplitError(
                "Pillow not available. Install Pillow: pip install Pillow"
            )
        if not REPORTLAB_AVAILABLE:
            raise DocumentSplitError(
                "ReportLab not available. Install ReportLab: pip install reportlab"
            )
        
        pages = []
        img = None
        
        try:
            # Open TIFF image
            img = Image.open(input_path)
            
            # Load image to ensure n_frames is reliable (TIFF pages are a linked list)
            img.load()
            
            # Build frames with seek+copy to ensure each frame has independent pixel data
            # ImageSequence.Iterator can yield shared references, causing duplicate pages
            frames = []
            frame_idx = 0
            while True:
                try:
                    img.seek(frame_idx)
                    frames.append(img.copy())  # Independent copy of pixel data
                    frame_idx += 1
                except EOFError:
                    break
            
            if not frames:
                raise DocumentSplitError(f"TIFF file has no frames: {input_path}")
            
            logger = logging.getLogger(__name__)
            logger.info(f"Splitting TIFF with {len(frames)} frames: {input_path}")
            
            # Process each frame (already copied with independent pixel data)
            for frame_idx, frame in enumerate(frames):
                try:
                    # Convert frame to RGB if necessary
                    # Frame is already a copy, but we may need to convert color mode
                    if frame.mode != 'RGB':
                        frame_img = frame.convert('RGB')
                    else:
                        frame_img = frame  # Already RGB and independent copy
                    
                    # Output file path
                    page_filename = f"page_{frame_idx + 1:04d}.pdf"
                    output_path = output_dir / page_filename
                    
                    # Convert frame to PDF using reportlab
                    # Get image dimensions
                    img_width, img_height = frame_img.size
                    
                    # Create PDF with image
                    c = canvas.Canvas(str(output_path), pagesize=(img_width, img_height))
                    # Draw image at full size
                    c.drawImage(ImageReader(frame_img), 0, 0, width=img_width, height=img_height)
                    c.save()
                    
                    # Get file size and hash
                    file_size = output_path.stat().st_size
                    sha256 = self._calculate_sha256(output_path)
                    
                    # Destination blob path
                    dest_blob_path = f"{processing_path}pages/{page_filename}"
                    
                    pages.append(SplitPage(
                        page_number=frame_idx + 1,
                        local_path=str(output_path),
                        dest_blob_path=dest_blob_path,
                        content_type="application/pdf",
                        file_size_bytes=file_size,
                        sha256=sha256
                    ))
                    
                except Exception as e:
                    # Clean up on error
                    for page in pages:
                        if Path(page.local_path).exists():
                            try:
                                Path(page.local_path).unlink()
                            except Exception:
                                pass
                    raise DocumentSplitError(f"Failed to process TIFF frame {frame_idx + 1}: {e}") from e
            
            logger.info(f"Successfully split {len(frames)}-frame TIFF into {len(pages)} PDF pages")
            
        except DocumentSplitError:
            # Re-raise DocumentSplitError as-is
            raise
        except Exception as e:
            # Clean up any created files
            for page in pages:
                if Path(page.local_path).exists():
                    try:
                        Path(page.local_path).unlink()
                    except Exception:
                        pass
            raise DocumentSplitError(f"Failed to split TIFF: {e}") from e
        finally:
            # Ensure image is closed
            if img is not None:
                try:
                    img.close()
                except Exception:
                    pass
        
        return pages
    
    def _split_image(self, input_path: Path, output_dir: Path, processing_path: str) -> List[SplitPage]:
        """Convert single image (JPG/PNG) to 1-page PDF"""
        if not PIL_AVAILABLE:
            raise DocumentSplitError(
                "Pillow not available. Install Pillow: pip install Pillow"
            )
        if not REPORTLAB_AVAILABLE:
            raise DocumentSplitError(
                "ReportLab not available. Install ReportLab: pip install reportlab"
            )
        
        try:
            # Open image
            img = Image.open(input_path)
            
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Get image dimensions
            img_width, img_height = img.size
            
            # Output file path
            page_filename = "page_0001.pdf"
            output_path = output_dir / page_filename
            
            # Convert image to PDF using reportlab
            c = canvas.Canvas(str(output_path), pagesize=(img_width, img_height))
            # Draw image at full size
            c.drawImage(ImageReader(img), 0, 0, width=img_width, height=img_height)
            c.save()
            
            # Get file size and hash
            file_size = output_path.stat().st_size
            sha256 = self._calculate_sha256(output_path)
            
            # Destination blob path
            dest_blob_path = f"{processing_path}pages/{page_filename}"
            
            return [SplitPage(
                page_number=1,
                local_path=str(output_path),
                dest_blob_path=dest_blob_path,
                content_type="application/pdf",
                file_size_bytes=file_size,
                sha256=sha256
            )]
        
        except Exception as e:
            # Clean up on error
            output_path = output_dir / "page_0001.pdf"
            if output_path.exists():
                try:
                    output_path.unlink()
                except Exception:
                    pass
            raise DocumentSplitError(f"Failed to convert image to PDF: {e}") from e
    
    def _split_text(self, input_path: Path, output_dir: Path, processing_path: str) -> List[SplitPage]:
        """Convert text file to 1-page PDF"""
        if not REPORTLAB_AVAILABLE:
            raise DocumentSplitError(
                "ReportLab not available. Install ReportLab: pip install reportlab"
            )
        
        try:
            # Read text file
            with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
                text_content = f.read()
            
            # Output file path
            page_filename = "page_0001.pdf"
            output_path = output_dir / page_filename
            
            # Create PDF with text
            c = canvas.Canvas(str(output_path), pagesize=letter)
            width, height = letter
            
            # Set margins
            margin = 72  # 1 inch
            x = margin
            y = height - margin
            line_height = 14
            
            # Split text into lines and render
            lines = text_content.split('\n')
            for line in lines:
                # Word wrap if line is too long
                words = line.split()
                current_line = ""
                for word in words:
                    test_line = current_line + (" " if current_line else "") + word
                    text_width = c.stringWidth(test_line, "Helvetica", 10)
                    if text_width > (width - 2 * margin):
                        if current_line:
                            c.drawString(x, y, current_line)
                            y -= line_height
                            if y < margin:
                                # Start new page (though we're only creating 1 page)
                                c.showPage()
                                y = height - margin
                        current_line = word
                    else:
                        current_line = test_line
                
                if current_line:
                    c.drawString(x, y, current_line)
                    y -= line_height
                    if y < margin:
                        c.showPage()
                        y = height - margin
            
            c.save()
            
            # Get file size and hash
            file_size = output_path.stat().st_size
            sha256 = self._calculate_sha256(output_path)
            
            # Destination blob path
            dest_blob_path = f"{processing_path}pages/{page_filename}"
            
            return [SplitPage(
                page_number=1,
                local_path=str(output_path),
                dest_blob_path=dest_blob_path,
                content_type="application/pdf",
                file_size_bytes=file_size,
                sha256=sha256
            )]
        
        except Exception as e:
            # Clean up on error
            output_path = output_dir / "page_0001.pdf"
            if output_path.exists():
                try:
                    output_path.unlink()
                except Exception:
                    pass
            raise DocumentSplitError(f"Failed to convert text to PDF: {e}") from e
    
    def _calculate_sha256(self, file_path: Path) -> str:
        """Calculate SHA256 hash of a file"""
        sha256_hash = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

