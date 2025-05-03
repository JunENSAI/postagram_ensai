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
    """Poste un post en utilisant le préfixe USER#."""
    if not table:
       logger.error("POST /posts: Table not initialized")
       return JSONResponse(status_code=500, content={"message": "Internal server error: Table not configured"})
    if not authorization:
        logger.error("POST /posts: Authorization header missing")
        return JSONResponse(status_code=401, content={"message": "Authorization header required"})


    user = f"USER#{authorization}"
    post_id= f"POST#{uuid.uuid4()}"

    logger.info(f"Creating post for user key: {user}, post ID key: {post_id}")
    logger.info(f"Title: {post.title}, Body: {post.body}")

    item_to_create = {
        'user': user, 
        'id': post_id, 
        'title': post.title,
        'body': post.body,
        'image': None,
        'labels': []
    }


    res = table.put_item(Item=item_to_create)
    logger.info(f"DynamoDB put_item successful. Metadata: {res.get('ResponseMetadata')}")
    return item_to_create


@app.get("/posts")
async def get_all_posts(user: Union[str, None] = None):
    """
    Récupère tous les postes.
    - Si un user est présent dans la requête, récupère uniquement les siens (avec préfixe USER#)
    - Si aucun user n'est présent, récupère TOUS les postes de la table !!
    """
    logger.info(f"--- GET /posts --- Received request with user parameter: '{user}'")

    if not table:
        logger.error("GET /posts: Table not initialized")
        return JSONResponse(status_code=500, content={"message": "Internal server error: Table not configured"})
    if not bucket: # Vérifie aussi le bucket pour les URLs signées
        logger.error("GET /posts: S3 Bucket not initialized")
        # On pourrait retourner les données sans images, mais pour la cohérence, retournons une erreur
        return JSONResponse(status_code=500, content={"message": "Internal server error: Bucket not configured"})

    items = []
    try:
        if user:
            # <<< AJOUT DU PREFIXE ICI >>>
            query_user_key = f"USER#{user}"
            logger.info(f"Attempting DynamoDB Query for user key: '{query_user_key}'")
            # <<< UTILISATION DE LA CLE PREFIXEE >>>
            response = table.query(
                KeyConditionExpression=Key('user').eq(query_user_key)
            )
            items = response.get('Items', [])
            logger.info(f"DynamoDB Query returned {len(items)} items.")
            # Pas besoin de pagination pour Query généralement, sauf si > 1MB de données
        else:
            logger.warning("Attempting DynamoDB Scan for all users (no user parameter provided)")
            # ATTENTION: Scan est coûteux et lent sur de grosses tables!
            response = table.scan()
            items = response.get('Items', [])
            # Gérer la pagination pour Scan
            while 'LastEvaluatedKey' in response:
                logger.debug(f"Scanning next page... (retrieved {len(items)} so far)")
                response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
                items.extend(response.get('Items', []))
            logger.info(f"DynamoDB Scan returned {len(items)} items total.")

    except ClientError as e:
         logger.error(f"DynamoDB ClientError during table access: {e}", exc_info=True)
         # Renvoyer une erreur 500 serait plus approprié ici
         return JSONResponse(status_code=500, content={"message": f"Database error: {e.response['Error']['Message']}"})
    except Exception as e:
        logger.error(f"!!! UNEXPECTED EXCEPTION during DynamoDB access: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"message": "Internal server error during data retrieval"})

    # --- Traitement des items (URL signée, formatage des labels) ---
    logger.info(f"Processing {len(items)} items for response...")
    processed_items = []
    for item in items:
        # Créer une copie pour éviter de modifier l'original si on le réutilise
        processed_item = dict(item)

        # Enlever les préfixes pour l'affichage (optionnel, dépend de ce que l'UI attend)
        if 'user' in processed_item and isinstance(processed_item['user'], str):
             processed_item['user'] = processed_item['user'].replace('USER#', '')
        if 'id' in processed_item and isinstance(processed_item['id'], str):
             processed_item['id'] = processed_item['id'].replace('POST#', '')


        # Générer l'URL de l'image S3 si une clé d'image existe
        image_key = processed_item.get('image') # Clé S3 stockée (ex: 'Anya/POST#id_post/nom_image.jpg')
        if image_key:
             # S'assurer que bucket est défini avant d'appeler
             if bucket:
                 processed_item['image_url'] = create_presigned_url(bucket, image_key) # Utiliser un nom de clé différent
                 if not processed_item['image_url']:
                     logger.warning(f"Failed to generate presigned URL for image key: {image_key}")
                 # Optionnel : supprimer la clé brute de l'image si non nécessaire dans la réponse
                 # del processed_item['image']
             else:
                 processed_item['image_url'] = None
                 logger.warning(f"Cannot generate presigned URL for {image_key}, bucket name not configured.")
        else:
             processed_item['image_url'] = None # Assure que le champ existe même si vide

        # Le champ 'image' dans la base contient la clé S3, pas l'URL. Renommons pour l'API.
        processed_item['image_s3_key'] = processed_item.pop('image', None)


        # Nettoyer les labels (déjà corrigé dans ta version précédente, on garde)
        # DynamoDB peut retourner List<Map<{'S': 'string'}>>. L'UI attend List<String>.
        raw_labels = processed_item.get('labels', [])
        simple_labels: List[str] = [] # Typage pour clarté
        if isinstance(raw_labels, list):
            for label_obj in raw_labels:
                 # Vérifie si c'est un dict et a la clé 'S' (format DynamoDB standard pour string set/list)
                 # OU si c'est déjà une string simple (si la lambda a été modifiée)
                 if isinstance(label_obj, dict) and 'S' in label_obj:
                     simple_labels.append(label_obj['S'])
                 elif isinstance(label_obj, str): # Gère le cas où c'est déjà une string
                      simple_labels.append(label_obj)
                 else:
                      logger.warning(f"Item ID {processed_item.get('id', 'N/A')} contains unexpected label format: {label_obj}")
        else:
            logger.warning(f"Item ID {processed_item.get('id', 'N/A')} has non-list format for labels: {raw_labels}")

        processed_item['labels'] = simple_labels # Remplace par la liste de strings simple

        processed_items.append(processed_item)

    logger.info(f"--- GET /posts --- Returning {len(processed_items)} processed items for user parameter: '{user}'")
    return processed_items # Retourne la liste d'items correctement formatée


@app.delete("/posts/{post_id}")
async def delete_post(post_id: str, authorization: str | None = Header(default=None)):
    """
    Supprime un post spécifique (en utilisant les préfixes) et son image S3 associée.
    Note: post_id reçu de l'URL n'a PAS le préfixe.
    """
    if not table:
        logger.error(f"DELETE /posts/{post_id}: Table not initialized")
        return JSONResponse(status_code=500, content={"message": "Internal server error: Table not configured"})
    if not bucket or not s3_client:
        logger.error(f"DELETE /posts/{post_id}: S3 Bucket or client not initialized")
        # On pourrait continuer sans supprimer l'image, mais c'est risqué.
        return JSONResponse(status_code=500, content={"message": "Internal server error: Bucket not configured"})
    if not authorization:
        logger.error(f"DELETE /posts/{post_id}: Authorization header missing")
        return JSONResponse(status_code=401, content={"message": "Authorization header required"})

    # Ajout des préfixes pour la requête DynamoDB
    user_key = f"USER#{authorization}"
    post_id_key = f"POST#{post_id}" # Le post_id de l'URL n'a pas de préfixe

    logger.info(f"Attempting to delete post for user key: {user_key}, post ID key: {post_id_key}")

    try:
        # Il faut d'abord récupérer l'item pour connaître la clé S3 de l'image
        get_response = table.get_item(
            Key={'user': user_key, 'id': post_id_key}
        )
        item_to_delete = get_response.get('Item')

        if not item_to_delete:
            logger.warning(f"Delete failed: Post not found for user_key='{user_key}', post_id_key='{post_id_key}'")
            # Retourner 404 Not Found serait plus précis
            return JSONResponse(status_code=404, content={"message": "Post not found"})

        # Supprimer l'image S3 si elle existe
        image_s3_key = item_to_delete.get('image') # Récupère la clé S3 de l'item
        if image_s3_key:
            logger.info(f"Deleting associated image from S3 bucket '{bucket}': {image_s3_key}")
            try:
                s3_client.delete_object(Bucket=bucket, Key=image_s3_key)
                logger.info(f"S3 delete_object call successful for {image_s3_key}")
            except ClientError as e:
                 # Log l'erreur S3 mais continue pour supprimer l'item DynamoDB
                 logger.error(f"S3 ClientError deleting object {image_s3_key}: {e}", exc_info=True)
            except Exception as e:
                 logger.error(f"Unexpected error deleting object {image_s3_key} from S3: {e}", exc_info=True)


        # Supprimer l'item de DynamoDB
        delete_response = table.delete_item(
            Key={'user': user_key, 'id': post_id_key},
            ReturnValues='ALL_OLD' # Optionnel: utile pour confirmer ce qui a été supprimé
        )
        logger.info(f"DynamoDB delete_item successful. Metadata: {delete_response.get('ResponseMetadata')}")
        # Retourner l'item supprimé (sans préfixes si besoin) ou juste un succès
        deleted_item_cleaned = dict(delete_response.get('Attributes', {})) # Récupère l'item supprimé
        if 'user' in deleted_item_cleaned: deleted_item_cleaned['user'] = deleted_item_cleaned['user'].replace('USER#', '')
        if 'id' in deleted_item_cleaned: deleted_item_cleaned['id'] = deleted_item_cleaned['id'].replace('POST#', '')

        return deleted_item_cleaned # Ou retourne juste {"message": "Post deleted successfully"}

    except ClientError as e:
        logger.error(f"DynamoDB ClientError during delete operation for {post_id_key}: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"message": f"Failed to delete post: {e.response['Error']['Message']}"})
    except Exception as e:
        logger.error(f"Unexpected error during delete operation for {post_id_key}: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"message": "Internal server error during post deletion"})


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