# Assignment A4: Bookstore microservices on EKS

Five Python microservices (three backends, two BFFs), a shared library, and Kubernetes manifests for deployment on AWS EKS. Optional infrastructure is defined in `CF-A4-cmu.yml`.

## Repository layout

| Path | Purpose |
|------|---------|
| `book_service/`, `customer_service/`, `crm_service/` | Backend services (Flask) + Dockerfiles |
| `web_bff/`, `mobile_bff/` | BFFs + Dockerfiles (build from repo root so `shared/` is in context) |
| `shared/` | JWT and BFF helpers used by both BFFs |
| `k8s/*.yaml` | Kubernetes templates (`YOUR_*` placeholders); render with `scripts/render_k8s_from_env.sh` |
| `k8s/deploy.env.example` | Copy to `k8s/deploy.env` (gitignored) and fill for your cluster |
| `k8s/rendered/` | Generated manifests (gitignored); produced by the render script |
| `scripts/` | Render script, Docker push helper, SQL init/truncate helpers, nginx config for local compose |
| `docker-compose.yml` | Optional local stack (MySQL, Kafka, all services, mock recommendation API) |
| `DEPLOY_4_EKS.md` | EKS deploy: env, build/push images, apply manifests, verify |
| `CF-A4-cmu.yml` | Optional course CloudFormation for VPC/EKS/Aurora/Kafka/MSK |
| `url.txt` | Four lines: web BFF base URL, mobile BFF base URL, Andrew ID, CRM sender email (`SMTP_SENDER_EMAIL`) |

Keep manifests under `k8s/` only (no duplicate `rendered/` at repo root).

## Architecture (A4)

<img width="3048" height="3456" alt="diagram (9)" src="https://github.com/user-attachments/assets/44373a70-6000-45bd-b13d-5c85134216e0" />


- **Web** and **mobile** BFFs expose HTTP (in EKS, typically via `LoadBalancer` Services). They validate **JWT** then **`X-Client-Type`** (`shared/bff_auth.py`).
- **Backend traffic** from BFFs goes to **`backend-router`** (nginx in the cluster), which routes `/customers*` and `/books*` to the customer and book services on port 3000. Set `URL_BASE_BACKEND_SERVICES` to `http://backend-router:3000` in the cluster.
- **Customer service** publishes customer events to **Kafka**; **CRM service** consumes them and sends email (SMTP env vars in manifests / `deploy.env`).
- **Book service** implements related-books with an external recommendation API, timeout, and circuit breaker (see `book_service/app.py` and env vars in `k8s/book-service.yaml`).

## JWT validation (BFFs)

- Header: `Authorization: Bearer <token>`.
- Payload: `sub` ∈ {starlord, gamora, drax, rocket, groot}, `iss` = `cmu.edu`, `exp` in the future.

## Mobile BFF response transformations

- **Books:** In JSON bodies, replace the string `"non-fiction"` with the number `3`.
- **Customers:** On `GET /customers/{id}` and `GET /customers?userId=…`, omit `address`, `address2`, `city`, `state`, `zipcode` from responses (not on `GET /customers` list).

## Web vs mobile behavior

- **`X-Client-Type`:** `Web` → web BFF; `iOS` / `Android` → mobile BFF; missing or invalid → **400** (after JWT passes).
- **Books:** Web BFF may map `genre` `3` → `'non-fiction'` for web clients; mobile keeps `3` where applicable.
- Services use `strict_slashes = False` so paths with or without trailing slashes behave consistently.

## Prerequisites

- Docker (build images)
- `kubectl` and AWS CLI (EKS)
- Aurora writer endpoint and credentials after stack/deploy; Kafka brokers reachable from the cluster for customer → CRM flow

## Database

1. From CloudFormation (or your infra), get the **Aurora writer** hostname and DB user/password.
2. From a host that can reach the writer:

   ```bash
   mysql -h <DBClusterEndpoint> -u <DBUsername> -p < scripts/init_db.sql
   ```

   Separate logical DBs (`books_db`, `customers_db`) match service configuration in Kubernetes and compose.

## Build images

From the **repository root** (BFF builds need `shared/`):

```bash
docker build -t <registry>/book-service ./book_service
docker build -t <registry>/customer-service ./customer_service
docker build -t <registry>/crm-service ./crm_service
docker build -f web_bff/Dockerfile -t <registry>/web-bff .
docker build -f mobile_bff/Dockerfile -t <registry>/mobile-bff .
```

Push to your registry and set image names in `k8s/deploy.env` before rendering (see `DEPLOY_A4_EKS.md`).

## Local run (Docker Compose)

```bash
docker compose up -d
```

- Web BFF: `http://localhost:8080` — use `X-Client-Type: Web` and `Authorization: Bearer <jwt>`.
- Mobile BFF: `http://localhost:8081` — use `X-Client-Type: iOS` or `Android` and JWT.

Details and env tuning are in `docker-compose.yml` comments.

## Deploy on EKS

Follow **`DEPLOY_A4_EKS.md`**: fill `k8s/deploy.env` from `k8s/deploy.env.example`, run `./scripts/render_k8s_from_env.sh`, `kubectl apply` the rendered manifests (or apply templates if you substitute values another way).

## API summary

- `GET /status` — health (all services); BFFs typically allow this without JWT for probes.
- **Customer service:** `GET /customers`, `GET /customers?userId=…`, `GET /customers/<id>`, `POST /customers` (Kafka side effects for CRM).
- **Book service:** `GET /books`, `GET|PUT /books/<isbn>`, `GET|PUT /books/isbn/<isbn>`, `POST /books`, `GET /books/<isbn>/related-books`.
- **BFFs** proxy the same paths; send `X-Client-Type` and `Authorization` on protected routes.

## Project layout

```
assign_3_aws/
├── book_service/
├── customer_service/
├── crm_service/
├── web_bff/
├── mobile_bff/
├── shared/
├── k8s/
│   ├── *.yaml
│   ├── deploy.env.example
│   └── rendered/          # generated; gitignored
├── scripts/
├── docker-compose.yml
├── CF-A4-cmu.yml
├── DEPLOY_A4_EKS.md
├── deploy.md                # legacy A2 EC2-oriented notes
├── url.txt
└── README.md
```

## Production readiness

- Do not commit `k8s/deploy.env`, `.env` files with secrets, or `*.pem`. Use `*.example` files as templates; inject secrets via Kubernetes Secrets or your CI/CD.
- Pin or range-pin dependencies in each `requirements.txt` for reproducible builds.
- For TLS in front of BFFs, terminate HTTPS on the load balancer and set probes to `GET /status` as in the manifests.
# 17-647-assignment-A4
