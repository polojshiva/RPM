#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Test Script for Multi-Page TIFF Workflow

Creates multiple TIFF documents with various page counts and tests:
1. PDF Merger: Converting multi-page TIFFs to consolidated PDF
2. Document Splitter: Splitting multi-page TIFFs into per-page PDFs
3. End-to-end: Merge multiple TIFFs, then split the result

This script simulates the real-world scenario where ESMD sends
multi-page TIFFs that need to be processed correctly.
"""

import sys
import os
import tempfile
import shutil
from pathlib import Path

# Fix Windows console encoding for Unicode characters
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Check if PIL is available
try:
    from PIL import Image, ImageSequence
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("ERROR: PIL/Pillow is not installed.")
    print("Please install it with: pip install Pillow")
    sys.exit(1)

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.pdf_merger import PDFMerger, PDFMergeError
from app.services.document_splitter import DocumentSplitter, DocumentSplitError


def create_multi_page_tiff(output_path: Path, num_pages: int, page_size=(800, 600)) -> Path:
    """
    Create a multi-page TIFF file with specified number of pages.
    Each page has a unique color and page number for easy identification.
    """
    images = []
    
    for page_num in range(num_pages):
        # Create a simple image for each page with unique color
        # Color varies based on page number for visual distinction
        color = (
            (page_num * 30) % 255,
            (page_num * 50) % 255,
            (page_num * 70) % 255
        )
        img = Image.new('RGB', page_size, color=color)
        images.append(img)
    
    # Save as multi-page TIFF
    if images:
        images[0].save(
            str(output_path),
            format='TIFF',
            save_all=True,
            append_images=images[1:] if len(images) > 1 else []
        )
        print(f"[OK] Created {num_pages}-page TIFF: {output_path}")
    
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
            print("⚠️  No PDF library available for verification")
            return -1


def test_pdf_merger_multipage_tiff():
    """Test PDF Merger with various multi-page TIFFs"""
    print("\n" + "="*80)
    print("TEST 1: PDF MERGER - Multi-Page TIFF Conversion")
    print("="*80)
    
    temp_dir = Path(tempfile.mkdtemp())
    try:
        merger = PDFMerger(temp_dir=str(temp_dir))
        
        test_cases = [
            ("single_page.tiff", 1),
            ("two_page.tiff", 2),
            ("four_page.tiff", 4),
            ("seven_page.tiff", 7),
            ("nine_page.tiff", 9),
            ("eighteen_page.tiff", 18),
            ("twenty_three_page.tiff", 23),
        ]
        
        all_passed = True
        
        for filename, expected_pages in test_cases:
            print(f"\n[TEST] Testing {filename} ({expected_pages} pages)...")
            
            tiff_path = temp_dir / filename
            create_multi_page_tiff(tiff_path, expected_pages)
            
            # Verify TIFF has correct frame count
            actual_frames = verify_tiff_frame_count(tiff_path)
            if actual_frames != expected_pages:
                print(f"[FAIL] TIFF frame count mismatch: expected {expected_pages}, got {actual_frames}")
                all_passed = False
                continue
            
            # Convert to PDF
            output_path = temp_dir / f"{filename}.pdf"
            try:
                page_count = merger.merge_documents(
                    input_paths=[str(tiff_path)],
                    mime_types=["image/tiff"],
                    output_path=str(output_path)
                )
                
                # Verify PDF page count
                pdf_pages = verify_pdf_page_count(output_path)
                
                if page_count == expected_pages and pdf_pages == expected_pages:
                    print(f"   [PASS] {expected_pages} pages -> PDF with {page_count} pages")
                else:
                    print(f"   [FAIL] Expected {expected_pages} pages, got {page_count} (PDF verification: {pdf_pages})")
                    all_passed = False
                    
            except Exception as e:
                print(f"   [FAIL] ERROR: {e}")
                all_passed = False
        
        return all_passed
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_document_splitter_multipage_tiff():
    """Test Document Splitter with various multi-page TIFFs"""
    print("\n" + "="*80)
    print("TEST 2: DOCUMENT SPLITTER - Multi-Page TIFF Splitting")
    print("="*80)
    
    temp_dir = Path(tempfile.mkdtemp())
    try:
        splitter = DocumentSplitter(temp_dir=str(temp_dir))
        
        test_cases = [
            ("single_page.tiff", 1),
            ("two_page.tiff", 2),
            ("four_page.tiff", 4),
            ("seven_page.tiff", 7),
            ("nine_page.tiff", 9),
            ("eighteen_page.tiff", 18),
            ("twenty_three_page.tiff", 23),
        ]
        
        all_passed = True
        
        for filename, expected_pages in test_cases:
            print(f"\n[TEST] Testing {filename} ({expected_pages} pages)...")
            
            tiff_path = temp_dir / filename
            create_multi_page_tiff(tiff_path, expected_pages)
            
            # Verify TIFF has correct frame count
            actual_frames = verify_tiff_frame_count(tiff_path)
            if actual_frames != expected_pages:
                print(f"[FAIL] TIFF frame count mismatch: expected {expected_pages}, got {actual_frames}")
                all_passed = False
                continue
            
            # Split TIFF
            try:
                result = splitter.split_document(
                    input_path=str(tiff_path),
                    unique_id="test-split",
                    document_unique_identifier=f"doc-{filename}",
                    original_file_name=filename,
                    mime_type="image/tiff"
                )
                
                # Verify split result
                if result.page_count == expected_pages and len(result.pages) == expected_pages:
                    # Verify each page PDF exists and has 1 page
                    all_pages_valid = True
                    for i, page in enumerate(result.pages, 1):
                        if not Path(page.local_path).exists():
                            print(f"   [FAIL] Page {i} PDF does not exist: {page.local_path}")
                            all_pages_valid = False
                            break
                        pdf_pages = verify_pdf_page_count(Path(page.local_path))
                        if pdf_pages != 1:
                            print(f"   [FAIL] Page {i} PDF has {pdf_pages} pages (expected 1)")
                            all_pages_valid = False
                            break
                    
                    if all_pages_valid:
                        print(f"   [PASS] PASS: {expected_pages} frames -> {len(result.pages)} PDF pages")
                    else:
                        all_passed = False
                else:
                    print(f"   [FAIL] FAIL: Expected {expected_pages} pages, got {result.page_count} (pages list: {len(result.pages)})")
                    all_passed = False
                    
            except Exception as e:
                print(f"   [FAIL] ERROR: {e}")
                import traceback
                traceback.print_exc()
                all_passed = False
        
        return all_passed
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_multiple_tiff_documents():
    """Test merging multiple multi-page TIFF documents"""
    print("\n" + "="*80)
    print("TEST 3: MULTIPLE TIFF DOCUMENTS - Merge Multiple Multi-Page TIFFs")
    print("="*80)
    
    temp_dir = Path(tempfile.mkdtemp())
    try:
        merger = PDFMerger(temp_dir=str(temp_dir))
        
        # Create multiple TIFFs with different page counts
        tiff_files = [
            ("tiff1.tiff", 4),
            ("tiff2.tiff", 7),
            ("tiff3.tiff", 9),
            ("tiff4.tiff", 2),
            ("tiff5.tiff", 18),
        ]
        
        total_expected_pages = sum(pages for _, pages in tiff_files)
        
        print(f"\n[TEST] Creating {len(tiff_files)} TIFF documents...")
        tiff_paths = []
        mime_types = []
        
        for filename, pages in tiff_files:
            tiff_path = temp_dir / filename
            create_multi_page_tiff(tiff_path, pages)
            actual_frames = verify_tiff_frame_count(tiff_path)
            if actual_frames != pages:
                print(f"[FAIL] TIFF {filename} frame count mismatch: expected {pages}, got {actual_frames}")
                return False
            tiff_paths.append(str(tiff_path))
            mime_types.append("image/tiff")
            print(f"   [PASS] {filename}: {pages} pages (verified: {actual_frames} frames)")
        
        # Merge all TIFFs
        print(f"\n[TEST] Merging {len(tiff_files)} TIFF documents...")
        output_path = temp_dir / "merged_multiple_tiffs.pdf"
        
        try:
            page_count = merger.merge_documents(
                input_paths=tiff_paths,
                mime_types=mime_types,
                output_path=str(output_path)
            )
            
            pdf_pages = verify_pdf_page_count(output_path)
            
            if page_count == total_expected_pages and pdf_pages == total_expected_pages:
                print(f"   [PASS] PASS: Merged {len(tiff_files)} TIFFs -> PDF with {page_count} pages")
                print(f"   📊 Breakdown: {', '.join(f'{name}: {pages}' for name, pages in tiff_files)}")
                return True
            else:
                print(f"   [FAIL] FAIL: Expected {total_expected_pages} pages, got {page_count} (PDF verification: {pdf_pages})")
                return False
                
        except Exception as e:
            print(f"   [FAIL] ERROR: {e}")
            import traceback
            traceback.print_exc()
            return False
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_end_to_end_workflow():
    """Test complete workflow: merge multiple TIFFs, then split the result"""
    print("\n" + "="*80)
    print("TEST 4: END-TO-END WORKFLOW - Merge Multiple TIFFs, Then Split")
    print("="*80)
    
    temp_dir = Path(tempfile.mkdtemp())
    try:
        merger = PDFMerger(temp_dir=str(temp_dir))
        splitter = DocumentSplitter(temp_dir=str(temp_dir))
        
        # Create multiple multi-page TIFFs
        tiff_files = [
            ("doc1.tiff", 4),
            ("doc2.tiff", 7),
            ("doc3.tiff", 9),
        ]
        
        total_expected_pages = sum(pages for _, pages in tiff_files)
        
        print(f"\n[TEST] Step 1: Creating {len(tiff_files)} TIFF documents...")
        tiff_paths = []
        for filename, pages in tiff_files:
            tiff_path = temp_dir / filename
            create_multi_page_tiff(tiff_path, pages)
            actual_frames = verify_tiff_frame_count(tiff_path)
            print(f"   [PASS] {filename}: {pages} pages (verified: {actual_frames} frames)")
            tiff_paths.append(str(tiff_path))
        
        # Step 2: Merge TIFFs into consolidated PDF
        print(f"\n[TEST] Step 2: Merging {len(tiff_files)} TIFFs into consolidated PDF...")
        merged_pdf = temp_dir / "merged.pdf"
        
        try:
            page_count = merger.merge_documents(
                input_paths=tiff_paths,
                mime_types=["image/tiff"] * len(tiff_files),
                output_path=str(merged_pdf)
            )
            
            pdf_pages = verify_pdf_page_count(merged_pdf)
            
            if page_count != total_expected_pages:
                print(f"   [FAIL] FAIL: Merge expected {total_expected_pages} pages, got {page_count}")
                return False
            
            print(f"   [PASS] Merged PDF has {page_count} pages (verified: {pdf_pages})")
            
        except Exception as e:
            print(f"   [FAIL] ERROR during merge: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # Step 3: Split the merged PDF
        print(f"\n[TEST] Step 3: Splitting merged PDF into per-page PDFs...")
        
        try:
            split_result = splitter.split_document(
                input_path=str(merged_pdf),
                unique_id="test-e2e",
                document_unique_identifier="doc-e2e",
                original_file_name="merged.pdf",
                mime_type="application/pdf"
            )
            
            if split_result.page_count == total_expected_pages and len(split_result.pages) == total_expected_pages:
                # Verify each page PDF exists and has 1 page
                all_pages_valid = True
                for i, page in enumerate(split_result.pages, 1):
                    if not Path(page.local_path).exists():
                        print(f"   [FAIL] Page {i} PDF does not exist: {page.local_path}")
                        all_pages_valid = False
                        break
                    pdf_pages = verify_pdf_page_count(Path(page.local_path))
                    if pdf_pages != 1:
                        print(f"   [FAIL] Page {i} PDF has {pdf_pages} pages (expected 1)")
                        all_pages_valid = False
                        break
                
                if all_pages_valid:
                    print(f"   [PASS] Split into {len(split_result.pages)} PDF pages (all valid)")
                    print(f"\n   [PASS] END-TO-END PASS: {len(tiff_files)} TIFFs -> {page_count}-page PDF -> {len(split_result.pages)} split PDFs")
                    return True
                else:
                    return False
            else:
                print(f"   [FAIL] FAIL: Expected {total_expected_pages} pages, got {split_result.page_count} (pages list: {len(split_result.pages)})")
                return False
                
        except Exception as e:
            print(f"   [FAIL] ERROR during split: {e}")
            import traceback
            traceback.print_exc()
            return False
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("MULTI-PAGE TIFF WORKFLOW TEST SUITE")
    print("="*80)
    print("\nThis script tests the fixed multi-page TIFF handling in:")
    print("  - PDF Merger: Converting multi-page TIFFs to consolidated PDF")
    print("  - Document Splitter: Splitting multi-page TIFFs into per-page PDFs")
    print("  - End-to-end: Complete workflow with multiple TIFF documents")
    
    results = []
    
    # Test 1: PDF Merger
    results.append(("PDF Merger Multi-Page TIFF", test_pdf_merger_multipage_tiff()))
    
    # Test 2: Document Splitter
    results.append(("Document Splitter Multi-Page TIFF", test_document_splitter_multipage_tiff()))
    
    # Test 3: Multiple TIFF Documents
    results.append(("Multiple TIFF Documents", test_multiple_tiff_documents()))
    
    # Test 4: End-to-End Workflow
    results.append(("End-to-End Workflow", test_end_to_end_workflow()))
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    all_passed = True
    for test_name, passed in results:
        status = "[PASS] PASS" if passed else "[FAIL] FAIL"
        print(f"{status}: {test_name}")
        if not passed:
            all_passed = False
    
    print("\n" + "="*80)
    if all_passed:
        print("[PASS] ALL TESTS PASSED")
    else:
        print("[FAIL] SOME TESTS FAILED")
    print("="*80)
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    sys.exit(main())
