"""Isolated Textract + Tesseract bake-off harness.

Self-contained — does not import from poc/. Reads .env.bedrock at the repo root
for AWS credentials (same tanishq IAM user as Bedrock). All outputs land under
textract_probe/output/ which is gitignored alongside the rest of the FERPA
sample data.
"""
