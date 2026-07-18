package provider

import (
	"context"
	"errors"
	"fmt"

	"github.com/byteburners/terraform-provider-aegis/internal/client"

	"github.com/hashicorp/terraform-plugin-framework/datasource"
	"github.com/hashicorp/terraform-plugin-framework/datasource/schema"
	"github.com/hashicorp/terraform-plugin-framework/types"
)

var (
	_ datasource.DataSource              = (*vmDataSource)(nil)
	_ datasource.DataSourceWithConfigure = (*vmDataSource)(nil)
)

type vmDataSource struct {
	client *client.Client
}

func NewVMDataSource() datasource.DataSource {
	return &vmDataSource{}
}

type vmDataSourceModel struct {
	Name      types.String `tfsdk:"name"`
	Status    types.String `tfsdk:"status"`
	OSType    types.String `tfsdk:"os_type"`
	CPUCores  types.Int64  `tfsdk:"cpu_cores"`
	Memory    types.String `tfsdk:"memory"`
	IPAddress types.String `tfsdk:"ip_address"`
	SSHPort   types.Int64  `tfsdk:"ssh_port"`
	Node      types.String `tfsdk:"node"`
}

func (d *vmDataSource) Metadata(_ context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_vm"
}

func (d *vmDataSource) Schema(_ context.Context, _ datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	resp.Schema = schema.Schema{
		MarkdownDescription: "Читает данные существующей ВМ по её имени.",
		Attributes: map[string]schema.Attribute{
			"name": schema.StringAttribute{
				MarkdownDescription: "Имя ВМ.",
				Required:            true,
			},
			"status":     schema.StringAttribute{MarkdownDescription: "Текущий статус ВМ.", Computed: true},
			"os_type":    schema.StringAttribute{MarkdownDescription: "Тип ОС.", Computed: true},
			"cpu_cores":  schema.Int64Attribute{MarkdownDescription: "Количество ядер CPU.", Computed: true},
			"memory":     schema.StringAttribute{MarkdownDescription: "Объём памяти (например, 2Gi).", Computed: true},
			"ip_address": schema.StringAttribute{MarkdownDescription: "Основной IP-адрес.", Computed: true},
			"ssh_port":   schema.Int64Attribute{MarkdownDescription: "Внешний SSH-порт.", Computed: true},
			"node":       schema.StringAttribute{MarkdownDescription: "Узел кластера, где размещена ВМ.", Computed: true},
		},
	}
}

func (d *vmDataSource) Configure(_ context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
	if req.ProviderData == nil {
		return
	}
	c, ok := req.ProviderData.(*client.Client)
	if !ok {
		resp.Diagnostics.AddError("Некорректный тип клиента",
			fmt.Sprintf("Ожидался *client.Client, получен %T", req.ProviderData))
		return
	}
	d.client = c
}

func (d *vmDataSource) Read(ctx context.Context, req datasource.ReadRequest, resp *datasource.ReadResponse) {
	var model vmDataSourceModel
	resp.Diagnostics.Append(req.Config.Get(ctx, &model)...)
	if resp.Diagnostics.HasError() {
		return
	}

	vm, err := d.client.GetVM(ctx, model.Name.ValueString())
	if errors.Is(err, client.ErrNotFound) {
		resp.Diagnostics.AddError("ВМ не найдена",
			fmt.Sprintf("ВМ с именем %q не существует.", model.Name.ValueString()))
		return
	}
	if err != nil {
		resp.Diagnostics.AddError("Не удалось прочитать ВМ", err.Error())
		return
	}

	model.Status = types.StringValue(vm.Status)
	model.OSType = types.StringValue(vm.OSType)
	model.CPUCores = types.Int64Value(vm.CPUCores)
	model.Memory = types.StringValue(vm.Memory)
	model.IPAddress = types.StringValue(vm.PrimaryIP())
	model.Node = types.StringValue(vm.Node)
	if vm.SSHPort != nil {
		model.SSHPort = types.Int64Value(*vm.SSHPort)
	} else {
		model.SSHPort = types.Int64Null()
	}

	resp.Diagnostics.Append(resp.State.Set(ctx, &model)...)
}
