#!/usr/bin/env bash
# Emit a valid kubeconfig for an EKS cluster using the current AWS credentials.
# Requires: aws CLI, cluster reachable by your IAM principal.
#
# Usage:
#   ./scripts/emit-eks-kubeconfig.sh [region] [cluster-name] > kubeconfig.bookstore.yaml
#   export KUBECONFIG=$PWD/kubeconfig.bookstore.yaml
#   kubectl get nodes
#
set -euo pipefail
REGION="${1:-us-east-1}"
NAME="${2:-bookstore-dev-BookstoreEKSCluster}"

CA=$(aws eks describe-cluster --name "$NAME" --region "$REGION" --query 'cluster.certificateAuthority.data' --output text)
SERVER=$(aws eks describe-cluster --name "$NAME" --region "$REGION" --query 'cluster.endpoint' --output text)
ARN=$(aws eks describe-cluster --name "$NAME" --region "$REGION" --query 'cluster.arn' --output text)

cat <<EOF
apiVersion: v1
kind: Config
preferences: {}
current-context: ${NAME}
contexts:
- name: ${NAME}
  context:
    cluster: ${NAME}
    user: ${NAME}
clusters:
- name: ${NAME}
  cluster:
    server: ${SERVER}
    certificate-authority-data: ${CA}
users:
- name: ${NAME}
  user:
    exec:
      apiVersion: client.authentication.k8s.io/v1beta1
      command: aws
      args:
        - eks
        - get-token
        - --cluster-name
        - ${NAME}
        - --region
        - ${REGION}
      # Uncomment if you use a named profile for the learner lab:
      # env:
      # - name: AWS_PROFILE
      #   value: your-profile
EOF
echo "# cluster ARN: ${ARN}" >&2
