import json
from urllib.parse import unquote_plus
import boto3
from botocore.exceptions import ClientError
import os
import logging

print('Loading function')
logger = logging.getLogger()
logger.setLevel("INFO")

# Initialisation hors handler
s3_client = boto3.client('s3')
rekognition_client = boto3.client('rekognition')
dynamodb = boto3.resource('dynamodb')

table = None
table_name = os.getenv("DYNAMO_TABLE")
if not table_name:
    logger.critical("CRITICAL ERROR: Environment variable 'DYNAMO_TABLE' not set!")
else:
    try:
        table = dynamodb.Table(table_name)
        logger.info(f"Successfully initialized DynamoDB table resource for: {table_name}")
    except Exception as e:
        logger.critical(f"CRITICAL ERROR: Failed to initialize DynamoDB table resource '{table_name}': {e}", exc_info=True)
        # table restera None

def lambda_handler(event, context):
    # logger.info("Received event: " + json.dumps(event, indent=2)) # Décommenter pour debug détaillé

    if not table:
         logger.error("DynamoDB table resource is not initialized. Aborting.")
         return {'statusCode': 500, 'body': json.dumps('Internal server error: Table not configured')}

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

            # --- Extraction de user et post_id SANS préfixes ---
            parts = key.split('/')
            if len(parts) < 3:
                logger.error(f"Invalid key format: '{key}'. Expected 'user/post_id/filename'. Skipping.")
                continue

            user_from_key = parts[0]
            post_id_from_key = parts[1]

            logger.info(f"Extracted from key: user='{user_from_key}', post_id='{post_id_from_key}'")

            # --- Appel Rekognition ---
            logger.info(f"Calling Rekognition for bucket='{bucket_name}', key='{key}'")
            try:
                label_data = rekognition_client.detect_labels(
                    Image={
                        "S3Object": {
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

            # --- Préparation des clés DynamoDB AVEC préfixes ---
            # Utilisation de noms de variables clairs ici
            user = f"USER#{user_from_key}"
            post_id = f"POST#{post_id_from_key}"

            # --- Mise à jour DynamoDB ---
            # Utilisation des clés préfixées dans l'appel, mais avec des noms de variables
            # qui peuvent être jugés plus lisibles dans le contexte de la Key DynamoDB.
            # (Tu peux même renommer user_key_for_db en user et post_id_key_for_db en id si tu préfères)
            logger.info(f"Attempting to update DynamoDB item with Key: user='{user}', id='{post_id}'")
            try:
                update_response = table.update_item(
                    Key={
                        'user': user,    # Clé de partition AVEC préfixe
                        'id': post_id     # Clé de tri AVEC préfixe
                    },
                    UpdateExpression="SET image = :img, labels = :lbl",
                    ExpressionAttributeValues={
                        ':img': key,
                        ':lbl': labels
                    },
                    ReturnValues="UPDATED_NEW"
                )
                logger.info(f"DynamoDB update successful for post '{post_id}'.")

            except ClientError as e:
                 if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                     logger.error(f"DynamoDB update failed for post '{post_id}': Item does not exist or condition failed.", exc_info=True)
                 elif e.response['Error']['Code'] == 'ResourceNotFoundException':
                     logger.error(f"DynamoDB update failed: Table '{table_name}' not found.", exc_info=True)
                 elif e.response['Error']['Code'] == 'ValidationException':
                      logger.error(f"DynamoDB update failed for post '{post_id}': Validation error. Error: {e}", exc_info=True)
                 else:
                      logger.error(f"DynamoDB ClientError updating post '{post_id}': {e}", exc_info=True)
                 continue
            except Exception as e:
                  logger.error(f"Unexpected error updating DynamoDB for post '{post_id_}': {e}", exc_info=True)
                  continue

        except Exception as e:
            logger.error(f"Error processing record: {record}. Error: {e}", exc_info=True)
            continue

    return {
        'statusCode': 200,
        'body': json.dumps('Finished processing S3 event.')
    }