// terraform-provider-aegis — Terraform-провайдер для панели хостинга
// ByteBurners (Aegis). Позволяет описывать ВМ и базы данных как код.
package main

import (
	"context"
	"flag"
	"log"

	"github.com/byteburners/terraform-provider-aegis/internal/provider"

	"github.com/hashicorp/terraform-plugin-framework/providerserver"
)

// version подставляется при сборке через -ldflags "-X main.version=...".
var version = "dev"

func main() {
	var debug bool
	flag.BoolVar(&debug, "debug", false, "запустить провайдер в режиме отладки (для delve)")
	flag.Parse()

	opts := providerserver.ServeOpts{
		Address: "registry.terraform.io/byteburners/aegis",
		Debug:   debug,
	}

	if err := providerserver.Serve(context.Background(), provider.New(version), opts); err != nil {
		log.Fatal(err.Error())
	}
}
