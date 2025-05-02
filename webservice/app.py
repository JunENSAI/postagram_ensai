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

DYNAMO_TABLE_NAME = os.getenv("DYNAMO_TABLE")
S3_BUCKET_NAME = os.getenv("BUCKET") 
s3_client = boto3.client('s3', region_name='us-east-1',config=boto3.session.Config(signature_version='s3v4'))

table = None
if not DYNAMO_TABLE_NAME:
    logger.error("FATAL: La variable d'environnement DYNAMO_TABLE est manquante !")
if not S3_BUCKET_NAME:
    logger.error("FATAL: La variable d'environnement BUCKET est manquante !")

# Initialiser l'objet Table seulement si le nom est défini
if DYNAMO_TABLE_NAME:
    table = dynamodb.Table(DYNAMO_TABLE_NAME)
    logger.info(f"Utilisation de la table DynamoDB: {DYNAMO_TABLE_NAME}")
else:
    # L'application ne peut pas fonctionner sans table, mais on loggue l'erreur plus haut
    pass

if S3_BUCKET_NAME:
     logger.info(f"Utilisation du bucket S3: {S3_BUCKET_NAME}")
else:
     # L'application ne peut pas fonctionner sans bucket pour les URLs
     pass

## ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ##
##                                                                                                ##
####################################################################################################


def create_presigned_url(bucket_name, object_name, expiration=3600):
    """Generate a presigned URL to share an S3 object (for GET requests)
    :param bucket_name: string
    :param object_name: string
    :param expiration: Time in seconds for the presigned URL to remain valid
    :return: Presigned URL as string. If error, returns None.
    """


    if not object_name:
        return None
    try:
        response = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': object_name},
            ExpiresIn=expiration
        )
    except ClientError as e:
        logger.error(f"Error generating presigned URL for {object_name}: {e}")
        return None
    except Exception as e: 
        logger.error(f"Unexpected error generating presigned URL for {object_name}: {e}")
        return None

    return response


@app.post("/posts", status_code=status.HTTP_201_CREATED)
async def post_a_post(post: Post, authorization: str | None = Header(default=None)):
    """
    Poste un post ! Les informations du poste sont dans post.title, post.body et le user dans authorization
    """

    if not table:
       logger.error("POST /posts: Table not initialized")

    if not authorization:
        logger.error("POST /posts: Authorization header missing")

    user = authorization
    post_id = str(uuid.uuid4())

    logger.info(f"title : {post.title}")
    logger.info(f"body : {post.body}")
    logger.info(f"user : {user}")
    logger.debug(f"Generated post ID: {post_id}")

    item_to_create = {
        'user': user,
        'id': post_id,
        'title': post.title,
        'body': post.body,
        'image': None,
        'labels': []
    }

    res = table.put_item(Item=item_to_create)
    logger.info(f"DynamoDB put_item response metadata: {res.get('ResponseMetadata')}")
    return res

@app.get("/posts")
async def get_all_posts(user: Union[str, None] = None):
    """
    Récupère tout les postes.
    - Si un user est présent dans le requête, récupère uniquement les siens
    - Si aucun user n'est présent, récupère TOUS les postes de la table !!
    """
    logger.info(f"--- GET /posts --- Received request for user parameter: '{user}'")

    if not table: logger.error("GET /posts: Table not initialized"); return []
    if not S3_BUCKET_NAME: logger.error("GET /posts: S3 Bucket not initialized"); return []

    items = []
    raw_response = None
    try:
        if user :
            logger.info(f"Attempting DynamoDB Query for user: '{user}'")
            raw_response = table.query(
                KeyConditionExpression=Key('user').eq(user)
            )
            items = raw_response.get('Items', [])
            logger.info(f"DynamoDB Query returned {len(items)} items.")
        else :
            logger.warning("Attempting DynamoDB Scan for all users")
            raw_response = table.scan()
            items = raw_response.get('Items', [])
            # (Logique de pagination Scan)
            while 'LastEvaluatedKey' in raw_response:
                 logger.debug("Scanning next page...")
                 raw_response = table.scan(ExclusiveStartKey=raw_response['LastEvaluatedKey'])
                 items.extend(raw_response.get('Items', []))
            logger.info(f"DynamoDB Scan returned {len(items)} items total.")

    except Exception as e:
        logger.error(f"!!! EXCEPTION during DynamoDB access: {e}", exc_info=True)
        return [] # Retourne vide en cas d'erreur

    logger.info(f"Processing {len(items)} items for response...")
    processed_items = []
    for item in items:
        # Récupérer l'item tel quel
        processed_item = dict(item) # Crée une copie pour travailler dessus

        # Générer l'URL de l'image
        image_key = processed_item.get('image')
        processed_item['image'] = create_presigned_url(S3_BUCKET_NAME, image_key)

        # --- CORRECTION IMPORTANTE : Conversion des Labels ---
        raw_labels = processed_item.get('labels', []) # Obtient [{ "S": "..." }, ...] ou []
        if isinstance(raw_labels, list): # Vérifie que c'est bien une liste
            # Extrait la valeur 'S' de chaque dictionnaire dans la liste
            simple_labels = [label_map['S'] for label_map in raw_labels if isinstance(label_map, dict) and 'S' in label_map]
        else:
            # Si ce n'est pas une liste (donnée corrompue?), retourne une liste vide
            simple_labels = []
            logger.warning(f"Item ID {processed_item.get('id')} has unexpected format for labels: {raw_labels}")

        processed_item['labels'] = simple_labels # Remplace par la liste de strings simple
        # ----------------------------------------------------

        processed_items.append(processed_item) # Ajoute l'item traité

    logger.info(f"--- GET /posts --- Returning {len(processed_items)} processed items for user: '{user}'")
    return processed_items # Retourne la liste d'items correctement formatée

@app.delete("/posts/{post_id}")
async def delete_post(post_id: str, authorization: str | None = Header(default=None)):
    """
    Supprime un post spécifique et son image S3 associée.
    """
    # Vérification rapide
    if not table:
        logger.error(f"DELETE /posts/{post_id}: Table not initialized")
    if not S3_BUCKET_NAME:
        logger.error(f"DELETE /posts/{post_id}: S3 Bucket not initialized")
    if not authorization:
        logger.error(f"DELETE /posts/{post_id}: Authorization header missing")


    user = authorization
    logger.info(f"post id : {post_id}")
    logger.info(f"user: {user}")

    get_response = table.get_item(
        Key={'user': user, 'id': post_id}
    )
    item = get_response.get('Item')

    if not item:
         logger.warning(f"Delete failed: Post not found for user='{user}', post_id='{post_id}'")
         return None 
    
    image_key = item.get('image')
    if image_key:
        logger.info(f"Deleting associated image from S3: {image_key}")
        s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=image_key)
        logger.info(f"S3 delete_object call made for {image_key}")

    delete_response = table.delete_item(
        Key={'user': user, 'id': post_id},
        ReturnValues='ALL_OLD'
    )
    logger.info(f"DynamoDB delete_item response metadata: {delete_response.get('ResponseMetadata')}")

    return item 



#################################################################################################
##                                                                                             ##
##                                 NE PAS TOUCHER CETTE PARTIE                                 ##
##                                                                                             ##
## 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 👇 ##
@app.get("/signedUrlPut")
async def get_signed_url_put(filename: str,filetype: str, postId: str,authorization: str | None = Header(default=None)):
    return getSignedUrl(filename, filetype, postId, authorization)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="debug")

## ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ☝️ ##
##                                                                                                ##
####################################################################################################