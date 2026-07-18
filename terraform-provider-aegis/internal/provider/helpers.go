package provider

import (
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/int64planmodifier"
	"github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier"
)

// Часто используемые пути к атрибутам.
var (
	pathID   = path.Root("id")
	pathName = path.Root("name")
)

// requiresReplaceInt — план-модификатор «пересоздать при изменении» для int64.
func requiresReplaceInt() []planmodifier.Int64 {
	return []planmodifier.Int64{int64planmodifier.RequiresReplace()}
}
