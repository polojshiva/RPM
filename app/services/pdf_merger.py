"""
PDF Merger Service
Merges multiple PDF files into a single consolidated PDF.

Supports:
- Multiple PDF files
- Images (TIFF, PNG, JPG) - converts to PDF first
- Text files - converts to PDF first

All input files are normalized to PDF format before merging.
"""
import logging
from pathlib import Path
from typing import List, Optional
import tempfile

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
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

logger = logging.getLogger(__name__)


class PDFMergeError(Exception):
    """Custom exception for PDF merge operations"""
    pass


class PDFMerger:
    """
    Merges multiple documents into a single consolidated PDF.
    
    All input files are normalized to PDF format before merging:
    - PDF files: used as-is
    - Images (TIFF, PNG, JPG): converted to PDF
    - Text files: rendered to PDF
    """
    
    def __init__(self, temp_dir: Optional[str] = None):
        """
        Initialize PDF merger.
        
        Args:
            temp_dir: Base directory for temporary files. If None, uses system temp directory.
        """
        if PDF_LIB is None:
            raise PDFMergeError(
                "No PDF library available. Please install PyMuPDF (fitz), pypdf, or PyPDF2."
            )
        
        if temp_dir:
            self.temp_dir = Path(temp_dir)
            self.temp_dir.mkdir(parents=True, exist_ok=True)
        else:
            import tempfile
            self.temp_dir = Path(tempfile.gettempdir()) / "service_ops_merge"
            self.temp_dir.mkdir(parents=True, exist_ok=True)
    
    def merge_documents(
        self,
        input_paths: List[str],
        mime_types: List[str],
        output_path: str
    ) -> int:
        """
        Merge multiple documents into a single consolidated PDF.
        
        Args:
            input_paths: List of local file paths to merge (in order)
            mime_types: List of MIME types corresponding to input_paths
            output_path: Local file path for the merged PDF output
            
        Returns:
            Total number of pages in the merged PDF
            
        Raises:
            PDFMergeError: If merging fails
        """
        if len(input_paths) != len(mime_types):
            raise PDFMergeError(
                f"input_paths ({len(input_paths)}) and mime_types ({len(mime_types)}) "
                "must have the same length"
            )
        
        if not input_paths:
            raise PDFMergeError("No input files provided for merging")
        
        logger.info(f"Merging {len(input_paths)} documents into consolidated PDF: {output_path}")
        
        # Normalize all inputs to PDF format first
        normalized_pdfs = []
        temp_files_to_cleanup = []
        
        try:
            for idx, (input_path, mime_type) in enumerate(zip(input_paths, mime_types)):
                input_path_obj = Path(input_path)
                if not input_path_obj.exists():
                    raise PDFMergeError(f"Input file does not exist: {input_path}")
                
                mime_lower = mime_type.lower().strip()
                
                # Normalize to PDF
                # Handle various PDF MIME type formats: "pdf", "application/pdf", "image/pdf", etc.
                if (mime_lower == "pdf" or 
                    mime_lower == "application/pdf" or 
                    mime_lower.endswith("/pdf")):
                    # Already PDF, use as-is
                    normalized_pdfs.append(str(input_path_obj))
                elif mime_lower in ["image/tiff", "image/tif"]:
                    # Convert TIFF to PDF
                    pdf_path = self._convert_tiff_to_pdf(input_path_obj, idx)
                    normalized_pdfs.append(pdf_path)
                    temp_files_to_cleanup.append(pdf_path)
                elif mime_lower in ["image/jpeg", "image/jpg", "image/png"]:
                    # Convert image to PDF
                    pdf_path = self._convert_image_to_pdf(input_path_obj, idx)
                    normalized_pdfs.append(pdf_path)
                    temp_files_to_cleanup.append(pdf_path)
                elif mime_lower == "text/plain" or mime_lower.endswith("/plain"):
                    # Convert text to PDF
                    pdf_path = self._convert_text_to_pdf(input_path_obj, idx)
                    normalized_pdfs.append(pdf_path)
                    temp_files_to_cleanup.append(pdf_path)
                else:
                    raise PDFMergeError(
                        f"Unsupported MIME type for merging: {mime_type}. "
                        f"Supported types: PDF, TIFF, JPEG, PNG, TXT"
                    )
            
            # Merge all normalized PDFs
            total_pages = self._merge_pdfs(normalized_pdfs, output_path)
            
            logger.info(
                f"Successfully merged {len(input_paths)} documents into {output_path} "
                f"({total_pages} total pages)"
            )
            
            return total_pages
            
        finally:
            # Cleanup temporary normalized PDFs
            for temp_file in temp_files_to_cleanup:
                try:
                    Path(temp_file).unlink()
                except Exception as e:
                    logger.warning(f"Failed to cleanup temp file {temp_file}: {e}")
    
    def _merge_pdfs(self, pdf_paths: List[str], output_path: str) -> int:
        """
        Merge multiple PDF files into one.
        
        Args:
            pdf_paths: List of PDF file paths to merge (in order)
            output_path: Output file path for merged PDF
            
        Returns:
            Total number of pages in merged PDF
        """
        if PDF_LIB == "PyMuPDF":
            return self._merge_pdfs_pymupdf(pdf_paths, output_path)
        else:
            return self._merge_pdfs_pypdf(pdf_paths, output_path)
    
    def _merge_pdfs_pymupdf(self, pdf_paths: List[str], output_path: str) -> int:
        """Merge PDFs using PyMuPDF (fitz)"""
        merged_doc = fitz.open()
        total_pages = 0
        
        for pdf_path in pdf_paths:
            src_doc = fitz.open(pdf_path)
            merged_doc.insert_pdf(src_doc)
            total_pages += len(src_doc)
            src_doc.close()
        
        merged_doc.save(output_path)
        merged_doc.close()
        
        return total_pages
    
    def _merge_pdfs_pypdf(self, pdf_paths: List[str], output_path: str) -> int:
        """Merge PDFs using pypdf/PyPDF2"""
        merger = pypdf.PdfMerger()
        total_pages = 0
        
        try:
            for pdf_path in pdf_paths:
                with open(pdf_path, 'rb') as f:
                    reader = pypdf.PdfReader(f)
                    merger.append(reader)
                    total_pages += len(reader.pages)
            
            with open(output_path, 'wb') as f:
                merger.write(f)
            
            return total_pages
        finally:
            merger.close()
    
    def _convert_tiff_to_pdf(self, tiff_path: Path, index: int) -> str:
        """
        Convert multi-page TIFF to PDF with all frames.
        
        Uses seek+copy pattern to ensure each frame has independent pixel data.
        ImageSequence.Iterator can yield shared references, causing all pages to show the same image.
        Each TIFF frame becomes one distinct PDF page.
        """
        if not PIL_AVAILABLE:
            raise PDFMergeError("PIL/Pillow not available for TIFF conversion")
        
        output_path = self.temp_dir / f"normalized_{index}_tiff.pdf"
        
        try:
            # Open TIFF image
            img = Image.open(tiff_path)
            
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
                raise PDFMergeError(f"TIFF file has no frames: {tiff_path}")
            
            logger.info(f"Converting TIFF with {len(frames)} frames to PDF: {tiff_path}")
            
            if PDF_LIB == "PyMuPDF":
                # Use PyMuPDF for better quality - create one page per frame
                pdf_doc = fitz.open()
                
                for frame_idx, frame in enumerate(frames):
                    # Convert frame to RGB if necessary
                    if frame.mode != 'RGB':
                        frame = frame.convert('RGB')
                    
                    # Create a page for this frame
                    pdf_page = pdf_doc.new_page(width=frame.width, height=frame.height)
                    
                    # Save frame to temporary file for PyMuPDF to insert
                    # PyMuPDF needs a file path, not PIL Image object
                    temp_frame_path = self.temp_dir / f"temp_frame_{index}_{frame_idx}.png"
                    frame.save(temp_frame_path, "PNG")
                    
                    # Insert frame as image on PDF page
                    pdf_page.insert_image(
                        fitz.Rect(0, 0, frame.width, frame.height),
                        filename=str(temp_frame_path)
                    )
                    
                    # Clean up temp frame file
                    try:
                        temp_frame_path.unlink()
                    except Exception as e:
                        logger.warning(f"Failed to cleanup temp frame file {temp_frame_path}: {e}")
                
                pdf_doc.save(str(output_path))
                pdf_doc.close()
            else:
                # Fallback: convert to PDF using PIL + reportlab
                if not REPORTLAB_AVAILABLE:
                    raise PDFMergeError("ReportLab not available for TIFF conversion")
                
                # For multi-page TIFF, we need to create a multi-page PDF
                # PIL's save() with "PDF" only saves the first frame
                # So we'll use reportlab to create a multi-page PDF
                from reportlab.lib.pagesizes import letter
                from reportlab.pdfgen import canvas
                from reportlab.lib.utils import ImageReader
                
                c = canvas.Canvas(str(output_path))
                
                for frame in frames:
                    # Convert frame to RGB if necessary
                    if frame.mode != 'RGB':
                        frame = frame.convert('RGB')
                    
                    # Create page with frame dimensions
                    c.setPageSize((frame.width, frame.height))
                    c.drawImage(ImageReader(frame), 0, 0, width=frame.width, height=frame.height)
                    c.showPage()  # Move to next page
                
                c.save()
            
            # Verify output PDF has correct page count
            if PDF_LIB == "PyMuPDF":
                verify_doc = fitz.open(str(output_path))
                actual_pages = len(verify_doc)
                verify_doc.close()
            else:
                import pypdf
                with open(output_path, 'rb') as f:
                    verify_reader = pypdf.PdfReader(f)
                    actual_pages = len(verify_reader.pages)
            
            if actual_pages != len(frames):
                logger.warning(
                    f"TIFF conversion page count mismatch: expected {len(frames)} pages, "
                    f"got {actual_pages} pages in PDF {output_path}"
                )
            
            logger.info(f"Successfully converted {len(frames)}-frame TIFF to {actual_pages}-page PDF")
            
            return str(output_path)
            
        except PDFMergeError:
            # Re-raise PDFMergeError as-is
            raise
        except Exception as e:
            # Clean up output file on error
            if output_path.exists():
                try:
                    output_path.unlink()
                except Exception:
                    pass
            raise PDFMergeError(f"Failed to convert TIFF to PDF: {e}") from e
        finally:
            # Ensure image is closed
            try:
                if 'img' in locals():
                    img.close()
            except Exception:
                pass
    
    def _convert_image_to_pdf(self, image_path: Path, index: int) -> str:
        """Convert image (PNG/JPG) to PDF"""
        if not PIL_AVAILABLE:
            raise PDFMergeError("PIL/Pillow not available for image conversion")
        
        output_path = self.temp_dir / f"normalized_{index}_image.pdf"
        
        try:
            img = Image.open(image_path)
            if PDF_LIB == "PyMuPDF":
                # Use PyMuPDF for better quality
                pdf_doc = fitz.open()
                pdf_page = pdf_doc.new_page(width=img.width, height=img.height)
                pdf_page.insert_image(fitz.Rect(0, 0, img.width, img.height), filename=str(image_path))
                pdf_doc.save(str(output_path))
                pdf_doc.close()
            else:
                # Fallback: convert to PDF using PIL
                img.save(str(output_path), "PDF", resolution=100.0)
            
            return str(output_path)
        except Exception as e:
            raise PDFMergeError(f"Failed to convert image to PDF: {e}") from e
    
    def _convert_text_to_pdf(self, text_path: Path, index: int) -> str:
        """Convert text file to PDF"""
        if not REPORTLAB_AVAILABLE:
            raise PDFMergeError("ReportLab not available for text-to-PDF conversion")
        
        output_path = self.temp_dir / f"normalized_{index}_text.pdf"
        
        try:
            # Read text file
            with open(text_path, 'r', encoding='utf-8', errors='ignore') as f:
                text_content = f.read()
            
            # Create PDF with text
            c = canvas.Canvas(str(output_path), pagesize=letter)
            width, height = letter
            
            # Simple text rendering (wraps at page width)
            y = height - 50
            line_height = 14
            margin = 50
            
            for line in text_content.split('\n'):
                if y < margin:
                    c.showPage()
                    y = height - 50
                
                # Truncate long lines
                max_chars = int((width - 2 * margin) / 7)  # Approximate char width
                if len(line) > max_chars:
                    # Split long lines
                    words = line.split()
                    current_line = ""
                    for word in words:
                        if len(current_line + word) > max_chars:
                            if current_line:
                                c.drawString(margin, y, current_line)
                                y -= line_height
                                if y < margin:
                                    c.showPage()
                                    y = height - 50
                            current_line = word + " "
                        else:
                            current_line += word + " "
                    if current_line:
                        c.drawString(margin, y, current_line)
                        y -= line_height
                else:
                    c.drawString(margin, y, line)
                    y -= line_height
            
            c.save()
            return str(output_path)
        except Exception as e:
            raise PDFMergeError(f"Failed to convert text to PDF: {e}") from e

