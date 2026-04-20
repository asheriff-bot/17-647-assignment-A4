# A3 EKS Deploy Order and Value Checklist

This is the exact deployment order for this repository after the A3 refactor.

## 1) Fill runtime values once

1. Copy env template:

```bash
cp k8s/deploy.env.example k8s/deploy.env
```

2. Edit `k8s/deploy.env` with your real values.

Required fields:
- `IMAGE_REGISTRY`, `IMAGE_TAG`
- `RDS_ENDPOINT`, `DB_USER`, `DB_PASSWORD`
- `KAFKA_BROKERS`
- `ANDREW_ID`, `EMAIL_ADDRESS`
- `RECOMMENDATION_SERVICE_URL`, `RECOMMENDATION_PATH_TEMPLATE` (see Canvas; typical values: testing `http://52.73.13.84`, Gradescope `http://100.51.187.149`, path `/recommended-titles/isbn/{isbn}`)
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_STARTTLS`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SENDER_EMAIL`
- `AWS_REGION`, `EKS_CLUSTER_NAME`

## 2) Discover AWS values correctly

Use these commands to avoid guessing:

```bash
# RDS endpoint (Aurora writer endpoint)
aws rds describe-db-clusters \
  --query "DBClusters[?DBClusterIdentifier=='bookstore-db-dev'].Endpoint" \
  --output text

# EKS cluster names, then set EKS_CLUSTER_NAME in k8s/deploy.env
aws eks list-clusters --region us-east-1 --output table

# Kafka brokers: from your Canvas announcement (paste into KAFKA_BROKERS)
# Recommendation URL: testing http://52.73.13.84 | Gradescope http://100.51.187.149
# Path template: /recommended-titles/isbn/{isbn}
```

If you prefer CloudFormation queries, use:

```bash
aws cloudformation describe-stacks --stack-name <your-stack-name> --region us-east-1
```

## 2.5) Initialize Aurora databases (required once)

Pods use **`customers_db`** and **`books_db`** (`DB_NAME` in the rendered manifests). A fresh Aurora cluster has neither, which surfaces as MySQL **`1049 Unknown database`** and **HTTP 500** on `POST /customers` and `POST /books`.

From a host that can reach the **Aurora writer** (same VPC bastion, or tunnel), run the repo script **once** (idempotent `CREATE DATABASE IF NOT EXISTS`):

```bash
cd <path-to-assign_3_aws-repo-root>
source k8s/deploy.env
mysql -h "$RDS_ENDPOINT" -u "$DB_USER" -p"$DB_PASSWORD" < scripts/init_db.sql
```

If `mysql` is not installed: `sudo yum install -y mariadb101-client` (Amazon Linux 2) or use the RDS query editor / any MySQL client with the same host, user, password, and SQL file.

Until this succeeds, Gradescope tests that add books or customers will fail with **500** and `Unknown database 'books_db'` / `'customers_db'`.

### Aurora writer vs reader (MySQL **1836** / “Running in read-only mode”)

`POST /books` and `POST /customers` require a **write** connection. If `DB_HOST` points at the **reader** endpoint, MySQL returns **`(1836, 'Running in read-only mode')`** and the API returns **500**.

- **Writer** hostname looks like: `bookstore-db-dev.cluster-xxxx.region.rds.amazonaws.com` (note **`cluster-`**, not **`cluster-ro-`**).
- **Reader (read-only)** hostname looks like: `bookstore-db-dev.cluster-ro-xxxx.region.rds.amazonaws.com` — **never** put this in `RDS_ENDPOINT`.

Confirm in AWS (first line = writer — use this as `RDS_ENDPOINT`; second = reader — do not use):

```bash
aws rds describe-db-clusters --region us-east-1 --db-cluster-identifier bookstore-db-dev \
  --query 'DBClusters[0].[Endpoint,ReaderEndpoint]' --output text
```

If unsure, use the **writer instance** endpoint (the instance with `IsClusterWriter` **true**):

```bash
aws rds describe-db-instances --region us-east-1 \
  --query "DBInstances[?DBClusterIdentifier=='bookstore-db-dev'].{id:DBInstanceIdentifier,writer:IsClusterWriter,host:Endpoint.Address}" \
  --output table
```

After fixing `k8s/deploy.env`, re-run `./scripts/render_k8s_from_env.sh`, re-apply `k8s/rendered/customer-service.yaml` and `k8s/rendered/book-service.yaml`, and verify what pods actually use:

```bash
kubectl -n bookstore-ns exec deploy/book-service -- printenv DB_HOST
kubectl -n bookstore-ns exec deploy/customer-service -- printenv DB_HOST
```

## 3) Build and push all images

From repo root, use the **A3** script so image **repository names** match `k8s/*.yaml` (`customer-service`, `book-service`, `crm-service`, `web-bff`, `mobile-bff`). Do **not** use `build-push-dockerhub-amd64.sh` for A3 EKS — that script builds the older **`bookstore-*`** image names and **omits `crm-service`**.

```bash
export DH=<your_registry_user_or_prefix>
export TAG=<image_tag>
./scripts/build-push-dockerhub-a3.sh
```

Then set in `k8s/deploy.env`:
- `IMAGE_REGISTRY=<same as DH>` (add `docker.io/` prefix if you use it consistently in renders)
- `IMAGE_TAG=<same as TAG>`

## 4) Render Kubernetes manifests with your values

```bash
./scripts/render_k8s_from_env.sh
```

Rendered files are written to `k8s/rendered/`.

## 5) Configure kubectl for EKS

```bash
source k8s/deploy.env
aws eks update-kubeconfig --region "$AWS_REGION" --name "$EKS_CLUSTER_NAME"
kubectl get nodes
```

## 6) Apply manifests in this exact order

```bash
kubectl apply -f k8s/rendered/namespace.yaml
kubectl apply -f k8s/rendered/backend-router.yaml
kubectl apply -f k8s/rendered/customer-service.yaml
kubectl apply -f k8s/rendered/book-service.yaml
kubectl apply -f k8s/rendered/crm-service.yaml
kubectl apply -f k8s/rendered/web-bff.yaml
kubectl apply -f k8s/rendered/mobile-bff.yaml
```

Why this order:
- namespace first
- internal routing and backend services first
- BFFs last (they depend on backend-router/book/customer services)

## 7) Wait for healthy rollout

```bash
kubectl -n bookstore-ns get pods
kubectl -n bookstore-ns rollout status deploy/backend-router
kubectl -n bookstore-ns rollout status deploy/customer-service
kubectl -n bookstore-ns rollout status deploy/book-service
kubectl -n bookstore-ns rollout status deploy/crm-service
kubectl -n bookstore-ns rollout status deploy/web-bff
kubectl -n bookstore-ns rollout status deploy/mobile-bff
```

## 8) Get the two BFF base URLs for `url.txt`

```bash
WEB_URL="http://$(kubectl -n bookstore-ns get svc web-bff -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')"
MOBILE_URL="http://$(kubectl -n bookstore-ns get svc mobile-bff -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')"
echo "$WEB_URL"
echo "$MOBILE_URL"
```

Set `url.txt` to **exactly four lines** (no leading or trailing blank lines):
1. web BFF URL
2. mobile BFF URL
3. Andrew ID
4. email address used by CRM sender (`SMTP_SENDER_EMAIL`, same as in `k8s/deploy.env` / the CRM Deployment env)

**CRM / Gradescope email checks:** Use a real **Gmail App Password** in `SMTP_PASSWORD` (not your normal password). For Gmail, set **`SMTP_USERNAME`** and **`SMTP_SENDER_EMAIL`** to the **same** mailbox you authenticate. The activation email is sent **To** the customer’s **`userId`** from the Kafka event (the address the autograder uses for `POST /customers`). If email tests fail but Kafka passes, check `kubectl -n bookstore-ns logs deploy/crm-service` for SMTP errors and confirm the cluster allows **egress TCP 587** (or 465 if you use SSL).

## 9) Verify assignment-critical behavior

- `GET /status` on both BFF URLs returns `200`
- `POST /customers` publishes Kafka event
- CRM consumes event and sends activation email
- `GET /books/{isbn}/related-books`:
  - `200/204` when recommendation service responds in <= 3s
  - `504` on timeout while circuit closed
  - `503` while circuit open (<60s)
  - retry after 60s behaves as specified
