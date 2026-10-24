# Runtime image only: the binary is cross-compiled outside (CGO_ENABLED=0 GOOS=linux GOARCH=amd64, -tags timetzdata).
# distroless/static = CA certificates + tzdata + a nonroot user, no shell.
FROM gcr.io/distroless/static-debian12:nonroot
COPY gp-api /gp-api
COPY eval-latest.json /app/eval-latest.json
ENV GP_ADDR=:8080 GP_EVAL_PATH=/app/eval-latest.json
EXPOSE 8080
USER nonroot:nonroot
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD ["/gp-api", "-healthcheck"]
ENTRYPOINT ["/gp-api"]
