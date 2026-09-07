resource "aws_s3_bucket" "app_data" {
  bucket = "example-app-data"

  tags = {
    Project     = "infrai-fixture"
    Environment = var.environment
  }
}

resource "aws_s3_bucket_versioning" "app_data" {
  bucket = aws_s3_bucket.app_data.id

  versioning_configuration {
    status = "Enabled"
  }
}
