import boto3
from botocore.config import Config
from os import walk
import os 

try:
    from data import data
except ImportError:
    print("Avertissement: Le fichier data.py est introuvable ou ne définit pas la variable 'data'.")
    data = []

bucket = "my-cdtf-test-bucket20250502165546728300000001"
table_name = "MyDynamoDB"


s3 = boto3.resource('s3')

print(f"Téléversement des fichiers du dossier 's3' vers le bucket '{bucket}'...")
for dirpath, dirnames, filenames in walk("s3"):
    if filenames:
        local_file_path = os.path.join(dirpath, filenames[0])
        s3_key = "/".join(dirpath.split(os.sep)[1:]) + "/" + filenames[0]
        if not s3_key.startswith('/'):
            print(f"  -> Téléversement de '{local_file_path}' vers 's3://{bucket}/{s3_key}'")
            try:
                with open(local_file_path, 'rb') as file_body:
                    s3.Object(bucket, s3_key).put(Body=file_body)
            except Exception as e:
                print(f"  ERREUR lors du téléversement de {local_file_path}: {e}")
        else:
             print(f"  Ignoré: Fichier directement dans le dossier racine 's3': {local_file_path}")


print(f"\nÉcriture batch dans la table DynamoDB '{table_name}'...")
my_config = Config(
    region_name='us-east-1',
    signature_version='v4',
)

dynamodb = boto3.resource('dynamodb', config=my_config)
table_object = dynamodb.Table(table_name)

if data:
    try:
        with table_object.batch_writer() as batch:
            item_count = 0
            for row in data:
                batch.put_item(Item=row)
                item_count += 1
            print(f"  {item_count} items envoyés à l'écriture batch.")
        print("  Écriture batch terminée.")
    except Exception as e:
        print(f"  ERREUR durant l'écriture batch DynamoDB: {e}")
else:
    print("  Aucune donnée à écrire dans DynamoDB (variable 'data' vide ou non importée).")

print("\nScript import_data.py terminé.")