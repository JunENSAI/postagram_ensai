import json
from urllib.parse import unquote_plus
import boto3
from botocore.exceptions import ClientError
import os
import logging

print('Loading function')
logger = logging.getLogger()
logger.setLevel("INFO")

s3_client = boto3.client('s3')
rekognition = boto3.client('rekognition')

dynamodb_resource = None
table = None

table_name = os.getenv("DYNAMO_TABLE")

if table_name:
    try:
        dynamodb_resource = boto3.resource('dynamodb')
        table = dynamodb_resource.Table(table_name)
        logger.info(f"Successfully initialized DynamoDB table object for table: {table_name}")
    except Exception as e:
        logger.error(f"Failed to initialize DynamoDB table resource for table name '{table_name}': {e}", exc_info=True)
else:
    logger.error("Environment variable DYNAMO_TABLE is not set!")


def lambda_handler(event, context):

    if not table:
         logger.error("DynamoDB table resource is not initialized. Aborting.")
         return {'statusCode': 500, 'body': json.dumps('Internal server error: Table not configured or initialization failed')}

    for record in event.get("Records", []):
        try:
            s3_data = record.get("s3", {})
            bucket_name = s3_data.get("bucket", {}).get("name")
            object_key = s3_data.get("object", {}).get("key")

            if not bucket_name or not object_key:
                logger.warning(f"Skipping record due to missing bucket name or object key: {record}")
                continue

            key = unquote_plus(object_key)
            logger.info(f"Processing object s3://{bucket_name}/{key}")

            parts = key.split('/')
            if len(parts) < 3:
                logger.error(f"Invalid key format: '{key}'. Expected 'user/post_id/filename'. Skipping.")
                continue

            user = parts[0]
            post_id = parts[1]

            logger.info(f"Extracted from key: user='{user}', post_id='{post_id}'")

            logger.info(f"Calling Rekognition for bucket='{bucket_name}', key='{key}'")
            try:
                label_data = rekognition.detect_labels(
                    Image={"S3Object": {
                        "Bucket": bucket_name,
                        "Name": key
                        }
                    },
                    MaxLabels=5,
                    MinConfidence=75
                )
                logger.debug(f"Rekognition raw response keys: {label_data.keys()}")
            except ClientError as e:
                 logger.error(f"Rekognition ClientError for key '{key}': {e}", exc_info=True)
                 continue
            except Exception as e:
                 logger.error(f"Unexpected error calling Rekognition for key '{key}': {e}", exc_info=True)
                 continue

            labels = [label["Name"] for label in label_data.get("Labels", [])]
            logger.info(f"Labels detected: {labels}")

            logger.info(f"Attempting to update DynamoDB item with Key: user='{user}', id='{post_id}'")
            try:
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
                logger.info(f"DynamoDB update successful for post '{post_id}'. Updated attributes: {update_response.get('Attributes')}")

            except ClientError as e:
                 if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                     logger.error(f"DynamoDB update failed for post '{post_id}': Item does not exist or condition failed.", exc_info=True)
                 else:
                      logger.error(f"DynamoDB ClientError updating post '{post_id}': {e}", exc_info=True)
                 continue
            except Exception as e:
                  logger.error(f"Unexpected error updating DynamoDB for post '{post_id}': {e}", exc_info=True)
                  continue

        except Exception as e:
            logger.error(f"Error processing record: {record}. Error: {e}", exc_info=True)
            continue

    return {
        'statusCode': 200,
        'body': json.dumps('Finished processing S3 event.')
    }