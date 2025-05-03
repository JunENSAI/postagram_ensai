#################################################################################################
##                                                                                             ##
##                                 NE PAS TOUCHER CETTE PARTIE                                 ##
##                                                                                             ##
## 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 ##
import boto3
from botocore.config import Config
import os
import uuid
from dotenv import load_dotenv
from typing import Union
import logging
from fastapi import FastAPI, Request, status, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
from boto3.dynamodb.conditions import Key

from getSignedUrl import getSignedUrl

load_dotenv()

app = FastAPI()
logger = logging.getLogger("uvicorn")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
	exc_str = f'{exc}'.replace('\n', ' ').replace('   ', ' ')
	logger.error(f"{request}: {exc_str}")
	content = {'status_code': 10422, 'message': exc_str, 'data': None}
	return JSONResponse(content=content, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


class Post(BaseModel):
    title: str
    body: str

my_config = Config(
    region_name='us-east-1',
    signature_version='v4',
)

try:
    DYNAMO_TABLE_NAME = os.getenv("DYNAMO_TABLE")
    S3_BUCKET_NAME = os.getenv("BUCKET")

    if not DYNAMO_TABLE_NAME:
        logger.critical("CRITICAL ERROR: Environment variable DYNAMO_TABLE not set!")
        table = None
    else:
        dynamodb = boto3.resource('dynamodb', config=my_config)
        table = dynamodb.Table(DYNAMO_TABLE_NAME)
        logger.info(f"DynamoDB Table resource initialized for table: {DYNAMO_TABLE_NAME}")

    if not S3_BUCKET_NAME:
        logger.critical("CRITICAL ERROR: Environment variable BUCKET not set!")
        bucket = None
        s3_client = None
    else:
        # Correction: config s3v4 doit être dans Config, pas boto3.session.Config
        s3_config = Config(signature_version='s3v4', region_name=my_config.region_name)
        s3_client = boto3.client('s3', config=s3_config)
        bucket = S3_BUCKET_NAME
        logger.info(f"S3 Client initialized for bucket: {bucket}")

except Exception as e:
    logger.critical(f"CRITICAL ERROR during Boto3 initialization: {e}", exc_info=True)
    table = None
    bucket = None
    s3_client = None


## ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ##
##                                                                                                ##
####################################################################################################


def create_presigned_url(bucket_name, object_name, expiration=3600):
    """Generate a presigned URL to share an S3 object (for GET requests)"""
    if not s3_client or not bucket_name or not object_name:
        logger.warning(f"Skipping presigned URL generation for {object_name} due to missing client, bucket, or key.")
        return None

    try:
        response = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': object_name},
            ExpiresIn=expiration
        )
        logger.debug(f"Generated presigned URL for {object_name}")
        return response
    except ClientError as e:
        logger.error(f"S3 ClientError generating presigned URL for {object_name}: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Unexpected error generating presigned URL for {object_name}: {e}", exc_info=True)
        return None


@app.post("/posts", status_code=status.HTTP_201_CREATED)
async def post_a_post(post: Post, authorization: str | None = Header(default=None)):
    """Poste un post SANS préfixe."""
    if not table:
       logger.error("POST /posts: Table not initialized")
       return JSONResponse(status_code=500, content={"message": "Internal server error: Table not configured"})
    if not authorization:
        logger.error("POST /posts: Authorization header missing")
        return JSONResponse(status_code=401, content={"message": "Authorization header required"})

    user = authorization
    post_id = str(uuid.uuid4())

    logger.info(f"Creating post for user: {user}, post ID: {post_id}")
    logger.info(f"Title: {post.title}, Body: {post.body}")

    item_to_create = {
        'user': user,
        'id': post_id,
        'title': post.title,
        'body': post.body,
        'image': None,
        'labels': []
    }
    try:
        res = table.put_item(Item=item_to_create)
        logger.info(f"DynamoDB put_item successful. Metadata: {res.get('ResponseMetadata')}")
        return item_to_create
    except ClientError as e:
        logger.error(f"DynamoDB ClientError during put_item: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"message": f"Failed to create post: {e.response['Error']['Message']}"})
    except Exception as e:
        logger.error(f"Unexpected error during put_item: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"message": "Internal server error during post creation"})


@app.get("/posts")
async def get_all_posts(user: Union[str, None] = None):
    """Récupère les posts SANS utiliser de préfixes pour la query."""
    logger.info(f"--- GET /posts --- Received request with user parameter: '{user}'")

    if not table:
        logger.error("GET /posts: Table not initialized")
        return JSONResponse(status_code=500, content={"message": "Internal server error: Table not configured"})
    if not bucket:
        logger.error("GET /posts: S3 Bucket not initialized")
        return JSONResponse(status_code=500, content={"message": "Internal server error: Bucket not configured"})

    items = []
    try:
        if user:
            # <<< QUERY SANS PREFIXE >>>
            logger.info(f"Attempting DynamoDB Query for user: '{user}'")
            response = table.query(
                KeyConditionExpression=Key('user').eq(user) # Utilisation directe
            )
            items = response.get('Items', [])
            logger.info(f"DynamoDB Query returned {len(items)} items.")
        else:
            logger.warning("Attempting DynamoDB Scan for all users (no user parameter provided)")
            response = table.scan()
            items = response.get('Items', [])
            while 'LastEvaluatedKey' in response:
                logger.debug(f"Scanning next page... (retrieved {len(items)} so far)")
                response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
                items.extend(response.get('Items', []))
            logger.info(f"DynamoDB Scan returned {len(items)} items total.")

    except ClientError as e:
         logger.error(f"DynamoDB ClientError during table access: {e}", exc_info=True)
         return JSONResponse(status_code=500, content={"message": f"Database error: {e.response['Error']['Message']}"})
    except Exception as e:
        logger.error(f"!!! UNEXPECTED EXCEPTION during DynamoDB access: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"message": "Internal server error during data retrieval"})

    logger.info(f"Processing {len(items)} items for response...")
    processed_items = []
    for item in items:
        processed_item = dict(item)

        # Pas besoin d'enlever les préfixes car il n'y en a pas
        # if 'user' in processed_item: processed_item['user'] = processed_item['user'].replace('USER#', '')
        # if 'id' in processed_item: processed_item['id'] = processed_item['id'].replace('POST#', '')

        image_key = processed_item.get('image') # Contient la clé S3 ou None
        processed_item['image_url'] = None
        if image_key and bucket and s3_client:
             processed_item['image_url'] = create_presigned_url(bucket, image_key)
             if not processed_item['image_url']:
                 logger.warning(f"Failed to generate presigned URL for key: {image_key}")
        elif image_key:
             logger.warning(f"Cannot generate presigned URL for {image_key}, bucket or s3_client not configured.")

        processed_item['image_s3_key'] = processed_item.pop('image', None) # Garde la clé s3 sous un autre nom

        # Nettoyage des labels (inchangé)
        raw_labels = processed_item.get('labels', [])
        simple_labels: List[str] = []
        if isinstance(raw_labels, list):
            for label_obj in raw_labels:
                 if isinstance(label_obj, dict) and 'S' in label_obj:
                     simple_labels.append(label_obj['S'])
                 elif isinstance(label_obj, str):
                      simple_labels.append(label_obj)
                 else:
                      logger.warning(f"Item ID {processed_item.get('id', 'N/A')} contains unexpected label format: {label_obj}")
        else:
            logger.warning(f"Item ID {processed_item.get('id', 'N/A')} has non-list format for labels: {raw_labels}")
        processed_item['labels'] = simple_labels

        processed_items.append(processed_item)

    logger.info(f"--- GET /posts --- Returning {len(processed_items)} processed items for user parameter: '{user}'")
    return processed_items

@app.delete("/posts/{post_id}")
async def delete_post(post_id: str, authorization: str | None = Header(default=None)):
    """Supprime un post spécifique SANS utiliser de préfixes."""
    # ... (vérifications initiales pour table, bucket, authorization) ...
    if not table: return JSONResponse(status_code=500, content={"message": "Internal server error: Table not configured"})
    if not bucket or not s3_client: return JSONResponse(status_code=500, content={"message": "Internal server error: Bucket not configured"})
    if not authorization: return JSONResponse(status_code=401, content={"message": "Authorization header required"})

    user = authorization

    logger.info(f"Attempting to delete post for user: {user}, post ID: {post_id}")

    try:
        get_response = table.get_item(
            Key={'user': user, 'id': post_id}
        )
        item_to_delete = get_response.get('Item')

        if not item_to_delete:
            logger.warning(f"Delete failed: Post not found for user='{user}', post_id='{post_id}'")
            return JSONResponse(status_code=404, content={"message": "Post not found"})

        image_s3_key = item_to_delete.get('image')
        if image_s3_key:...
            logger.info(f"Deleting associated image from S3 bucket '{bucket}': {image_s3_key}")
            try:
                s3_client.delete_object(Bucket=bucket, Key=image_s3_key)
                logger.info(f"S3 delete_object call successful for {image_s3_key}")
            except ClientError as e:
                 logger.error(f"S3 ClientError deleting object {image_s3_key}: {e}", exc_info=True)
            except Exception as e:
                 logger.error(f"Unexpected error deleting object {image_s3_key} from S3: {e}", exc_info=True)
        delete_response = table.delete_item(
            Key={'user': user, 'id': post_id},
            ReturnValues='ALL_OLD'
        )
        logger.info(f"DynamoDB delete_item successful. Metadata: {delete_response.get('ResponseMetadata')}")
        deleted_item_cleaned = dict(delete_response.get('Attributes', {}))
        return deleted_item_cleaned

    except ClientError as e:
        logger.error(f"DynamoDB ClientError during delete operation for {post_id}: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"message": f"Failed to delete post: {e.response['Error']['Message']}"})
    except Exception as e:
        logger.error(f"Unexpected error during delete operation for {post_id}: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"message": "Internal server error during post deletion"})


#################################################################################################
##                                                                                             ##
##                                 NE PAS TOUCHER CETTE PARTIE                                 ##
##                                                                                             ##
## 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 ##
@app.get("/signedUrlPut")
async def get_signed_url_put(filename: str,filetype: str, postId: str,authorization: str | None = Header(default=None)):
    return getSignedUrl(filename, filetype, postId, authorization, bucket)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="debug")

## ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ##
##                                                                                                ##
####################################################################################################