ARG KUBECTL_IMAGE=registry.k8s.io/kubectl:v1.31.5
FROM ${KUBECTL_IMAGE} AS kubectl

# Production builds should override this with an immutable digest.
ARG COSIGN_IMAGE=ghcr.io/sigstore/cosign/cosign:v2.4.1
FROM ${COSIGN_IMAGE} AS cosign

ARG CODEMATE_BACKEND_IMAGE=codemate-backend:staging
FROM ${CODEMATE_BACKEND_IMAGE}
COPY --from=kubectl /bin/kubectl /usr/local/bin/kubectl
COPY --from=cosign /ko-app/cosign /usr/local/bin/cosign
USER 65532:65532
