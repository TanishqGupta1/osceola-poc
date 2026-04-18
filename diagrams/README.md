# Diagrams

## Source

- `phase2_arch.html` — canonical Phase 2 production architecture diagram. Single-file HTML + inline CSS + SVG edges + PNG/SVG icons. Open directly in a browser to view/edit, or serve locally for capture into Figma.

## Icon attribution

AWS service icons pulled from the [icepanel.io](https://icon.icepanel.io/) public mirror of the official **AWS Architecture Icons** asset pack. Permitted for use in architecture diagrams per [AWS Icon Usage Guidelines](https://aws.amazon.com/architecture/icons/).

Services used: S3, EventBridge, Step Functions, Lambda, DynamoDB, SQS, CloudFront, Cognito, API Gateway, Kinesis Data Firehose, CloudWatch, Athena.

`bedrock.svg` is a hand-drawn AWS-orange monogram (Bd), since the public mirror does not yet include a Bedrock icon in the set we used. Replace with the official icon once available.

## Usage

**View locally:**

```bash
open diagrams/phase2_arch.html
```

**Serve + capture to Figma:**

```bash
python3 -m http.server 8765 --directory diagrams
# then use Figma MCP generate_figma_design on http://localhost:8765/phase2_arch.html
```
