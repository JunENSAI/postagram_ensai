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

dynamodb = boto3.resource('dynamodb', config=my_config)
table = dynamodb.Table(os.getenv("DYNAMO_TABLE"))
s3_client = boto3.client('s3', config=boto3.session.Config(signature_version='s3v4'))
bucket = os.getenv("BUCKET")

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

    user = authorization
    post_id = str(uuid.uuid4())

    logger.info(f"Creating post for user: {user}, post ID: {post_id}")
    logger.info(f"Title: {post.title}, Body: {post.body}")

    item = {
        'user': user,
        'id': post_id,
        'title': post.title,
        'body': post.body,
        'image': None,
        'labels': []
    }
    try:
        res = table.put_item(Item=item)
        logger.info(f"DynamoDB put_item successful. Metadata: {res.get('ResponseMetadata')}")
        return item
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

    items = []
    try:
        if user:
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
    res = []
    for item in items:
        p_item = dict(item)

        image_key = p_item.get('image')
        p_item['image_url'] = None
        if image_key and bucket and s3_client:
             p_item['image_url'] = create_presigned_url(bucket, image_key)
             if not p_item['image_url']:
                 logger.warning(f"Failed to generate presigned URL for key: {image_key}")
        elif image_key:
             logger.warning(f"Cannot generate presigned URL for {image_key}, bucket or s3_client not configured.")

        p_item['image_s3_key'] = p_item.pop('image', None)

        raw_labels = p_item.get('labels', [])
        simple_labels: List[str] = []
        if isinstance(raw_labels, list):
            for label_obj in raw_labels:
                 if isinstance(label_obj, dict) and 'S' in label_obj:
                     simple_labels.append(label_obj['S'])
                 elif isinstance(label_obj, str):
                      simple_labels.append(label_obj)
                 else:
                      logger.warning(f"Item ID {p_item.get('id', 'N/A')} contains unexpected label format: {label_obj}")
        else:
            logger.warning(f"Item ID {p_item.get('id', 'N/A')} has non-list format for labels: {raw_labels}")
        p_item['labels'] = simple_labels

        res.append(p_item)

    return res

@app.delete("/posts/{post_id}")
async def delete_post(post_id: str, authorization: str | None = Header(default=None)):
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
        if image_s3_key:
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
        item = dict(delete_response.get('Attributes', {}))
        return item

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