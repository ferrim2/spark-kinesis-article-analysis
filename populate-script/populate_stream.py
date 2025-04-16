from faker import Faker
from flask import Flask, jsonify
import boto3
import json
import os
import time
import threading

# Get configs from environment variables
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")
BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
STREAM_NAME = os.getenv("KINESIS_STREAM_NAME")
DATASET_SIZE_MB = int(os.getenv("DATASET_SIZE_MB"))
NUM_ITERATIONS = int(os.getenv("NUM_ITERATIONS"))

# Other global variables
app = Flask(__name__)
fake = Faker()
publishing_started = False
server_thread = None
bucket_created = False
stream_created = False

aws_config = {
    'endpoint_url': AWS_ENDPOINT_URL,
    'aws_access_key_id': AWS_ACCESS_KEY_ID,
    'aws_secret_access_key': AWS_SECRET_ACCESS_KEY,
    'region_name': AWS_REGION
}

def create_s3_bucket(bucket_name, max_retries=5, retry_delay=2):
    global bucket_created
    s3_client = boto3.client('s3', **aws_config)
    for i in range(max_retries):
        try:
            bucket_list = s3_client.list_buckets()
            if bucket_name not in [bucket['Name'] for bucket in bucket_list.get('Buckets', [])]:
                s3_client.create_bucket(Bucket=bucket_name)
                print(f"Bucket '{bucket_name}' created.")
            else:
                print(f"Bucket '{bucket_name}' already exists.")
            bucket_created = True
            return
        except ClientError as e:
            print(f"Error creating S3 bucket (attempt {i+1}/{max_retries}): {e}")
            if i < max_retries - 1:
                time.sleep(retry_delay)
    print(f"Failed to create or check S3 bucket after {max_retries} retries.")

def create_kinesis_stream(stream_name, shard_count=1, max_retries=5, retry_delay=2):
    global stream_created
    kinesis_client = boto3.client('kinesis', **aws_config)
    for i in range(max_retries):
        try:
            kinesis_client.create_stream(StreamName=stream_name, ShardCount=shard_count)
            print(f"Stream '{stream_name}' created.")
            time.sleep(5)  # Wait for stream to be created
            stream_created = True
            return
        except kinesis_client.exceptions.ResourceInUseException:
            print(f"Stream '{stream_name}' already exists.")
            stream_created = True
            return
        except ClientError as e:
            print(f"Error creating Kinesis stream (attempt {i+1}/{max_retries}): {e}")
            if i < max_retries - 1:
                time.sleep(retry_delay)
    print(f"Failed to create Kinesis stream after {max_retries} retries.")

def generate_mock_article():
    return {
        'article_id': fake.uuid4(),
        'title': fake.sentence(nb_words=6),
        'author': fake.name(),
        'publish_date': fake.date_time_this_year().isoformat(),
        'content': ' '.join(fake.paragraphs(nb=10))
    }

def publish_articles_to_kinesis(stream_name, target_size_mb, num_iterations):
    global publishing_started
    kinesis_client = boto3.client('kinesis', **aws_config)
    articles_count = 0
    initial_published_count = 0
    initial_publish_threshold = 100  # Number of initial articles to trigger 'healthy'

    for iteration in range(num_iterations):
        print(f"Iteration {iteration + 1}...")
        total_size = 0
        target_bytes = target_size_mb * 1024 * 1024  # Convert MB to Bytes

        while total_size < target_bytes:
            article = generate_mock_article()
            article_json = json.dumps(article)
            article_bytes = article_json.encode('utf-8')
            try:
                kinesis_client.put_record(StreamName=stream_name, Data=article_bytes, PartitionKey=article['article_id'])
                total_size += len(article_bytes)
                articles_count += 1
                initial_published_count += 1

                if not publishing_started and initial_published_count >= initial_publish_threshold:
                    print(f"Successfully published the initial {initial_publish_threshold} articles.")
                    publishing_started = True

                if articles_count % 100 == 0:
                    print(f"Published {articles_count} articles, {total_size / (1024 * 1024)} MB so far...")

            except Exception as e:
                print(f"Error during publishing: {e}")
                time.sleep(5)

        if iteration < num_iterations - 1:
            time.sleep(60) # Wait between iterations

    print(f"Finished: Published a total of {articles_count} articles, approx {total_size / (1024 * 1024)} MB of data to Kinesis.")

@app.route('/health', methods=['GET'])
def health_check():
    # Returns 200 OK if bucket/stream created and publishing started, else 503 with status.
    if bucket_created and stream_created and publishing_started:
        return jsonify({"status": "healthy", "message": "Initial setup and publishing started"}), 200
    else:
        status = "unhealthy"
        message = "Waiting for initial setup"
        if bucket_created:
            message += ", Bucket created"
        if stream_created:
            message += ", Stream created"
        if publishing_started:
            message += ", Initial publishing started"
        return jsonify({"status": status, "message": message}), 503

def health_check_server():
    app.run(host='0.0.0.0', port=8000)

if __name__ == '__main__':

    create_s3_bucket(BUCKET_NAME)
    create_kinesis_stream(STREAM_NAME)

    # Start the health check server first
    server_thread = threading.Thread(target=health_check_server)
    server_thread.daemon = True
    server_thread.start()
    time.sleep(1) # Give the server a moment to start (optional but helpful)

    publishing_thread = threading.Thread(target=publish_articles_to_kinesis, args=(STREAM_NAME, DATASET_SIZE_MB, NUM_ITERATIONS))
    publishing_thread.start()
    publishing_thread.join()

    print("Publishing thread finished.")

    print("All publishing threads have finished.") # Optional confirmation
