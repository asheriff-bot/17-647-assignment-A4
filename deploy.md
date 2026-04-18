# A2 Deployment Guide: Build and Deploy on AWS

For **A3 / EKS**, use **`DEPLOY_A3_EKS.md`** and **`k8s/`** manifests (render with `./scripts/render_k8s_from_env.sh`).

This document gives a **logical sequence of steps** to build the four A2 Docker images and deploy them on AWS using the CloudFormation stack (CF-A2-cmu.yml). The **Dockerfiles** and **docker-compose.yml** are aligned with the A2 API (ports 80 for BFFs, 3000 for backend; `/status`, `/customers*`, `/books*`).

---

## Local Run (Docker Compose) — Optional

To run all A2 services locally with one command (for development or testing before AWS deploy):

| Step | Action |
|------|--------|
| 1 | From repo root: `docker compose up -d` |
| 2 | Wait for DB to be healthy and backend_router to start (e.g. `docker compose ps`) |
| 3 | **Web BFF**: `http://localhost:8080` (use header `X-Client-Type: Web` and `Authorization: Bearer <jwt>`) |
| 4 | **Mobile BFF**: `http://localhost:8081` (use header `X-Client-Type: iOS` or `Android` and JWT) |
| 5 | **Backend router** (like Internal ALB): available **inside Docker network** at `backend_router:3000` (hit BFFs via `http://localhost:8080` and `http://localhost:8081`) |

The `docker-compose.yml` defines the four A2 API services (customer_service, book_service, web_bff, mobile_bff) plus `db` (MySQL) and `backend_router` (nginx) so BFFs have a single backend URL.

---

## Phase 1: Prerequisites

| Step | Action | Notes |
|------|--------|--------|
| 1.1 | Install **Docker** (and Docker Compose for local runs) | On your laptop and/or build host |
| 1.2 | Install **AWS CLI** and configure credentials | `aws configure` with lab/Academy credentials |
| 1.3 | Ensure **CloudFormation stack** is created from `CF-A2-cmu.yml` | Stack must be in `CREATE_COMPLETE` |
| 1.4 | Note stack **name** and **region** | e.g. `bookstore-dev`, `us-east-1` |

---

## Phase 2: Get Stack Outputs and Parameters

| Step | Action | Notes |
|------|--------|--------|
| 2.1 | Get **Internal ALB DNS name** (for BFF `URL_BASE_BACKEND_SERVICES`) | From stack **Outputs**: `InternalALBDNSName` |
| 2.2 | Get **DB cluster endpoint** (for backend services) | From stack **Outputs**: `DBClusterEndpoint` |
| 2.3 | Get **DB credentials** | From stack **Parameters**: `DBUsername`, `DBPassword` (you provided these at stack creation) |

**Example (AWS CLI):**

```bash
STACK_NAME="bookstore-dev"   # replace with your stack name
REGION="us-east-1"

aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" \
  --query 'Stacks[0].Outputs' --output table

aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" \
  --query 'Stacks[0].Parameters' --output table
```

Set variables for later steps:

```bash
INTERNAL_ALB_DNS="<value of InternalALBDNSName>"
DB_ENDPOINT="<value of DBClusterEndpoint>"
DB_USER="<DBUsername>"
DB_PASSWORD="<DBPassword>"
```

**Book and customer containers** accept **`DB_HOST`** or **`DB_ENDPOINT`** for the RDS hostname (same value as `DBClusterEndpoint`). If neither is set, they use `localhost` and all DB calls fail.

---

## Phase 3: Initialize the Database

Backend services (Customer and Book) need the `bookstore` database and tables.

| Step | Action | Notes |
|------|--------|--------|
| 3.1 | From a host that can reach the VPC (e.g. **SSH into one EC2**), ensure `mysql` client is available | Amazon Linux: `sudo dnf install mariadb105 -y` |
| 3.2 | Run the init script | `mysql -h "$DB_ENDPOINT" -u "$DB_USER" -p"$DB_PASSWORD" < scripts/init_db.sql` (or from repo: `mysql ... < scripts/init_db.sql`) |
| 3.3 | Verify | e.g. `mysql -h "$DB_ENDPOINT" -u "$DB_USER" -p"$DB_PASSWORD" -e "USE bookstore; SELECT * FROM books;"` |

---

## Phase 4: Build Docker Images

Build **all four** images from the **repository root** (`assign_2_aws`). Order does not matter, but all must succeed before deploy.

### EC2 is `linux/amd64` (important on Apple Silicon Macs)

Your template uses **t3.micro** EC2 → **x86_64** → Docker expects **`linux/amd64`** images.

If you build on an **ARM Mac** with plain `docker build`, images are often **arm64** only. Then `docker pull` on EC2 fails with:

`no matching manifest for linux/amd64 in the manifest list entries`

**Fix:** build and push for **`linux/amd64`** using **buildx**, then pull on EC2.

**From repo root** (after `docker login`):

```bash
export DH=yourdockerhubuser    # lowercase
export TAG=a2-latest

chmod +x scripts/build-push-dockerhub-amd64.sh
./scripts/build-push-dockerhub-amd64.sh
```

That script runs `docker buildx build --platform linux/amd64 --push` for all four images.

**One-off manual example** (customer service):

```bash
docker buildx build --platform linux/amd64 --push \
  -t "${DH}/bookstore-customer-service:${TAG}" \
  -f customer_service/Dockerfile ./customer_service
```

Repeat for `book_service`, `web_bff`, `mobile_bff` (BFF Dockerfiles use context `.` from repo root).

---

### Local-only builds (Mac / same-arch testing)

| Step | Action | Command | Image |
|------|--------|--------|--------|
| 4.1 | Build **Customer service** | `docker build -t bookstore/customer-service ./customer_service` | Port 3000, `/customers`, `/status` |
| 4.2 | Build **Book service** | `docker build -t bookstore/book-service ./book_service` | Port 3000, `/books`, `/status` |
| 4.3 | Build **Web BFF** | `docker build -f web_bff/Dockerfile -t bookstore/web-bff .` | Port 80, must build from repo root (uses `shared/`) |
| 4.4 | Build **Mobile BFF** | `docker build -f mobile_bff/Dockerfile -t bookstore/mobile-bff .` | Port 80, must build from repo root (uses `shared/`) |

**Single script (run from repo root):**

```bash
set -e
docker build -t bookstore/customer-service ./customer_service
docker build -t bookstore/book-service ./book_service
docker build -f web_bff/Dockerfile -t bookstore/web-bff .
docker build -f mobile_bff/Dockerfile -t bookstore/mobile-bff .
docker images | grep bookstore
```

---

## Phase 5: Make Images Available on EC2

You have two options: **push to ECR and pull on each EC2**, or **build on each EC2** (slower, no registry needed).

### Option A: Push to Amazon ECR and Pull on EC2

| Step | Action |
|------|--------|
| 5.A.1 | Create an ECR repository per image (or one repo with multiple tags), e.g. `bookstore/customer-service`, etc. |
| 5.A.2 | Tag and push: `docker tag bookstore/customer-service <account>.dkr.ecr.<region>.amazonaws.com/bookstore/customer-service:latest`, then `docker push ...` (after `aws ecr get-login-password \| docker login ...`) |
| 5.A.3 | On each EC2: `aws ecr get-login-password`, `docker pull ...` for each of the four images (using the same repo/URI you pushed). |

### Option B: Build on Each EC2

| Step | Action |
|------|--------|
| 5.B.1 | Copy the whole repo to each EC2 (e.g. `scp -r assign_2_aws ec2-user@<EC2_IP>:~/`) or clone from Git. |
| 5.B.2 | On each EC2, run the same four `docker build` commands from **Phase 4** (from the repo root on that EC2). |

---

## Phase 6: Deploy Containers on Each EC2

Deploy in this order so that **backend services** are up before ALB health checks matter. Use the **same** `INTERNAL_ALB_DNS`, `DB_ENDPOINT`, `DB_USER`, `DB_PASSWORD` on every instance.

### 6.1 EC2BookstoreA (Web BFF + Customer service)

| Step | Service | Command |
|------|---------|--------|
| 1 | Web BFF (port 80) | `docker run -d --name web-bff -p 80:80 -e URL_BASE_BACKEND_SERVICES=http://<InternalALBDNSName>:3000 bookstore/web-bff` |
| 2 | Customer service (port 3000) | `docker run -d --name customer-svc -p 3000:3000 -e DB_HOST=<DBClusterEndpoint> -e DB_USER=<DBUser> -e DB_PASSWORD=<DBPassword> -e DB_NAME=bookstore bookstore/customer-service` |

Replace placeholders with your values.

### 6.2 EC2BookstoreB (Web BFF + Book service)

| Step | Service | Command |
|------|---------|--------|
| 1 | Web BFF (port 80) | `docker run -d --name web-bff -p 80:80 -e URL_BASE_BACKEND_SERVICES=http://<InternalALBDNSName>:3000 bookstore/web-bff` |
| 2 | Book service (port 3000) | `docker run -d --name book-svc -p 3000:3000 -e DB_HOST=<DBClusterEndpoint> -e DB_USER=<DBUser> -e DB_PASSWORD=<DBPassword> -e DB_NAME=bookstore bookstore/book-service` |

### 6.3 EC2BookstoreC (Mobile BFF + Book service)

| Step | Service | Command |
|------|---------|--------|
| 1 | Mobile BFF (port 80) | `docker run -d --name mobile-bff -p 80:80 -e URL_BASE_BACKEND_SERVICES=http://<InternalALBDNSName>:3000 bookstore/mobile-bff` |
| 2 | Book service (port 3000) | `docker run -d --name book-svc -p 3000:3000 -e DB_HOST=<DBClusterEndpoint> -e DB_USER=<DBUser> -e DB_PASSWORD=<DBPassword> -e DB_NAME=bookstore bookstore/book-service` |

### 6.4 EC2BookstoreD (Mobile BFF + Customer service)

| Step | Service | Command |
|------|---------|--------|
| 1 | Mobile BFF (port 80) | `docker run -d --name mobile-bff -p 80:80 -e URL_BASE_BACKEND_SERVICES=http://<InternalALBDNSName>:3000 bookstore/mobile-bff` |
| 2 | Customer service (port 3000) | `docker run -d --name customer-svc -p 3000:3000 -e DB_HOST=<DBClusterEndpoint> -e DB_USER=<DBUser> -e DB_PASSWORD=<DBPassword> -e DB_NAME=bookstore bookstore/customer-service` |

---

## Phase 7: Verify Deployment

| Step | Action |
|------|--------|
| 7.1 | In AWS Console, check **Target Groups** for the four target groups (WebBFF, MobileBFF, CustSvc, BookSvc). Targets should become **Healthy** after health checks pass (`/status` returns 200). |
| 7.2 | Get **External ALB DNS** from stack Outputs (`ExternalALBDNSName`). |
| 7.3 | Call health: `curl -s -o /dev/null -w "%{http_code}" http://<ExternalALBDNSName>/status -H "X-Client-Type: Web" -H "Authorization: Bearer <valid-jwt>"` → expect **200**. |
| 7.4 | Call APIs: e.g. `GET /books`, `GET /customers` with same headers; test Mobile BFF with `X-Client-Type: iOS` and confirm transformations (e.g. `non-fiction` → `3`, address fields removed in customer response). |

---

## Summary: Logical Order

1. **Prerequisites** → Docker, AWS CLI, stack created  
2. **Stack outputs/parameters** → Internal ALB DNS, DB endpoint, DB credentials  
3. **Database** → Run `init_db.sql` once from inside VPC  
4. **Build** → All four images from repo root (backends first or BFFs first, any order)  
5. **Images on EC2** → ECR push/pull **or** build on each EC2  
6. **Deploy** → On each EC2: start BFF then backend (or backend then BFF), with correct env vars  
7. **Verify** → Target health, then curl External ALB with `X-Client-Type` and JWT  

---

## Reference: A2 API and Ports

| Service | Port | Endpoints |
|---------|------|-----------|
| Customer service | 3000 | `GET /status`, `GET /customers`, `GET /customers?userId=`, `GET /customers/<id>`, `POST /customers` |
| Book service | 3000 | `GET /status`, `GET /books`, `GET /books/<isbn>`, `GET /books/isbn/<isbn>`, `POST /books` |
| Web BFF | 80 | Same paths as above; forwards to Internal ALB; requires JWT and `X-Client-Type: Web` |
| Mobile BFF | 80 | Same paths; forwards to Internal ALB; transforms book/customer responses; requires JWT and `X-Client-Type: iOS` or `Android` |

The **Dockerfiles** and **docker-compose.yml** in this repo are aligned with these ports and APIs.

---

## Dockerfiles and docker-compose (A2 API alignment)

| File | Purpose |
|------|--------|
| `customer_service/Dockerfile` | Customer service on port 3000; `/status`, `/customers`, `/customers/<id>`, `/customers?userId=`, `POST /customers` |
| `book_service/Dockerfile` | Book service on port 3000; `/status`, `/books`, `/books/<isbn>`, `/books/isbn/<isbn>`, `POST /books` |
| `web_bff/Dockerfile` | Web BFF on port 80; same paths, forwards to backend; requires JWT and `X-Client-Type: Web` (build from repo root) |
| `mobile_bff/Dockerfile` | Mobile BFF on port 80; same paths, forwards and transforms responses; requires JWT and `X-Client-Type: iOS/Android` (build from repo root) |
| `docker-compose.yml` | Local run: db, customer_service, book_service, backend_router (nginx), web_bff (8080), mobile_bff (8081); matches A2 ports and APIs |
