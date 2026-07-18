BINARY  = terraform-provider-aegis
VERSION ?= 0.1.0
# Каталог для локальной установки провайдера (dev overrides / плагины).
HOSTNAME = registry.terraform.io
NAMESPACE = byteburners
NAME     = aegis
OS_ARCH ?= $(shell go env GOOS)_$(shell go env GOARCH)
INSTALL_DIR = ~/.terraform.d/plugins/$(HOSTNAME)/$(NAMESPACE)/$(NAME)/$(VERSION)/$(OS_ARCH)

.PHONY: build test vet install clean

build:
	go build -ldflags "-X main.version=$(VERSION)" -o $(BINARY) .

test:
	go test ./... -count=1

vet:
	go vet ./...

# Собирает провайдер и кладёт его в каталог плагинов Terraform,
# чтобы можно было ссылаться на source = "byteburners/aegis".
install: build
	mkdir -p $(INSTALL_DIR)
	cp $(BINARY) $(INSTALL_DIR)/$(BINARY)_v$(VERSION)

clean:
	rm -f $(BINARY)
