#!/usr/bin/env python3
"""
PDF Classification Script

This script processes PDF files in a specified folder, extracts text content,
sends the text to OpenAI's API for classification, and renames the files
to include the classification tags.
"""

import os
import sys
import logging
import argparse
import re
from typing import List, Dict, Tuple
import json

import PyPDF2
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
    "reciprocation (People feel obligated to return favors. Phishing attackers exploit this by offering fake gifts or benefits to create a sense of indebtedness, making victims more likely to comply with malicious requests in 'return.')",
    "consistency (People desire to be consistent with their prior commitments and actions. Phishing attackers leverage this by referencing fake past agreements or sign-ups to pressure victims into acting in a way that aligns with this fabricated consistency, like confirming details or completing transactions.)",
    "social_proof (People look to others to determine appropriate behavior, especially in uncertain situations. Phishing attackers use fake indicators of popularity or consensus (like fake reviews, likes, or claims of widespread action) to make their scams appear legitimate and encourage victims to follow 'the crowd.')",
    "liking (People are more likely to comply with requests from individuals they like or know. Phishing attackers exploit this by impersonating trusted individuals (friends, colleagues, brands) or building fake rapport to lower defenses and increase compliance, appealing to common interests or hobbies)",
    "authority (People tend to obey figures perceived as authoritative. Phishing attackers impersonate authority figures or institutions (like banks or government agencies) to pressure victims into compliance by creating a false sense of legitimacy and obligation.)",
    "scarcity (People value things that are rare or limited. Phishing attackers use urgency and limited availability (like time-sensitive offers or account suspension threats) to create fear of missing out (FOMO) and pressure victims into acting impulsively without thinking critically.)"
]


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extract text content from a PDF file.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Extracted text content as a string

    Raises:
        Exception: If PDF extraction fails
    """
    try:
        logger.info(f"Extracting text from {pdf_path}")
        text = ""

        with open(pdf_path, 'rb') as pdf_file:
            pdf_reader = PyPDF2.PdfReader(pdf_file)

            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                text += page.extract_text() + "\n"

        if not text.strip():
            logger.warning(f"No text extracted from {pdf_path}")

        return text
    except Exception as e:
        logger.error(f"Error extracting text from {pdf_path}: {str(e)}")
        raise


def classify_text(text: str) -> List[str]:
    """
    Classify text using OpenAI's API.

    Args:
        text: Text content to classify

    Returns:
        List of applicable category tags

    Raises:
        Exception: If API call fails
    """
    try:
        logger.info("Sending text to OpenAI API for classification")

        # Prepare the prompt for classification
        categories_str = ", ".join(CATEGORIES)
        prompt = f"""
        Analyze the following text and classify it based ONLY on these categories: {categories_str}.
        Return ONLY the applicable category names as a JSON array, with no explanation or additional text.
        If none apply, return an empty array.

        Text to analyze:
        {text[:4000]}  # Limit text to avoid token limits
        """

        # Call OpenAI API
        response = openai.chat.completions.create(
            model="gpt-4o-mini-2024-07-18",  # or another appropriate model
            messages=[
                {"role": "system",
                 "content": "You are a classifier that returns only the requested categories as a JSON array."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0  # Use low temperature for more deterministic results
        )

        # Extract and parse the classification result
        result_text = response.choices[0].message.content.strip()

        # Handle different response formats
        if result_text.startswith("[") and result_text.endswith("]"):
            # Direct JSON array
            tags = json.loads(result_text)
        elif result_text.startswith("{") and result_text.endswith("}"):
            # JSON object
            result_json = json.loads(result_text)
            if "categories" in result_json:
                tags = result_json["categories"]
            else:
                # Try to extract any list value from the JSON
                for value in result_json.values():
                    if isinstance(value, list):
                        tags = value
                        break
                else:
                    tags = []
        else:
            # Handle free text response by looking for category matches
            tags = [cat for cat in CATEGORIES if cat.lower() in result_text.lower()]

        # Validate that all returned tags are from our predefined categories
        valid_tags = [tag for tag in tags if tag.lower() in [cat.lower() for cat in CATEGORIES]]

        if not valid_tags:
            logger.info("No applicable categories found")
        else:
            logger.info(f"Classified with tags: {', '.join(valid_tags)}")

        return valid_tags

    except Exception as e:
        logger.error(f"Error classifying text: {str(e)}")
        raise


def generate_new_filename(original_path: str, tags: List[str]) -> str:
    """
    Generate a new filename that includes classification tags.

    Args:
        original_path: Original file path
        tags: List of classification tags

    Returns:
        New file path with tags included in the filename
    """
    try:
        # Get directory and filename
        directory = os.path.dirname(original_path)
        filename = os.path.basename(original_path)

        # Extract prefix and base name
        match = re.match(r"^([^_]+)_(.+)\.pdf$", filename)

        if match:
            prefix = match.group(1)
            base_name = match.group(2)
        else:
            # If no prefix found, use the whole filename as base_name
            prefix = ""
            base_name = os.path.splitext(filename)[0]

        # Create new filename with tags
        if tags:
            tags_str = "_".join(tags)
            if prefix:
                new_filename = f"{prefix}_{tags_str}_{base_name}.pdf"
            else:
                new_filename = f"{tags_str}_{base_name}.pdf"
        else:
            # If no tags, keep original filename
            new_filename = filename

        return os.path.join(directory, new_filename)

    except Exception as e:
        logger.error(f"Error generating new filename: {str(e)}")
        raise


def process_pdf_file(pdf_path: str) -> Tuple[str, List[str]]:
    """
    Process a single PDF file: extract text, classify, and generate new filename.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Tuple of (new_file_path, tags)

    Raises:
        Exception: If processing fails
    """
    try:
        # Extract text from PDF
        text = extract_text_from_pdf(pdf_path)

        # Classify the text
        tags = classify_text(text)

        # Generate new filename
        new_file_path = generate_new_filename(pdf_path, tags)

        return new_file_path, tags

    except Exception as e:
        logger.error(f"Error processing {pdf_path}: {str(e)}")
        raise


def rename_pdf_file(original_path: str, new_path: str) -> bool:
    """
    Rename a PDF file with the new path.

    Args:
        original_path: Original file path
        new_path: New file path

    Returns:
        True if successful, False otherwise
    """
    try:
        # Skip if new path is the same as original
        if original_path == new_path:
            logger.info(f"No rename needed for {original_path}")
            return True

        # Check if destination file already exists
        if os.path.exists(new_path):
            logger.warning(f"Destination file already exists: {new_path}")
            base, ext = os.path.splitext(new_path)
            new_path = f"{base}_copy{ext}"
            logger.info(f"Using alternative name: {new_path}")

        # Rename the file
        os.rename(original_path, new_path)
        logger.info(f"Renamed {original_path} to {new_path}")
        return True

    except Exception as e:
        logger.error(f"Error renaming {original_path}: {str(e)}")
        return False


def process_folder(folder_path: str, dry_run: bool = False) -> Dict[str, List[str]]:
    """
    Process all PDF files in a folder.

    Args:
        folder_path: Path to the folder containing PDF files
        dry_run: If True, don't actually rename files

    Returns:
        Dictionary mapping file paths to their tags
    """
    results = {}

    try:
        logger.info(f"Processing folder: {folder_path}")

        # Check if folder exists
        if not os.path.exists(folder_path):
            logger.error(f"Folder not found: {folder_path}")
            return results

        # Get all PDF files in the folder
        pdf_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.pdf')]

        if not pdf_files:
            logger.warning(f"No PDF files found in {folder_path}")
            return results

        logger.info(f"Found {len(pdf_files)} PDF files to process")

        # Process each PDF file
        for pdf_file in pdf_files:
            pdf_path = os.path.join(folder_path, pdf_file)

            try:
                # Process the PDF file
                new_path, tags = process_pdf_file(pdf_path)
                results[pdf_path] = tags

                # Rename the file if not a dry run
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
        # Process the folder
        results = process_folder(args.folder, args.dry_run)

        # Print summary
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