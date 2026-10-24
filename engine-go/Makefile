# engine-go: the Go twin of the Groundplan backend.
.PHONY: test vet sync run deploy

test:
	go test ./...

vet:
	go vet ./... && staticcheck ./...

# re-copy the three shared contracts (each has a drift test)
sync:
	cp ../fixtures/engine/states.json engine/statetax/states.json
	cp ../backend/migrations.sql migrations/alembic_head.sql
	cp ../fixtures/seed/okafor-lindqvist.json internal/service/seeddata/okafor-lindqvist.json

run:
	go run ./cmd/gp-api

deploy:
	./deploy.sh
