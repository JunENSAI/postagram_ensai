import json
from urllib.parse import unquote_plus
import boto3
import os
import logging

print('Loading function')
logger = logging.getLogger()
logger.setLevel("INFO")

s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
rekognition = boto3.client('rekognition')

table_name = os.getenv("table")
if not table_name:
    logger.error("Environment variable 'table' not set!")
    table = None
else:
    table = dynamodb.Table(table_name)

def lambda_handler(event, context):
    logger.info("Received event: " + json.dumps(event, indent=2))

    if not table:
         logger.error("DynamoDB table resource is not initialized.")
         return {'statusCode': 500, 'body': 'Table not configured'}

    try:
        bucket = event["Records"][0]["s3"]["bucket"]["name"]
        key = unquote_plus(event["Records"][0]["s3"]["object"]["key"])

        parts = key.split('/')
        if len(parts) < 3:
            logger.error(f"Invalid key format: {key}. Expected user/post_id/filename.")
            return {'statusCode': 400, 'body': 'Invalid key format'}

        user = parts[0]
        post_id = parts[1]

        logger.info(f"Processing object: bucket='{bucket}', key='{key}', user='{user}', post_id='{post_id}'")

        logger.info(f"Calling Rekognition for bucket={bucket}, key={key}")
        label_data = rekognition.detect_labels(
            Image={
                "S3Object": {
                    "Bucket": bucket,
                    "Name": key
                }
            },
            MaxLabels=5,
            MinConfidence=75
        )
        logger.info(f"Rekognition response: {json.dumps(label_data)}")

        labels = [label["Name"] for label in label_data.get("Labels", [])]
        logger.info(f"Labels detected: {labels}")

        logger.info(f"Updating DynamoDB item for user='{user}', post_id='{post_id}'")
        update_response = table.update_item(
            Key={
                'user': user,
                'id': post_id 
            },

            UpdateExpression="SET image = :img, labels = :lbl",
            ExpressionAttributeValues={
                ':img': key,
                ':lbl': labels 
            },
            ReturnValues="UPDATED_NEW"
        )
        logger.info(f"DynamoDB update response: {json.dumps(update_response)}")

        return {
            'statusCode': 200,
            'body': json.dumps(f'Successfully processed {key} and updated DynamoDB.')
        }

    except Exception as e:
        logger.error(f"Error processing event: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps(f'Error processing event: {str(e)}')
        }