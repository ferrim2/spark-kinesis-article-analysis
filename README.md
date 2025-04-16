# Real-time Article Processing with Spark and Kinesis

This project demonstrates a real-time data processing pipeline using Apache Spark Streaming to consume articles from a Kinesis stream, perform basic enrichment (word count), and store the results in an S3 bucket. It also includes a data publisher to populate the Kinesis stream and a health check endpoint for monitoring.

## Overview

The Docker Compose setup defines the following services:

* **`localstack`**: A local AWS cloud service emulator providing Kinesis and S3 for local development and testing.
* **`article-publisher`**: A Python Flask application that generates mock article data and publishes it to the Kinesis stream. It also exposes a health check endpoint.
* **`spark-master`**: The master node for the Spark cluster.
* **`spark-worker-1` (and optionally `spark-worker-2`)**: Worker nodes that execute tasks assigned by the Spark master.
* **`spark-app`**: The Spark application responsible for reading from the Kinesis stream, processing the article data, and writing the enriched results to S3.


## Components and Configuration

### `docker-compose.yml`

This file defines the multi-container Docker application. Key configurations include:

* **`localstack`**:
    * Configures `SERVICES` to include `kinesis` and `s3`.
    * Defines a health check to ensure S3 is operational.
* **`article-publisher`**:
    * Depends on `localstack` and waits for it to be healthy.
    * Exposes a health check at `http://localhost:8000/health`.
* **`spark-master`**:
    * Configures the Spark master hostname and port.
    * Mounts the `./app` directory to `/opt/spark/work-dir` and a Docker volume `spark_checkpoints` for Spark checkpointing.
    * Starts the Spark master process.
* **`spark-worker-1` (and `spark-worker-2`)**:
    * Depends on `spark-master`.
    * Sets the `SPARK_MASTER_URL` to connect to the master.
    * Mounts the application code and the `spark_checkpoints` volume.
    * Starts the Spark worker process, connecting to the master.
* **`spark-app`**:
    * Builds the image from the `./spark-app` directory (which in this case uses the base Spark image and copies the processing script).
    * Depends on `article-publisher` (to ensure data is being published) and `spark-master`.
    * Mounts the application code and the `spark_checkpoints` volume.
    * Sets environment variables for AWS connection, Kinesis and S3 names, Spark master URL, checkpoint locations, and the Spark application name.
    * Submits the `process_articles.py` script to the Spark master, including necessary Kinesis and Hadoop AWS connector packages.
* **`volumes`**:
    * Defines a named Docker volume `spark_checkpoints` to persist Spark checkpoint data across container restarts.

### `./spark-app/Dockerfile`

This Dockerfile is used to build the `spark-app` service. It's currently very basic, extending the official Spark image and performing the following:
* Creates a `/opt/spark/checkpoints` directory.
* Changes ownership of the checkpoint directory to the `spark` user.

### `./app/process_articles.py`

This is the main Spark Streaming application:

* Configures a Spark session, connecting to the Spark master and LocalStack for AWS services.
* Reads data from the specified Kinesis stream using the `spark-sql-kinesis` connector, starting from the earliest available record (`TRIM_HORIZON`).
* Parses the JSON data from Kinesis into an `article_schema`.
* Calculates the word count for each article.
* Aggregates the average word count per author within 5-minute windows, updated every minute, using a watermark to handle late data.
* Writes the enriched data (window start/end, author, average word count) to the specified S3 bucket in Parquet format, using a checkpoint location for fault tolerance.

### `./populate-script/populate_stream.py`

This script is responsible for generating and publishing mock article data to the Kinesis stream:

* Generates mock articles and publishes the generated articles as JSON to the Kinesis stream.
* Implements a Flask health check server on `/health` to indicate if the initial setup (bucket and stream creation) and publishing have started.

## Usage

1.  **Ensure Docker Compose is running:**
    ```bash
    docker-compose up -d
    ```

2.  **Monitor the logs:** Observe the logs of the `article-publisher` to see when it starts publishing data. Monitor the `spark-app` logs to see when it starts processing data from Kinesis and writing to S3.

3.  **Check the health endpoint:** You can check the health of the `article-publisher` service by accessing `http://localhost:8000/health` in your web browser or using `curl`.


4.  **Inspect S3 output:** Once the Spark application starts processing, you can inspect the data written to the S3 bucket (named `my-bucket` by default) using the `awslocal` CLI within the `localstack` container:
    ```bash
    docker exec -it localstack awslocal s3 ls s3://my-bucket/enriched_articles/
    ```


5.  **Removing Spark Checkpoints (if needed):**
    If you encounter issues related to Spark's previous processing state (e.g., after code changes or to force a re-read of the Kinesis stream from the beginning), you might need to remove the Spark checkpoint data. To do this:
    ```bash
    docker-compose down -v
    ```
    The `-v` flag will remove the named volumes defined in your `docker-compose.yml`, including the `spark_checkpoints` volume. If you only want to remove the `spark_checkpoints` volume without stopping other services or removing other volumes, you can identify its specific name (it might be prefixed with your project name, e.g., `your_project_spark_checkpoints`) using `docker volume ls` and then remove it with:
    ```bash
    docker volume rm <your_spark_checkpoints_volume_name>
    ```