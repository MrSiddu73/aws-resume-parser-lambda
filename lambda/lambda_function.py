import boto3
import json
import os
import io
import docx
from pdfminer.high_level import extract_text

s3 = boto3.client("s3")
sns = boto3.client("sns")
comprehend = boto3.client("comprehend")

UPLOAD_BUCKET = os.environ["UPLOAD_BUCKET"]
OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]


def extract_text_from_docx(obj_body):
    doc = docx.Document(io.BytesIO(obj_body))
    full_text = []
    for para in doc.paragraphs:
        full_text.append(para.text)
    return "\n".join(full_text)


def extract_text_from_pdf(file_path):
    return extract_text(file_path)


def lambda_handler(event, context):
    try:
        # Get S3 file details
        record = event["Records"][0]
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]

        print(f"Processing file: {key}")

        # Download file from S3
        tmp_path = f"/tmp/{key.split('/')[-1]}"
        s3.download_file(bucket, key, tmp_path)

        # Detect file type
        extension = key.lower().split(".")[-1]

        if extension == "txt":
            with open(tmp_path, "r") as file:
                text = file.read()

        elif extension == "pdf":
            text = extract_text_from_pdf(tmp_path)

        elif extension == "docx":
            obj = s3.get_object(Bucket=bucket, Key=key)
            obj_body = obj["Body"].read()
            text = extract_text_from_docx(obj_body)

        else:
            raise Exception("Unsupported file type")

        print("Text extracted successfully.")

        # Send extracted text to Comprehend
        entities = comprehend.detect_entities(
            Text=text[:4500], LanguageCode="en")["Entities"]
        key_phrases = comprehend.detect_key_phrases(
            Text=text[:4500], LanguageCode="en")["KeyPhrases"]
        syntax = comprehend.detect_syntax(
            Text=text[:4500], LanguageCode="en")["Syntax"]
        dominant_language = comprehend.detect_dominant_language(
            Text=text[:4500])["Languages"]

        result = {
            "file_name": key,
            "entities": entities,
            "key_phrases": key_phrases,
            "syntax": syntax,
            "dominant_language": dominant_language,
            "extracted_text": text[:2000]  # limit for email
        }

        # Save result JSON to output bucket
        output_key = f"parsed/{key}.json"
        s3.put_object(
            Bucket=OUTPUT_BUCKET,
            Key=output_key,
            Body=json.dumps(result, indent=2),
            ContentType="application/json"
        )

        # Send Email via SNS
        message = f"""
Resume Parsed Successfully!

File: {key}

Top Skills Extracted:
- {", ".join(set([e['Text'] for e in entities if e['Type'] == 'OTHER']))}

Dominant Language:
- {dominant_language[0]['LanguageCode']}

Sample Text:
{text[:400]}
"""

        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject="Resume Parsed Successfully",
            Message=message
        )

        return {"status": "success", "file": key}

    except Exception as e:
        print(str(e))
        raise e
