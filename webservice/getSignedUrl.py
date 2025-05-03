##################################################
##                                              ##
##           NE PAS TOUCHER !!!!!!!!!           ## 
##                                              ##
##################################################


import logging
import boto3
from boto3.dynamodb.conditions import Key
import os
import json
import uuid
from pathlib import Path
from botocore.exceptions import ClientError

bucket = os.getenv("BUCKET")
s3_client = boto3.client('s3', config=boto3.session.Config(signature_version='s3v4'))
logger = logging.getLogger("uvicorn")

def getSignedUrl(filename: str, filetype: str, postId: str, user: str, bucket: str):

    unique_filename = f'{uuid.uuid4()}{Path(filename).suffix}'
    object_name = f"{user}/{postId}/{unique_filename}"

    try:
        url = s3_client.generate_presigned_url(
            ClientMethod='put_object',
            Params={
                'Bucket': bucket,
                'Key': object_name,
                'ContentType': filetype
                },
            ExpiresIn=3600
            )
    except ClientError as e:
        logging.error(e)
    
    logger.info(f'Url: {url}')
    return {
            "uploadURL": url,
            "objectName" : object_name
        }