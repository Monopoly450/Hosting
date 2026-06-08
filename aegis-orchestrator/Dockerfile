FROM golang:1.21-alpine AS builder
WORKDIR /app
COPY go.mod ./
COPY *.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -o aegis-orchestrator .

FROM alpine:latest
WORKDIR /app
COPY --from=builder /app/aegis-orchestrator /app/aegis-orchestrator
EXPOSE 8001
CMD ["/app/aegis-orchestrator"]
