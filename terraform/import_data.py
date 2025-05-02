import boto3
from botocore.config import Config
from os import walk
from data import data

bucket = "postgram20250419111920912800000001"
table = "postagram"

# Create an S3 resource
s3 = boto3.resource('s3')


f = []
for (dirpath, dirnames, filenames) in walk("s3"):
    if filenames:
        with open(f"{dirpath}/{filenames[0]}", 'rb') as file:
            s3.Object(bucket, f"{"/".join(dirpath.split("/")[1:])}/{filenames[0]}" ).put(Body=file)

# Batch upload
# Get the service resource.
# Get the service resource.
my_config = Config(
    region_name='us-east-1',
    signature_version='v4',
)

dynamodb = boto3.resource('dynamodb', config=my_config)
# Get the table.
table = dynamodb.Table(table)
# Read file
with table.batch_writer() as batch:
    for row in data:
        batch.put_item(Item=row)