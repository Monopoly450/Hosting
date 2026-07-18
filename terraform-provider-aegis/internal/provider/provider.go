// Package provider реализует Terraform-провайдер для панели хостинга
// ByteBurners (Aegis): ресурсы aegis_vm и aegis_database.
package provider

import (
	"context"
	"os"

	"github.com/byteburners/terraform-provider-aegis/internal/client"

	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/provider"
	"github.com/hashicorp/terraform-plugin-framework/provider/schema"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

// Проверка соответствия интерфейсу.
var _ provider.Provider = (*aegisProvider)(nil)

type aegisProvider struct {
	version string
}

type aegisProviderModel struct {
	URL   types.String `tfsdk:"url"`
	Token types.String `tfsdk:"token"`
}

// New возвращает фабрику провайдера для заданной версии.
func New(version string) func() provider.Provider {
	return func() provider.Provider {
		return &aegisProvider{version: version}
	}
}

func (p *aegisProvider) Metadata(_ context.Context, _ provider.MetadataRequest, resp *provider.MetadataResponse) {
	resp.TypeName = "aegis"
	resp.Version = p.version
}

func (p *aegisProvider) Schema(_ context.Context, _ provider.SchemaRequest, resp *provider.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "Провайдер для панели хостинга ByteBurners (Aegis). " +
			"Управляет виртуальными машинами и базами данных через REST API панели.",
		Attributes: map[string]schema.Attribute{
			"url": schema.StringAttribute{
				MarkdownDescription: "Адрес панели, например `http://SERVER:8000`. " +
					"Можно задать через переменную окружения `AEGIS_URL`.",
				Optional: true,
			},
			"token": schema.StringAttribute{
				MarkdownDescription: "Персональный API-токен (`aeg_...`), созданный во вкладке «API-токены». " +
					"Можно задать через переменную окружения `AEGIS_TOKEN`.",
				Optional:  true,
				Sensitive: true,
			},
		},
	}
}

func (p *aegisProvider) Configure(ctx context.Context, req provider.ConfigureRequest, resp *provider.ConfigureResponse) {
	var cfg aegisProviderModel
	resp.Diagnostics.Append(req.Config.Get(ctx, &cfg)...)
	if resp.Diagnostics.HasError() {
		return
	}

	url := os.Getenv("AEGIS_URL")
	if !cfg.URL.IsNull() && cfg.URL.ValueString() != "" {
		url = cfg.URL.ValueString()
	}
	token := os.Getenv("AEGIS_TOKEN")
	if !cfg.Token.IsNull() && cfg.Token.ValueString() != "" {
		token = cfg.Token.ValueString()
	}

	if url == "" {
		resp.Diagnostics.AddAttributeError(
			path.Root("url"),
			"Не задан адрес панели",
			"Укажите `url` в блоке provider или переменную окружения AEGIS_URL.",
		)
	}
	if token == "" {
		resp.Diagnostics.AddAttributeError(
			path.Root("token"),
			"Не задан API-токен",
			"Укажите `token` в блоке provider или переменную окружения AEGIS_TOKEN. "+
				"Токен создаётся во вкладке «API-токены» панели.",
		)
	}
	if resp.Diagnostics.HasError() {
		return
	}

	c := client.New(url, token)
	resp.ResourceData = c
	resp.DataSourceData = c
}

func (p *aegisProvider) Resources(_ context.Context) []func() resource.Resource {
	return []func() resource.Resource{
		NewVMResource,
		NewDatabaseResource,
	}
}

func (p *aegisProvider) DataSources(_ context.Context) []func() datasource.DataSource {
	return []func() datasource.DataSource{
		NewVMDataSource,
	}
}
