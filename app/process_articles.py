import os
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, from_json, split, size, avg, window, to_timestamp, current_timestamp
from pyspark.sql.types import StructType, StructField, StringType, TimestampType


# Get configs from environment variables
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION")
KINESIS_STREAM_NAME = os.getenv("KINESIS_STREAM_NAME")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_CHECKPOINT_LOCATION = os.getenv("S3_CHECKPOINT_LOCATION")
SPARK_CHECKPOINT_LOCATION = os.getenv("SPARK_CHECKPOINT_LOCATION")
SPARK_APP_NAME = os.getenv("SPARK_APP_NAME")
SPARK_MASTER_URL = os.getenv("SPARK_MASTER_URL")

s3_output_path = f"s3a://{S3_BUCKET_NAME}/enriched_articles"

kinesis_schema = StructType([
    StructField("data", StringType(), True),
    StructField("approximateArrivalTimestamp", TimestampType(), True),
    StructField("partitionKey", StringType(), True),
    StructField("sequenceNumber", StringType(), True),
    StructField("kinesisShardId", StringType(), True)
])

article_schema = StructType([
    StructField("article_id", StringType(), True),
    StructField("title", StringType(), True),
    StructField("author", StringType(), True),
    StructField("publish_date", StringType(), True),
    StructField("content", StringType(), True)
])

if __name__ == "__main__":

    # Create Spark session 
    spark = SparkSession.builder \
        .appName(SPARK_APP_NAME) \
        .config("spark.master", SPARK_MASTER_URL) \
        .config("spark.hadoop.fs.s3a.endpoint", AWS_ENDPOINT_URL) \
        .config("spark.hadoop.fs.s3a.access.key", AWS_ACCESS_KEY_ID) \
        .config("spark.hadoop.fs.s3a.secret.key", AWS_ACCESS_KEY_ID) \
        .config("spark.hadoop.fs.s3a.path.style.access", "true") \
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem") \
        .config("spark.sql.streaming.checkpointLocation", SPARK_CHECKPOINT_LOCATION) \
        .config("spark.logging.level", "DEBUG") \
        .getOrCreate()

    # Read from Kinesis stream
    kinesis_stream_df = spark.readStream.format("kinesis") \
        .option("streamName", KINESIS_STREAM_NAME) \
        .option("endpointUrl", AWS_ENDPOINT_URL) \
        .option("awsAccessKeyId", AWS_ACCESS_KEY_ID) \
        .option("awsSecretKey", AWS_ACCESS_KEY_ID) \
        .option("regionName", AWS_REGION) \
        .option("startingPosition", "TRIM_HORIZON") \
        .option("checkpointLocation", SPARK_CHECKPOINT_LOCATION) \
        .load() \
        .select(col("data").cast("string"))

    # Add a unique UUID to each incoming Kinesis record and the timestamp of processing.
    articles_with_id_ts_df = kinesis_stream_df \
        .select(from_json(col("data"), article_schema).alias("article")) \
        .select("article.*") \
        .withColumn("publish_date", to_timestamp(col("publish_date")))
        # .withColumn("unique_id", uuid()) # I wanted to add a uuid and processing timestamp here but ran out of time
        # .withColumn("processing_timestamp", current_timestamp()) 

    # Calculate word count
    word_count_df = articles_with_id_ts_df \
        .withColumn("words", split(col("content"), "\\s+")) \
        .withColumn("word_count", size(col("words")))

    # Apply watermark, group by 5-min window (sliding 1 min), aggregate avg word count
    enriched_articles_df = word_count_df \
        .withWatermark("publish_date", "10 seconds") \
        .groupBy(window(col("publish_date"), "5 minutes", "1 minute"), col("author")) \
        .agg(avg("word_count").alias("average_word_count")) \
        .select("window.start", "window.end", "author", "average_word_count")

    # Write enriched articles to S3
    s3_write_query = enriched_articles_df \
        .writeStream \
        .outputMode("append") \
        .format("parquet") \
        .option("path", s3_output_path) \
        .option("checkpointLocation", S3_CHECKPOINT_LOCATION) \
        .start()

    spark.streams.awaitAnyTermination()
