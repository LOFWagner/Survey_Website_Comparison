#!/usr/bin/env python3
"""
PDF Classification Script (revised to use pdfplumber)
"""

import os
import sys
import logging
import argparse
import re
from typing import List, Dict, Tuple
import json

import pdfplumber
import openai
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pdf_classifier.log")
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file (for API keys)
load_dotenv()

# Set OpenAI API key from environment variable
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    logger.error("OpenAI API key not found. Please set OPENAI_API_KEY environment variable.")
    sys.exit(1)

# Define the categories for classification
CATEGORIES = [
    "reciprocation (People feel obligated to return favors. Phishing attackers exploit this by offering fake gifts or benefits...)",
    "consistency (People desire to be consistent with their prior commitments and actions. Phishing attackers leverage this...)",
    "social_proof (People look to others to determine appropriate behavior, especially in uncertain situations...)",
    "liking (People are more likely to comply with requests from individuals they like or know. Phishing attackers exploit this...)",
    "authority (People tend to obey figures perceived as authoritative. Phishing attackers impersonate authority figures...)",
    "scarcity (People value things that are rare or limited. Phishing attackers use urgency and limited availability...)"
]

def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extract text content from a PDF file using pdfplumber.
    """
    try:
        logger.info(f"Extracting text from {pdf_path}")
        text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                text += page_text + "\n"

        if not text.strip():
            logger.warning(f"No text extracted from {pdf_path}")

        return text
    except Exception as e:
        logger.error(f"Error extracting text from {pdf_path}: {str(e)}")
        raise

def classify_text(text: str) -> List[str]:
    """
    Classify text using OpenAI's API.
    """
    try:
        logger.info("Sending text to OpenAI API for classification")
        categories_str = ", ".join(CATEGORIES)
        prompt = f"""
        Analyze the following text and classify it based ONLY on these categories: {categories_str}.
        Return ONLY the applicable category names as a JSON array, with no explanation or additional text.
        Every email will somewhat fit into a category. If an email hardly fits, return only a single category that is most applicable.

        Text to analyze:
        {text[:4000]}
        """
        response = openai.chat.completions.create(
            model="gpt-4o-mini-2024-07-18",
            messages=[
                {"role": "system",
                 "content": "You are a classifier that returns only the requested categories as a JSON array."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )

        text = response.choices[0].message.content.strip()
        print(response.choices[0].message.content)
        pattern = r'^```json\s*(.*?)\s*```$'
        match = re.match(pattern, text, flags=re.DOTALL)
        if match:
            result_text = match.group(1).strip()
        else:
            result_text = text
        if result_text.startswith("[") and result_text.endswith("]"):
            tags = json.loads(result_text)
        elif result_text.startswith("{") and result_text.endswith("}"):
            result_json = json.loads(result_text)
            if "categories" in result_json:
                tags = result_json["categories"]
            else:
                for value in result_json.values():
                    if isinstance(value, list):
                        tags = value
                        break
                else:
                    tags = []
        else:
            tags = [cat for cat in CATEGORIES if cat.lower() in result_text.lower()]
        print("Determined tags:", tags)

        if not tags:
            logger.info("No applicable categories found")
        else:
            logger.info(f"Classified with tags: {', '.join(tags)}")
        return tags

    except Exception as e:
        logger.error(f"Error classifying text: {str(e)}")
        raise

def generate_new_filename(original_path: str, tags: List[str]) -> str:
    directory = os.path.dirname(original_path)
    filename = os.path.basename(original_path)

    match = re.match(r'^([^_]+)_(.+)\.pdf$', filename)
    if match:
        prefix = match.group(1)
        base_name = match.group(2)
    else:
        prefix = ''
        base_name = os.path.splitext(filename)[0]

    # Replace underscores in the base name with dashes
    base_name = base_name.replace('_', '-')

    if tags:
        tags_str = '_'.join(tags)
        if prefix:
            new_filename = f'{prefix}_{tags_str}_{base_name}.pdf'
        else:
            new_filename = f'{tags_str}_{base_name}.pdf'
    else:
        if prefix:
            new_filename = f'{prefix}_{base_name}.pdf'
        else:
            new_filename = f'{base_name}.pdf'

    return os.path.join(directory, new_filename)

def process_pdf_file(pdf_path: str) -> Tuple[str, List[str]]:
    """
    Process a single PDF file: extract text, classify, and generate new filename.
    """
    try:
        text = extract_text_from_pdf(pdf_path)
        tags = classify_text(text)
        new_file_path = generate_new_filename(pdf_path, tags)
        return new_file_path, tags

    except Exception as e:
        logger.error(f"Error processing {pdf_path}: {str(e)}")
        raise

def rename_pdf_file(original_path: str, new_path: str) -> bool:
    """
    Rename a PDF file with the new path.
    """
    try:
        if original_path == new_path:
            logger.info(f"No rename needed for {original_path}")
            return True
        if os.path.exists(new_path):
            logger.warning(f"Destination file already exists: {new_path}")
            base, ext = os.path.splitext(new_path)
            new_path = f"{base}_copy{ext}"
            logger.info(f"Using alternative name: {new_path}")
        os.rename(original_path, new_path)
        logger.info(f"Renamed {original_path} to {new_path}")
        return True
    except Exception as e:
        logger.error(f"Error renaming {original_path}: {str(e)}")
        return False

def process_folder(folder_path: str, dry_run: bool = False) -> Dict[str, List[str]]:
    """
    Process all PDF files in a folder.
    """
    results = {}
    try:
        logger.info(f"Processing folder: {folder_path}")
        if not os.path.exists(folder_path):
            logger.error(f"Folder not found: {folder_path}")
            return results
        pdf_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.pdf')]
        if not pdf_files:
            logger.warning(f"No PDF files found in {folder_path}")
            return results
        logger.info(f"Found {len(pdf_files)} PDF files to process")

        for pdf_file in pdf_files:
            pdf_path = os.path.join(folder_path, pdf_file)
            try:
                new_path, tags = process_pdf_file(pdf_path)
                results[pdf_path] = tags
                if not dry_run and new_path != pdf_path:
                    rename_pdf_file(pdf_path, new_path)
                elif dry_run and new_path != pdf_path:
                    logger.info(f"Dry run: Would rename {pdf_path} to {new_path}")
            except Exception as e:
                logger.error(f"Error processing {pdf_path}: {str(e)}")
                results[pdf_path] = []
        return results

    except Exception as e:
        logger.error(f"Error processing folder {folder_path}: {str(e)}")
        return results

def main():
    """Main function to parse arguments and run the script."""
    parser = argparse.ArgumentParser(description="Process PDF files and classify them using OpenAI API")
    parser.add_argument("folder", help="Path to the folder containing PDF files")
    parser.add_argument("--dry-run", action="store_true", help="Analyze files without renaming them")
    args = parser.parse_args()

    try:
        results = process_folder(args.folder, args.dry_run)
        logger.info("=== Processing Summary ===")
        total_files = len(results)
        classified_files = sum(1 for tags in results.values() if tags)
        logger.info(f"Total files processed: {total_files}")
        logger.info(f"Files classified: {classified_files}")
        logger.info(f"Files with no classification: {total_files - classified_files}")
    except Exception as e:
        logger.error(f"Error in main execution: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()